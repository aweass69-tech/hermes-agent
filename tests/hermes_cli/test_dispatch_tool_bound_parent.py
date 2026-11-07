"""ctx.dispatch_tool uses the turn-bound parent when no CLI agent is attached."""

from __future__ import annotations

from agent.subagent_lifecycle import bind_subagent_parent
from hermes_cli.plugins import PluginContext, PluginManager, PluginManifest
from tools.registry import registry


def test_dispatch_tool_passes_the_turn_bound_parent_without_a_cli_ref():
    manager = PluginManager()
    assert manager._cli_ref is None
    ctx = PluginContext(PluginManifest(name="synthetic-plugin", source="user"), manager)
    parent = object()
    seen = {}

    def handler(args, parent_agent=None):
        seen["parent"] = parent_agent
        return "{}"

    registry.register(
        name="_synthetic_dispatch_parent", toolset="delegation",
        schema={"name": "_synthetic_dispatch_parent", "description": "probe",
                "parameters": {"type": "object", "properties": {}}},
        handler=handler,
    )
    try:
        with bind_subagent_parent(parent):
            assert ctx.dispatch_tool("_synthetic_dispatch_parent", {}) == "{}"
        assert seen["parent"] is parent
        assert ctx.dispatch_tool("_synthetic_dispatch_parent", {}) == "{}"
        assert seen["parent"] is None
    finally:
        registry.deregister("_synthetic_dispatch_parent")
