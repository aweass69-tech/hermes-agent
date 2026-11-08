"""An already-enabled plugin's new register() stays out of the CLI catalog until re-import.

The native CLI catalog is the process that already called discover_plugins(). A later
edit of the plugin directory is what Plugin Doctor loads. A non-forced discovery
returns immediately, so tool_search still sees the original tools. The running
gateway's reload-plugins verb is discover_plugins(force=True). hermes plugins enable
of a plugin that is already enabled asks that gateway to re-import.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_cli.config import load_config
from hermes_cli.plugin_dev import doctor_plugin
from hermes_cli.plugins import _reset_plugin_managers_for_tests, discover_plugins, get_plugin_manager
from hermes_cli.tools_config import _get_platform_tools
from model_tools import get_tool_definitions
from tools.tool_search import dispatch_tool_describe, dispatch_tool_search

PLUGIN = "local-fixed-role-tools"
OTHER = "other-probe"
OLD = ("local_source_work", "local_source_review")
NEW = ("local_public_job_submit", "local_public_job_status", "local_public_job_release")
OTHER_TOOL = "other_probe_ping"


def _tool_module(names: tuple[str, ...], toolset: str) -> str:
    listed = ", ".join(repr(name) for name in names)
    return (
        "import json\n"
        f"def register(ctx):\n"
        f"    for name in ({listed},):\n"
        f"        ctx.register_tool(name=name, toolset={toolset!r},\n"
        "            schema={'name': name, 'description': 'Synthetic ' + name,\n"
        "                    'parameters': {'type': 'object', 'properties': {}, 'required': []}},\n"
        "            handler=lambda params, **kw: json.dumps({'ok': True}))\n"
    )


def _write_plugin(root: Path, name: str, init: str, tools: tuple[str, ...]) -> Path:
    plugin = root / "plugins" / name
    plugin.mkdir(parents=True, exist_ok=True)
    provides = "".join(f"  - {tool}\n" for tool in tools)
    (plugin / "plugin.yaml").write_text(
        f"name: {name}\nversion: '1.0.0'\ndescription: synthetic\nprovides_tools:\n{provides}",
        encoding="utf-8",
    )
    (plugin / "__init__.py").write_text(init, encoding="utf-8")
    return plugin


def _install_v1(home: Path) -> Path:
    fixed = home / "plugins" / PLUGIN
    fixed.mkdir(parents=True)
    (fixed / "fixed_roles.py").write_text(_tool_module(OLD, "local_fixed_roles"), encoding="utf-8")
    plugin = _write_plugin(
        home, PLUGIN,
        "from .fixed_roles import register as register_fixed\n"
        "def register(ctx):\n"
        "    register_fixed(ctx)\n",
        OLD,
    )
    _write_plugin(home, OTHER, _tool_module((OTHER_TOOL,), "other_probe"), (OTHER_TOOL,))
    return plugin


def _upgrade_v2(plugin: Path) -> None:
    (plugin / "public_board.py").write_text(_tool_module(NEW, "local_fixed_roles"), encoding="utf-8")
    (plugin / "__init__.py").write_text(
        "from .fixed_roles import register as register_fixed\n"
        "from .public_board import register as register_board\n"
        "def register(ctx):\n"
        "    register_fixed(ctx)\n"
        "    register_board(ctx)\n",
        encoding="utf-8",
    )
    (plugin / "plugin.yaml").write_text(
        "name: local-fixed-role-tools\nversion: '1.1.0'\ndescription: synthetic\nprovides_tools:\n"
        + "".join(f"  - {name}\n" for name in (*OLD, *NEW)),
        encoding="utf-8",
    )


def _config(text: str) -> None:
    from hermes_constants import get_hermes_home
    (get_hermes_home() / "config.yaml").write_text(text, encoding="utf-8")


def _cli_names() -> set[str]:
    enabled = sorted(_get_platform_tools(load_config(), "cli"))
    defs = get_tool_definitions(
        enabled_toolsets=enabled, quiet_mode=True, skip_tool_search_assembly=True,
    ) or []
    return {((td.get("function") or {}).get("name")) for td in defs}


def _search_new(names: set[str]) -> dict:
    defs = get_tool_definitions(
        enabled_toolsets=sorted(_get_platform_tools(load_config(), "cli")),
        quiet_mode=True, skip_tool_search_assembly=True,
    ) or []
    assert names <= {((td.get("function") or {}).get("name")) for td in defs} or names == set()
    return {
        "search": json.loads(dispatch_tool_search(
            {"queries": [" ".join(NEW)]}, current_tool_defs=defs,
        )),
        "describe": json.loads(dispatch_tool_describe({"names": list(NEW)}, current_tool_defs=defs)),
    }


@pytest.fixture
def enabled_home():
    from hermes_constants import get_hermes_home
    home = get_hermes_home()
    plugin = _install_v1(home)
    _config("plugins:\n  enabled:\n    - local-fixed-role-tools\n    - other-probe\n")
    _reset_plugin_managers_for_tests()
    try:
        discover_plugins(force=True)
        yield home, plugin
    finally:
        manager = get_plugin_manager()
        host = getattr(manager, "_plugin_host_instance", None)
        _reset_plugin_managers_for_tests()
        if host is not None:
            host.shutdown()


def test_enabled_plugin_keeps_the_booted_register_until_force_reload(enabled_home):
    home, plugin = enabled_home
    assert set(OLD) <= _cli_names()
    assert OTHER_TOOL in _cli_names()
    assert set(NEW).isdisjoint(_cli_names())

    _upgrade_v2(plugin)
    report = doctor_plugin(plugin)
    assert report.ok
    assert set(report.registered_tools) == set(OLD) | set(NEW)

    discover_plugins()
    stale = _search_new(set())
    assert set(NEW).isdisjoint(_cli_names())
    assert set(OLD) <= _cli_names()
    assert stale["search"]["tools"] == {}
    assert set(stale["describe"]["not_found"]) == set(NEW)

    discover_plugins(force=True)
    fresh = _search_new(set(NEW))
    one = json.loads(dispatch_tool_search(
        {"queries": ["local_public_job_submit"]},
        current_tool_defs=get_tool_definitions(
            enabled_toolsets=sorted(_get_platform_tools(load_config(), "cli")),
            quiet_mode=True, skip_tool_search_assembly=True,
        ) or [],
    ))
    assert set(OLD) | set(NEW) <= _cli_names()
    assert OTHER_TOOL in _cli_names()
    assert "local_public_job_submit" in one["tools"]
    assert set(fresh["describe"]["tools"]) == set(NEW)
    assert "not_found" not in fresh["describe"]
    assert home.joinpath("config.yaml").read_text(encoding="utf-8").count("local-fixed-role-tools") == 1


@pytest.mark.platforms("posix")
def test_host_isolation_reimports_the_sibling_register(enabled_home, monkeypatch):
    from hermes_cli import plugins as plugins_mod
    home, plugin = enabled_home
    _config(
        "plugins:\n  enabled:\n    - local-fixed-role-tools\n    - other-probe\n"
        "  isolation: host\n",
    )
    empty = home / "bundled-empty"
    empty.mkdir()
    monkeypatch.setattr(plugins_mod, "get_bundled_plugins_dir", lambda: empty)
    _reset_plugin_managers_for_tests()
    discover_plugins(force=True)
    assert set(OLD) <= _cli_names()
    assert set(NEW).isdisjoint(_cli_names())

    _upgrade_v2(plugin)
    assert doctor_plugin(plugin).ok
    assert set(doctor_plugin(plugin).registered_tools) == set(OLD) | set(NEW)
    discover_plugins()
    assert set(NEW).isdisjoint(_cli_names())

    discover_plugins(force=True)
    assert set(OLD) | set(NEW) <= _cli_names()
    assert OTHER_TOOL in _cli_names()


def test_enable_of_an_already_enabled_plugin_reimports_the_gateway(tmp_path, monkeypatch, capsys):
    from hermes_cli import plugins_cmd
    from hermes_cli.config import save_config

    home = tmp_path / "hermes-home"
    plugin_dir = home / "plugins" / "probe"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.yaml").write_text("name: probe\nversion: '1.0'\n", encoding="utf-8")
    (plugin_dir / "__init__.py").write_text("def register(ctx):\n    pass\n", encoding="utf-8")
    (home / "config.yaml").write_text("plugins:\n  enabled: [probe]\n  disabled: []\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))

    def admit(enabled, disabled, **_kwargs):
        cfg = load_config()
        cfg["plugins"] = {"enabled": sorted(enabled), "disabled": sorted(disabled)}
        save_config(cfg)

    monkeypatch.setattr("hermes_cli.plugins_admission.admit_plugin_set_change", admit)
    calls = []

    def reload_gateway_plugins(target, *, profile_home=None, timeout=30.0):
        calls.append(Path(target))
        return {"reloaded": True, "plugins": ["probe"], "activations": []}

    monkeypatch.setattr("gateway.control_socket.reload_gateway_plugins", reload_gateway_plugins)
    before = (home / "config.yaml").read_bytes()
    plugins_cmd.cmd_enable("probe")
    out = capsys.readouterr().out
    assert calls and calls[0].resolve() == home.resolve()
    assert (home / "config.yaml").read_bytes() == before
    assert "already enabled" in out
    assert "re-imported" in out
    assert "/tools" in out
