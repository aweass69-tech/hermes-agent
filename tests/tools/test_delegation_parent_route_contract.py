"""Parent context, route placement, and completion-vs-success for delegate_task.

These tests never call a model. A misplaced or invalid route returns before any
child agent is constructed. A valid route is checked on the credential bundle
handed to the child constructor, which is a stub.
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent.delegation_provider import DelegationProvider, DelegationRouteError
from agent.subagent_lifecycle import bind_subagent_parent
from tools.delegate_tool_child_run import _SchemaOutcome, _build_result_entry
from tools.process_registry_notifications import (
    async_delegation_display_text, format_process_notification,
)
from tools.registry import registry


WORK = "gemma4:12b"
REVIEW = "qwen3:30b-a3b"
PARENT_MODEL = "gemma4:26b"
LOCAL = "http://127.0.0.1:11434/v1"


class _WorkerReviewMap(DelegationProvider):
    """Synthetic stand-in for advanced-delegation's model_map. ``option`` is per task."""

    @property
    def name(self) -> str:
        return "model_map"

    def task_parameters(self, config):
        return {"option": {
            "type": "string", "enum": ["work", "review"],
            "description": "work executes; review reviews on a different model",
        }}

    def route_task(self, task, config):
        choice = task.get("option")
        if choice == "work":
            return {"model": WORK, "base_url": LOCAL, "api_key": "synthetic", "label": "work"}
        if choice == "review":
            return {"model": REVIEW, "base_url": LOCAL, "api_key": "synthetic", "label": "review"}
        raise DelegationRouteError(
            "option is required. Refusing to inherit the parent or work model."
        )


def _parent():
    parent = MagicMock()
    parent.model = PARENT_MODEL
    parent.provider = "custom"
    parent.base_url = LOCAL
    parent.api_key = "parent-key"
    parent.api_mode = "chat_completions"
    parent.platform = "cli"
    parent.session_id = "parent-session"
    parent._delegate_depth = 0
    parent._active_children = []
    parent._active_children_lock = threading.Lock()
    parent._print_fn = parent.tool_progress_callback = parent.thinking_callback = None
    parent.request_overrides = {}
    parent.reasoning_config = {"enabled": True, "effort": "medium"}
    parent._session_db = None
    parent._subagent_id = None
    return parent


def _install_map():
    return (
        patch("tools.delegate_tool._load_config", return_value={"backend": "model_map"}),
        patch("tools.delegate_tool_routes._active_provider", return_value=_WorkerReviewMap()),
    )


def _error(text: str) -> str:
    payload = json.loads(text)
    assert "error" in payload, payload
    return payload["error"]


def test_missing_parent_does_not_construct_a_child():
    with patch("run_agent.AIAgent", side_effect=AssertionError("model client constructed")):
        from tools.delegate_tool import delegate_task
        error = _error(delegate_task(goal="Review the synthetic change carefully"))
    assert "parent agent context" in error


def test_turn_bound_parent_reaches_a_tool_that_does_not_forward_it():
    """The extension failure: a registered tool called delegate_task() with no parent_agent.

    Mock tests that passed the argument never hit this. A normal turn has already
    bound the parent; the call must use that agent and still not run a model.
    """
    parent = _parent()
    seen = {}

    def handler(args, **_kw):
        from tools.delegate_tool import delegate_task
        return delegate_task(tasks=[{"goal": "Execute the synthetic worker task", "option": "work"}])

    registry.register(
        name="_synthetic_parent_probe", toolset="delegation",
        schema={"name": "_synthetic_parent_probe", "description": "probe",
                "parameters": {"type": "object", "properties": {}}},
        handler=handler,
    )
    try:
        def _construct(**kw):
            seen["kwargs"] = kw
            return MagicMock()

        def _stop(batch, background):
            seen["parent"] = batch.parent_agent
            return json.dumps({"status": "built"})

        with _install_map()[0], _install_map()[1], (
            patch("run_agent.AIAgent", side_effect=_construct)
        ), patch("tools.delegate_tool._run_batch", side_effect=_stop):
            with bind_subagent_parent(parent):
                result = json.loads(registry.dispatch("_synthetic_parent_probe", {}))
        assert result == {"status": "built"}
        assert seen["parent"] is parent
        assert seen["kwargs"]["model"] == WORK
        assert seen["kwargs"]["model"] != PARENT_MODEL
    finally:
        registry.deregister("_synthetic_parent_probe")


def test_explicit_parent_wins_over_the_turn_binding():
    bound, explicit = _parent(), _parent()
    explicit.session_id = "explicit-session"
    seen = {}
    def _stop(batch, background):
        seen["parent"] = batch.parent_agent
        return json.dumps({"status": "built"})

    with _install_map()[0], _install_map()[1], (
        patch("run_agent.AIAgent", return_value=MagicMock())
    ), patch("tools.delegate_tool._run_batch", side_effect=_stop):
        with bind_subagent_parent(bound):
            from tools.delegate_tool import delegate_task
            result = json.loads(delegate_task(
                tasks=[{"goal": "Execute the synthetic worker task", "option": "work"}],
                parent_agent=explicit,
            ))
    assert result == {"status": "built"}
    assert seen["parent"] is explicit


def test_misplaced_option_beside_goal_builds_no_child():
    from run_agent import AIAgent
    dispatch = AIAgent._dispatch_delegate_task
    with patch("run_agent.AIAgent", side_effect=AssertionError("model client constructed")):
        error = _error(dispatch(object(), {
            "goal": "Review the synthetic change for correctness",
            "option": "review",
        }))
    assert "option" in error and "tasks" in error

    error = _error(registry.dispatch("delegate_task", {
        "goal": "Review the synthetic change for correctness",
        "tasks": [{"goal": "Review the synthetic change for correctness"}],
        "route": "review",
    }))
    assert "route" in error
    assert "work model" in error


def test_invalid_option_is_refused_before_a_child_is_built():
    with _install_map()[0], _install_map()[1], (
        patch("run_agent.AIAgent", side_effect=AssertionError("model client constructed"))
    ):
        from tools.delegate_tool import delegate_task
        error = _error(delegate_task(
            tasks=[{"goal": "Review the synthetic change carefully", "option": "nope"}],
            parent_agent=_parent(),
        ))
    assert "nope" in error
    assert "work" in error and "review" in error


def test_omitted_option_does_not_silently_select_the_work_model():
    with _install_map()[0], _install_map()[1], (
        patch("run_agent.AIAgent", side_effect=AssertionError("model client constructed"))
    ):
        from tools.delegate_tool import delegate_task
        error = _error(delegate_task(
            tasks=[{"goal": "Review the synthetic change carefully"}],
            parent_agent=_parent(),
        ))
    assert "option is required" in error
    assert WORK not in error


def test_work_and_review_select_different_models_and_do_not_run():
    built = []

    def construct(**kwargs):
        built.append(kwargs)
        child = MagicMock()
        child.model = kwargs.get("model")
        child.provider = kwargs.get("provider")
        child.run_conversation.side_effect = AssertionError("child conversation started")
        return child

    with _install_map()[0], _install_map()[1], (
        patch("run_agent.AIAgent", side_effect=construct)
    ), patch("tools.delegate_tool._run_batch",
             side_effect=lambda batch, background: json.dumps({"status": "built", "n": len(batch.children)})):
        from tools.delegate_tool import delegate_task
        result = json.loads(delegate_task(tasks=[
            {"goal": "Execute the synthetic worker task", "option": "work"},
            {"goal": "Review the synthetic worker result independently", "option": "review"},
        ], parent_agent=_parent()))
    assert result == {"status": "built", "n": 2}
    assert [call["model"] for call in built] == [WORK, REVIEW]
    assert all(call["model"] != PARENT_MODEL for call in built)
    assert all(call["base_url"] == LOCAL for call in built)


def test_schema_miss_keeps_the_text_and_is_not_task_success():
    child = SimpleNamespace(
        model=WORK, session_estimated_cost_usd=0.0, session_cost_status="unknown",
        session_prompt_tokens=1, session_completion_tokens=1, _delegate_role="leaf",
        reasoning_config=None, service_tier=None, request_overrides={},
    )
    prose = "Irrelevant template: lorem ipsum, not the requested findings."
    missed = _build_result_entry(
        child, {"final_response": prose, "completed": True, "api_calls": 2}, 0, 1.5,
        _SchemaOutcome({"type": "object", "required": ["findings"]}, False, ["'findings' is required"], 1),
    )
    assert missed["status"] == "completed"
    assert missed["summary"] == prose
    assert missed["schema_valid"] is False
    assert missed["task_success"] is False
    assert missed["model"] == WORK

    accepted = _build_result_entry(
        child, {"final_response": '{"findings": []}', "completed": True}, 0, 1.0,
        _SchemaOutcome({"type": "object"}, True, [], 0),
    )
    assert accepted["task_success"] is True

    plain = _build_result_entry(
        child, {"final_response": prose, "completed": True}, 0, 1.0,
        _SchemaOutcome(None, None, [], 0),
    )
    assert "task_success" not in plain and "schema_valid" not in plain

    event = {
        "type": "async_delegation", "delegation_id": "deleg_synthetic", "is_batch": True,
        "goals": ["Review the synthetic change"], "results": [missed],
        "dispatched_at": 1.0, "completed_at": 2.0,
    }
    text = format_process_notification(event)
    assert text is not None
    assert "task_success=false" in text
    assert WORK in text
    assert prose in text
    assert "Unverified" in async_delegation_display_text(event)


def test_async_return_completion_failure_and_searchable_persistence(tmp_path):
    """A background call returns before the child finishes. Completion and failure
    are different, and the stored completion text is findable by session_search.
    """
    from hermes_state import SessionDB
    from tests.waiting import wait_until
    from tools import async_delegation as ad
    from tools.delegate_tool import delegate_task
    from tools.process_registry import process_registry
    from tools.session_search_tool import session_search

    ad._reset_for_tests()
    parent = _parent()
    gate = threading.Event()
    marker = "SYNTHETICQWENREVIEWMARKER"

    def child_run(task_index, goal, child=None, parent_agent=None, **_kw):
        gate.wait(timeout=5)
        if "fail" in goal:
            return {
                "task_index": task_index, "status": "failed", "summary": None,
                "error": "synthetic child failure", "api_calls": 1, "duration_seconds": 0.1,
                "model": WORK, "exit_reason": "error", "task_success": False,
            }
        return {
            "task_index": task_index, "status": "completed",
            "summary": f"template dump {marker}", "api_calls": 1, "duration_seconds": 0.1,
            "model": REVIEW, "exit_reason": "completed", "task_success": False,
            "schema_valid": False,
        }

    creds = {"model": WORK, "provider": None, "base_url": LOCAL, "api_key": "synthetic",
             "api_mode": None, "command": None, "args": None}
    try:
        with patch("tools.delegate_tool._build_child_agent", return_value=MagicMock(_delegate_role="leaf")), (
            patch("tools.delegate_tool._run_single_child", side_effect=child_run)
        ), patch("tools.delegate_tool._resolve_delegation_credentials", return_value=creds):
            failed = json.loads(delegate_task(
                tasks=[{"goal": "fail this synthetic task now"}], background=True, parent_agent=parent,
            ))
            assert failed["status"] == "dispatched"
            assert process_registry.completion_queue.empty()
            gate.set()
            failed_evt = wait_until(
                lambda: _take(process_registry, failed["delegation_id"]),
                timeout=5, what="failed delegation completion",
            )
        assert failed_evt["results"][0]["status"] == "failed"
        assert failed_evt["results"][0]["task_success"] is False
        saved = ad.get_durable_delegation(failed["delegation_id"])
        assert saved is not None
        assert "synthetic child failure" in json.dumps(saved)

        gate.clear()
        with patch("tools.delegate_tool._build_child_agent", return_value=MagicMock(_delegate_role="leaf")), (
            patch("tools.delegate_tool._run_single_child", side_effect=child_run)
        ), patch("tools.delegate_tool._resolve_delegation_credentials", return_value=creds):
            done = json.loads(delegate_task(
                tasks=[{"goal": "review the synthetic change carefully"}],
                background=True, parent_agent=parent,
            ))
            assert done["status"] == "dispatched"
            assert process_registry.completion_queue.empty()
            gate.set()
            done_evt = wait_until(
                lambda: _take(process_registry, done["delegation_id"]),
                timeout=5, what="review delegation completion",
            )
        assert done_evt["results"][0]["status"] == "completed"
        assert done_evt["results"][0]["task_success"] is False
        assert done_evt["results"][0]["model"] == REVIEW
        text = format_process_notification(done_evt)
        assert "task_success=false" in text and REVIEW in text and marker in text

        db = SessionDB(tmp_path / "state.db")
        db.create_session("review-session", source="cli")
        db.append_message("review-session", role="assistant", content=text)
        db.create_session("work-session", source="cli")
        db.append_message("work-session", role="assistant", content=f"worker ran {WORK} on an unrelated note")
        found = json.loads(session_search(query=marker, db=db, detail="full"))
        assert found["success"] is True
        blob = json.dumps(found)
        assert marker in blob and REVIEW in blob and "task_success=false" in blob
        assert "work-session" not in blob
    finally:
        gate.set()
        wait_until(lambda: ad.active_count() == 0, timeout=5, what="async workers finished")
        ad._reset_for_tests()


def _take(process_registry, delegation_id):
    while not process_registry.completion_queue.empty():
        event = process_registry.completion_queue.get_nowait()
        if event.get("delegation_id") == delegation_id:
            return event
    return None
