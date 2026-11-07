"""A dangerous command is not executed until a person approves that scope.

The prompt callback runs before the process. Deny and an unanswered prompt
leave the executor uncalled. ``once`` runs it once. ``session`` runs it again
later without a second prompt. A blocked result is not itself the gate.
"""

from __future__ import annotations

import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

import tools.approval as approval_module
from tools import approval_context
from tools.terminal_tool import _ExecPlan, set_approval_callback, terminal_tool


COMMAND = "rm -rf /tmp/hermes-synthetic-approval-probe"


@pytest.fixture(autouse=True)
def _manual_cli(monkeypatch):
    for key in (
        "HERMES_EXEC_ASK", "HERMES_GATEWAY_SESSION", "HERMES_SESSION_PLATFORM",
        "HERMES_CRON_SESSION", "HERMES_YOLO_MODE",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HERMES_INTERACTIVE", "1")
    monkeypatch.setattr(approval_module, "_YOLO_MODE_FROZEN", False)
    monkeypatch.setattr(approval_context, "_get_approval_mode", lambda: "manual")
    approval_module._session_approved.clear()
    approval_module._permanent_approved.clear()
    approval_module._pending.clear()
    approval_module._denial_tally.clear()
    set_approval_callback(None)
    token = approval_context.set_current_session_key("synthetic-approval-session")
    yield
    approval_context.reset_current_session_key(token)
    approval_module._denial_tally.clear()
    approval_module._session_approved.clear()
    set_approval_callback(None)


@pytest.fixture
def executed(monkeypatch):
    calls = []

    def _foreground(command, env, plan, **_kwargs):
        calls.append(command)
        return json.dumps({"output": "ran", "exit_code": 0})

    plan = _ExecPlan(
        config={}, env_type="local", effective_task_id="approval-task", image="",
        cwd="/tmp", host_cwd=None, effective_timeout=30,
    )
    monkeypatch.setattr("tools.terminal_tool._plan_execution", lambda *a, **k: plan)
    monkeypatch.setattr("tools.terminal_tool._acquire_env", lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr("tools.terminal_tool._pre_exec_block", lambda *a, **k: None)
    monkeypatch.setattr("tools.terminal_tool._call_in_flight", lambda *a, **k: nullcontext())
    monkeypatch.setattr("tools.terminal_tool._run_foreground", _foreground)
    return calls


def _run():
    return json.loads(terminal_tool(COMMAND, task_id="approval-task"))


def test_denied_command_has_not_started_when_the_prompt_is_open_or_after_denial(executed):
    def decide(command, description, **_kwargs):
        assert executed == []
        assert command == COMMAND
        return "deny"

    set_approval_callback(decide)
    result = _run()
    assert executed == []
    assert result.get("status") == "blocked"
    assert "ran" not in json.dumps(result)


def test_once_approval_runs_the_command_and_does_not_stick(executed):
    answers = iter(("once", "deny"))

    def decide(command, description, **_kwargs):
        assert executed == []
        return next(answers)

    set_approval_callback(decide)
    first = _run()
    assert executed == [COMMAND]
    assert "ran" in json.dumps(first)
    executed.clear()
    second = _run()
    assert executed == []
    assert second.get("status") == "blocked"


def test_session_approval_runs_now_and_again_without_another_prompt(executed):
    prompts = []

    def decide(command, description, **_kwargs):
        prompts.append(command)
        assert executed == []
        return "session"

    set_approval_callback(decide)
    first = _run()
    second = _run()
    assert prompts == [COMMAND]
    assert executed == [COMMAND, COMMAND]
    assert "ran" in json.dumps(first) and "ran" in json.dumps(second)
