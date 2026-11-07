"""approvals.mode manual is read from config.yaml, not from a patched getter.

A direct terminal_tool call with no CLI, gateway, ask, cron, -q, or unattended
platform cannot prompt. A command the dangerous-pattern list flags must not
reach the executor. A bound interactive CLI still prompts through the real
approval callback. security.allow_lazy_installs is not that gate.

The shell is never started: the executor is replaced with a recorder so a
guard bug cannot delete the synthetic sentinel.
"""

from __future__ import annotations

import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from hermes_constants import get_hermes_home
from tools.approval import check_all_command_guards, detect_dangerous_command
from tools.terminal_tool import _ExecPlan, set_approval_callback, terminal_tool


def _write_config(text: str) -> None:
    home = get_hermes_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(text, encoding="utf-8")


def _quiet_env(monkeypatch):
    for key in (
        "HERMES_INTERACTIVE", "HERMES_EXEC_ASK", "HERMES_GATEWAY_SESSION",
        "HERMES_SESSION_PLATFORM", "HERMES_CRON_SESSION", "HERMES_YOLO_MODE",
        "HERMES_SINGLE_QUERY",
    ):
        monkeypatch.delenv(key, raising=False)
    set_approval_callback(None)


@pytest.fixture
def recorder(monkeypatch):
    calls = []

    def _foreground(command, env, plan, **_kwargs):
        calls.append(command)
        return json.dumps({"output": "ran", "exit_code": 0})

    plan = _ExecPlan(
        config={}, env_type="local", effective_task_id="manual-surface", image="",
        cwd="/tmp", host_cwd=None, effective_timeout=30,
    )
    monkeypatch.setattr("tools.terminal_tool._plan_execution", lambda *a, **k: plan)
    monkeypatch.setattr("tools.terminal_tool._acquire_env", lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr("tools.terminal_tool._pre_exec_block", lambda *a, **k: None)
    monkeypatch.setattr("tools.terminal_tool._call_in_flight", lambda *a, **k: nullcontext())
    monkeypatch.setattr("tools.terminal_tool._run_foreground", _foreground)
    return calls


def test_rm_rf_of_a_sentinel_is_classified_dangerous_and_is_not_hardline(tmp_path):
    sentinel = tmp_path / "approval-disposable-sentinel"
    command = f"rm -rf {sentinel}"
    flagged, _key, description = detect_dangerous_command(command)
    # An absolute path matches "delete in root path"; a relative path matches
    # "recursive delete". Neither is the hardline wipe of the filesystem root.
    assert flagged is True
    assert "delete" in description
    assert "root filesystem" not in description


def test_manual_config_blocks_before_execution_when_nothing_can_prompt(monkeypatch, tmp_path, recorder):
    _quiet_env(monkeypatch)
    _write_config("approvals:\n  mode: manual\nsecurity:\n  allow_lazy_installs: false\n")
    sentinel = tmp_path / "approval-disposable-sentinel"
    sentinel.mkdir()
    (sentinel / "marker").write_text("synthetic", encoding="utf-8")
    command = f"rm -rf {sentinel}"

    decision = check_all_command_guards(command, "local")
    assert decision["approved"] is False
    assert "manual" in decision["message"]
    assert "not run" in decision["message"]

    result = json.loads(terminal_tool(command, force=False, task_id="t-manual-no-surface"))
    assert recorder == []
    assert result.get("status") == "blocked"
    assert sentinel.is_dir() and (sentinel / "marker").read_text(encoding="utf-8") == "synthetic"


def test_manual_config_still_runs_a_command_that_is_not_flagged(monkeypatch, recorder):
    _quiet_env(monkeypatch)
    _write_config("approvals:\n  mode: manual\n")
    command = "printf synthetic-ok"
    assert detect_dangerous_command(command)[0] is False
    assert check_all_command_guards(command, "local")["approved"] is True
    result = json.loads(terminal_tool(command, force=False, task_id="t-manual-benign"))
    assert recorder == [command]
    assert "ran" in json.dumps(result)


def test_cron_approve_still_allows_under_manual_and_cron_deny_blocks(monkeypatch):
    _quiet_env(monkeypatch)
    monkeypatch.setenv("HERMES_CRON_SESSION", "1")
    command = "rm -rf /tmp/hermes-synthetic-cron-sentinel"
    _write_config("approvals:\n  mode: manual\n  cron_mode: approve\n")
    assert check_all_command_guards(command, "local")["approved"] is True
    _write_config("approvals:\n  mode: manual\n  cron_mode: deny\n")
    denied = check_all_command_guards(command, "local")
    assert denied["approved"] is False
    assert "cron" in denied["message"]


def test_smart_without_a_surface_does_not_use_this_manual_block(monkeypatch):
    """Default smart mode does not consult an auxiliary model on a bare terminal_tool call.

    It still allows a flagged command when no named headless context is active.
    That is not what approvals.mode manual does.
    """
    _quiet_env(monkeypatch)
    _write_config("approvals:\n  mode: smart\n")
    decision = check_all_command_guards("rm -rf /tmp/hermes-synthetic-smart-sentinel", "local")
    assert decision["approved"] is True


def test_bound_cli_manual_config_denies_and_then_approves_once(monkeypatch, tmp_path, recorder):
    _quiet_env(monkeypatch)
    monkeypatch.setenv("HERMES_INTERACTIVE", "1")
    _write_config("approvals:\n  mode: manual\n")
    sentinel = tmp_path / "approval-disposable-sentinel"
    sentinel.mkdir()
    command = f"rm -rf {sentinel}"
    answers = iter(("deny", "once"))

    def decide(seen, description, **_kwargs):
        assert recorder == []
        assert seen == command
        return next(answers)

    set_approval_callback(decide)
    denied = json.loads(terminal_tool(command, force=False, task_id="t-manual-cli"))
    assert recorder == []
    assert denied.get("status") == "blocked"
    assert sentinel.is_dir()

    recorder.clear()
    approved = json.loads(terminal_tool(command, force=False, task_id="t-manual-cli"))
    assert recorder == [command]
    assert "ran" in json.dumps(approved)
