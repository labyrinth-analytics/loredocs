#!/usr/bin/env python3
"""
LoreDocs MCP Server

Knowledge management for AI projects -- search, tag, version, and organize
your project knowledge across Claude Code and Cowork.

Usage:
    python -m loredocs.server          # stdio transport (default)
    loredocs                           # via installed entry point
"""

import hmac
import json
import os
import re
import sys
import time
import uuid
import warnings
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP, Context
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .storage import (
    VaultStorage, CROSS_LINK_SCHEMA_VERSION, discover_product_db, DiscoveryError,
    _CROSS_LINK_EMBEDDING_MODEL,
)
from .tiers import TierLimitError, get_tier, set_tier, TIER_LIMITS, TIER_PRO
from .license import get_license_status
from .onboard_tool import run_onboard as _run_onboard
from .compat_check import check as _compat_check, emit_startup_warnings as _compat_emit


# ---------------------------------------------------------------------------
# Token estimation (SH-12014 / Gap 1)
# ---------------------------------------------------------------------------

_tiktoken_encoder = None
_tiktoken_available = False
_warned_tiktoken = False


def _load_tiktoken():
    global _tiktoken_encoder, _tiktoken_available
    try:
        import tiktoken as _tiktoken
        _tiktoken_encoder = _tiktoken.encoding_for_model("cl100k_base")
        _tiktoken_available = True
    except (ImportError, Exception):
        _tiktoken_available = False


_load_tiktoken()


def _estimate_tokens(text: str) -> int:
    """Estimate token count for text. Uses tiktoken if available, else char-based fallback."""
    global _warned_tiktoken
    if not text:
        return 0
    if _tiktoken_available and _tiktoken_encoder is not None:
        try:
            return len(_tiktoken_encoder.encode(text))
        except Exception:
            pass
    # Char-based fallback
    if not _warned_tiktoken:
        _warned_tiktoken = True
        warnings.warn(
            "[LOREDOCS-WARN] tiktoken unavailable; token estimates use char-based fallback "
            "(+-50% error). Install loredocs[token-count] for better accuracy.",
            RuntimeWarning,
            stacklevel=2,
        )
    non_ascii = sum(1 for c in text if ord(c) > 127)
    if non_ascii / max(len(text), 1) > 0.20:
        return max(1, len(text) // 2)
    return max(1, len(text) // 4)


def _token_estimator_name() -> str:
    if _tiktoken_available:
        return "tiktoken/cl100k_base"
    return "char//4"


# ---------------------------------------------------------------------------
# Per-session injection cache (SH-12014 / Gap 1)
# ---------------------------------------------------------------------------

def _detect_multi_worker() -> bool:
    if os.environ.get("LOREDOCS_DISABLE_SESSION_CACHE", "0") == "1":
        return True
    if os.environ.get("GUNICORN_PID"):
        return True
    try:
        if int(os.environ.get("WEB_CONCURRENCY", "1")) > 1:
            return True
    except ValueError:
        pass
    return False


_SESSION_CACHE_DISABLED = _detect_multi_worker()
if _SESSION_CACHE_DISABLED:
    warnings.warn(
        "[LOREDOCS] Per-session injection cache DISABLED: multi-worker deployment "
        "detected (GUNICORN_PID or WEB_CONCURRENCY>1). Set LOREDOCS_DISABLE_SESSION_CACHE=1 "
        "to suppress this warning.",
        RuntimeWarning,
        stacklevel=1,
    )

_SESSION_CACHE_MAX_ENTRIES: int = int(os.environ.get("LOREDOCS_SESSION_CACHE_MAX_ENTRIES", "1000"))
_injection_cache: "OrderedDict[tuple, '_InjectionCacheEntry']" = OrderedDict()
_injection_cache_eviction_warned: bool = False
_PROCESS_START_TS: float = time.monotonic()


@dataclass
class _InjectionCacheEntry:
    injected_doc_ids: List[str]
    estimated_token_count: int
    vault_max_updated_at: str


def _cache_lookup(cache_key: tuple) -> "Optional[_InjectionCacheEntry]":
    if _SESSION_CACHE_DISABLED:
        return None
    entry = _injection_cache.get(cache_key)
    if entry is not None:
        _injection_cache.move_to_end(cache_key)
    return entry


def _cache_store(cache_key: tuple, entry: _InjectionCacheEntry) -> None:
    global _injection_cache_eviction_warned
    if _SESSION_CACHE_DISABLED:
        return
    if cache_key in _injection_cache:
        _injection_cache.move_to_end(cache_key)
        _injection_cache[cache_key] = entry
        return
    if len(_injection_cache) >= _SESSION_CACHE_MAX_ENTRIES:
        _injection_cache.popitem(last=False)  # LRU eviction
        if not _injection_cache_eviction_warned:
            _injection_cache_eviction_warned = True
            warnings.warn(
                f"[LOREDOCS-WARN] Session cache LRU eviction triggered "
                f"({_SESSION_CACHE_MAX_ENTRIES} entries); consider raising "
                "LOREDOCS_SESSION_CACHE_MAX_ENTRIES or reducing session_token variety.",
                RuntimeWarning,
                stacklevel=2,
            )
    _injection_cache[cache_key] = entry


def _build_cache_key(
    session_token: Optional[str],
    vault_name: str,
    max_tokens: Optional[int],
    tags_frozen: "Optional[frozenset[str]]",
    query: str,
    vault_max_updated_at: str,
) -> tuple:
    return (
        session_token or "",
        os.getpid(),
        _PROCESS_START_TS,
        vault_name,
        max_tokens,
        tags_frozen or frozenset(),
        query or "",
        vault_max_updated_at,
    )


# ---------------------------------------------------------------------------
# Admin token security (SH-12014 / Gap 1)
# ---------------------------------------------------------------------------

_WEAK_TOKENS = frozenset({
    "admin", "test", "password", "secret", "12345", "loredocs",
    "loredocs_admin", "changeme", "token",
})
_ADMIN_LOCKOUT_THRESHOLD = 5
_admin_fail_count: int = 0
_admin_lockout_until: float = 0.0
_lockout_path = Path.home() / ".loredocs" / "admin_lockout.json"


def _load_lockout_state() -> None:
    global _admin_fail_count, _admin_lockout_until
    try:
        if _lockout_path.exists():
            data = json.loads(_lockout_path.read_text())
            _admin_fail_count = data.get("fail_count", 0)
            _admin_lockout_until = data.get("until", 0.0)
    except Exception:
        pass


def _persist_lockout_state() -> None:
    try:
        _lockout_path.parent.mkdir(parents=True, exist_ok=True)
        _lockout_path.write_text(json.dumps(
            {"until": _admin_lockout_until, "fail_count": _admin_fail_count}
        ))
    except Exception:
        pass


_load_lockout_state()


def _admin_token_valid() -> bool:
    """Check whether LOREDOCS_ADMIN_TOKEN passes weak-token validation."""
    token = os.environ.get("LOREDOCS_ADMIN_TOKEN", "")
    if not token or len(token) < 16:
        return False
    if token in _WEAK_TOKENS:
        return False
    has_upper = any(c.isupper() for c in token)
    has_lower = any(c.islower() for c in token)
    has_digit = any(c.isdigit() for c in token)
    has_special = any(c in "!@#$%^&*()-_=+[]{}|;:,.<>?" for c in token)
    char_classes = sum([has_upper, has_lower, has_digit, has_special])
    return char_classes >= 2


def _check_admin_token(provided: str) -> bool:
    """Compare provided token against LOREDOCS_ADMIN_TOKEN.

    Enforces constant-time comparison and brute-force lockout.
    Returns True if valid.
    """
    global _admin_fail_count, _admin_lockout_until
    lockout_secs = float(os.environ.get("LOREDOCS_ADMIN_LOCKOUT_SECS", "300"))
    now = time.monotonic()

    if _admin_lockout_until > 0.0 and now < _admin_lockout_until:
        remaining = int(_admin_lockout_until - now)
        raise PermissionError(
            f"[LOREDOCS-SECURITY] Admin token locked out for {remaining}s after repeated failures."
        )

    expected = os.environ.get("LOREDOCS_ADMIN_TOKEN", "")
    if not expected:
        _admin_fail_count += 1
        _persist_lockout_state()
        raise PermissionError("[LOREDOCS-SECURITY] LOREDOCS_ADMIN_TOKEN is not set.")

    valid = hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))
    if valid:
        _admin_fail_count = 0
        _persist_lockout_state()
        return True

    _admin_fail_count += 1
    if _admin_fail_count >= _ADMIN_LOCKOUT_THRESHOLD:
        _admin_lockout_until = now + lockout_secs
    _persist_lockout_state()

    if os.environ.get("LOREDOCS_SECURITY_LOG") == "1":
        _lockout_path.parent.mkdir(parents=True, exist_ok=True)
        sec_log = _lockout_path.parent / "security.log"
        try:
            with open(sec_log, "a") as f:
                f.write(
                    f"[LOREDOCS-SECURITY] Admin token failure {_admin_fail_count}/"
                    f"{_ADMIN_LOCKOUT_THRESHOLD}\n"
                )
            os.chmod(str(sec_log), 0o600)
        except Exception:
            pass

    raise PermissionError(
        f"[LOREDOCS-SECURITY] Admin token rejected "
        f"(failure {_admin_fail_count}/{_ADMIN_LOCKOUT_THRESHOLD})."
    )


# ---------------------------------------------------------------------------
# Startup gate flag (SH-12014 / Gap 1)
# ---------------------------------------------------------------------------

_mcp_server_accepting_connections: bool = False

_SESSION_TOKEN_REGISTRY_ENABLED: bool = (
    os.environ.get("LOREDOCS_SESSION_TOKEN_REGISTRY", "0") == "1"
)
_registered_session_tokens: "set[str]" = set()


# ---------------------------------------------------------------------------
# Injection cap helper
# ---------------------------------------------------------------------------

_INJECTION_CAP_VALID_BEHAVIORS = frozenset({"best_effort", "strict"})
_SESSION_TOKEN_REGEX = re.compile(r'^[A-Za-z0-9_:/.@-]{1,128}$')
_INJECTION_DEFAULT_CAP: int = int(os.environ.get("LOREDOCS_INJECTION_DEFAULT_CAP_TOKENS", "100000"))


def _validate_injection_params(
    max_tokens: Optional[int],
    safety_factor: float,
    max_single_doc_tokens: Optional[int],
    cap_behavior: str,
    session_token: Optional[str],
) -> Optional[str]:
    """Validate injection parameters. Returns an error message string, or None if valid."""
    if max_tokens is not None and max_tokens < 100:
        return f"[LOREDOCS-ERROR] max_tokens must be >= 100 (got {max_tokens})."
    if not (0.0 < safety_factor <= 1.0):
        return f"[LOREDOCS-ERROR] safety_factor must be in range (0.0, 1.0] (got {safety_factor})."
    if max_single_doc_tokens is not None and max_single_doc_tokens < 100 and max_single_doc_tokens != 0:
        return f"[LOREDOCS-ERROR] max_single_doc_tokens must be >= 100 or 0 (got {max_single_doc_tokens})."
    if cap_behavior not in _INJECTION_CAP_VALID_BEHAVIORS:
        return (
            f"[LOREDOCS-ERROR] cap_behavior must be 'best_effort' or 'strict' "
            f"(got {cap_behavior!r})."
        )
    if session_token is not None and not _SESSION_TOKEN_REGEX.match(session_token):
        return (
            "[LOREDOCS-ERROR] session_token must be 1-128 chars matching "
            "[A-Za-z0-9_:/.@-] or None."
        )
    return None


def _resolve_max_tokens(
    caller_max_tokens: Optional[int],
    vault_cap: Optional[int],
) -> Optional[int]:
    """Resolve effective max_tokens using priority chain.

    Priority: caller > vault DB > env var > process default.
    Returns None if all sources are None (no cap -- caller must handle).
    """
    if caller_max_tokens is not None:
        return caller_max_tokens
    if vault_cap is not None:
        return vault_cap
    env_cap = os.environ.get("LOREDOCS_INJECTION_CAP_TOKENS")
    if env_cap is not None:
        try:
            v = int(env_cap)
            if v > 0:
                return v
        except ValueError:
            pass
    if _INJECTION_DEFAULT_CAP > 0:
        return _INJECTION_DEFAULT_CAP
    return None


def _do_injection(
    docs: List[Dict],
    effective_cap: Optional[int],
    cap_behavior: str,
    max_single_doc_tokens: Optional[int],
    vault_name: str,
) -> Dict[str, Any]:
    """Apply token cap logic and build injection output.

    Returns dict with:
      text: str -- formatted injection text
      injected_doc_ids: List[str]
      estimated_token_count: int
      cap_exceeded: bool
      overflow_tokens: int
      omitted_count: int
    """
    if not docs:
        return {
            "text": f"[LoreDocs: {vault_name} -- no documents found]",
            "injected_doc_ids": [],
            "estimated_token_count": 0,
            "cap_exceeded": False,
            "overflow_tokens": 0,
            "omitted_count": 0,
        }

    injected = []
    running_tokens = 0
    omitted_count = 0
    overflow_tokens = 0

    for i, doc in enumerate(docs):
        content = doc["content"] or ""
        doc_tokens = _estimate_tokens(content)

        # Apply per-doc truncation if requested
        single_doc_limit = max_single_doc_tokens
        if single_doc_limit is None and effective_cap is not None:
            single_doc_limit = effective_cap  # default: cap single doc at effective_cap

        truncated = False
        if single_doc_limit is not None and single_doc_limit != 0 and doc_tokens > single_doc_limit:
            # Truncate content to approximately single_doc_limit tokens
            if _tiktoken_available and _tiktoken_encoder is not None:
                try:
                    tokens = _tiktoken_encoder.encode(content)
                    content = _tiktoken_encoder.decode(tokens[:single_doc_limit])
                    doc_tokens = single_doc_limit
                    truncated = True
                except Exception:
                    # Fall back to char-based truncation
                    approx_chars = single_doc_limit * 4
                    content = content[:approx_chars]
                    doc_tokens = _estimate_tokens(content)
                    truncated = True
            else:
                approx_chars = single_doc_limit * 4
                content = content[:approx_chars]
                doc_tokens = _estimate_tokens(content)
                truncated = True

        if truncated:
            content += f"\n[...TRUNCATED: document exceeded max_single_doc_tokens ({single_doc_limit} estimated tokens)]"

        if effective_cap is not None:
            remaining = effective_cap - running_tokens
            if doc_tokens > remaining:
                if i == 0:
                    # First document exceeds cap
                    if cap_behavior == "strict":
                        smallest_name = docs[0]["name"]
                        smallest_tokens = doc_tokens
                        for d2 in docs[1:]:
                            t2 = _estimate_tokens(d2["content"] or "")
                            if t2 < smallest_tokens:
                                smallest_tokens = t2
                                smallest_name = d2["name"]
                        return {
                            "text": (
                                f"[LOREDOCS-WARN] {vault_name}: no documents fit within cap "
                                f"(strict mode). Smallest estimated doc is ~{smallest_tokens} tokens. "
                                f"Increase cap or reduce document sizes."
                            ),
                            "injected_doc_ids": [],
                            "estimated_token_count": 0,
                            "cap_exceeded": True,
                            "overflow_tokens": 0,
                            "omitted_count": len(docs),
                        }
                    else:
                        # best_effort: inject first doc (already truncated above if needed)
                        if running_tokens + doc_tokens > effective_cap:
                            overflow = (running_tokens + doc_tokens) - effective_cap
                            overflow_tokens += overflow
                        injected.append((doc, content))
                        running_tokens += doc_tokens
                        omitted_count += len(docs) - 1
                        break
                else:
                    # Subsequent doc doesn't fit: skip it, continue for best_effort
                    if cap_behavior == "strict":
                        omitted_count += len(docs) - i
                        break
                    else:
                        # best_effort: skip this doc, continue
                        omitted_count += 1
                        continue
            else:
                injected.append((doc, content))
                running_tokens += doc_tokens
        else:
            # No cap
            injected.append((doc, content))
            running_tokens += doc_tokens

    if not injected:
        # InjectionCapError: no doc could be injected even in best_effort
        return {
            "text": (
                f"[LOREDOCS-ERROR] InjectionCapError: {vault_name}: no document can be injected. "
                f"All {len(docs)} documents exceed max_single_doc_tokens "
                f"(smallest ~{min(_estimate_tokens(d['content'] or '') for d in docs)} tokens). "
                "Options: (1) increase max_single_doc_tokens, (2) increase max_tokens, "
                "(3) use cap_behavior='strict', (4) reduce document sizes."
            ),
            "injected_doc_ids": [],
            "estimated_token_count": 0,
            "cap_exceeded": True,
            "overflow_tokens": 0,
            "omitted_count": len(docs),
        }

    # Build output text
    parts = []
    injected_ids = []
    for doc, content in injected:
        parts.append(f"=== {doc['name']} ({doc['doc_id']}) ===")
        parts.append(f"Priority: {doc['priority']}")
        parts.append("")
        parts.append(content)
        parts.append("")
        parts.append("=" * 60)
        parts.append("")
        injected_ids.append(doc["doc_id"])

    cap_exceeded = overflow_tokens > 0
    text = "\n".join(parts)
    if effective_cap is not None:
        inaccurate = "" if _tiktoken_available else " (estimates may be inaccurate without tiktoken)"
        sys.stderr.write(
            f"[LOREDOCS-INJECT] {vault_name}: {len(injected_ids)} docs "
            f"(~{running_tokens} estimated tokens, effective_cap={effective_cap}){inaccurate}, "
            f"{omitted_count} omitted\n"
        )

    return {
        "text": text,
        "injected_doc_ids": injected_ids,
        "estimated_token_count": running_tokens,
        "cap_exceeded": cap_exceeded,
        "overflow_tokens": overflow_tokens,
        "omitted_count": omitted_count,
    }


# ---------------------------------------------------------------------------
# Lifespan -- initialize storage once, share across all tools
# ---------------------------------------------------------------------------

@asynccontextmanager
async def app_lifespan(app):
    """Initialize the VaultStorage instance for the server lifetime."""
    global _mcp_server_accepting_connections
    root_override = os.environ.get("LOREDOCS_ROOT")
    root = Path(root_override) if root_override else None
    storage = VaultStorage(root=root)
    _mcp_server_accepting_connections = True
    yield {"storage": storage}
    _mcp_server_accepting_connections = False


mcp = FastMCP(
    "loredocs_mcp",
    lifespan=app_lifespan,
    instructions=(
        "LoreDocs organizes project knowledge in searchable vaults. "
        "Use loredocs_onboard to set up your workspace on first install. "
        "Use vault_create to create vaults, vault_add_doc to store documents. "
        "Use vault_search to find documents by keyword (FTS5 syntax supported). "
        "Use vault_search with semantic=true (Pro) for meaning-based retrieval. "
        "Use vault_rebuild_index (Pro) to build the semantic index after install. "
        "Use vault_inject or vault_inject_by_tag to load documents into context. "
        "Categories: reference, report, template, config, archive, general. "
        "Priority: authoritative (source of truth), normal, draft, outdated. "
        "Tags are freeform strings for cross-vault retrieval."
    )
)


def _get_storage(ctx: Context) -> VaultStorage:
    """Helper to get storage from lifespan context."""
    return ctx.request_context.lifespan_context["storage"]


# ---------------------------------------------------------------------------
# Enums and shared models
# ---------------------------------------------------------------------------

class ResponseFormat(str, Enum):
    MARKDOWN = "markdown"
    JSON = "json"


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class DocSortField(str, Enum):
    NAME = "name"
    UPDATED = "updated_at"
    CREATED = "created_at"
    SIZE = "file_size_bytes"
    CATEGORY = "category"


class DocCategory(str, Enum):
    GENERAL = "general"
    REFERENCE = "reference"
    CONFIG = "config"
    REPORT = "report"
    TEMPLATE = "template"
    ARCHIVE = "archive"
    IMPORTED = "imported"


class DocPriority(str, Enum):
    AUTHORITATIVE = "authoritative"
    NORMAL = "normal"
    DRAFT = "draft"
    OUTDATED = "outdated"


# ---------------------------------------------------------------------------
# Helper: format file sizes
# ---------------------------------------------------------------------------

def _fmt_size(b: int) -> str:
    """Format bytes as human-readable size."""
    if b < 1024:
        return f"{b} B"
    elif b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    elif b < 1024 * 1024 * 1024:
        return f"{b / (1024 * 1024):.1f} MB"
    return f"{b / (1024 * 1024 * 1024):.1f} GB"


def _resolve_vault(storage: VaultStorage, vault: str) -> Optional[Dict[str, Any]]:
    """Resolve a vault by ID or name."""
    result = storage.get_vault(vault)
    if not result:
        result = storage.find_vault_by_name(vault)
    return result


# ===================================================================
# VAULT MANAGEMENT TOOLS
# ===================================================================

class VaultCreateInput(BaseModel):
    """Input for creating a new vault."""
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., description="Name for the vault (e.g., 'Tax Prep 2025', 'Rental Properties')", min_length=1, max_length=100)
    description: str = Field(default="", description="Description of what this vault contains", max_length=500)
    tags: Optional[List[str]] = Field(default=None, description="Tags for the vault itself (e.g., ['finance', '2025'])")
    linked_projects: Optional[List[str]] = Field(default=None, description="Claude Project names to associate with this vault")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Output format: json (full vault dict) or markdown (brief summary)")


@mcp.tool(
    title="Create Vault",
    name="vault_create",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}
)
async def vault_create(
    ctx: Context,
    name: str,
    description: str = "",
    tags: Optional[List[str]] = None,
    linked_projects: Optional[List[str]] = None,
    response_format: ResponseFormat = ResponseFormat.JSON,
) -> str:
    """Create a new knowledge vault for organizing project documents.

    A vault is a container for related documents -- like a project folder with
    superpowers (search, tags, versioning). You can link a vault to one or more
    Claude Projects, but vaults are independent and can serve multiple projects.

    Returns the new vault's ID and metadata.
    """
    params = VaultCreateInput(name=name, description=description, tags=tags, linked_projects=linked_projects, response_format=response_format)
    storage = _get_storage(ctx)
    try:
        vault = storage.create_vault(
            name=params.name,
            description=params.description,
            tags=params.tags,
            linked_projects=params.linked_projects,
        )
    except TierLimitError as exc:
        return f"Error: {exc}"
    # Add setup_tip on first vault if Config vault doesn't already exist
    vault_count = len(storage.list_vaults(include_archived=False))
    config_exists = storage.find_vault_by_name("Config") is not None
    if vault_count == 1 and not config_exists:
        vault["setup_tip"] = (
            "First vault created. Run loredocs_onboard() to add a Config vault "
            "with a reference doc your AI assistant can query at session start."
        )
    if params.response_format == ResponseFormat.MARKDOWN:
        result = f"Vault '{vault['name']}' created. ID: {vault['id']}"
        if "setup_tip" in vault:
            result += f"\n\n{vault['setup_tip']}"
        return result
    return json.dumps(vault, indent=2)


class VaultListInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    include_archived: bool = Field(default=False, description="Include archived vaults in the list")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format")


@mcp.tool(
    title="List Vaults",
    name="vault_list",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_list(
    ctx: Context,
    include_archived: bool = False,
    response_format: ResponseFormat = ResponseFormat.MARKDOWN,
) -> str:
    """List all knowledge vaults with summary stats (document count, total size, last modified).

    Use this to see what vaults exist and find the one you need.
    """
    params = VaultListInput(include_archived=include_archived, response_format=response_format)
    storage = _get_storage(ctx)
    vaults = storage.list_vaults(include_archived=params.include_archived)

    if not vaults:
        return (
            "No vaults found. Create one with vault_create, or run "
            "loredocs_onboard() to get a starter structure with a Config vault "
            "and reference doc your AI assistant can query."
        )

    if params.response_format == ResponseFormat.JSON:
        return json.dumps(vaults, indent=2)

    lines = ["# Your Vaults", ""]
    for v in vaults:
        status = " [ARCHIVED]" if v["archived"] else ""
        lines.append(f"## {v['name']}{status} (`{v['id']}`)")
        if v["description"]:
            lines.append(f"  {v['description']}")
        lines.append(f"  - Documents: {v['doc_count']} | Size: {_fmt_size(v['total_size_bytes'])}")
        if v["tags"]:
            lines.append(f"  - Tags: {', '.join(v['tags'])}")
        if v["linked_projects"]:
            lines.append(f"  - Linked projects: {', '.join(v['linked_projects'])}")
        lines.append(f"  - Last updated: {v['updated_at'][:10]}")
        lines.append("")
    return "\n".join(lines)


class VaultIdInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    vault: str = Field(..., description="Vault ID or name", min_length=1)
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format")


@mcp.tool(
    title="Get Vault Info",
    name="vault_info",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_info(
    ctx: Context,
    vault: str,
    response_format: ResponseFormat = ResponseFormat.MARKDOWN,
) -> str:
    """Get detailed information about a vault, including its full document manifest.

    Accepts either a vault ID or vault name.
    """
    params = VaultIdInput(vault=vault, response_format=response_format)
    storage = _get_storage(ctx)
    vault = _resolve_vault(storage, params.vault)
    if not vault:
        return f"Error: Vault '{params.vault}' not found. Use vault_list to see available vaults."

    if params.response_format == ResponseFormat.JSON:
        return json.dumps(vault, indent=2)

    lines = [f"# Vault: {vault['name']} (`{vault['id']}`)", ""]
    if vault["description"]:
        lines.append(vault["description"])
        lines.append("")
    lines.append(f"- **Documents:** {vault['doc_count']}")
    lines.append(f"- **Total size:** {_fmt_size(vault['total_size_bytes'])}")
    lines.append(f"- **Created:** {vault['created_at'][:10]}")
    lines.append(f"- **Last updated:** {vault['updated_at'][:10]}")
    if vault["tags"]:
        lines.append(f"- **Tags:** {', '.join(vault['tags'])}")
    if vault["linked_projects"]:
        lines.append(f"- **Linked projects:** {', '.join(vault['linked_projects'])}")

    if vault["documents"]:
        lines.append("")
        lines.append("## Documents")
        lines.append("")
        for doc in vault["documents"]:
            tag_str = f" [{', '.join(doc['tags'])}]" if doc["tags"] else ""
            lines.append(
                f"- **{doc['name']}** (`{doc['id']}`) "
                f"| {doc['category']} | {_fmt_size(doc['file_size_bytes'])}{tag_str}"
            )

    return "\n".join(lines)


class VaultArchiveInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    vault: str = Field(..., description="Vault ID or name to archive", min_length=1)


@mcp.tool(
    title="Archive Vault",
    name="vault_archive",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_archive(ctx: Context, vault: str) -> str:
    """Archive a vault (soft delete). Archived vaults are hidden from vault_list by default but can be restored."""
    params = VaultArchiveInput(vault=vault)
    storage = _get_storage(ctx)
    vault = _resolve_vault(storage, params.vault)
    if not vault:
        return f"Error: Vault '{params.vault}' not found."
    if storage.archive_vault(vault["id"]):
        return f"Vault '{vault['name']}' has been archived. Use vault_list with include_archived=true to see it."
    return "Error: Could not archive vault."


class VaultDeleteInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    vault: str = Field(..., description="Vault ID or name to permanently delete", min_length=1)
    confirm: bool = Field(default=False, description="Must be true to confirm permanent deletion")


@mcp.tool(
    title="Delete Vault",
    name="vault_delete",
    annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False}
)
async def vault_delete(ctx: Context, vault: str, confirm: bool = False) -> str:
    """Permanently delete a vault and ALL its documents. This cannot be undone.

    You must set confirm=true to proceed. Consider using vault_archive instead.
    """
    params = VaultDeleteInput(vault=vault, confirm=confirm)
    if not params.confirm:
        return "Error: Set confirm=true to permanently delete this vault. This action cannot be undone. Consider vault_archive instead."
    storage = _get_storage(ctx)
    vault = _resolve_vault(storage, params.vault)
    if not vault:
        return f"Error: Vault '{params.vault}' not found."
    name = vault["name"]
    if storage.delete_vault(vault["id"]):
        return f"Vault '{name}' and all its documents have been permanently deleted."
    return "Error: Could not delete vault."


class OnboardInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: Optional[str] = Field(default=None, description="Workspace or team name")
    domains: Optional[List[str]] = Field(default=None, description="Work domains -- each becomes a vault (e.g. ['finance', 'research'])")
    agents: Optional[List[str]] = Field(default=None, description="Agent names -- each gets a '[Name] Reports' vault")
    tag_style: str = Field(default="simple", description="'simple' (status+priority) or 'detailed' (adds effort, agent tags)")


@mcp.tool(
    title="Onboard LoreDocs",
    name="loredocs_onboard",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def loredocs_onboard(
    ctx: Context,
    name: Optional[str] = None,
    domains: Optional[List[str]] = None,
    agents: Optional[List[str]] = None,
    tag_style: str = "simple",
) -> str:
    """Set up or update your LoreDocs workspace configuration.

    Call once after installing LoreDocs to get a recommended vault structure.
    Call again to add new domains or agents -- existing data is never modified.

    Creates:
    - A Config vault with a 'My LoreDocs Setup' reference doc (tagged authoritative)
    - One vault per domain in domains
    - One '[Name] Reports' vault per agent in agents
    - The reference doc is queryable: vault_search('my setup')

    Args:
        name: Workspace or team name
        domains: Work areas, each becomes a vault (e.g. ['finance', 'research'])
        agents: Agent names, each gets a '[Name] Reports' vault
        tag_style: 'simple' (default) or 'detailed'

    Vault tags: freeform strings on documents for cross-vault retrieval.
    Categories: reference, report, template, config, archive, general.
    Priority: authoritative, normal, draft, outdated.
    """
    params = OnboardInput(name=name, domains=domains, agents=agents, tag_style=tag_style)
    if params.tag_style not in ("simple", "detailed"):
        return "Error: tag_style must be 'simple' or 'detailed'"
    storage = _get_storage(ctx)
    return _run_onboard(
        storage,
        name=params.name,
        domains=params.domains,
        agents=params.agents,
        tag_style=params.tag_style,
    )


class VaultLinkProjectInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    vault: str = Field(..., description="Vault ID or name", min_length=1)
    project_name: str = Field(..., description="Claude Project name to link", min_length=1)


@mcp.tool(
    title="Link Project to Vault",
    name="vault_link_project",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_link_project(ctx: Context, vault: str, project_name: str) -> str:
    """Associate a Claude Project name with a vault.

    This is metadata for your organization -- it records which Claude Projects
    use knowledge from this vault. A vault can be linked to multiple projects.
    """
    params = VaultLinkProjectInput(vault=vault, project_name=project_name)
    storage = _get_storage(ctx)
    vault = _resolve_vault(storage, params.vault)
    if not vault:
        return f"Error: Vault '{params.vault}' not found."
    if storage.link_project(vault["id"], params.project_name):
        return f"Linked Claude Project '{params.project_name}' to vault '{vault['name']}'."
    return "Error: Could not link project."


class VaultOpenWorkspaceInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    workspace_path: str = Field(
        ...,
        description="Absolute path to the workspace directory (e.g. '/Users/me/projects/myapp'). "
                    "Tilde expansion is supported.",
        min_length=1,
    )
    description: str = Field(
        default="",
        description="Description for the vault if it needs to be created.",
        max_length=500,
    )


@mcp.tool(
    title="Open Workspace Vault",
    name="vault_open_workspace",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_open_workspace(
    ctx: Context,
    workspace_path: str,
    description: str = "",
) -> str:
    """Open (or create) a vault scoped to a workspace directory.

    If a vault is already linked to this directory path, returns it.
    Otherwise, creates a new vault named after the directory and records
    the workspace_path so future calls return the same vault.

    This mirrors how MemClaw scopes memory to workspaces -- lower friction
    than naming vaults manually. Named vaults remain available for users
    who prefer explicit management.
    """
    params = VaultOpenWorkspaceInput(workspace_path=workspace_path, description=description)
    storage = _get_storage(ctx)
    resolved = str(Path(params.workspace_path).expanduser().resolve())

    existing = storage.get_vault_by_workspace_path(resolved)
    if existing:
        return json.dumps({
            "status": "found",
            "vault": {
                "id": existing["id"],
                "name": existing["name"],
                "workspace_path": existing["workspace_path"],
                "doc_count": existing["doc_count"],
            }
        }, indent=2)

    vault_name = Path(resolved).name or "Workspace"
    try:
        vault = storage.create_vault(
            name=vault_name,
            description=params.description or f"Workspace vault for {resolved}",
            workspace_path=resolved,
        )
    except TierLimitError as exc:
        return f"Error: {exc}"

    return json.dumps({
        "status": "created",
        "vault": {
            "id": vault["id"],
            "name": vault["name"],
            "workspace_path": vault["workspace_path"],
            "doc_count": 0,
        }
    }, indent=2)


# ===================================================================
# DOCUMENT MANAGEMENT TOOLS
# ===================================================================

class DocAddInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    vault: str = Field(..., description="Vault ID or name to add the document to", min_length=1)
    name: str = Field(..., description="Display name for the document (e.g., 'Depreciation Schedule 2025')", min_length=1, max_length=200)
    content: Optional[str] = Field(default=None, description="The text content of the document (required if path not provided)", min_length=1)
    path: Optional[str] = Field(default=None, description="File path to read document content from (required if content not provided)")
    filename: Optional[str] = Field(default=None, description="Filename with extension (e.g., 'schedule.md'). Defaults to name.md")
    tags: Optional[List[str]] = Field(default=None, description="Tags for the document")
    category: DocCategory = Field(default=DocCategory.GENERAL, description="Document category")
    priority: DocPriority = Field(default=DocPriority.NORMAL, description="Document priority/status")
    notes: str = Field(default="", description="Notes about this document")

    def model_post_init(self, __context):
        if not self.content and not self.path:
            raise ValueError('Either content or path must be provided')
        if self.content and self.path:
            raise ValueError('Provide either content or path, not both')


@mcp.tool(
    title="Add Document",
    name="vault_add_doc",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}
)
async def vault_add_doc(
    ctx: Context,
    vault: str,
    name: str,
    content: Optional[str] = None,
    path: Optional[str] = None,
    filename: Optional[str] = None,
    tags: Optional[List[str]] = None,
    category: DocCategory = DocCategory.GENERAL,
    priority: DocPriority = DocPriority.NORMAL,
    notes: str = "",
) -> str:
    """Add a text document to a vault with metadata (tags, category, priority, notes).

    The document will be full-text indexed for search and stored with version tracking.
    Content can be provided inline (content parameter) or from a file path (path parameter).
    For binary files (PDF, DOCX, etc.), use vault_import_dir to import from a directory.
    """
    params = DocAddInput(vault=vault, name=name, content=content, path=path, filename=filename, tags=tags, category=category, priority=priority, notes=notes)
    storage = _get_storage(ctx)
    vault = _resolve_vault(storage, params.vault)
    if not vault:
        return f"Error: Vault '{params.vault}' not found. Use vault_list to see available vaults."

    text_content = params.content
    if params.path:
        try:
            text_content = Path(params.path).read_text(encoding='utf-8')
        except FileNotFoundError:
            return f"Error: File not found at path '{params.path}'"
        except (IOError, OSError) as exc:
            return f"Error: Could not read file '{params.path}': {exc}"

    try:
        result = storage.add_document_from_text(
            vault_id=vault["id"],
            name=params.name,
            text_content=text_content,
            filename=params.filename,
            tags=params.tags,
            category=params.category.value,
            priority=params.priority.value,
            notes=params.notes,
        )
    except TierLimitError as exc:
        return f"Error: {exc}"
    if result:
        return json.dumps(result, indent=2)
    return "Error: Could not add document."


class DocUpdateInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    doc_id: str = Field(..., description="Document ID to update", min_length=1)
    content: Optional[str] = Field(default=None, description="New text content (previous version will be saved automatically)")
    name: Optional[str] = Field(default=None, description="New display name", max_length=200)
    tags: Optional[List[str]] = Field(default=None, description="Replace all tags with this list")
    category: Optional[DocCategory] = Field(default=None, description="New category")
    priority: Optional[DocPriority] = Field(default=None, description="New priority/status")
    notes: Optional[str] = Field(default=None, description="New notes")


@mcp.tool(
    title="Update Document",
    name="vault_update_doc",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}
)
async def vault_update_doc(
    ctx: Context,
    doc_id: str,
    content: Optional[str] = None,
    name: Optional[str] = None,
    tags: Optional[List[str]] = None,
    category: Optional[DocCategory] = None,
    priority: Optional[DocPriority] = None,
    notes: Optional[str] = None,
) -> str:
    """Update a document's content or metadata.

    If content changes, the previous version is saved automatically in the
    version history. You can restore old versions with vault_doc_restore.
    """
    params = DocUpdateInput(doc_id=doc_id, content=content, name=name, tags=tags, category=category, priority=priority, notes=notes)
    storage = _get_storage(ctx)
    content_bytes = params.content.encode("utf-8") if params.content else None
    result = storage.update_document(
        doc_id=params.doc_id,
        content=content_bytes,
        name=params.name,
        tags=params.tags,
        category=params.category.value if params.category else None,
        priority=params.priority.value if params.priority else None,
        notes=params.notes,
    )
    if result:
        return json.dumps(result, indent=2)
    return f"Error: Document '{params.doc_id}' not found."


class DocIdInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    doc_id: str = Field(..., description="Document ID", min_length=1)


@mcp.tool(
    title="Remove Document",
    name="vault_remove_doc",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_remove_doc(ctx: Context, doc_id: str) -> str:
    """Soft-delete a document. The document is hidden but can be recovered.

    For permanent deletion, use vault_delete to remove the entire vault.
    """
    params = DocIdInput(doc_id=doc_id)
    storage = _get_storage(ctx)
    if storage.remove_document(params.doc_id):
        return f"Document '{params.doc_id}' has been removed (soft-deleted)."
    return f"Error: Document '{params.doc_id}' not found."


class DocGetInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    doc_id: str = Field(..., description="Document ID", min_length=1)
    include_content: bool = Field(default=True, description="Include the document text content in the response")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format")


@mcp.tool(
    title="Get Document",
    name="vault_get_doc",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_get_doc(
    ctx: Context,
    doc_id: str,
    include_content: bool = True,
    response_format: ResponseFormat = ResponseFormat.MARKDOWN,
) -> str:
    """Retrieve a document's metadata and optionally its text content.

    Use include_content=false to get just the metadata without loading the full text.
    """
    params = DocGetInput(doc_id=doc_id, include_content=include_content, response_format=response_format)
    storage = _get_storage(ctx)
    doc = storage.get_document(params.doc_id)
    if not doc:
        return f"Error: Document '{params.doc_id}' not found."

    if params.include_content:
        doc["content"] = storage.get_document_content(params.doc_id) or ""

    if params.response_format == ResponseFormat.JSON:
        return json.dumps(doc, indent=2)

    lines = [f"# {doc['name']}", ""]
    lines.append(f"- **ID:** `{doc['id']}`")
    lines.append(f"- **Category:** {doc['category']}")
    lines.append(f"- **Priority:** {doc['priority']}")
    lines.append(f"- **Size:** {_fmt_size(doc['file_size_bytes'])}")
    lines.append(f"- **Versions:** {doc['version_count']}")
    if doc["tags"]:
        lines.append(f"- **Tags:** {', '.join(doc['tags'])}")
    if doc["notes"]:
        lines.append(f"- **Notes:** {doc['notes']}")
    lines.append(f"- **Last updated:** {doc['updated_at']}")

    if params.include_content and doc.get("content"):
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(doc["content"])

    return "\n".join(lines)


class DocListInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    vault: str = Field(..., description="Vault ID or name", min_length=1)
    sort_by: DocSortField = Field(default=DocSortField.UPDATED, description="Sort field")
    sort_order: SortOrder = Field(default=SortOrder.DESC, description="Sort order")
    category: Optional[DocCategory] = Field(default=None, description="Filter by category")
    tag: Optional[str] = Field(default=None, description="Filter by tag")
    limit: int = Field(default=50, description="Max results", ge=1, le=200)
    offset: int = Field(default=0, description="Pagination offset", ge=0)
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format")


@mcp.tool(
    title="List Documents",
    name="vault_list_docs",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_list_docs(
    ctx: Context,
    vault: str,
    sort_by: DocSortField = DocSortField.UPDATED,
    sort_order: SortOrder = SortOrder.DESC,
    category: Optional[DocCategory] = None,
    tag: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    response_format: ResponseFormat = ResponseFormat.MARKDOWN,
) -> str:
    """List documents in a vault with sorting and filtering options.

    Supports sorting by name, date, size, or category.
    Filter by category or tag to narrow results.
    """
    params = DocListInput(vault=vault, sort_by=sort_by, sort_order=sort_order, category=category, tag=tag, limit=limit, offset=offset, response_format=response_format)
    storage = _get_storage(ctx)
    vault = _resolve_vault(storage, params.vault)
    if not vault:
        return f"Error: Vault '{params.vault}' not found."

    result = storage.list_documents(
        vault_id=vault["id"],
        sort_by=params.sort_by.value,
        sort_order=params.sort_order.value,
        category=params.category.value if params.category else None,
        tag=params.tag,
        limit=params.limit,
        offset=params.offset,
    )

    if params.response_format == ResponseFormat.JSON:
        return json.dumps(result, indent=2)

    if not result["documents"]:
        return f"No documents found in vault '{vault['name']}'."

    lines = [f"# Documents in '{vault['name']}'", ""]
    lines.append(f"Showing {result['count']} of {result['total']} documents")
    lines.append("")

    for doc in result["documents"]:
        tag_str = f" [{', '.join(doc['tags'])}]" if doc["tags"] else ""
        priority_badge = ""
        if doc["priority"] == "authoritative":
            priority_badge = " [AUTHORITATIVE]"
        elif doc["priority"] == "outdated":
            priority_badge = " [OUTDATED]"
        elif doc["priority"] == "draft":
            priority_badge = " [DRAFT]"

        lines.append(
            f"- **{doc['name']}** (`{doc['id']}`){priority_badge}"
        )
        lines.append(
            f"  {doc['category']} | {_fmt_size(doc['file_size_bytes'])} | "
            f"v{doc['version_count']} | {doc['updated_at'][:10]}{tag_str}"
        )
        if doc["notes"]:
            lines.append(f"  Note: {doc['notes']}")
        lines.append("")

    if result["has_more"]:
        lines.append(f"*{result['total'] - result['offset'] - result['count']} more documents. Use offset={result['offset'] + result['count']} to see the next page.*")

    return "\n".join(lines)


# ===================================================================
# SEARCH TOOLS
# ===================================================================

class SearchInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(..., description="Search query (supports FTS5 syntax: AND, OR, NOT, phrase matching with quotes)", min_length=1)
    vault: Optional[str] = Field(default=None, description="Vault ID or name to search within. Leave empty to search all vaults.")
    limit: int = Field(default=20, description="Max results", ge=1, le=100)
    offset: int = Field(default=0, description="Pagination offset", ge=0)
    semantic: bool = Field(default=False, description="Use semantic (vector) search instead of keyword-only FTS5. Requires LoreDocs Pro and the Pro deps installed (pip install loredocs[pro]).")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format")


@mcp.tool(
    title="Search Vault",
    name="vault_search",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_search(
    ctx: Context,
    query: str,
    vault: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    semantic: bool = False,
    response_format: ResponseFormat = ResponseFormat.MARKDOWN,
) -> str:
    """Full-text or semantic search across document contents.

    Default (semantic=False): SQLite FTS5 keyword search. Supports FTS5 syntax:
    - Simple words: depreciation schedule
    - Phrases: "rental income"
    - Boolean: depreciation AND schedule
    - Negation: rental NOT commercial
    - Prefix: deprec*

    Semantic (semantic=True, Pro only): hybrid vector + BM25 search via LanceDB.
    Finds documents by meaning even when exact keywords differ. Requires
    LoreDocs Pro and `pip install loredocs[pro]`. Falls back to FTS5 if the
    semantic index has not been built yet (run vault_rebuild_index first).
    """
    params = SearchInput(query=query, vault=vault, limit=limit, offset=offset, semantic=semantic, response_format=response_format)
    storage = _get_storage(ctx)
    vault_id = None
    vault_name = None
    if params.vault:
        vault = _resolve_vault(storage, params.vault)
        if not vault:
            return f"Error: Vault '{params.vault}' not found."
        vault_id = vault["id"]
        vault_name = vault["name"]

    setup_tip = None
    if params.semantic:
        status = storage.enforcer.status_dict()
        if not status.get("is_pro"):
            setup_tip = (
                "Semantic search requires LoreDocs Pro. "
                "Returning keyword results instead. "
                "Use vault_set_tier with tier='pro' to activate your license."
            )
        else:
            result = storage.search_semantic(
                query=params.query,
                vault_id=vault_id,
                limit=params.limit,
            )
            if params.response_format == ResponseFormat.JSON:
                return json.dumps(result, indent=2)
            scope = f"vault '{vault_name}'" if vault_name else "all vaults"
            if not result["results"]:
                return f"No semantic results found for '{params.query}' in {scope}. Try vault_rebuild_index if the index is empty."
            lines = [f"# Semantic Search Results: '{params.query}'", ""]
            lines.append(f"Found {result['count']} results in {scope} (semantic)")
            lines.append("")
            for r in result["results"]:
                lines.append(f"- **{r['doc_name']}** (`{r['doc_id']}`) in *{r['vault_name']}*")
                if r["snippet"]:
                    lines.append(f"  {r['snippet']}...")
                lines.append("")
            return "\n".join(lines)

    result = storage.search(
        query=params.query,
        vault_id=vault_id,
        limit=params.limit,
        offset=params.offset,
    )

    if params.response_format == ResponseFormat.JSON:
        if setup_tip:
            result["setup_tip"] = setup_tip
        return json.dumps(result, indent=2)

    scope = f"vault '{vault_name}'" if vault_name else "all vaults"
    lines = []
    if setup_tip:
        lines.append(f"*Note: {setup_tip}*")
        lines.append("")

    if not result["results"]:
        return "\n".join(lines) + f"No results found for '{params.query}' in {scope}."

    lines.append(f"# Search Results: '{params.query}'")
    lines.append("")
    lines.append(f"Found {result['count']} results in {scope}")
    lines.append("")

    for r in result["results"]:
        lines.append(f"- **{r['doc_name']}** (`{r['doc_id']}`) in *{r['vault_name']}*")
        lines.append(f"  ...{r['snippet']}...")
        lines.append("")

    return "\n".join(lines)


class RebuildIndexInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    confirm: bool = Field(..., description="Set to true to confirm the rebuild. Rebuilding re-indexes all documents; large vaults may take several minutes.")


@mcp.tool(
    title="Rebuild Semantic Index",
    name="vault_rebuild_index",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_rebuild_index(ctx: Context, confirm: bool = False) -> str:
    """Rebuild the LanceDB semantic search index from all stored documents. Pro only.

    Run this after first installing the Pro deps (pip install loredocs[pro]) or
    after restoring from backup. The index is kept in sync automatically for
    new documents added after install, but existing documents require a one-time
    rebuild to become searchable semantically.
    """
    params = RebuildIndexInput(confirm=confirm)
    if not params.confirm:
        return "Error: Set confirm=true to start the rebuild."

    storage = _get_storage(ctx)
    status = storage.enforcer.status_dict()
    if not status.get("is_pro"):
        return (
            "Error: vault_rebuild_index requires LoreDocs Pro. "
            "Use vault_set_tier with tier='pro' to activate your license."
        )

    try:
        result = storage.rebuild_lance_index()
    except Exception as exc:
        return f"Error during index rebuild: {exc}"

    return (
        f"Semantic index rebuilt: {result['docs_indexed']} documents, "
        f"{result['chunks_indexed']} chunks indexed."
    )


class SearchByTagInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    tag: str = Field(..., description="Tag to search for", min_length=1)
    vault: Optional[str] = Field(default=None, description="Vault ID or name. Leave empty to search all vaults.")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format")


@mcp.tool(
    title="Search by Tag",
    name="vault_search_by_tag",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_search_by_tag(
    ctx: Context,
    tag: str,
    vault: Optional[str] = None,
    response_format: ResponseFormat = ResponseFormat.MARKDOWN,
) -> str:
    """Find all documents with a specific tag, across one vault or all vaults."""
    params = SearchByTagInput(tag=tag, vault=vault, response_format=response_format)
    storage = _get_storage(ctx)
    vault_id = None
    if params.vault:
        vault = _resolve_vault(storage, params.vault)
        if not vault:
            return f"Error: Vault '{params.vault}' not found."
        vault_id = vault["id"]

    results = storage.search_by_tag(params.tag, vault_id=vault_id)

    if params.response_format == ResponseFormat.JSON:
        return json.dumps(results, indent=2)

    if not results:
        return f"No documents found with tag '{params.tag}'."

    lines = [f"# Documents tagged '{params.tag}'", ""]
    lines.append(f"Found {len(results)} documents")
    lines.append("")
    for r in results:
        lines.append(f"- **{r['name']}** (`{r['id']}`) in *{r['vault_name']}* | {r['category']} | {_fmt_size(r['file_size_bytes'])}")
    return "\n".join(lines)


# ===================================================================
# METADATA AND TAGGING TOOLS
# ===================================================================

class TagDocInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    doc_id: str = Field(..., description="Document ID", min_length=1)
    add_tags: Optional[List[str]] = Field(default=None, description="Tags to add")
    remove_tags: Optional[List[str]] = Field(default=None, description="Tags to remove")


@mcp.tool(
    title="Tag Document",
    name="vault_tag_doc",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_tag_doc(
    ctx: Context,
    doc_id: str,
    add_tags: Optional[List[str]] = None,
    remove_tags: Optional[List[str]] = None,
) -> str:
    """Add or remove tags on a document.

    You can add and remove tags in a single operation.
    Tags are case-sensitive strings. Duplicates are automatically removed.
    """
    params = TagDocInput(doc_id=doc_id, add_tags=add_tags, remove_tags=remove_tags)
    storage = _get_storage(ctx)
    result = storage.tag_document(
        params.doc_id,
        add_tags=params.add_tags,
        remove_tags=params.remove_tags,
    )
    if result is None:
        return f"Error: Document '{params.doc_id}' not found."
    return f"Tags updated. Current tags: {', '.join(result) if result else '(none)'}"


class BulkTagInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    doc_ids: List[str] = Field(..., description="List of document IDs to tag", min_length=1)
    add_tags: Optional[List[str]] = Field(default=None, description="Tags to add to all documents")
    remove_tags: Optional[List[str]] = Field(default=None, description="Tags to remove from all documents")


@mcp.tool(
    title="Bulk Tag Documents",
    name="vault_bulk_tag",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_bulk_tag(
    ctx: Context,
    doc_ids: List[str],
    add_tags: Optional[List[str]] = None,
    remove_tags: Optional[List[str]] = None,
) -> str:
    """Apply tag changes to multiple documents at once.

    Useful for organizing a batch of documents after import or reclassification.
    """
    params = BulkTagInput(doc_ids=doc_ids, add_tags=add_tags, remove_tags=remove_tags)
    storage = _get_storage(ctx)
    count = storage.bulk_tag(
        params.doc_ids,
        add_tags=params.add_tags,
        remove_tags=params.remove_tags,
    )
    return f"Updated tags on {count} of {len(params.doc_ids)} documents."


class CategorizeInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    doc_id: str = Field(..., description="Document ID", min_length=1)
    category: DocCategory = Field(..., description="New category")


@mcp.tool(
    title="Categorize Document",
    name="vault_categorize",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_categorize(ctx: Context, doc_id: str, category: DocCategory) -> str:
    """Set a document's category (general, reference, config, report, template, archive, imported)."""
    params = CategorizeInput(doc_id=doc_id, category=category)
    storage = _get_storage(ctx)
    result = storage.update_document(params.doc_id, category=params.category.value)
    if result:
        return f"Document '{result['name']}' category set to '{params.category.value}'."
    return f"Error: Document '{params.doc_id}' not found."


class SetPriorityInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    doc_id: str = Field(..., description="Document ID", min_length=1)
    priority: DocPriority = Field(..., description="New priority/status")


@mcp.tool(
    title="Set Document Priority",
    name="vault_set_priority",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_set_priority(ctx: Context, doc_id: str, priority: DocPriority) -> str:
    """Mark a document's priority/status: authoritative, normal, draft, or outdated.

    'authoritative' means this document is the source of truth.
    'outdated' flags the document as no longer current.
    """
    params = SetPriorityInput(doc_id=doc_id, priority=priority)
    storage = _get_storage(ctx)
    result = storage.update_document(params.doc_id, priority=params.priority.value)
    if result:
        return f"Document '{result['name']}' priority set to '{params.priority.value}'."
    return f"Error: Document '{params.doc_id}' not found."


class AddNoteInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    doc_id: str = Field(..., description="Document ID", min_length=1)
    notes: str = Field(..., description="Note to attach (e.g., 'Use this for 2025 tax prep only')", max_length=1000)


@mcp.tool(
    title="Add Document Note",
    name="vault_add_note",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_add_note(ctx: Context, doc_id: str, notes: str) -> str:
    """Attach a contextual note to a document.

    Notes help you and your AI assistant understand when/how to use this document.
    """
    params = AddNoteInput(doc_id=doc_id, notes=notes)
    storage = _get_storage(ctx)
    result = storage.update_document(params.doc_id, notes=params.notes)
    if result:
        return f"Note added to '{result['name']}'."
    return f"Error: Document '{params.doc_id}' not found."


# ===================================================================
# VERSION HISTORY TOOLS
# ===================================================================

@mcp.tool(
    title="View Document History",
    name="vault_doc_history",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_doc_history(ctx: Context, doc_id: str) -> str:
    """View the version history for a document.

    Every time a document's content is updated, the previous version is saved
    automatically. Use vault_doc_restore to revert to an earlier version.
    """
    params = DocIdInput(doc_id=doc_id)
    storage = _get_storage(ctx)
    doc = storage.get_document(params.doc_id)
    if not doc:
        return f"Error: Document '{params.doc_id}' not found."

    history = storage.get_doc_history(params.doc_id)
    if not history:
        return f"No version history for document '{params.doc_id}'."

    lines = [f"# Version History: {doc['name']}", ""]
    for v in history:
        current = " (current)" if v.get("current") else ""
        lines.append(f"- **v{v['version']}**{current} | {v['modified_at'][:10]} | {_fmt_size(v['file_size_bytes'])}")
    return "\n".join(lines)


class DocRestoreInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    doc_id: str = Field(..., description="Document ID", min_length=1)
    version: int = Field(..., description="Version number to restore", ge=1)


@mcp.tool(
    title="Restore Document Version",
    name="vault_doc_restore",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}
)
async def vault_doc_restore(ctx: Context, doc_id: str, version: int) -> str:
    """Restore a document to a previous version.

    The current version is saved to history first, then the specified version
    becomes the new current version.
    """
    params = DocRestoreInput(doc_id=doc_id, version=version)
    storage = _get_storage(ctx)
    doc = storage.get_document(params.doc_id)
    if not doc:
        return f"Error: Document '{params.doc_id}' not found."

    vault_id = doc["vault_id"]
    ext = doc["file_extension"]
    doc_dir = storage.vaults_dir / vault_id / "docs" / params.doc_id
    version_file = doc_dir / "history" / f"v{params.version}{ext}"

    if not version_file.exists():
        return f"Error: Version {params.version} not found for document '{params.doc_id}'."

    content = version_file.read_bytes()
    result = storage.update_document(
        params.doc_id,
        content=content,
        filename=doc["original_filename"],
    )
    if result:
        return f"Document '{doc['name']}' restored to version {params.version}. Previous content saved as v{doc['version_count']}."
    return "Error: Could not restore version."


# ===================================================================
# CROSS-VAULT OPERATIONS
# ===================================================================

class CopyDocInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    doc_id: str = Field(..., description="Document ID to copy", min_length=1)
    target_vault: str = Field(..., description="Target vault ID or name", min_length=1)


@mcp.tool(
    title="Copy Document",
    name="vault_copy_doc",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}
)
async def vault_copy_doc(ctx: Context, doc_id: str, target_vault: str) -> str:
    """Copy a document from one vault to another, including all metadata."""
    params = CopyDocInput(doc_id=doc_id, target_vault=target_vault)
    storage = _get_storage(ctx)
    target = _resolve_vault(storage, params.target_vault)
    if not target:
        return f"Error: Target vault '{params.target_vault}' not found."

    result = storage.copy_document(params.doc_id, target["id"])
    if result:
        return f"Document copied to vault '{target['name']}'. New ID: {result['id']}"
    return f"Error: Could not copy document '{params.doc_id}'. Check that it exists."


class MoveDocInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    doc_id: str = Field(..., description="Document ID to move", min_length=1)
    target_vault: str = Field(..., description="Target vault ID or name", min_length=1)


@mcp.tool(
    title="Move Document",
    name="vault_move_doc",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}
)
async def vault_move_doc(ctx: Context, doc_id: str, target_vault: str) -> str:
    """Move a document to a different vault. Removes it from the source vault."""
    params = MoveDocInput(doc_id=doc_id, target_vault=target_vault)
    storage = _get_storage(ctx)
    target = _resolve_vault(storage, params.target_vault)
    if not target:
        return f"Error: Target vault '{params.target_vault}' not found."

    result = storage.move_document(params.doc_id, target["id"])
    if result:
        return f"Document moved to vault '{target['name']}'. New ID: {result['id']}"
    return f"Error: Could not move document '{params.doc_id}'. Check that it exists."


# ===================================================================
# CONTEXT INJECTION TOOLS
# ===================================================================

def _run_vault_injection(
    storage: VaultStorage,
    vault_name: str,
    query: str,
    max_tokens: Optional[int],
    cap_behavior: str,
    session_token: Optional[str],
    max_single_doc_tokens: Optional[int],
    safety_factor: float,
    tags: "Optional[List[str]]" = None,
) -> str:
    """Shared injection logic for vault_inject / vault_prime / vault_inject_by_tag.

    Resolves the token cap, checks the per-session cache, fetches docs from storage,
    delegates to _do_injection, stores the cache entry, and returns formatted text.
    """
    err = _validate_injection_params(max_tokens, safety_factor, max_single_doc_tokens, cap_behavior, session_token)
    if err:
        return err

    v = _resolve_vault(storage, vault_name)
    if not v:
        return f"[LOREDOCS-ERROR] Vault '{vault_name}' not found."

    vault_id = v["id"]
    vault_max_updated_at = storage.get_vault_max_updated_at(vault_id) or ""
    vault_cap = storage.get_injection_cap(vault_id)
    effective_cap_raw = _resolve_max_tokens(max_tokens, vault_cap)
    effective_cap = int(effective_cap_raw * safety_factor) if effective_cap_raw is not None else None

    if effective_cap is not None and effective_cap < 100:
        effective_cap = 100  # floor: never cap below 100 tokens

    tags_frozen: "Optional[frozenset[str]]" = frozenset(tags) if tags is not None else None
    cache_key = _build_cache_key(
        session_token, vault_name, max_tokens, tags_frozen, query or "", vault_max_updated_at
    )
    cached = _cache_lookup(cache_key)
    if cached is not None:
        cache_label = "(cached)"
        est = cached.estimated_token_count
        inj_ids = cached.injected_doc_ids
        # Re-fetch content for cached entry to build text (content is not cached, only ids)
        # For cache hit, just indicate cache was used -- we do NOT re-build the full text here
        # because we need to re-fetch doc content. Instead, we skip cache for text rebuilding.
        # Note: the cache's value is "did we already inject this set", but since we need the
        # actual text returned to the caller, we still need to fetch content on a cache hit.
        # The cache's purpose is to skip the DB query + FTS step, not the text-building step.
        # We store injected_doc_ids so we can fast-path retrieve exactly those docs in order.
        docs = []
        for doc_id in inj_ids:
            doc_meta = storage.get_document(doc_id)
            if doc_meta:
                content = storage.get_document_content(doc_id) or ""
                docs.append({
                    "doc_id": doc_id,
                    "name": doc_meta.get("name", doc_id),
                    "priority": doc_meta.get("priority", "normal"),
                    "updated_at": doc_meta.get("updated_at", ""),
                    "content": content,
                })
        # Re-apply injection (idempotent since we have the exact id list)
        result = _do_injection(docs, effective_cap, cap_behavior, max_single_doc_tokens, vault_name)
    else:
        cache_label = ""
        if tags is not None:
            docs = storage.get_docs_for_injection_by_tags(vault_id, list(tags), limit=500)
        else:
            docs = storage.get_docs_for_injection(vault_id, query=query or "", limit=500)
        result = _do_injection(docs, effective_cap, cap_behavior, max_single_doc_tokens, vault_name)
        # Store cache entry
        cache_entry = _InjectionCacheEntry(
            injected_doc_ids=result["injected_doc_ids"],
            estimated_token_count=result["estimated_token_count"],
            vault_max_updated_at=vault_max_updated_at,
        )
        _cache_store(cache_key, cache_entry)

    # Append metadata footer
    footer_lines = []
    if cache_label:
        footer_lines.append(f"[LoreDocs: {vault_name} | CACHE HIT]")
    if result["omitted_count"] > 0:
        footer_lines.append(
            f"[LoreDocs: {result['omitted_count']} document(s) omitted due to token cap "
            f"(cap={effective_cap}, behavior={cap_behavior})]"
        )
    if result.get("cap_exceeded") and result["overflow_tokens"] > 0:
        footer_lines.append(
            f"[LoreDocs-WARN: injection exceeded cap by ~{result['overflow_tokens']} tokens (best_effort)]"
        )
    if footer_lines:
        return result["text"].rstrip() + "\n\n" + "\n".join(footer_lines)
    return result["text"]


@mcp.tool(
    title="Inject Vault Documents",
    name="vault_inject",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_inject(
    ctx: Context,
    vault_name: str,
    query: str = "",
    max_tokens: Optional[int] = None,
    cap_behavior: str = "best_effort",
    session_token: Optional[str] = None,
    max_single_doc_tokens: Optional[int] = None,
    safety_factor: float = 0.60,
) -> str:
    """Load ranked vault documents into conversation context with token-budget enforcement.

    Documents are ranked by FTS5 relevance (when query is provided) and priority weight,
    then packed greedily until the effective token cap is reached.

    Args:
        vault_name: Vault name or ID.
        query: Optional FTS5 search query to rank documents by relevance.
        max_tokens: Hard token budget. Overrides vault DB cap. Effective cap = max_tokens * safety_factor.
        cap_behavior: 'best_effort' (inject as many docs as fit) or 'strict' (error if any doc exceeds cap).
        session_token: Optional opaque string used as per-session cache key.
        max_single_doc_tokens: Truncate individual documents to this many tokens. 0 = no per-doc limit.
        safety_factor: Fraction of max_tokens to use as effective cap (default 0.60 = 60%).
    """
    if not _mcp_server_accepting_connections:
        return "[LOREDOCS-ERROR] Server is still initializing. Retry in a moment."
    storage = _get_storage(ctx)
    return _run_vault_injection(
        storage, vault_name, query, max_tokens, cap_behavior,
        session_token, max_single_doc_tokens, safety_factor, tags=None
    )


@mcp.tool(
    title="Prime Vault Context",
    name="vault_prime",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_prime(
    ctx: Context,
    vault_name: str,
    max_tokens: Optional[int] = None,
    cap_behavior: str = "best_effort",
    session_token: Optional[str] = None,
    max_single_doc_tokens: Optional[int] = None,
    safety_factor: float = 0.60,
) -> str:
    """Pre-load all vault documents into the current session by priority order.

    Equivalent to vault_inject with no query: loads all documents ordered by
    priority weight (authoritative first), then by recency. Use at session start
    to orient yourself on all knowledge available in a vault.

    Args:
        vault_name: Vault name or ID.
        max_tokens: Hard token budget. Effective cap = max_tokens * safety_factor.
        cap_behavior: 'best_effort' (inject as many docs as fit) or 'strict' (error if cap exceeded).
        session_token: Optional opaque string used as per-session cache key.
        max_single_doc_tokens: Truncate individual documents to this many tokens.
        safety_factor: Fraction of max_tokens to use as effective cap (default 0.60 = 60%).
    """
    if not _mcp_server_accepting_connections:
        return "[LOREDOCS-ERROR] Server is still initializing. Retry in a moment."
    storage = _get_storage(ctx)
    return _run_vault_injection(
        storage, vault_name, "", max_tokens, cap_behavior,
        session_token, max_single_doc_tokens, safety_factor, tags=None
    )


@mcp.tool(
    title="Inject Documents by Tag",
    name="vault_inject_by_tag",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_inject_by_tag(
    ctx: Context,
    vault_name: str,
    tags: List[str],
    max_tokens: Optional[int] = None,
    cap_behavior: str = "best_effort",
    session_token: Optional[str] = None,
    max_single_doc_tokens: Optional[int] = None,
    safety_factor: float = 0.60,
) -> str:
    """Load all documents matching any of the given tags into the current conversation context.

    Documents matching any of the provided tags are fetched, ranked by priority weight
    and recency, then packed greedily within the token cap.

    Args:
        vault_name: Vault name or ID.
        tags: List of tags to match (OR semantics: any matching tag includes the doc).
        max_tokens: Hard token budget. Effective cap = max_tokens * safety_factor.
        cap_behavior: 'best_effort' (inject as many docs as fit) or 'strict'.
        session_token: Optional opaque string used as per-session cache key.
        max_single_doc_tokens: Truncate individual documents to this many tokens.
        safety_factor: Fraction of max_tokens to use as effective cap (default 0.60 = 60%).
    """
    if not _mcp_server_accepting_connections:
        return "[LOREDOCS-ERROR] Server is still initializing. Retry in a moment."
    if not tags:
        return "[LOREDOCS-ERROR] vault_inject_by_tag: 'tags' must be a non-empty list."
    storage = _get_storage(ctx)
    return _run_vault_injection(
        storage, vault_name, "", max_tokens, cap_behavior,
        session_token, max_single_doc_tokens, safety_factor, tags=tags
    )


class InjectSummaryInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    vault: str = Field(..., description="Vault ID or name", min_length=1)


@mcp.tool(
    title="Inject Vault Summary",
    name="vault_inject_summary",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_inject_summary(ctx: Context, vault: str) -> str:
    """Generate a summary overview of a vault's contents for conversation orientation.

    Lists all documents with their categories, tags, priorities, and notes.
    Useful at the start of a conversation to understand what knowledge is available.
    """
    params = InjectSummaryInput(vault=vault)
    storage = _get_storage(ctx)
    v = _resolve_vault(storage, params.vault)
    if not v:
        return f"Error: Vault '{params.vault}' not found."

    # This is essentially vault_info in markdown format
    return await vault_info(ctx=ctx, vault=v["id"])


# ---------------------------------------------------------------------------
# Token injection cap admin tools (SH-12014 / Gap 1)
# Gated by LOREDOCS_ENABLE_CAP_TOOLS=1 for vault_set_injection_cap (admin-only).
# vault_get_injection_cap, vault_get_session_token, vault_estimate_tokens, and
# vault_get_server_capabilities are always available (read-only or no-side-effect).
# ---------------------------------------------------------------------------

@mcp.tool(
    title="Get Injection Cap",
    name="vault_get_injection_cap",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_get_injection_cap(ctx: Context, vault_name: str) -> str:
    """Return the stored per-vault injection token cap (or 'not set' if none).

    If not set, the server falls back to LOREDOCS_INJECTION_CAP_TOKENS env var,
    then LOREDOCS_INJECTION_DEFAULT_CAP_TOKENS (default 100000).
    """
    storage = _get_storage(ctx)
    v = _resolve_vault(storage, vault_name)
    if not v:
        return f"[LOREDOCS-ERROR] Vault '{vault_name}' not found."
    cap = storage.get_injection_cap(v["id"])
    if cap is None:
        return (
            f"Vault '{vault_name}': no injection cap stored. "
            f"Effective default: {_INJECTION_DEFAULT_CAP} tokens "
            f"(LOREDOCS_INJECTION_DEFAULT_CAP_TOKENS)."
        )
    return (
        f"Vault '{vault_name}': injection_cap_tokens = {cap}. "
        f"Effective cap per call = int({cap} * safety_factor)."
    )


@mcp.tool(
    title="Get Session Token",
    name="vault_get_session_token",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}
)
async def vault_get_session_token(ctx: Context) -> str:
    """Generate a fresh session token (UUID4) for use with vault_inject / vault_prime.

    Pass the returned token as session_token in subsequent injection calls so the
    per-session cache can scope cached results to this conversation.
    Cache hits are valid until any document in the vault is updated.
    """
    token = str(uuid.uuid4())
    if _SESSION_TOKEN_REGISTRY_ENABLED:
        _registered_session_tokens.add(token)
    cache_note = "disabled (multi-worker deployment)" if _SESSION_CACHE_DISABLED else "enabled"
    return (
        f"session_token: {token}\n"
        f"Per-session cache: {cache_note}.\n"
        "Pass this token as session_token in vault_inject / vault_prime / vault_inject_by_tag calls."
    )


@mcp.tool(
    title="Estimate Injection Tokens",
    name="vault_estimate_tokens",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_estimate_tokens(
    ctx: Context,
    vault_name: str,
    query: str = "",
    max_single_doc_tokens: Optional[int] = None,
) -> str:
    """Preview the token count of a vault injection without injecting documents.

    Returns estimated token counts for each document (up to 500) so you can
    choose an appropriate max_tokens value before calling vault_inject.
    Uses tiktoken if available; falls back to char-based estimation.
    """
    storage = _get_storage(ctx)
    v = _resolve_vault(storage, vault_name)
    if not v:
        return f"[LOREDOCS-ERROR] Vault '{vault_name}' not found."

    vault_id = v["id"]
    docs = storage.get_docs_for_injection(vault_id, query=query or "", limit=500)
    if not docs:
        return f"Vault '{vault_name}' has no documents."

    lines = [f"Token estimates for vault '{vault_name}' (estimator: {_token_estimator_name()}):"]
    total = 0
    for doc in docs:
        content = doc["content"] or ""
        tok = _estimate_tokens(content)
        per_doc_limit = max_single_doc_tokens
        truncated_note = ""
        if per_doc_limit is not None and per_doc_limit != 0 and tok > per_doc_limit:
            truncated_note = f" [would truncate to {per_doc_limit}]"
            tok = per_doc_limit
        total += tok
        lines.append(f"  {doc['name']!r} ({doc['doc_id']}): ~{tok} tokens{truncated_note}")
    lines.append(f"Total (all {len(docs)} docs): ~{total} tokens")
    vault_cap = storage.get_injection_cap(vault_id)
    effective_resolved = _resolve_max_tokens(None, vault_cap)
    if effective_resolved is not None:
        eff = int(effective_resolved * 0.60)
        lines.append(
            f"Default effective cap (safety_factor=0.60): ~{eff} tokens "
            f"({'vault DB cap' if vault_cap else 'env/default'} = {effective_resolved})"
        )
    return "\n".join(lines)


@mcp.tool(
    title="Get Server Capabilities",
    name="vault_get_server_capabilities",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_get_server_capabilities(ctx: Context) -> str:
    """Return a summary of this LoreDocs server's injection capabilities and token estimation settings.

    Useful for diagnosing injection behavior or verifying which features are active.
    """
    import importlib.metadata
    try:
        version = importlib.metadata.version("loredocs")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"

    admin_token_ok = _admin_token_valid()
    cap_tools_enabled = os.environ.get("LOREDOCS_ENABLE_CAP_TOOLS") == "1"
    lines = [
        f"LoreDocs server capabilities (v{version})",
        "",
        f"  token_estimator: {_token_estimator_name()}",
        f"  tiktoken_available: {_tiktoken_available}",
        f"  session_cache: {'disabled (multi-worker)' if _SESSION_CACHE_DISABLED else 'enabled'}",
        f"  session_cache_size: {len(_injection_cache)} / {_SESSION_CACHE_MAX_ENTRIES}",
        f"  cap_tools_registered: {cap_tools_enabled}",
        f"  admin_token_configured: {bool(os.environ.get('LOREDOCS_ADMIN_TOKEN'))}",
        f"  admin_token_strength_ok: {admin_token_ok}",
        f"  admin_lockout_active: {time.monotonic() < _admin_lockout_until}",
        f"  default_injection_cap_tokens: {_INJECTION_DEFAULT_CAP}",
        f"  server_accepting_connections: {_mcp_server_accepting_connections}",
    ]
    env_cap = os.environ.get("LOREDOCS_INJECTION_CAP_TOKENS")
    if env_cap:
        lines.append(f"  LOREDOCS_INJECTION_CAP_TOKENS: {env_cap}")
    return "\n".join(lines)


if os.environ.get("LOREDOCS_ENABLE_CAP_TOOLS") == "1":
    @mcp.tool(
        title="Set Vault Injection Cap",
        name="vault_set_injection_cap",
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
    )
    async def vault_set_injection_cap(
        ctx: Context,
        vault_name: str,
        max_tokens: int,
        admin_token: str,
    ) -> str:
        """Set the per-vault injection token cap (admin-only).

        Requires LOREDOCS_ENABLE_CAP_TOOLS=1 and a valid LOREDOCS_ADMIN_TOKEN.
        Once set, all vault_inject / vault_prime / vault_inject_by_tag calls
        for this vault use this cap unless the caller overrides with max_tokens.

        Args:
            vault_name: Vault name or ID.
            max_tokens: Token cap to store (must be >= 100).
            admin_token: Value of LOREDOCS_ADMIN_TOKEN (never logged or echoed).
        """
        try:
            _check_admin_token(admin_token)
        except PermissionError as exc:
            return str(exc)

        if max_tokens < 100:
            return f"[LOREDOCS-ERROR] max_tokens must be >= 100 (got {max_tokens})."

        storage = _get_storage(ctx)
        v = _resolve_vault(storage, vault_name)
        if not v:
            return f"[LOREDOCS-ERROR] Vault '{vault_name}' not found."

        ok = storage.set_injection_cap(v["id"], max_tokens)
        if not ok:
            return f"[LOREDOCS-ERROR] Failed to set injection cap for vault '{vault_name}'."
        return (
            f"Vault '{vault_name}': injection_cap_tokens set to {max_tokens}. "
            f"Effective per-call cap at default safety_factor=0.60: ~{int(max_tokens * 0.60)} tokens. "
            "Session cache invalidated (updated_at changed)."
        )


# ===================================================================
# IMPORT / EXPORT TOOLS
# ===================================================================

class ImportDirInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    vault: str = Field(..., description="Vault ID or name to import into", min_length=1)
    directory: str = Field(..., description="Absolute path to directory containing files to import")
    tags: Optional[List[str]] = Field(default=None, description="Tags to apply to all imported documents")
    category: DocCategory = Field(default=DocCategory.IMPORTED, description="Category for imported documents")
    recursive: bool = Field(default=True, description="Traverse subdirectories recursively (default True). Set False for single-level import.")


@mcp.tool(
    title="Import Directory",
    name="vault_import_dir",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}
)
async def vault_import_dir(
    ctx: Context,
    vault: str,
    directory: str,
    tags: Optional[List[str]] = None,
    category: DocCategory = DocCategory.IMPORTED,
    recursive: bool = True,
) -> str:
    """Bulk import all supported files from a directory into a vault.

    Imports text files, PDFs, Word docs, Excel files, PowerPoints, and more.
    Each file becomes a separate document with text extracted for search indexing.
    Files over 30MB are skipped. Hidden files (starting with .) are skipped.

    Supports Obsidian vaults: subdirectories are traversed recursively by default
    (set recursive=False for single-level import). Markdown files with YAML frontmatter
    tags (tags: [a, b] or block-list style) have those tags merged into the document.
    """
    params = ImportDirInput(vault=vault, directory=directory, tags=tags, category=category, recursive=recursive)
    storage = _get_storage(ctx)
    vault = _resolve_vault(storage, params.vault)
    if not vault:
        return f"Error: Vault '{params.vault}' not found."

    dir_path = Path(params.directory)
    if not dir_path.is_dir():
        return f"Error: Directory '{params.directory}' not found or is not a directory."

    results = storage.import_directory(
        vault_id=vault["id"],
        dir_path=dir_path,
        tags=params.tags,
        category=params.category.value,
        recursive=params.recursive,
    )

    if not results:
        return f"No files imported from '{params.directory}'. Check that the directory contains supported files under 30MB."

    lines = [f"Imported {len(results)} files into vault '{vault['name']}':", ""]
    for r in results:
        lines.append(f"- {r['name']} ({r['original_filename']}) - {_fmt_size(r['file_size_bytes'])}")

    return "\n".join(lines)


class ExportInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    vault: str = Field(..., description="Vault ID or name to export", min_length=1)
    directory: str = Field(..., description="Absolute path to output directory")


@mcp.tool(
    title="Export Vault",
    name="vault_export",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_export(ctx: Context, vault: str, directory: str) -> str:
    """Export all documents from a vault to a local directory.

    Copies the original files (not extracted text) to the specified directory.
    Useful for backing up or sharing vault contents.
    """
    params = ExportInput(vault=vault, directory=directory)
    storage = _get_storage(ctx)
    vault = _resolve_vault(storage, params.vault)
    if not vault:
        return f"Error: Vault '{params.vault}' not found."

    output_dir = Path(params.directory)
    count = storage.export_vault(vault["id"], output_dir)

    if count == 0:
        return f"No documents to export from vault '{vault['name']}'."
    return f"Exported {count} documents from vault '{vault['name']}' to {params.directory}"


# ---------------------------------------------------------------------------
# Phase 2: Document linking
# ---------------------------------------------------------------------------

class LinkDocInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source_doc: str = Field(..., description="Source document ID", min_length=1)
    target_doc: str = Field(..., description="Target document ID", min_length=1)
    label: str = Field(default="related", description="Relationship label, e.g. 'related', 'references', 'supersedes', 'part-of'")


@mcp.tool(
    title="Link Documents",
    name="vault_link_doc",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_link_doc(
    ctx: Context,
    source_doc: str,
    target_doc: str,
    label: str = "related",
) -> str:
    """Create a link between two documents across any vault.

    Links are bidirectional and labelled (e.g. 'related', 'references',
    'supersedes', 'part-of').  If the link already exists, reports it.
    Use vault_find_related to discover all docs linked to a given document.
    """
    params = LinkDocInput(source_doc=source_doc, target_doc=target_doc, label=label)
    storage = _get_storage(ctx)
    result = storage.link_doc(params.source_doc, params.target_doc, params.label)
    if result is None:
        return (
            f"Error: One or both documents not found "
            f"(source='{params.source_doc}', target='{params.target_doc}')."
        )
    if result.get("already_existed"):
        return (
            f"Link already exists between '{result['source_doc_name']}' and "
            f"'{result['target_doc_name']}' (label: {result['label']})."
        )
    return (
        f"Linked '{result['source_doc_name']}' -> '{result['target_doc_name']}' "
        f"(label: {result['label']}, link ID: {result['id']})"
    )


class UnlinkDocInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source_doc: str = Field(..., description="Source document ID", min_length=1)
    target_doc: str = Field(..., description="Target document ID", min_length=1)


@mcp.tool(
    title="Unlink Documents",
    name="vault_unlink_doc",
    annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": False}
)
async def vault_unlink_doc(ctx: Context, source_doc: str, target_doc: str) -> str:
    """Remove a link between two documents (both directions).

    If no link exists between the two documents, reports that cleanly.
    """
    params = UnlinkDocInput(source_doc=source_doc, target_doc=target_doc)
    storage = _get_storage(ctx)
    deleted = storage.unlink_doc(params.source_doc, params.target_doc)
    if deleted == 0:
        return f"No link found between '{params.source_doc}' and '{params.target_doc}'."
    return (
        f"Removed link between '{params.source_doc}' and '{params.target_doc}' "
        f"({deleted} row(s) deleted)."
    )


class FindRelatedInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    doc_id: str = Field(..., description="Document ID to find related documents for", min_length=1)


@mcp.tool(
    title="Find Related Documents",
    name="vault_find_related",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_find_related(ctx: Context, doc_id: str) -> str:
    """Find all documents linked to a given document. Pro only.

    Returns each related document with its vault, category, tags, and link label.
    Use vault_link_doc to create new links.
    """
    params = FindRelatedInput(doc_id=doc_id)
    status = get_license_status()
    if not status["is_pro"]:
        return (
            "Error: vault_find_related requires LoreDocs Pro. "
            "Use vault_set_tier with tier='pro' to activate your license."
        )

    storage = _get_storage(ctx)
    related = storage.find_related_docs(params.doc_id)
    if not related:
        return (
            f"No related documents found for '{params.doc_id}'. "
            "Use vault_link_doc to create links."
        )

    lines = [f"Found {len(related)} related document(s):", ""]
    for r in related:
        tag_str = ", ".join(r["tags"]) if r["tags"] else "none"
        lines.append(
            f"- [{r['label']}] {r['name']} "
            f"(vault: {r['vault_name']}, category: {r['category']}, tags: {tag_str})"
        )
        lines.append(f"  ID: {r['id']}  updated: {r['updated_at'][:10]}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Phase 2: vault_suggest
# ---------------------------------------------------------------------------

class VaultSuggestInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    vault: Optional[str] = Field(
        default=None,
        description="Vault ID or name to scope suggestions to (omit for all vaults)"
    )
    limit: int = Field(default=5, ge=1, le=20, description="Max suggestions to return")


@mcp.tool(
    title="Get Document Suggestions",
    name="vault_suggest",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_suggest(
    ctx: Context,
    vault: Optional[str] = None,
    limit: int = 5,
) -> str:
    """Get suggestions for documents that may need attention.

    Surfaces documents that are undocumented (no notes), unorganized (no tags),
    or isolated (no links to other documents).  Use to guide housekeeping work
    or to discover documents that haven't been connected to the broader graph.

    Optionally scope to a single vault.
    """
    params = VaultSuggestInput(vault=vault, limit=limit)
    storage = _get_storage(ctx)
    vault_id: Optional[str] = None
    if params.vault:
        vault = _resolve_vault(storage, params.vault)
        if not vault:
            return f"Error: Vault '{params.vault}' not found."
        vault_id = vault["id"]

    suggestions = storage.get_suggestions(vault_id=vault_id, limit=params.limit)
    if not suggestions:
        return "No suggestions right now -- your vaults look well-organized!"

    lines = [f"Found {len(suggestions)} suggestion(s):", ""]
    for s in suggestions:
        lines.append(f"[{s['reason']}] {s['doc_name']} (vault: {s['vault_name']})")
        lines.append(f"  -> {s['label']}")
        lines.append(f"  doc_id: {s['doc_id']}  updated: {s['updated_at'][:10]}")
        lines.append("")
    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# Phase 2: vault_export_manifest
# ---------------------------------------------------------------------------

class ExportManifestInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    vault: str = Field(..., description="Vault ID or name to export manifest for", min_length=1)
    format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: markdown or json"
    )


@mcp.tool(
    title="Export Vault Manifest",
    name="vault_export_manifest",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_export_manifest(
    ctx: Context,
    vault: str,
    format: ResponseFormat = ResponseFormat.MARKDOWN,
) -> str:
    """Export a complete manifest of a vault's contents.

    Returns vault metadata, document list with tags and categories,
    tag frequency index, category counts, and link count.
    Use the json format for machine-readable output.
    Use the markdown format for human-readable summaries.
    """
    params = ExportManifestInput(vault=vault, format=format)
    storage = _get_storage(ctx)
    vault = _resolve_vault(storage, params.vault)
    if not vault:
        return f"Error: Vault '{params.vault}' not found."

    manifest = storage.get_vault_manifest(vault["id"])
    if not manifest:
        return f"Error: Could not generate manifest for vault '{params.vault}'."

    if params.format == ResponseFormat.JSON:
        import json as _json
        return _json.dumps(manifest, indent=2, default=str)

    # Markdown format
    v = manifest["vault"]
    lines = [
        f"# Vault Manifest: {v['name']}",
        "",
        f"**Description:** {v['description'] or '(none)'}",
        f"**Documents:** {manifest['document_count']}",
        f"**Links:** {manifest['link_count']}",
        f"**Generated:** {manifest['generated_at'][:19]}",
        "",
    ]

    if manifest["category_counts"]:
        lines.append("## By Category")
        for cat, cnt in sorted(manifest["category_counts"].items()):
            lines.append(f"- {cat}: {cnt}")
        lines.append("")

    if manifest["tag_counts"]:
        lines.append("## Tag Index")
        sorted_tags = sorted(manifest["tag_counts"].items(), key=lambda x: -x[1])
        for tag, cnt in sorted_tags:
            lines.append(f"- {tag}: {cnt}")
        lines.append("")

    if manifest["documents"]:
        lines.append("## Documents")
        for doc in manifest["documents"]:
            tag_str = ", ".join(doc["tags"]) if doc["tags"] else "untagged"
            lines.append(f"- **{doc['name']}** [{doc['category']}]  tags: {tag_str}")
            lines.append(f"  ID: {doc['id']}  updated: {doc['updated_at'][:10]}")

    return "\n".join(lines)


# ===================================================================
# TIER MANAGEMENT TOOLS
# ===================================================================

class VaultTierStatusInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' (default) or 'json'"
    )


@mcp.tool(
    title="Get Tier Status",
    name="vault_tier_status",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_tier_status(
    ctx: Context,
    response_format: ResponseFormat = ResponseFormat.MARKDOWN,
) -> str:
    """Show current tier (Free or Pro) and usage vs. limits.

    Displays how many vaults and how much storage are in use, with percentages
    against Free tier limits. Useful before hitting a limit to know how close
    you are, or to confirm Pro tier is active after upgrading.
    """
    params = VaultTierStatusInput(response_format=response_format)
    storage = _get_storage(ctx)

    vault_count = len(storage.list_vaults(include_archived=False))
    total_bytes = storage.get_total_storage_bytes()
    status = storage.enforcer.status_dict(vault_count, total_bytes)

    if params.response_format == ResponseFormat.JSON:
        return json.dumps(status, indent=2)

    tier_label = "Pro (unlimited)" if status["is_pro"] else "Free"
    lines = [
        "# LoreDocs Tier Status",
        "",
        f"**Tier:** {tier_label}",
        "",
        "## Usage",
        "",
    ]

    # Vaults
    vault_limit_str = str(status["vault_limit"]) if status["vault_limit"] is not None else "unlimited"
    pct_str = f" ({status['vault_usage_pct']}%)" if status["vault_usage_pct"] is not None else ""
    lines.append(f"- **Vaults:** {status['vault_count']} / {vault_limit_str}{pct_str}")

    # Storage
    storage_limit_str = (
        f"{status['storage_limit_mb']} MB" if status["storage_limit_mb"] is not None else "unlimited"
    )
    storage_pct_str = (
        f" ({status['storage_usage_pct']}%)" if status["storage_usage_pct"] is not None else ""
    )
    lines.append(
        f"- **Storage:** {status['storage_used_mb']} MB / {storage_limit_str}{storage_pct_str}"
    )

    # Per-vault and per-doc limits
    doc_limit = status["docs_per_vault_limit"]
    ver_limit = status["versions_per_doc_limit"]
    lines.append(
        f"- **Docs per vault:** "
        f"{doc_limit if doc_limit is not None else 'unlimited'}"
    )
    lines.append(
        f"- **Versions per doc:** "
        f"{ver_limit if ver_limit is not None else 'unlimited'}"
    )

    if not status["is_pro"]:
        lines += [
            "",
            "## Upgrade to Pro",
            "",
            "Pro tier removes all limits. Use `vault_set_tier` with `tier='pro'` "
            "to activate your license after purchase.",
        ]

    return "\n".join(lines)


class VaultSetTierInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    tier: str = Field(
        ...,
        description="Tier to activate: 'free' or 'pro'",
        pattern="^(free|pro)$"
    )


@mcp.tool(
    title="Set License Tier",
    name="vault_set_tier",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
)
async def vault_set_tier(ctx: Context, tier: str) -> str:
    """Activate a tier (free or pro) for LoreDocs.

    Pro tier removes all vault, document, storage, and version limits.
    After purchasing a Pro license, set LOREDOCS_PRO=<your-license-key> in
    your environment and restart the server, then call this tool with tier='pro'
    to persist the Pro tier. Reverting to tier='free' re-enables limits (but
    does not delete any existing data that exceeds the limits -- it only blocks
    new writes).
    """
    params = VaultSetTierInput(tier=tier)
    storage = _get_storage(ctx)

    # Require a valid license key before persisting Pro tier.
    # This prevents callers from bypassing license validation by writing 'pro'
    # directly to config.json (GINA-001 / SEC-017).
    if params.tier == "pro":
        status = get_license_status()
        if not status["is_pro"]:
            if status.get("mode") == "invalid_key":
                return (
                    "Error: Invalid or expired license key in LOREDOCS_PRO. "
                    + status.get("error", "")
                    + " Get a new key at labyrinthanalyticsconsulting.com."
                )
            return (
                "Error: No Pro license key found. "
                "Set LOREDOCS_PRO=<your-license-key> in your environment and "
                "restart the server, then call vault_set_tier again. "
                "Get a license key at labyrinthanalyticsconsulting.com."
            )

    prev_tier = get_tier(storage.root)
    try:
        set_tier(storage.root, params.tier)
    except ValueError as exc:
        return f"Error: {exc}"

    # Phase 2a: archive/unarchive embedding links on tier transition (defense-in-depth)
    if prev_tier == "pro" and params.tier == "free":
        storage.archive_embedding_links()
    elif prev_tier == "free" and params.tier == "pro":
        storage.unarchive_embedding_links()

    limits = TIER_LIMITS[params.tier]
    if limits.is_unlimited():
        summary = "All limits removed. Enjoy unlimited vaults, documents, and storage."
    else:
        summary = (
            f"Free tier active. Limits: {limits.max_vaults} vaults, "
            f"{limits.max_docs_per_vault} docs/vault, "
            f"{(limits.max_storage_bytes or 0) // (1024 * 1024)} MB storage, "
            f"{limits.max_versions_per_doc} versions/doc."
        )

    return f"[OK] Tier set to '{params.tier}'. {summary}"


# ---------------------------------------------------------------------------
# License tier diagnostic
# ---------------------------------------------------------------------------

@mcp.tool(title="Get License Tier", name="get_license_tier")
def get_license_tier() -> dict:
    """Return the current LoreDocs license tier and status.

    Use this to confirm whether the Pro license key is loaded and valid.

    Returns a dict with keys:
        is_pro  -- bool, True if Pro tier is active
        mode    -- "licensed" | "dev_bypass" | "free" | "invalid_key"
        product -- product name from the license payload (if licensed)
        exp     -- expiry date or "never" (if licensed)
        email   -- customer email (if licensed and present)
        error   -- error message (if mode is "invalid_key")
    """
    return get_license_status()


# ---------------------------------------------------------------------------
# Cross-product linking tools (Phase 2b, SH-10727)
# Requires LoreConvo to be installed. Pro tier only for auto-links.
# ---------------------------------------------------------------------------

@mcp.tool(title="Link Session to Doc", name="vault_link_session")
def vault_link_session(
    ctx: Context,
    session_id: str,
    doc_id: str,
    vault_id: str,
) -> dict:
    """Create a manual cross-product link from a LoreConvo session to a LoreDocs doc.

    Both LoreConvo and LoreDocs must be installed. Manual links are accessible
    on all tiers. The linked doc must not be in an opt-out vault.

    Args:
        session_id  -- LoreConvo session UUID
        doc_id      -- LoreDocs document ID
        vault_id    -- LoreDocs vault containing the document

    Returns dict with:
        ok          -- bool
        session_id, doc_id on success
        reason      -- failure description (generic; details in debug log)
    """
    storage = _get_storage(ctx)
    try:
        lc_db = discover_product_db("loreconvo")
    except DiscoveryError:
        return {"ok": False, "reason": "Cross-product linking unavailable"}
    if lc_db is None:
        return {"ok": False, "reason": "Cross-product linking unavailable"}

    is_pro = get_tier(storage.root) == TIER_PRO
    return storage.link_session_to_doc(
        session_id=session_id,
        doc_id=doc_id,
        vault_id=vault_id,
        link_type="manual",
        is_pro=is_pro,
    )


@mcp.tool(title="Get Session Links for Doc", name="vault_get_session_links")
def vault_get_session_links(ctx: Context, doc_id: str, limit: int = 5) -> dict:
    """Return cross-product LoreConvo sessions linked to a LoreDocs document.

    Both LoreConvo and LoreDocs must be installed. Requires Pro tier for
    auto-links. Manual links are always returned.

    Args:
        doc_id  -- LoreDocs document ID
        limit   -- max results (default 5)

    Returns dict with:
        schema_version          -- CROSS_LINK_SCHEMA_VERSION for version negotiation
        cross_product_available -- bool
        tier_gate               -- "satisfied" | "pro_required"
        links                   -- list of {target_product, target_id, similarity_score,
                                   link_type, created_at, is_stale}
    """
    storage = _get_storage(ctx)
    try:
        lc_db = discover_product_db("loreconvo")
    except DiscoveryError:
        return {
            "schema_version": CROSS_LINK_SCHEMA_VERSION,
            "cross_product_available": False,
            "reason": "Cross-product linking unavailable",
            "links": [],
        }
    if lc_db is None:
        return {
            "schema_version": CROSS_LINK_SCHEMA_VERSION,
            "cross_product_available": False,
            "reason": "Cross-product linking unavailable",
            "links": [],
        }

    is_pro = get_tier(storage.root) == TIER_PRO
    return storage.get_cross_product_links(
        source_product="loredocs",
        source_id=doc_id,
        current_embedding_model=_CROSS_LINK_EMBEDDING_MODEL,
        limit=limit,
        is_pro=is_pro,
    )


@mcp.tool(title="Get Linked Sessions", name="vault_get_linked_sessions")
def vault_get_linked_sessions(ctx: Context, session_id: str, limit: int = 5) -> dict:
    """Return LoreDocs documents linked to a given LoreConvo session.

    Queries the LoreDocs cross_product_links table for links where the session
    is the source or target. Returns both auto and manual links. Requires Pro
    tier for auto-links.

    Args:
        session_id  -- LoreConvo session UUID
        limit       -- max results (default 5)

    Returns same structure as vault_get_session_links.
    """
    storage = _get_storage(ctx)
    try:
        lc_db = discover_product_db("loreconvo")
    except DiscoveryError:
        return {
            "schema_version": CROSS_LINK_SCHEMA_VERSION,
            "cross_product_available": False,
            "reason": "Cross-product linking unavailable",
            "links": [],
        }
    if lc_db is None:
        return {
            "schema_version": CROSS_LINK_SCHEMA_VERSION,
            "cross_product_available": False,
            "reason": "Cross-product linking unavailable",
            "links": [],
        }

    is_pro = get_tier(storage.root) == TIER_PRO
    return storage.get_cross_product_links(
        source_product="loreconvo",
        source_id=session_id,
        current_embedding_model=_CROSS_LINK_EMBEDDING_MODEL,
        limit=limit,
        is_pro=is_pro,
    )


# ---------------------------------------------------------------------------
# Compatibility guard
# ---------------------------------------------------------------------------

@mcp.tool(title="Get Server Info")
def get_server_info() -> dict:
    """Return MCP compatibility status for this LoreDocs server.

    Returns product version, installed mcp SDK version, tested version, and
    compatibility status. Useful for diagnosing version mismatches on running
    servers without requiring a restart.

    Returns dict with: product_name, product_version, mcp_installed, mcp_tested,
    mcp_accepted, status (ok|mismatch|undetermined|disabled|internal_error), note.
    """
    result = _compat_check()
    return {k: v for k, v in result.items() if k != "error_detail"}


# ---------------------------------------------------------------------------
# Web UI (SH-11803: Pro vault startup warning)
# ---------------------------------------------------------------------------

def run_ui(port: int, open_browser: bool, token: Optional[str] = None, suppress_warning: bool = False):
    """Run the LoreDocs web UI (stub -- full implementation in SH-10404).

    This function implements the Pro vault startup warning (SH-11803).
    Full web UI routes, templates, and tier checking are deferred to SH-10404.
    """
    import sqlite3
    import urllib.parse

    # Get database path using same logic as MCP server
    db_path = VaultStorage()._db_path()

    if db_path.exists():
        try:
            encoded_path = urllib.parse.quote(str(db_path))
            conn = sqlite3.connect(f"file:{encoded_path}?mode=ro", uri=True)
            conn.execute("PRAGMA busy_timeout=2000")

            # Check for Pro vaults if token not set and warning not suppressed
            if not token and not suppress_warning:
                pro_vault_count = conn.execute(
                    "SELECT COUNT(*) FROM vaults WHERE tier IN ('pro', 'team') AND archived=0"
                ).fetchone()[0]
                if pro_vault_count > 0:
                    sys.stderr.write(
                        f"WARNING: {pro_vault_count} Pro/Team vault(s) detected. "
                        "Set LOREDOCS_UI_TOKEN=<token> for additional protection "
                        "against local process access. Example: "
                        "LOREDOCS_UI_TOKEN=$(openssl rand -hex 16) loredocs ui\n"
                    )
            conn.close()
        except sqlite3.OperationalError:
            pass

    # Placeholder: full web UI implementation deferred to SH-10404
    print(f"LoreDocs web UI stub: listening on port {port}")
    print("(Full web UI implementation pending SH-10404)")
    sys.exit(0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Run the LoreDocs MCP server."""
    _compat_emit(_compat_check())
    from . import idle_watchdog
    # Reap this process if the client parks it idle, freeing resources.
    idle_watchdog.install(mcp, env_var="LOREDOCS_IDLE_TIMEOUT")
    mcp.run()


if __name__ == "__main__":
    main()
