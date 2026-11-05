"""Pinned Hermes model_tools selection; registry resolution is explicit test data.

Source: NousResearch/hermes-agent@71d34bad/model_tools.py.
The two SDK function bodies below are unchanged. The wrapper supplies resolved
fixture toolsets; it does not claim to load a complete SDK or real builtin schemas.
"""
import logging
import builtins
import os
from types import FunctionType, ModuleType, SimpleNamespace
from typing import Optional
from unittest.mock import patch

SOURCE_SHA256 = '872ca571c17379c8df19c0bcf639919bb0cb3a2706efc08e4dc6a1f3d8789662'

def _apply_toolset_selection(tools: set, names: list[str], quiet_mode: bool, *, disable: bool) -> None:
    """Add (or subtract) every toolset in *names* to/from *tools*, printing the selection unless quiet."""
    from toolsets import bundle_non_core_tools, get_toolset
    verb, icon = ("Disabled", "🚫") if disable else ("Enabled", "✅")
    for name in names:
        if validate_toolset(name):
            label = f"{verb} toolset"
            if disable and (name.startswith("hermes-") or (get_toolset(name) or {}).get("posture")):
                # Bundles/postures re-list the core tools without owning them;
                # subtracting the whole set would empty the list — remove only the non-core delta.
                resolved = sorted(bundle_non_core_tools(name))
                if not quiet_mode and name.startswith("hermes-") and name not in _WARNED_DISABLED_BUNDLES:
                    _WARNED_DISABLED_BUNDLES.add(name)
                    logger.info(
                        "agent.disabled_toolsets contains platform-bundle name '%s'; core tools are "
                        "preserved and only its platform-specific tools (%s) are removed. Bundle names "
                        "usually belong in `toolsets:`, not `disabled_toolsets` (#33924).",
                        name, ", ".join(resolved) if resolved else "none",
                    )
            else:
                resolved = resolve_toolset(name)
        elif name in _LEGACY_TOOLSET_MAP:
            label = f"{verb} legacy toolset"
            resolved = _LEGACY_TOOLSET_MAP[name]
        else:
            if not quiet_mode:
                print(f"⚠️  Unknown toolset: {name}")
            continue
        (tools.difference_update if disable else tools.update)(resolved)
        if not quiet_mode:
            print(f"{icon} {label} '{name}': {', '.join(resolved) if resolved else 'no tools'}")

def _select_tool_names(enabled_toolsets: Optional[list[str]], disabled_toolsets: Optional[list[str]], quiet_mode: bool) -> set:
    """Tool names requested by the toolset selection (before check_fn filtering)."""
    tools: set = set()
    if enabled_toolsets is not None:
        enabled = list(enabled_toolsets)
        # Dispatcher-spawned kanban workers always get the lifecycle handoff
        # tools, even when the assignee profile restricts its chat toolsets.
        if (os.environ.get("HERMES_KANBAN_TASK") and not _is_delegated_child_context()
                and _is_dispatcher_owned_worker() and "kanban" not in enabled):
            enabled.append("kanban")
        _apply_toolset_selection(tools, enabled, quiet_mode, disable=False)
    else:
        from toolsets import TOOLSET_SESSION_PLATFORMS, get_all_toolsets
        for ts_name in get_all_toolsets():
            if ts_name not in TOOLSET_SESSION_PLATFORMS:
                tools.update(resolve_toolset(ts_name))
    # Disabled toolsets are always subtracted LAST, so a tool in a disabled
    # toolset is stripped even when a composite (hermes-cli) re-enables it.
    # This ensures that even if a composite toolset (like hermes-cli) is enabled, any tools belonging to a
    # disabled toolset are strictly stripped out. See issue #17309.
    if disabled_toolsets:
        _apply_toolset_selection(tools, disabled_toolsets, quiet_mode, disable=True)
    return tools

def select_resolved_tool_names(enabled, disabled, resolved):
    namespace = dict(__builtins__=builtins.__dict__, os=SimpleNamespace(environ={}),
                     logger=logging.getLogger(__name__),
                     _LEGACY_TOOLSET_MAP={}, _WARNED_DISABLED_BUNDLES=set(),
                     resolve_toolset=lambda name:list(resolved[name]),
                     validate_toolset=lambda name:name in resolved)
    for original in (_apply_toolset_selection, _select_tool_names):
        namespace[original.__name__] = FunctionType(original.__code__,namespace,
            original.__name__,original.__defaults__,original.__closure__)
    module = ModuleType('toolsets')
    module.get_toolset = lambda name:({'tools':resolved[name]} if name in resolved else None)
    module.bundle_non_core_tools = lambda name:set(resolved[name])
    with patch.dict('sys.modules', {'toolsets':module}):
        return namespace['_select_tool_names'](enabled,disabled,True)
