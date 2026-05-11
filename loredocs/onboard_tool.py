"""Core logic for the loredocs_onboard MCP tool.

Creates or updates an initial vault configuration so new users have a
ready-to-use workspace with a Config vault, optional domain vaults, and
optional agent report vaults.
"""

import datetime
from typing import List, Optional

from .storage import VaultStorage


def _generate_reference_doc(
    name: str,
    domains: List[str],
    agents: List[str],
    tag_style: str,
) -> str:
    lines = [
        "# My LoreDocs Setup",
        f"Workspace: {name}",
        f"Last updated: {datetime.date.today()}",
        "",
        "## Vaults",
        "- Config: Setup and reference documents (this vault)",
    ]
    for d in domains:
        lines.append(f"- {d}: {d.title()} documents")
    for a in agents:
        lines.append(f"- {a.title()} Reports: Outputs from the {a} agent")

    lines += [
        "",
        "## Tag Conventions",
        "Use tags to cross-reference documents across vaults:",
        "- Domain tags: finance, legal, research, ...",
        "- Date tags: 2025, 2026",
        "- Status tags: current, superseded",
    ]

    if tag_style == "detailed":
        lines += [
            "- Priority tags: high, medium, low",
            "- Agent tags: agent:name",
        ]

    lines += [
        "",
        "## Categories",
        "- reference: Source of truth -- pair with authoritative priority",
        "- report: Generated outputs (QA, security, analytics)",
        "- template: Reusable document templates",
        "- config: Setup and configuration docs",
        "- archive: Historical / superseded docs",
        "- general: Everything else",
        "",
        "## Priority Guide",
        "- authoritative: Source of truth, do not edit without review",
        "- normal: Standard working document",
        "- draft: Work in progress",
        "- outdated: No longer current -- candidate for archive",
    ]

    if agents:
        lines += ["", "## Agents"]
        for a in agents:
            lines.append(f"- {a}: Stores outputs in '{a.title()} Reports' vault")

    return "\n".join(lines)


def _find_or_create_vault(storage: VaultStorage, name: str,
                           description: str = "") -> dict:
    """Return existing vault by name or create a new one."""
    vault = storage.find_vault_by_name(name)
    if vault is None:
        vault = storage.create_vault(name, description=description)
    return vault


def _find_setup_doc(storage: VaultStorage, vault_id: str) -> Optional[dict]:
    """Find the 'My LoreDocs Setup' document in a vault."""
    listing = storage.list_documents(vault_id)
    for doc in listing["documents"]:
        if doc["name"] == "My LoreDocs Setup":
            return storage.get_document(doc["id"])
    return None


def run_onboard(
    storage: VaultStorage,
    name: Optional[str] = None,
    domains: Optional[List[str]] = None,
    agents: Optional[List[str]] = None,
    tag_style: str = "simple",
) -> str:
    """Set up or refresh an initial LoreDocs workspace.

    Creates:
    - A 'Config' vault with a reference setup document
    - One vault per domain (if domains provided)
    - One '[Name] Reports' vault per agent (if agents provided)

    Idempotent: calling again updates the setup doc without duplicating vaults.

    Returns a summary string describing what was created or updated.
    """
    ws_name = name or "My Workspace"
    domains = domains or []
    agents = agents or []

    # Find or create Config vault
    config_vault = _find_or_create_vault(
        storage, "Config",
        description="Setup and reference documents"
    )

    # Find or create domain vaults
    for domain in domains:
        _find_or_create_vault(storage, domain,
                              description=f"{domain.title()} documents")

    # Find or create agent vaults ("[Name] Reports")
    for agent in agents:
        vault_name = f"{agent.title()} Reports"
        _find_or_create_vault(storage, vault_name,
                              description=f"Outputs from the {agent} agent")

    # Generate reference doc content
    ref_content = _generate_reference_doc(ws_name, domains, agents, tag_style)

    # Find existing setup doc -- update if present, create if not
    existing_doc = _find_setup_doc(storage, config_vault["id"])
    if existing_doc is not None:
        storage.update_document(
            existing_doc["id"],
            content=ref_content.encode("utf-8"),
        )
        doc_id = existing_doc["id"]
        action = "updated"
    else:
        doc = storage.add_document_from_text(
            config_vault["id"],
            "My LoreDocs Setup",
            ref_content,
            filename="my_loredocs_setup.md",
            tags=["config", "setup"],
            category="config",
            priority="authoritative",
        )
        doc_id = doc["id"]
        action = "created"

    parts = [
        f"Config vault: {config_vault['id']}",
        f"My LoreDocs Setup doc ({action}): {doc_id}",
    ]
    if domains:
        parts.append(f"Domain vaults: {', '.join(domains)}")
    if agents:
        parts.append(f"Agent vaults: {', '.join(f'{a.title()} Reports' for a in agents)}")

    return "\n".join(parts)
