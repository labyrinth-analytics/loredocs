"""
LoreDocs Notion Import Bridge -- NotionImporter and supporting classes.

This module implements the import-once-and-own model: pages and databases are
fetched from Notion once and stored as LoreDocs documents. There is no live
sync dependency; Notion changes after import do not propagate automatically.

Key classes:
- NotionImporter: orchestrates page/database import, block flattening,
  and block-depth truncation reporting.
- RateLimitTracker: per-page 429 tracking with saturation detection.
- WorkspaceSaturationError: raised when consecutive 429s exceed threshold.

Security:
- All Notion SDK calls are wrapped with redact_secrets exception handling.
- The raw token is accessed only via .secret_value inside this module.
- Exception rethrow uses `from None` to strip the cause chain, preventing
  token-bearing exception objects from being attached to the re-raised exception.
"""

import base64
import json
import os
import re
import sys
import time
import uuid
import signal
import random
import platform
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional

from .notion_checkpoint import (
    _SecretStr,
    NotionTokenMissingError,
    NotionTokenRevokedError,
    NotionAPIError,
    NotionImportError,
    VaultNotFoundError,
    VaultAmbiguousError,
    CheckpointManager,
    redact_secrets,
    resolve_notion_token,
)
from .storage import normalize_origin_id

# ---------------------------------------------------------------------------
# Block depth truncation (r5/H4)
# ---------------------------------------------------------------------------

# Configurable via env var. Default 10: blocks below this depth are not
# fetched. The parent block at the cap depth gets an appended marker line.
# The same env-var rationale comment style is used for SATURATION_WINDOW.
BLOCK_DEPTH_DEFAULT = 10


def _get_max_block_depth():
    """Read block depth cap from env. Returns int."""
    try:
        return int(os.environ.get("LOREDOCS_NOTION_MAX_BLOCK_DEPTH", BLOCK_DEPTH_DEFAULT))
    except (ValueError, TypeError):
        return BLOCK_DEPTH_DEFAULT


# ---------------------------------------------------------------------------
# Rate limiting (r4 HIGH-15/HIGH-16, r5/H9/H11)
# ---------------------------------------------------------------------------

# Default consecutive cross-page 429 threshold. Fewer than 10 indicates burst
# traffic or transient workspace contention -- Retry-After backoff handles
# these. 10+ consecutive cross-page 429s after respecting Retry-After indicates
# genuine workspace saturation (another integration is consuming the full
# quota). At that point, a pause-and-alert response is correct.
# LOREDOCS_NOTION_SATURATION_WINDOW env var allows power users to tune for
# noisier workspaces (higher value) or fail-fast scenarios.
SATURATION_WINDOW_DEFAULT = 10


def _get_saturation_window():
    """Read saturation window from env. Returns int."""
    try:
        return int(
            os.environ.get(
                "LOREDOCS_NOTION_SATURATION_WINDOW", SATURATION_WINDOW_DEFAULT
            )
        )
    except (ValueError, TypeError):
        return SATURATION_WINDOW_DEFAULT


# [r5/H9] cap any server-supplied wait; a malformed or far-future Retry-After
# must never hang the import
MAX_RETRY_AFTER = 300


def _get_retry_after(headers, default_backoff):
    """
    Extract Retry-After value from rate-limit response headers.
    RFC 7231 permits BOTH delay-seconds and HTTP-date; parse both. [r5/H9]
    """
    after = (headers or {}).get("Retry-After") or (headers or {}).get("retry-after")
    if after:
        try:
            return min(max(float(after), 0.1), MAX_RETRY_AFTER)  # floor 0.1s, cap 300s
        except (ValueError, TypeError):
            pass
        try:  # [r5/H9] HTTP-date form (e.g. "Wed, 21 Oct 2026 07:28:00 GMT")
            parsed = parsedate_to_datetime(after)
            delay = (parsed - datetime.now(timezone.utc)).total_seconds()
            return min(max(delay, 0.1), MAX_RETRY_AFTER)
        except (ValueError, TypeError):
            pass
    return default_backoff


class WorkspaceSaturationError(Exception):
    """Raised when consecutive cross-page 429s reach the saturation window."""


class RateLimitTracker:
    """
    Tracks per-page 429 responses for saturation detection.

    The consecutive_429s counter increments only after per-page retry
    exhaustion (all per-page retries consumed with 429). This distinguishes
    "one page is hard to fetch" from "all fetches are 429ing".

    [r5/H11] The importer's per-page exception handler MUST call exactly one
    of record_success / record_429 / record_non_429_failure for every page
    outcome, so "consecutive" in the saturation check means genuinely
    consecutive 429s.
    """

    def __init__(self):
        self._consecutive_429s = 0

    def record_429(self, headers=None, base_backoff=1.0, attempt=1):
        """
        Record a page-level 429 after all per-page retries exhausted.
        Returns the wait duration (Retry-After-driven or exponential fallback).
        Raises WorkspaceSaturationError when consecutive count reaches
        SATURATION_WINDOW.
        """
        self._consecutive_429s += 1
        window = _get_saturation_window()
        if self._consecutive_429s >= window:
            raise WorkspaceSaturationError(
                f"{window} consecutive rate-limit responses across pages. "
                f"Workspace quota appears saturated by other integrations. "
                f"LOREDOCS_NOTION_SATURATION_WINDOW={window} (configurable)."
            )
        retry_after = _get_retry_after(headers, base_backoff * (2 ** min(attempt, 5)))
        jitter = random.uniform(0, retry_after * 0.1)
        return retry_after + jitter

    def record_success(self):
        self._consecutive_429s = 0

    def record_non_429_failure(self):
        # [r5/H11] a timeout / 5xx / connection reset breaks the consecutive-429
        # run; without this reset, alternating 429s and network errors trip
        # saturation falsely
        self._consecutive_429s = 0


# ---------------------------------------------------------------------------
# Vault resolution (r4 HIGH-04)
# ---------------------------------------------------------------------------


class _ResolvedVault:
    """Lightweight container for resolved vault metadata."""
    def __init__(self, vault_id, name):
        self.id = vault_id
        self.name = name


def _resolve_vault(storage, vault_spec):
    """
    Resolve a vault from name or opaque UUID string (both case-insensitive).

    Resolution order:
    1. Try exact UUID match against vault.id (case-insensitive).
    2. Try case-insensitive name match against vault.name.
    3. Zero matches: raise VaultNotFoundError.
    4. Multiple name matches: raise VaultAmbiguousError.

    Callers should prefer vault IDs for automation (stable across renames).
    Names are supported for interactive use.
    """
    import sqlite3

    with storage._db() as conn:
        # 1. Try UUID match (case-insensitive)
        row = conn.execute(
            "SELECT id, name FROM vaults WHERE LOWER(id) = LOWER(?) AND archived = 0",
            (vault_spec,),
        ).fetchone()
        if row:
            return _ResolvedVault(row["id"], row["name"])

        # 2. Try name match (case-insensitive)
        rows = conn.execute(
            "SELECT id, name FROM vaults WHERE LOWER(name) = LOWER(?) AND archived = 0",
            (vault_spec,),
        ).fetchall()
        if len(rows) == 1:
            return _ResolvedVault(rows[0]["id"], rows[0]["name"])
        if len(rows) > 1:
            ids = ", ".join(r["id"] for r in rows)
            raise VaultAmbiguousError(
                f"Vault name '{vault_spec}' matches {len(rows)} vaults: {ids}. "
                f"Use the vault ID."
            )

    raise VaultNotFoundError(
        f"Vault '{vault_spec}' not found. Use vault_list to see available vaults."
    )


# ---------------------------------------------------------------------------
# Continuation token (r4 HIGH-06/HIGH-07, r5/H2/H3)
# ---------------------------------------------------------------------------


def _encode_continuation_token(vault_id, remaining_page_ids, remaining_db_ids, checkpoint_file):
    """
    Encode continuation token as URL-safe base64 (no padding).

    [r5/H2] vault_id is the vault's primary-key UUID, not its name. A vault
    that is deleted and recreated under the same name receives a NEW primary
    key, so the token's equality check fails loudly (conflict error) rather
    than silently retargeting the new vault. Recreation-under-same-name is a
    deliberate token invalidation, not a resume path.
    """
    data = {
        "schema": 1,
        "vault_id": vault_id,
        "remaining_page_ids": remaining_page_ids or [],
        "remaining_db_ids": remaining_db_ids or [],
        "checkpoint_file": checkpoint_file,
    }
    raw = json.dumps(data).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_continuation_token(token):
    """Decode continuation token. Callers MUST NOT parse it."""
    padding = "=" * (4 - len(token) % 4) if len(token) % 4 else ""
    raw = base64.urlsafe_b64decode(token + padding)
    return json.loads(raw.decode("utf-8"))


def _validate_token_arg_consistency(token_data, resolved_vault_id,
                                     resolved_checkpoint_file,
                                     page_ids, database_ids):
    """
    Detect and reject mismatched token/arg combinations.
    Called immediately after token decode, before any Notion API call.

    [r5/H3] database_ids was accepted but never validated in r4. Now mirrors
    the page_ids check.
    """
    mismatches = []
    if token_data["vault_id"] != resolved_vault_id:
        mismatches.append(
            f"vault: token encodes '{token_data['vault_id']}', "
            f"current call resolves to '{resolved_vault_id}'"
        )
    token_ckpt = token_data.get("checkpoint_file")
    if token_ckpt != resolved_checkpoint_file:
        mismatches.append(
            f"checkpoint_file: token encodes '{token_ckpt}', "
            f"current call uses '{resolved_checkpoint_file}'"
        )
    # page_ids: if caller explicitly provides non-empty page_ids, check for
    # conflict. An empty/null page_ids is not a conflict -- the token drives
    # the remaining set.
    if page_ids and set(page_ids) != set(token_data.get("remaining_page_ids", [])):
        mismatches.append(
            "page_ids differ from token state; omit page_ids when resuming with a token"
        )
    # [r5/H3] mirror check -- database_ids was accepted but never validated in r4
    if database_ids and set(database_ids) != set(token_data.get("remaining_db_ids", [])):
        mismatches.append(
            "database_ids differ from token state; omit database_ids when resuming with a token"
        )
    if mismatches:
        raise ValueError(
            "continuation_token conflicts with provided arguments. "
            "To resume, omit page_ids/database_ids/vault/checkpoint_file, "
            "or pass only the continuation_token. "
            "To start fresh, omit continuation_token. "
            f"Conflicts: {'; '.join(mismatches)}"
        )


# ---------------------------------------------------------------------------
# Notion UUID validation
# ---------------------------------------------------------------------------

# Matches both 32-hex (no dashes) and 36-char (with dashes) Notion UUIDs
_NOTION_UUID_RE = re.compile(r"^[0-9a-f]{32}$|^[0-9a-f-]{36}$")


def _validate_notion_ids(ids, field_name):
    """Validate a list of Notion page/database UUIDs. Raises ValueError on invalid."""
    if not ids:
        return
    for uid in ids:
        if not _NOTION_UUID_RE.match(uid.lower()):
            raise ValueError(
                f"Invalid Notion UUID in {field_name}: {uid!r}. "
                f"Expected 32 hex chars (no dashes) or 36 chars (with dashes)."
            )


def _normalize_notion_id(raw_id):
    """Normalize a Notion page/database ID for storage as origin_id."""
    return normalize_origin_id("notion", raw_id)


# ---------------------------------------------------------------------------
# NotionImporter
# ---------------------------------------------------------------------------

# Per-page retry policy
PER_PAGE_BASE_BACKOFF = 1.0
PER_PAGE_MULTIPLIER = 2
PER_PAGE_MAX_WAIT = 30
PER_PAGE_MAX_RETRIES = 3

# Saturation pause (CLI only)
SATURATION_SLEEP_INTERVAL = 5  # seconds per check; signals fire between checks
SATURATION_PAUSE_CYCLES = 60  # 60 * 5s = 300s total
MAX_SATURATION_PAUSES = 3

# Active HTML block types rendered as placeholders to prevent stored-XSS
_ACTIVE_HTML_BLOCK_TYPES = {"equation", "synced_block", "link_preview"}

# [r5/H12] module-level idempotency flag for signal handler reentrancy
_handling_signal = False


class NotionImporter:
    """
    Imports Notion pages and databases into LoreDocs vaults.

    Import-once-and-own model: pages are fetched once and stored as LoreDocs
    documents. No live sync dependency.

    Block depth capped at LOREDOCS_NOTION_MAX_BLOCK_DEPTH (default 10). Blocks
    below the cap are not fetched; the parent block at the cap depth gets an
    appended marker line [r5/H4].
    """

    def __init__(self, storage, vault_id, token=None, checkpoint_mgr=None,
                 rate_tracker=None):
        self.storage = storage
        self.vault_id = vault_id
        self.token = token  # _SecretStr or None (resolved per-call)
        self.checkpoint_mgr = checkpoint_mgr
        self.rate_tracker = rate_tracker or RateLimitTracker()
        self._max_block_depth = _get_max_block_depth()

    def _get_client(self):
        """Create a Notion client using the resolved token."""
        if self.token is None:
            self.token = resolve_notion_token()
        raw = self.token.secret_value
        try:
            from notion_client import Client
            return Client(auth=raw)
        except ImportError:
            raise NotionImportError(
                "notion-client is not installed. "
                "Install with: pip install 'loredocs[notion]'"
            )

    def _safe_sdk_call(self, fn, *args, **kwargs):
        """
        Wrap a Notion SDK call with redaction and exception sanitization.

        Uses `from None` to strip the cause chain, preventing token-bearing
        exception objects from being attached to the re-raised exception.
        """
        raw = self.token.secret_value if self.token else None
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            # Check for 429 in the exception to feed the rate tracker
            safe_msg = redact_secrets(str(exc), raw_token=raw)
            # Re-raise with redacted message, stripped cause chain
            raise NotionAPIError(safe_msg) from None

    def _fetch_page_content(self, client, page_id):
        """
        Fetch and flatten a Notion page's block tree into markdown text.

        Block depth capped at self._max_block_depth. Blocks below the cap are
        NOT fetched. The parent block at the cap depth gets an appended marker
        line. Returns (text, was_truncated).
        """
        blocks = self._safe_sdk_call(
            client.blocks.children.list, block_id=page_id
        )
        results = blocks.get("results", []) if isinstance(blocks, dict) else []
        text_parts = []
        was_truncated = False

        for block in results:
            block_text, block_truncated = self._flatten_block(client, block, depth=1)
            text_parts.append(block_text)
            if block_truncated:
                was_truncated = True

        return "\n\n".join(text_parts), was_truncated

    def _flatten_block(self, client, block, depth):
        """
        Recursively flatten a Notion block into markdown text.

        Returns (text, was_truncated).
        """
        block_type = block.get("type", "")
        block_id = block.get("id", "")

        # Render block content based on type
        text = self._render_block_text(block, block_type)

        # Check for children
        has_children = block.get("has_children", False)
        if has_children and depth < self._max_block_depth:
            child_blocks = self._safe_sdk_call(
                client.blocks.children.list, block_id=block_id
            )
            child_results = child_blocks.get("results", []) if isinstance(child_blocks, dict) else []
            child_parts = []
            child_truncated = False
            for child in child_results:
                ct, ctrunc = self._flatten_block(client, child, depth + 1)
                child_parts.append(ct)
                if ctrunc:
                    child_truncated = True
            if child_parts:
                indent = "  " * depth
                text += "\n" + "\n".join(indent + cp for cp in child_parts)
            return text, child_truncated
        elif has_children and depth >= self._max_block_depth:
            # [r5/H4] Block-depth truncation is explicit
            marker = f"[truncated: nested content below depth {self._max_block_depth} not imported]"
            text += f"\n{marker}"
            return text, True

        return text, False

    def _render_block_text(self, block, block_type):
        """
        Render a single Notion block's text content as markdown.

        Active HTML block types (equation, synced_block, link_preview) are
        rendered as placeholders to prevent stored-XSS.
        """
        if block_type in _ACTIVE_HTML_BLOCK_TYPES:
            return f"[{block_type}: content placeholder -- active HTML type, not imported]"

        block_data = block.get(block_type, {})
        if not isinstance(block_data, dict):
            return ""

        # Rich text extraction (common to most block types)
        rich_text = block_data.get("rich_text", [])
        if rich_text:
            return self._rich_text_to_markdown(rich_text)

        # Code blocks
        if block_type == "code":
            code = block_data.get("rich_text", [])
            code_text = self._rich_text_to_markdown(code)
            lang = block_data.get("language", "")
            return f"```{lang}\n{code_text}\n```"

        # Heading levels
        if block_type.startswith("heading_"):
            level = block_type.count("_")  # heading_1 -> 1, heading_2 -> 2, etc.
            prefix = "#" * min(level, 6)
            rich_text = block_data.get("rich_text", [])
            return f"{prefix} {self._rich_text_to_markdown(rich_text)}"

        # Bulleted/numbered/to-do list items
        if block_type in ("bulleted_list_item", "numbered_list_item", "to_do"):
            prefix = "-" if "bulleted" in block_type else ("1." if "numbered" in block_type else "- [ ]")
            rich_text = block_data.get("rich_text", [])
            checked = block_data.get("checked", False)
            if block_type == "to_do":
                prefix = "- [x]" if checked else "- [ ]"
            return f"{prefix} {self._rich_text_to_markdown(rich_text)}"

        # Divider
        if block_type == "divider":
            return "---"

        # Image / file (just note the caption)
        if block_type in ("image", "file", "video", "pdf", "bookmark"):
            caption = block_data.get("caption", [])
            cap_text = self._rich_text_to_markdown(caption)
            if cap_text:
                return f"[{block_type}: {cap_text}]"
            return f"[{block_type}: external content -- not imported]"

        # Table (just note it exists)
        if block_type == "table":
            return "[table: structured data -- import as separate document if needed]"

        # Default: try to get plain text from any rich_text field
        rich_text = block_data.get("rich_text", [])
        if rich_text:
            return self._rich_text_to_markdown(rich_text)

        return ""

    def _rich_text_to_markdown(self, rich_text_list):
        """Convert Notion rich_text array to markdown string."""
        if not rich_text_list:
            return ""
        parts = []
        for rt in rich_text_list:
            if not isinstance(rt, dict):
                continue
            text = rt.get("plain_text", "")
            if not text:
                continue
            annotations = rt.get("annotations", {})
            if annotations.get("bold"):
                text = f"**{text}**"
            if annotations.get("italic"):
                text = f"*{text}*"
            if annotations.get("code"):
                text = f"`{text}`"
            href = rt.get("href")
            if href:
                text = f"[{text}]({href})"
            parts.append(text)
        return "".join(parts)

    def _properties_to_tags(self, page_data):
        """Extract tags from Notion page properties (multi-select fields)."""
        tags = []
        properties = page_data.get("properties", {})
        for prop_name, prop_data in properties.items():
            if not isinstance(prop_data, dict):
                continue
            prop_type = prop_data.get("type", "")
            if prop_type == "multi_select":
                for opt in prop_data.get("multi_select", []):
                    if isinstance(opt, dict) and opt.get("name"):
                        tags.append(opt["name"])
            elif prop_type == "select":
                sel = prop_data.get("select")
                if isinstance(sel, dict) and sel.get("name"):
                    tags.append(sel["name"])
        return tags

    def import_pages(self, page_ids, tags=None, category="reference",
                     checkpoint_data=None, run_id=None):
        """
        Import a list of Notion page IDs into the vault.

        Returns a dict with: imported, skipped, errors, truncated_pages.
        """
        tags = tags or []
        client = self._get_client()
        imported = 0
        skipped = 0
        errors = []
        truncated_pages = []
        run_id = run_id or str(uuid.uuid4())

        for page_id in page_ids:
            normalized_id = _normalize_notion_id(page_id)
            try:
                # Check dedup via origin_system + origin_id
                existing = self._check_existing(normalized_id)
                if existing and not existing.get("deleted"):
                    skipped += 1
                    self.rate_tracker.record_success()
                    continue

                # Fetch page metadata
                page_data = self._safe_sdk_call(client.pages.retrieve, page_id=page_id)
                page_title = self._extract_title(page_data)
                page_tags = self._properties_to_tags(page_data)
                all_tags = list(set(tags + page_tags))

                # Fetch and flatten block content
                content, was_truncated = self._fetch_page_content(client, page_id)
                if was_truncated:
                    truncated_pages.append(page_id)

                # Store as LoreDocs document
                doc_name = page_title or f"Notion page {page_id[:8]}"
                result = self.storage.add_document_from_text(
                    self.vault_id, doc_name, content,
                    tags=all_tags, category=category,
                    notes=f"Imported from Notion page {page_id}",
                )
                if result:
                    # Update origin_system + origin_id for dedup tracking
                    self._set_origin(result["id"], normalized_id)
                    imported += 1
                    self.rate_tracker.record_success()
                    # Update checkpoint
                    if checkpoint_data is not None:
                        ckpt_key = f"{self.vault_id}:{normalized_id}"
                        checkpoint_data["entries"][ckpt_key] = {
                            "vault_doc_id": result["id"],
                            "imported_at": datetime.now(timezone.utc).isoformat(),
                            "run_id": run_id,
                        }
                else:
                    errors.append(f"Failed to store page {page_id}")
                    self.rate_tracker.record_non_429_failure()

            except WorkspaceSaturationError:
                raise
            except (NotionAPIError, NotionImportError) as exc:
                errors.append(f"Page {page_id}: {exc}")
                self.rate_tracker.record_non_429_failure()
            except Exception as exc:
                raw = self.token.secret_value if self.token else None
                safe_msg = redact_secrets(str(exc), raw_token=raw)
                errors.append(f"Page {page_id}: {safe_msg}")
                self.rate_tracker.record_non_429_failure()

        return {
            "imported": imported,
            "skipped": skipped,
            "errors": errors,
            "truncated_pages": truncated_pages,
        }

    def import_database(self, database_id, tags=None, category="reference",
                         checkpoint_data=None, run_id=None):
        """
        Import all pages from a Notion database.

        Expands database_id to page IDs at first call time. Membership changes
        between continuation calls are NOT captured.

        Returns a dict with: imported, skipped, errors, truncated_pages,
        page_ids (the expanded list for continuation token encoding).
        """
        tags = tags or []
        client = self._get_client()
        run_id = run_id or str(uuid.uuid4())

        # Query database for all pages
        all_page_ids = []
        start_cursor = None
        while True:
            query_args = {"database_id": database_id}
            if start_cursor:
                query_args["start_cursor"] = start_cursor
            response = self._safe_sdk_call(client.databases.query, **query_args)
            if not isinstance(response, dict):
                break
            for page in response.get("results", []):
                pid = page.get("id")
                if pid:
                    all_page_ids.append(pid)
            if response.get("has_more"):
                start_cursor = response.get("next_cursor")
            else:
                break

        result = self.import_pages(
            all_page_ids, tags=tags, category=category,
            checkpoint_data=checkpoint_data, run_id=run_id,
        )
        result["page_ids"] = all_page_ids
        return result

    def _check_existing(self, normalized_origin_id):
        """Check if a document with this origin_id already exists in the vault."""
        with self.storage._db() as conn:
            row = conn.execute(
                "SELECT id, deleted FROM documents "
                "WHERE vault_id = ? AND origin_system = 'notion' "
                "AND origin_id = ? LIMIT 1",
                (self.vault_id, normalized_origin_id),
            ).fetchone()
            if row:
                return {"id": row["id"], "deleted": row["deleted"]}
        return None

    def _set_origin(self, doc_id, normalized_origin_id):
        """Set origin_system and origin_id on a stored document."""
        from .storage import _validate_origin_system
        _validate_origin_system("notion")
        with self.storage._db() as conn:
            conn.execute(
                "UPDATE documents SET origin_system = ?, origin_id = ? "
                "WHERE id = ?",
                ("notion", normalized_origin_id, doc_id),
            )

    def _extract_title(self, page_data):
        """Extract the title from a Notion page."""
        properties = page_data.get("properties", {})
        for prop_data in properties.values():
            if not isinstance(prop_data, dict):
                continue
            if prop_data.get("type") == "title":
                title_arr = prop_data.get("title", [])
                if title_arr and isinstance(title_arr, list):
                    return title_arr[0].get("plain_text", "") if title_arr else ""
        return ""


# ---------------------------------------------------------------------------
# Signal handler for CLI saturation sleep (r4 HIGH-18, r5/H12)
# ---------------------------------------------------------------------------


def _make_signal_handler(checkpoint_manager, checkpoint_data_ref):
    """
    Returns a signal handler that flushes the checkpoint and exits cleanly.

    checkpoint_data_ref is a mutable container (list with one dict) so the
    handler captures the latest state at signal time, not the state at handler
    creation.

    [r5/H12] Reentrancy:
    - _handling_signal: module-level flag; second SIGINT during flush is a
      no-op.
    - _locked: CheckpointManager flag; if the main thread holds the lock, a
      save is already in flight. Entering the lock would deadlock on flock /
      raise OSError after 10s on Windows msvcrt.locking. os.replace in save()
      is atomic, so the on-disk checkpoint is durable either way. Skip the
      handler's save.
    """
    def handler(sig, frame):
        global _handling_signal
        if _handling_signal:  # [r5/H12] second SIGINT during flush: do not re-enter
            return
        _handling_signal = True
        if checkpoint_manager._locked:
            # [r5/H12] main thread holds the lock: a save is already in flight.
            # Entering the lock here would deadlock on flock / raise OSError
            # after 10s on Windows msvcrt.locking. os.replace in save() is
            # atomic, so the on-disk checkpoint is durable either way. Skip
            # the handler's save.
            print(
                f"\n[interrupted] checkpoint save already in progress; state is durable",
                file=sys.stderr
            )
            sys.exit(128 + sig)
        try:
            with checkpoint_manager as ckpt:
                ckpt.save(checkpoint_data_ref[0])
            print(
                f"\n[interrupted] Signal {sig} received. "
                f"Checkpoint flushed. Resume with --resume.",
                file=sys.stderr
            )
        except Exception as flush_err:
            print(
                f"\n[interrupted] Signal {sig}. Checkpoint flush failed: {flush_err}",
                file=sys.stderr
            )
        sys.exit(128 + sig)
    return handler


# ---------------------------------------------------------------------------
# Notion extra availability check (distribution PART -- called from server.py)
# ---------------------------------------------------------------------------


def _notion_extra_available():
    """
    Returns (True, None) if all loredocs[notion] dependencies are importable.
    Returns (False, diagnostic) if any dependency is missing.

    Called once at server startup; result cached by the caller.
    Checks the FULL dependency graph so partial installs (notion-client
    present, keyring absent) are caught here rather than failing at first
    token resolution.
    """
    import importlib
    checks = [
        ("notion-client", "notion_client"),
        ("keyring", "keyring"),
    ]
    missing = []
    for pkg, import_name in checks:
        try:
            importlib.import_module(import_name)
        except ImportError as exc:
            missing.append(f"{pkg} ({exc})")
    if not missing:
        return True, None
    diag = (
        "loredocs[notion] extra is missing or incomplete. "
        "Missing packages: " + ", ".join(missing) + ". "
        "Fix: pip install 'loredocs[notion]'  "
        "or: uvx --with loredocs[notion] loredocs-mcp. "
        "Diagnostic: loredocs check-notion"
    )
    return False, diag