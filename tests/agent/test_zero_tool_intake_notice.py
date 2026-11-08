"""A model turn with no tool call is not a completed role intake.

The public 9680-character stand-in is not a private request. The diagnostic
records counters and the exit reason only.
"""

from pathlib import Path
from types import SimpleNamespace

from agent.iteration_budget import IterationBudget
from agent.turn_failure_copy import (
    FAILED_TURN_NOTICE, PARTIAL_FAILED_TURN_NOTICE, ZERO_TOOL_INTAKE_NOTICE,
    failed_turn_notice, intake_diagnostic, untyped_failed_turn_display_kind,
)

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


def test_no_call_keeps_the_original_notice_and_a_tool_call_stays_partial():
    assert failed_turn_notice([{"role": "user", "content": "hello"}], {"api_calls": 0}) == FAILED_TURN_NOTICE
    partial = [{"role": "assistant", "tool_calls": [{"id": "1"}]}, {"role": "tool", "content": "{}"}]
    assert failed_turn_notice(partial, {"api_calls": 6}) == PARTIAL_FAILED_TURN_NOTICE
