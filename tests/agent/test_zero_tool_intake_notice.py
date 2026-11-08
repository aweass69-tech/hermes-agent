"""A model turn with no tool call is not a completed role intake.

The public 9680-character stand-in is not a private request. The diagnostic
records counters and the exit reason only.
"""

import json
from pathlib import Path
from types import SimpleNamespace

from agent.conversation_loop import _close_durable_failed_turn
from agent.iteration_budget import IterationBudget
from agent.turn_failure_copy import (
    FAILED_TURN_NOTICE, PARTIAL_FAILED_TURN_NOTICE, ZERO_TOOL_INTAKE_NOTICE,
    failed_turn_notice, intake_diagnostic, untyped_failed_turn_display_kind,
)
from hermes_state import SessionDB
from tools.delegate_tool_child_run import _SchemaOutcome, _build_result_entry

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "reviewed_workflow" / "role-intake.txt"


def _agent():
    return SimpleNamespace(iteration_budget=IterationBudget(6))


def _consume(agent, n):
    for _ in range(n):
        assert agent.iteration_budget.consume()


def test_long_role_intake_with_no_tools_is_not_complete_and_keeps_the_request():
    request = _FIXTURE.read_text(encoding="utf-8")
    assert len(request) == 9680
    assert "review_contract" in request and "output_schema" in request
    agent = _agent()
    _consume(agent, 6)
    messages = [{"role": "user", "content": request}]
    result = {
        "messages": messages, "api_calls": 6, "completed": False, "failed": False,
        "turn_exit_reason": "empty_response_exhausted", "final_response": "",
    }
    notice = failed_turn_notice(messages, result)
    diagnostic = intake_diagnostic(agent, result)
    assert notice == ZERO_TOOL_INTAKE_NOTICE
    assert "not complete" in notice
    assert "Send it again" not in notice
    assert diagnostic == {
        "turn_exit_reason": "empty_response_exhausted",
        "api_calls": 6,
        "budget_used": 6,
        "budget_max": 6,
        "tool_turns": 0,
        "tool_results": 0,
        "completed": False,
        "failed": False,
        "final_response_chars": 0,
    }
    blob = str(diagnostic)
    assert "HARBOR-17" not in blob and request[:40] not in blob
    assert messages[0]["content"] == request
    assert untyped_failed_turn_display_kind("assistant", notice) == "failed_turn"


def test_tool_bearing_budget_stop_stamps_the_closing_assistant_row(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    sid = "local-synthetic"
    db.create_session(sid, source="cli", model="gemma4:26b")
    child = json.dumps({
        "results": [{
            "status": "failed", "exit_reason": "error", "failure_reason": "empty_response",
            "schema_valid": False, "task_success": False, "model": "gemma4:12b", "api_calls": 5,
            "error": "PRIVATE child prose that must not be copied",
            "route": {"label": "work", "model": "gemma4:12b"},
        }],
    })
    summary = "I reached the iteration limit and couldn't generate a summary."
    db.append_message(sid, "user", content="PUBLIC SYNTHETIC ROLE INTAKE")
    db.append_message(sid, "tool", content=child, tool_name="delegate_task")
    db.append_message(sid, "assistant", content=summary)
    messages = [
        {"role": "user", "content": "PUBLIC SYNTHETIC ROLE INTAKE"},
        {"role": "tool", "name": "delegate_task", "content": child},
        {"role": "assistant", "content": summary},
    ]
    agent = SimpleNamespace(_session_db=db, session_id=sid, _persist_disabled=False, iteration_budget=IterationBudget(6))
    for _ in range(6):
        agent.iteration_budget.consume()
    result = {
        "messages": messages, "api_calls": 6, "completed": False, "failed": False,
        "turn_exit_reason": "max_iterations_reached(6/6)", "final_response": summary,
    }
    result["intake_diagnostic"] = intake_diagnostic(agent, result)
    _close_durable_failed_turn(agent, result)
    rows = db.get_messages(sid)
    assert [row["role"] for row in rows] == ["user", "tool", "assistant"]
    assert rows[-1]["content"] == summary
    diagnostic = rows[-1]["display_metadata"]["intake_diagnostic"]
    assert diagnostic["turn_exit_reason"] == "max_iterations_reached(6/6)"
    assert diagnostic["api_calls"] == 6 and diagnostic["budget_used"] == 6
    assert diagnostic["tool_results"] == 1 and diagnostic["completed"] is False
    assert diagnostic["delegate_outcomes"][0]["children"][0]["failure_reason"] == "empty_response"
    assert diagnostic["delegate_outcomes"][0]["children"][0]["route_label"] == "work"
    blob = json.dumps(diagnostic)
    assert "PRIVATE" not in blob and "PUBLIC SYNTHETIC" not in blob


def test_failed_child_is_not_schema_valid():
    entry = _build_result_entry(
        SimpleNamespace(),
        {"failed": True, "error": "provider down", "failure_reason": "server_error",
         "final_response": '{"status": "draft_written"}', "api_calls": 5, "completed": False},
        0, 0.1, _SchemaOutcome({"type": "object"}, True, [], 0),
    )
    assert entry["status"] == "failed"
    assert entry["schema_valid"] is False
    assert entry["task_success"] is False
    assert entry["failure_reason"] == "server_error"


def test_empty_exhaustion_records_whether_reasoning_was_discarded():
    from agent.turn_empty_response import empty_terminal_observation
    discarded = empty_terminal_observation(
        prefill_retries=2, empty_retries=3, reasoning_chars=400, finish_reason="stop",
    )
    assert discarded["reasoning_discarded"] is True
    assert discarded["thinking_prefill_retries"] == 2 and discarded["empty_content_retries"] == 3
    assert "400" not in str({k: v for k, v in discarded.items() if k != "reasoning_chars"})
    blank = empty_terminal_observation(
        prefill_retries=0, empty_retries=3, reasoning_chars=0, finish_reason="stop",
    )
    assert blank["reasoning_discarded"] is False
    agent = _agent()
    agent._empty_terminal_observation = discarded
    diagnostic = intake_diagnostic(agent, {
        "messages": [], "api_calls": 6, "completed": False, "failed": False,
        "turn_exit_reason": "empty_response_exhausted", "final_response": "x" * 137,
    })
    assert diagnostic["empty_observation"]["reasoning_discarded"] is True
    assert diagnostic["final_response_chars"] == 137
    assert diagnostic["failed"] is False


def test_no_call_keeps_the_original_notice_and_a_tool_call_stays_partial():
    assert failed_turn_notice([{"role": "user", "content": "hello"}], {"api_calls": 0}) == FAILED_TURN_NOTICE
    partial = [{"role": "assistant", "tool_calls": [{"id": "1"}]}, {"role": "tool", "content": "{}"}]
    assert failed_turn_notice(partial, {"api_calls": 6}) == PARTIAL_FAILED_TURN_NOTICE
