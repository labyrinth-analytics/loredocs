"""Configurable MCP tool groups for LoreDocs.

Single source of truth for the group -> tool assignment.  Imported by
``server.py`` (startup gating) and ``scripts/check_tool_group_coverage.py``
(coverage enforcement).

Resolution order (PART:interfaces):
  1. ``LOREDOCS_TOOL_GROUPS`` env var (comma-separated) -- wins if set.
  2. ``tool_groups`` key in ``~/.loredocs/config.json``.
  3. All groups on (upgrade-safe default).

Malformed config fails *closed* to ``core`` + ``ALWAYS_ON`` only (the minimum
floor), never to all-on.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# -- Always-on tools (never removed by group gating) -------------------------

ALWAYS_ON: set[str] = {"get_server_info", "configure_tools"}

# -- Group -> tool assignment ------------------------------------------------

TOOL_GROUPS: dict[str, tuple[str, ...]] = {
    "core": (
        "vault_create",
        "vault_add_doc",
        "vault_get_doc",
        "vault_update_doc",
        "vault_remove_doc",
        "vault_list",
        "vault_list_docs",
        "vault_search",
        "vault_info",
    ),
    "organize": (
        "vault_bulk_tag",
        "vault_categorize",
        "vault_tag_doc",
        "vault_search_by_tag",
        "vault_link_doc",
        "vault_unlink_doc",
        "vault_find_related",
        "vault_copy_doc",
    ),
    "injection": (
        "vault_inject",
        "vault_inject_by_tag",
        "vault_inject_summary",
        "vault_get_injection_cap",
        "vault_link_session",
        "vault_get_linked_sessions",
        "vault_get_session_links",
        "vault_get_session_token",
    ),
    "history": (
        "vault_doc_history",
        "vault_doc_restore",
        "vault_archive",
        "vault_delete",
        "vault_verify",
        "vault_move_doc",
    ),
    "import_export": (
        "vault_export",
        "vault_export_manifest",
        "vault_import_dir",
        "vault_import_notion_setup",
        "vault_import_notion",
    ),
    "admin": (
        "get_license_tier",
        "loredocs_onboard",
        "vault_add_note",
        "vault_estimate_tokens",
        "vault_get_server_capabilities",
        "vault_link_project",
        "vault_open_workspace",
        "vault_prime",
        "vault_rebuild_index",
        "vault_rebuild_index_status",
        "vault_set_priority",
        "vault_set_tier",
        "vault_suggest",
        "vault_tier_status",
        "vault_set_injection_cap",
    ),
}

# Tools that are conditionally registered (not always present in the live
# FastMCP app).  The coverage checker excludes these from the "must be live"
# side of its set comparison.
#
# vault_import_notion     -- registered only when the notion extra is installed
# vault_set_injection_cap -- registered only when LOREDOCS_ENABLE_CAP_TOOLS=1
CONDITIONAL_TOOLS: set[str] = {"vault_import_notion", "vault_set_injection_cap"}

_ENV_VAR = "LOREDOCS_TOOL_GROUPS"


# -- Registry self-consistency (runs at import time) -------------------------


def _validate_registry() -> None:
    """Every name across ALWAYS_ON and all TOOL_GROUPS values is unique."""
    seen: dict[str, str] = {}
    for label, names in {"ALWAYS_ON": tuple(ALWAYS_ON), **TOOL_GROUPS}.items():
        for n in names:
            if n in seen:
                raise ValueError(
                    f"{n} duplicated in {seen[n]!r} and {label!r}"
                )
            seen[n] = label


_validate_registry()


# -- Public API ---------------------------------------------------------------


def all_tool_names() -> set[str]:
    """Return every tool name known to the registry (always-on + grouped)."""
    return set(ALWAYS_ON) | {n for tools in TOOL_GROUPS.values() for n in tools}


def classify_tool(name: str) -> str:
    """Return the owning group name, or the literal ``"ALWAYS_ON"``.

    Raises ``KeyError`` if *name* has no assignment anywhere, or ``ValueError``
    if *name* is assigned more than once (ALWAYS_ON + a group, or two groups) --
    both are registry bugs, not valid inputs.
    """
    in_always_on = name in ALWAYS_ON
    hits = [g for g, tools in TOOL_GROUPS.items() if name in tools]
    if in_always_on and hits:
        raise ValueError(f"{name} is in both ALWAYS_ON and group(s) {hits}")
    if in_always_on:
        return "ALWAYS_ON"
    if len(hits) == 0:
        raise KeyError(f"{name} has no group assignment")
    if len(hits) > 1:
        raise ValueError(f"{name} is assigned to multiple groups: {hits}")
    return hits[0]


def validate_group_names(names: list[str]) -> list[str]:
    """Validate a user-supplied list of group names.

    Returns the validated, deduplicated list.  Raises ``ValueError`` with the
    set of valid names if any entry is not a known group.
    """
    valid = set(TOOL_GROUPS.keys())
    unknown = [n for n in names if n not in valid]
    if unknown:
        raise ValueError(
            f"Unknown group name(s): {unknown}. "
            f"Valid groups: {sorted(valid)}"
        )
    # Deduplicate, preserve order.
    seen: set[str] = set()
    result: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            result.append(n)
    return result


def resolve_enabled_groups(config_path: Path | None = None) -> set[str]:
    """Resolve which optional groups are enabled (always includes ``core``).

    Resolution order: env var > config.json > all on.  Malformed config or
    unknown group names fail *closed* to ``{"core"}`` only.
    """
    # 1. Env var
    env_val = os.environ.get(_ENV_VAR)
    if env_val is not None:
        names = [g.strip() for g in env_val.split(",") if g.strip()]
        try:
            validated = validate_group_names(names)
        except ValueError:
            return {"core"}
        if not validated:
            return {"core"}
        return set(validated) | {"core"}

    # 2. Config file
    if config_path is not None and config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            return {"core"}
        raw = config.get("tool_groups")
        if "tool_groups" not in config:
            # Absent key = all on (upgrade-safe default).
            return set(TOOL_GROUPS.keys())
        if not isinstance(raw, list):
            return {"core"}
        if len(raw) == 0:
            return {"core"}
        try:
            validated = validate_group_names(raw)
        except ValueError:
            return {"core"}
        return set(validated) | {"core"}

    # 3. All on
    return set(TOOL_GROUPS.keys())