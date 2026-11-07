"""A user plugin Doctor can register is still absent from a normal CLI until it is enabled.

Plugin Doctor imports the plugin directory directly. A normal CLI loads a user
plugin only when ``plugins.enabled`` names it. With the list empty, tool_describe
reports the names not_found. After the name is added, a fresh CLI tool list
can search, describe, and call them. A release that requires an owner decision
does not write its target until that decision exists.
"""

from __future__ import annotations

import json
from pathlib import Path

from hermes_cli.config import load_config
from hermes_cli.plugin_dev import doctor_plugin
from hermes_cli.plugins import _reset_plugin_managers_for_tests, discover_plugins
from hermes_cli.tools_config import _get_platform_tools
from model_tools import get_tool_definitions
from tools.registry import registry
from tools.tool_search import dispatch_tool_describe, dispatch_tool_search

PLUGIN = "local-fixed-role-tools"
TOOLSET = "local_fixed_roles"
RELEASE = "local_public_job_release"
NAMES = ("local_public_job_submit", "local_public_job_status", RELEASE)


def _install(home: Path) -> Path:
    plugin = home / "plugins" / PLUGIN
    plugin.mkdir(parents=True)
    (plugin / "plugin.yaml").write_text(
        "name: local-fixed-role-tools\n"
        "version: '1.0.0'\n"
        "description: Synthetic public job tools for CLI discovery.\n"
        "provides_tools:\n"
        "  - local_public_job_submit\n"
        "  - local_public_job_status\n"
        "  - local_public_job_release\n",
        encoding="utf-8",
    )
    (plugin / "__init__.py").write_text(
        "import json\n"
        "from pathlib import Path\n"
        "ROOT = Path(__file__).resolve().parent\n"
        "def _release(params, **kwargs):\n"
        "    job = str((params or {}).get('job_id') or '')\n"
        "    decision_path = ROOT / 'decisions' / (job + '.json')\n"
        "    target = ROOT / 'approved-local-release' / job / 'guide.md'\n"
        "    decision = json.loads(decision_path.read_text()) if decision_path.is_file() else None\n"
        "    if not (isinstance(decision, dict) and decision.get('job_id') == job\n"
        "            and decision.get('decision') == 'approve_local_release'):\n"
        "        return json.dumps({'executed': False, 'status': 'blocked',\n"
        "                           'reason': 'no matching owner decision'})\n"
        "    target.parent.mkdir(parents=True, exist_ok=True)\n"
        "    target.write_text('synthetic release\\n', encoding='utf-8')\n"
        "    return json.dumps({'executed': True, 'status': 'released'})\n"
        "def register(ctx):\n"
        "    specs = [\n"
        "        ('local_public_job_submit', lambda params, **kw: json.dumps({'ok': True, 'status': 'draft_only'})),\n"
        "        ('local_public_job_status', lambda params, **kw: json.dumps({'ok': True, 'status': 'read'})),\n"
        "        ('local_public_job_release', _release),\n"
        "    ]\n"
        "    for name, handler in specs:\n"
        "        ctx.register_tool(name=name, toolset='local_fixed_roles',\n"
        "            schema={'name': name, 'description': 'Synthetic public job tool ' + name,\n"
        "                    'parameters': {'type': 'object', 'properties': {'job_id': {'type': 'string'}},\n"
        "                                   'required': []}},\n"
        "            handler=handler)\n",
        encoding="utf-8",
    )
    return plugin


def _config(text: str) -> None:
    from hermes_constants import get_hermes_home
    path = get_hermes_home() / "config.yaml"
    path.write_text(text, encoding="utf-8")


def _cli_defs() -> list:
    _reset_plugin_managers_for_tests()
    discover_plugins(force=True)
    enabled = sorted(_get_platform_tools(load_config(), "cli"))
    return get_tool_definitions(
        enabled_toolsets=enabled, quiet_mode=True, skip_tool_search_assembly=True,
    ) or []


def _names(defs: list) -> set[str]:
    return {((td.get("function") or {}).get("name")) for td in defs}


def test_empty_enabled_list_hides_tools_doctor_still_registers(tmp_path):
    from hermes_constants import get_hermes_home
    plugin = _install(get_hermes_home())
    _config("plugins:\n  enabled: []\n")
    try:
        defs = _cli_defs()
        assert set(NAMES).isdisjoint(_names(defs))
        described = json.loads(dispatch_tool_describe({"names": list(NAMES)}, current_tool_defs=defs))
        assert set(described["not_found"]) == set(NAMES)
        report = doctor_plugin(plugin)
        assert report.ok
        assert set(report.registered_tools) == set(NAMES)
    finally:
        _reset_plugin_managers_for_tests()


def test_enabled_plugin_is_searchable_and_release_stays_unexecuted(tmp_path):
    from hermes_constants import get_hermes_home
    plugin = _install(get_hermes_home())
    _config("plugins:\n  enabled:\n    - local-fixed-role-tools\n")
    try:
        defs = _cli_defs()
        assert set(NAMES) <= _names(defs)
        found = json.loads(dispatch_tool_search(
            {"queries": ["local_public_job_release"]}, current_tool_defs=defs,
        ))
        assert RELEASE in found["tools"]
        described = json.loads(dispatch_tool_describe({"names": list(NAMES)}, current_tool_defs=defs))
        assert set(described["tools"]) == set(NAMES)
        assert "not_found" not in described

        blocked = json.loads(registry.dispatch(RELEASE, {"job_id": "job-synthetic"}))
        assert blocked["executed"] is False
        assert blocked["status"] == "blocked"
        assert not (plugin / "approved-local-release" / "job-synthetic" / "guide.md").exists()

        decision = plugin / "decisions" / "job-synthetic.json"
        decision.parent.mkdir()
        decision.write_text(
            json.dumps({"job_id": "job-synthetic", "decision": "approve_local_release"}),
            encoding="utf-8",
        )
        released = json.loads(registry.dispatch(RELEASE, {"job_id": "job-synthetic"}))
        assert released["executed"] is True
        assert (plugin / "approved-local-release" / "job-synthetic" / "guide.md").is_file()
    finally:
        _reset_plugin_managers_for_tests()
