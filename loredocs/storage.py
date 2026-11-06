"""
LoreDocs Storage Layer

Manages the local filesystem and SQLite database that back all vault operations.
Storage is organized as:

    ~/.loredocs/
        config.json
        loredocs.db        (SQLite with FTS5)
        vaults/
            {vault_id}/
                docs/
                    {doc_id}/
                        current{.ext}
                        metadata.json
                        extracted.txt
                        history/
                            v1{.ext}
                            v2{.ext}
"""

import hashlib
import json
import logging
import math
import os
import platform
import re
import shutil
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .fts_query import sanitize_fts_query, validate_fts_query
from .tiers import TierEnforcer, TierLimitError, get_tier, TIER_PRO  # noqa: F401 (re-exported)
from .version_storage import (
    HistoryDivergedError, RecoveryAbortedError, DocumentLockedError,
    LockUnusableError, HistoryBudgetExceededError,
    DocumentLock, DocContext, DocContextManager,
    SIDECAR_SCHEMA_VERSION, JOURNAL_SCHEMA_VERSION, MAX_SIDECAR_SIZE,
    TOMBSTONE_MULTIPLIER, CLOUD_SYNC_PREFIXES,
    FREE_RETENTION_DEPTH, FREE_HISTORY_BUDGET_MB,
    PRO_RETENTION_DEPTH, PRO_HISTORY_BUDGET_MB,
    _hash_file, _safe_write_json, _safe_write_bytes, _fsync_dir,
    _parse_version_number, _content_file_glob, _sidecar_glob,
    _fs_max_version, _sidecar_max_version, _all_evidenced_numbers,
    _read_highwater, _write_highwater, _read_reset_floor,
    _read_intent_journal, _write_intent_journal, _delete_intent_journal,
    _check_lock_health, _compute_retention_depth, _compute_history_budget,
    _vault_history_bytes, _should_warn_substrate, _timestamp_suffix,
    _validate_sidecar, _write_sidecar, _rotate_history_version,
    doc_context_cm,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phase 2a: Deterministic link ID + per-vault circuit breaker
# ---------------------------------------------------------------------------

def _make_link_id(
    source_vault_id: str,
    source_doc_id: str,
    target_vault_id: str,
    target_doc_id: str,
    label: str,
) -> str:
    """Return a deterministic 16-char hex ID that covers the full UNIQUE key.

    The UNIQUE constraint on doc_links is (source_vault_id, source_doc_id,
    target_vault_id, target_doc_id, label). The ID is a SHA-1 hex digest of
    all five components so id collision always implies the same logical link.
    """
    raw = f"{source_vault_id}|{source_doc_id}|{target_vault_id}|{target_doc_id}|{label}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


_EMBD_THRESHOLD = 5
_EMBD_RESET_SECONDS = 1800

# vault_id -> (failure_count, circuit_open, opened_at)
_embd_circuits: Dict[str, Tuple[int, bool, float]] = {}


def _embd_check_circuit(vault_id: str) -> bool:
    state = _embd_circuits.get(vault_id, (0, False, 0.0))
    failures, open_, opened_at = state
    if not open_:
        return True
    reset_secs = int(os.environ.get("LOREDOCS_CIRCUIT_RESET_MINUTES", "30")) * 60
    if time.time() - opened_at >= reset_secs:
        _embd_circuits[vault_id] = (0, False, 0.0)
        return True
    return False


def _embd_record_success(vault_id: str) -> None:
    _embd_circuits.pop(vault_id, None)


def _embd_record_failure(vault_id: str) -> None:
    import logging
    failures, open_, opened_at = _embd_circuits.get(vault_id, (0, False, 0.0))
    if open_:
        _embd_circuits[vault_id] = (failures + 1, True, opened_at)
        return
    failures += 1
    if failures >= _EMBD_THRESHOLD:
        _embd_circuits[vault_id] = (failures, True, time.time())
        logging.getLogger(__name__).warning(
            "auto_link embedding circuit OPEN for vault=%r after %d failures. "
            "Will retry in 30 min.",
            vault_id, _EMBD_THRESHOLD,
        )
    else:
        _embd_circuits[vault_id] = (failures, False, 0.0)
        logging.getLogger(__name__).error(
            "auto_link_doc_embeddings failure %d/%d for vault=%r",
            failures, _EMBD_THRESHOLD, vault_id,
        )

_STOPWORDS = frozenset({
    "a", "about", "after", "again", "ago", "all", "also", "an", "and",
    "any", "are", "as", "at", "be", "been", "being", "but", "by", "can",
    "could", "did", "do", "does", "done", "down", "during", "each",
    "either", "every", "few", "for", "from", "get", "got", "had", "has",
    "have", "he", "her", "here", "him", "his", "how", "i", "if", "in",
    "into", "is", "it", "its", "just", "like", "may", "me", "more",
    "most", "my", "neither", "new", "no", "nor", "not", "now", "of",
    "off", "on", "once", "only", "or", "other", "our", "out", "over",
    "own", "per", "run", "s", "set", "she", "so", "some", "such", "t",
    "than", "that", "the", "their", "them", "then", "there", "these",
    "they", "this", "those", "through", "to", "too", "under", "up",
    "use", "used", "was", "we", "were", "what", "when", "where", "which",
    "while", "who", "will", "with", "would", "yet", "you", "your",
})


def _extract_keywords(text: str, top_n: int = 30) -> List[Tuple[str, int]]:
    """Extract top-N keywords from text using simple term frequency.

    Returns list of (term, frequency) tuples sorted descending by frequency.
    Only includes tokens of 3+ characters not in the stopword list.
    """
    if not text:
        return []
    tokens = re.findall(r'[a-z]{3,}', text.lower())
    counts: Dict[str, int] = {}
    for token in tokens:
        if token not in _STOPWORDS:
            counts[token] = counts.get(token, 0) + 1
    return sorted(counts.items(), key=lambda x: x[1], reverse=True)[:top_n]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_ROOT = Path.home() / ".loredocs"
CONFIG_FILE = "config.json"
DB_FILE = "loredocs.db"
VAULTS_DIR = "vaults"

DEFAULT_DB_FILENAMES = {
    "loreconvo": "sessions.db",
    "loredocs": "loredocs.db",
}

# Cross-product linking (Phase 2b, SH-10727)
# Increment when cross_product_links schema changes incompatibly.
CROSS_LINK_SCHEMA_VERSION = 1
# LoreConvo callers check >= REQUIRED_CROSS_LINK_SCHEMA_VERSION before using links.
REQUIRED_CROSS_LINK_SCHEMA_VERSION = 1
_CROSS_LINK_THRESHOLD = 0.80   # cosine similarity floor
_CROSS_LINK_L2_THRESHOLD = 0.6  # L2-normalized distance ceiling (cosine 0.80 ~ dist 0.632)
_CROSS_LINK_CAP = 5             # max cross-product links per session/doc
_CROSS_LINK_CAP_PER_DOC = 500   # max manual links to a single doc (WG-32 finding: unbounded growth up to 11,739)
_LIFETIME_AUTO_LINK_CAP = 500   # max total auto session links per doc (WG-32 D-31: lifetime cap going forward)
_CROSS_LINK_DEBOUNCE_SECS = 600 # 10-minute per-entity debounce
_CROSS_LINK_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
_CROSS_LINK_EMBEDDING_DIM = 384

# SH-104967: cross_link_doc previously instantiated a fresh TextEmbedding per
# document, reloading the ONNX model (~0.14s init) once per imported file. Cache
# a single instance so a bulk import loads it exactly once.
_cross_link_embedder_cache: Dict[str, Any] = {}


def _get_cross_link_embedder() -> Any:
    """Return a cached singleton TextEmbedding for cross-product linking."""
    model_name = _CROSS_LINK_EMBEDDING_MODEL
    embedder = _cross_link_embedder_cache.get(model_name)
    if embedder is None:
        from fastembed import TextEmbedding as _TE
        embedder = _TE(model_name)
        _cross_link_embedder_cache[model_name] = embedder
    return embedder

# Cap on find_related_docs() results (WG-32 D-10 median-result-count floor <= 15)
FIND_RELATED_MAX_RESULTS = 15

# File size limits (bytes)
MAX_FILE_SIZE = 30 * 1024 * 1024  # 30 MB per file (matches Claude Projects)


# ---------------------------------------------------------------------------
# Cross-product path discovery (Phase 2b)
# ---------------------------------------------------------------------------

class DiscoveryError(Exception):
    """Raised when an env-var DB path override is set but invalid."""


def _readonly_sqlite_uri(path: Path) -> str:
    """Build a read-only SQLite URI with the filesystem path URL-encoded.

    A bare f-string ``file:{path}?mode=ro`` breaks when the path contains
    spaces or URI-special characters (``?``, ``#``, ``%``), which sqlite3
    would then interpret as URI syntax instead of path text. quote() encodes
    those while leaving ``/`` path separators intact (SH-105513 B3).
    """
    from urllib.parse import quote
    return f"file:{quote(str(path), safe='/')}?mode=ro"


def discover_product_db(product: str) -> Optional[Path]:
    """Return the DB path for another Lore product, or None if not installed.

    Checks the <PRODUCT>_DB_PATH env var first (for testing / non-default install).
    Validated env paths must be under $HOME, end in .db, and be readable SQLite.

    Raises DiscoveryError only when the env var is explicitly set but the path
    fails validation (misconfiguration signal worth surfacing). Returns None
    silently when the product is simply not installed.
    """
    import logging as _logging
    log = _logging.getLogger(__name__)

    env_key = f"{product.upper().replace('-', '_')}_DB_PATH"
    env_override = os.environ.get(env_key)
    if env_override:
        p = Path(env_override)
        home = Path.home()
        try:
            p.resolve().relative_to(home.resolve())
        except ValueError:
            raise DiscoveryError(
                f"{env_key}={env_override!r} is outside $HOME -- refusing to open it"
            )
        if p.suffix != ".db":
            raise DiscoveryError(
                f"{env_key}={env_override!r} does not end in .db -- check the path"
            )
        if not p.exists():
            raise DiscoveryError(
                f"{env_key}={env_override!r} set but file does not exist. "
                f"Check {product} installation or unset {env_key}."
            )
        # Validate it is a readable SQLite file
        try:
            import sqlite3 as _sqlite3
            c = _sqlite3.connect(_readonly_sqlite_uri(p), uri=True)
            c.execute("SELECT 1")
            c.close()
        except Exception as exc:
            raise DiscoveryError(
                f"{env_key}={env_override!r} is not a readable SQLite file: {exc}"
            )
        return p

    default = Path.home() / f".{product}" / DEFAULT_DB_FILENAMES.get(product, f"{product}.db")
    if default.exists():
        log.debug("discover_product_db: found %s at default path", product)
        return default
    log.debug("discover_product_db: %s not installed (default path absent)", product)
    return None

# Free tier limits
FREE_MAX_VAULTS = 3
FREE_MAX_DOCS_PER_VAULT = 50
FREE_MAX_STORAGE_BYTES = 500 * 1024 * 1024  # 500 MB total
FREE_MAX_VERSIONS = 5


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------

def extract_text(file_path: Path) -> str:
    """Extract searchable text from a file based on its extension.

    For text-native formats, reads the file directly.
    For rich documents (PDF, DOCX, XLSX, PPTX), uses appropriate libraries.
    For binary/image/audio files, returns empty string (no extraction in v1).
    """
    suffix = file_path.suffix.lower()

    # Text-native formats -- read directly
    if suffix in (".txt", ".md", ".csv", ".html", ".htm", ".json", ".xml",
                   ".py", ".js", ".ts", ".sql", ".yaml", ".yml", ".toml",
                   ".ini", ".cfg", ".conf", ".log", ".sh", ".bat", ".ps1"):
        try:
            return file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""

    # PDF
    if suffix == ".pdf":
        try:
            import pdfplumber
            text_parts = []
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
            return "\n\n".join(text_parts)
        except Exception:
            return ""

    # DOCX
    if suffix == ".docx":
        try:
            import docx
            doc = docx.Document(str(file_path))
            return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception:
            return ""

    # XLSX
    if suffix == ".xlsx":
        try:
            import openpyxl
            wb = openpyxl.load_workbook(str(file_path), read_only=True, data_only=True)
            text_parts = []
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                text_parts.append(f"[Sheet: {sheet_name}]")
                for row in ws.iter_rows(values_only=True):
                    cells = [str(c) if c is not None else "" for c in row]
                    if any(cells):
                        text_parts.append("\t".join(cells))
            wb.close()
            return "\n".join(text_parts)
        except Exception:
            return ""

    # PPTX
    if suffix == ".pptx":
        try:
            from pptx import Presentation
            prs = Presentation(str(file_path))
            text_parts = []
            for i, slide in enumerate(prs.slides, 1):
                text_parts.append(f"[Slide {i}]")
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        for paragraph in shape.text_frame.paragraphs:
                            text = paragraph.text.strip()
                            if text:
                                text_parts.append(text)
            return "\n\n".join(text_parts)
        except Exception:
            return ""

    # Images, audio, and unknown formats -- no extraction in v1
    return ""


# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------

def _is_in_memory_db(db_path) -> bool:
    """True for in-memory SQLite databases.

    In-memory databases cannot use WAL -- ``PRAGMA journal_mode=WAL`` always
    returns "memory" -- and there is no file for a second client to lock into a
    conflicting mode, so the WAL mixing guard does not apply to them. The guard
    keys on the configured path (not the returned mode) so a file DB that fails
    WAL still raises.
    """
    p = str(db_path)
    if p == ":memory:":
        return True
    if p.startswith("file:"):
        return ":memory:" in p or "mode=memory" in p
    return False


def _init_db(db_path: Path) -> None:
    """Create the SQLite database with FTS5 tables if they don't exist."""
    conn = sqlite3.connect(str(db_path))
    row = conn.execute("PRAGMA journal_mode=WAL").fetchone()
    actual_mode = row[0] if row else "unknown"
    if actual_mode != "wal" and not _is_in_memory_db(db_path):
        logger.warning(
            "Database at '%s' fell back to journal mode '%s' (WAL unavailable); "
            "continuing without WAL. This is expected on network/FUSE filesystems "
            "or other environments without shared-memory support. Concurrent write "
            "throughput may be reduced until WAL mode can be established. "
            "Close all other LoreDocs connections if you expected WAL here.",
            db_path, actual_mode,
        )
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS vaults (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            archived INTEGER DEFAULT 0,
            tags TEXT DEFAULT '[]',
            linked_projects TEXT DEFAULT '[]',
            injection_cap_tokens INTEGER DEFAULT NULL
                CHECK(injection_cap_tokens IS NULL OR injection_cap_tokens > 0)
        );

        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            vault_id TEXT NOT NULL,
            name TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            file_extension TEXT DEFAULT '',
            category TEXT DEFAULT 'general',
            priority TEXT DEFAULT 'normal',
            tags TEXT DEFAULT '[]',
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            file_size_bytes INTEGER DEFAULT 0,
            version_count INTEGER DEFAULT 1,
            deleted INTEGER DEFAULT 0,
            origin_system TEXT DEFAULT NULL,
            origin_id TEXT DEFAULT NULL,
            -- CHECK for new DBs only; ALTER TABLE ADD COLUMN cannot add CHECK.
            -- Application-layer enforcement via _validate_origin_system() covers
            -- existing DBs that get origin_system via migration.
            CHECK (origin_system IS NULL OR (origin_system != '' AND LENGTH(origin_system) > 0)),
            FOREIGN KEY (vault_id) REFERENCES vaults(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS doc_links (
            id TEXT PRIMARY KEY,
            source_vault_id TEXT NOT NULL,
            source_doc_id TEXT NOT NULL,
            target_vault_id TEXT NOT NULL,
            target_doc_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (source_vault_id) REFERENCES vaults(id),
            FOREIGN KEY (target_vault_id) REFERENCES vaults(id)
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS doc_fts USING fts5(
            doc_id,
            vault_id,
            name,
            content,
            tags,
            notes,
            content_rowid='rowid'
        );

        CREATE INDEX IF NOT EXISTS idx_documents_vault ON documents(vault_id);
        CREATE INDEX IF NOT EXISTS idx_documents_deleted ON documents(deleted);
        CREATE INDEX IF NOT EXISTS idx_documents_category ON documents(category);
        CREATE INDEX IF NOT EXISTS idx_doc_links_target ON doc_links(target_doc_id);

        -- FTS sync triggers: keep doc_fts in sync with documents for UPDATE and DELETE.
        -- INSERT sync is handled by application code (content column requires extracted
        -- text from disk that is not available in the documents table row).
        CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
            UPDATE doc_fts SET
                vault_id = new.vault_id,
                name = new.name,
                tags = new.tags,
                notes = new.notes
            WHERE doc_id = new.id;
        END;

        CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
            DELETE FROM doc_fts WHERE doc_id = old.id;
        END;
    """)

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Schema migrations (safe to run on every startup)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Notion import bridge -- provenance data model (SH-13220, proposal r5)
# PART:data-model: schema migration + provenance model
# ---------------------------------------------------------------------------

VALID_ORIGIN_SYSTEMS = frozenset({"notion"})
# Extended as new importers land: VALID_ORIGIN_SYSTEMS | {"obsidian", "evernote", ...}

ORIGIN_ID_MAX_BYTES = 255


class MigrationConformanceError(Exception):
    """Raised when a migration conformance pass detects data that would violate
    a new constraint.  The migration is ABORTED; no schema changes are applied.
    The operator must resolve the conflict explicitly (e.g. --force-dedup).
    """

    def __init__(self, message, duplicates=None, count=0):
        super().__init__(message)
        self.duplicates = duplicates or []
        self.count = count


def _validate_origin_system(origin_system):
    """Validate origin_system before any INSERT/UPDATE that writes a non-NULL
    value.  Enforces registry membership AND rejects empty string.

    NULL is the local-origin sentinel and is always valid.
    Raises ValueError on invalid values.
    """
    if origin_system is None:
        return  # NULL = locally created; always valid
    if origin_system == '':
        raise ValueError(
            "origin_system must be a non-empty string or NULL; "
            "empty string is not valid (would bypass dedup index)"
        )
    if origin_system not in VALID_ORIGIN_SYSTEMS:
        raise ValueError(
            f"Unknown origin_system {origin_system!r}. "
            f"Valid values: {sorted(VALID_ORIGIN_SYSTEMS)}. "
            f"Adding a new importer? Extend VALID_ORIGIN_SYSTEMS first."
        )


def normalize_origin_id(origin_system, raw_id):
    """Canonical origin_id normalization.  All importers must call this before
    storage.

    Notion: lowercase UUID without dashes (32 hex chars).
    HTTP-URL-based systems: lowercase URL, query strings stripped.
    Opaque ID systems: lowercase string, max 255 chars.
    """
    if origin_system == "notion":
        clean = raw_id.replace("-", "").lower()
        if len(clean) != 32 or not all(c in "0123456789abcdef" for c in clean):
            raise ValueError(f"Invalid Notion UUID: {raw_id!r}")
        return clean
    import urllib.parse
    lowered = raw_id.lower()
    encoded = urllib.parse.quote(lowered, safe="a-z0-9_.~-")
    if len(encoded.encode("utf-8")) > ORIGIN_ID_MAX_BYTES:
        raise ValueError(
            f"origin_id for {origin_system} exceeds "
            f"{ORIGIN_ID_MAX_BYTES} bytes: {repr(raw_id)[:80]}"
        )
    return encoded


def _column_exists(conn, table, column):
    """Check if a column exists in a table using PRAGMA table_info.

    Uses PRAGMA table_info (binary existence test), NOT sqlite_master DDL
    substring search which breaks on column renames, case variation, and
    manual schema drift.
    """
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    # Each row: (cid, name, type, notnull, dflt_value, pk)
    return any(row[1] == column for row in rows)


def _bootstrap_schema_migrations(conn):
    """One-time bootstrap when schema_migrations table is absent.

    Uses PRAGMA table_info for column existence; NOT sqlite_master DDL
    substring search.

    [r5/H7 RISK-ACCEPT] Bootstrap infers v1-v3 from single-column existence
    tests.  Reopen condition: first field report of mis-bootstrapped
    schema_migrations, or any future migration whose detection is NOT a
    single-column existence test, requires a per-version fingerprint design.
    """
    v1_applied = _column_exists(conn, 'documents', 'last_cross_linked_at')
    # v2 and v3 had no schema changes; all databases from v0.1.5+ qualify
    v2_applied = v1_applied  # v2 required v1 first
    v3_applied = v1_applied  # v3 required v1 first
    with conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        for version, applied in [(1, v1_applied), (2, v2_applied), (3, v3_applied)]:
            if applied:
                conn.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at) "
                    "VALUES (?, datetime('now'))",
                    (version,)
                )


def _migrate_notion_provenance(conn, force_dedup=False):
    """Add origin_system, origin_id columns, conformance pass, UNIQUE index.

    Version 4 migration.  Uses SAVEPOINT for explicit transaction control
    so DDL (ALTER TABLE, CREATE INDEX) is transactional.  Python's sqlite3
    module in its default (legacy) isolation mode may auto-commit DDL
    outside explicit transactions; SAVEPOINT starts an implicit
    transaction if none is active, making DDL rollback possible on
    failure.

    [r5/H1] Count-first-then-decide: the conformance pass SELECT COUNTs
    duplicate tuples BEFORE any delete.  If count > 0, ABORT with
    MigrationConformanceError instead of silently deleting user documents.
    Only --force-dedup performs the dedup DELETE (keep MIN(rowid)).
    """
    conn.execute("SAVEPOINT notion_prov")
    try:
        # Add columns only if they don't already exist.  Fresh DBs get
        # them from _init_db CREATE TABLE; existing DBs get them here.
        if not _column_exists(conn, 'documents', 'origin_system'):
            conn.execute(
                "ALTER TABLE documents ADD COLUMN origin_system TEXT DEFAULT NULL"
            )
        if not _column_exists(conn, 'documents', 'origin_id'):
            conn.execute(
                "ALTER TABLE documents ADD COLUMN origin_id TEXT DEFAULT NULL"
            )

        # [r5/H1] Conformance COUNT -- detect duplicate (vault_id,
        # origin_system, origin_id) tuples BEFORE the UNIQUE constraint.
        # No delete is ever issued implicitly.
        dup_count = conn.execute(
            "SELECT COUNT(*) FROM documents "
            "WHERE origin_system IS NOT NULL "
            "  AND rowid NOT IN ("
            "    SELECT MIN(rowid) FROM documents "
            "    WHERE origin_system IS NOT NULL "
            "    GROUP BY vault_id, origin_system, origin_id"
            ")"
        ).fetchone()[0]

        if dup_count > 0 and not force_dedup:
            # Gather the offending tuples for the error message, then
            # raise.  The SAVEPOINT rollback undoes the ALTER TABLE
            # statements -- no schema change persists.
            dup_rows = conn.execute(
                "SELECT vault_id, origin_system, origin_id, COUNT(*) as n "
                "FROM documents WHERE origin_system IS NOT NULL "
                "GROUP BY vault_id, origin_system, origin_id "
                "HAVING COUNT(*) > 1"
            ).fetchall()
            duplicates = [
                {
                    "vault_id": r[0],
                    "origin_system": r[1],
                    "origin_id": r[2],
                    "row_count": r[3],
                }
                for r in dup_rows
            ]
            raise MigrationConformanceError(
                f"Migration v4 aborted: {dup_count} duplicate "
                f"(vault_id, origin_system, origin_id) tuple(s) would "
                f"violate the new UNIQUE index. "
                f"Run 'loredocs migrate --force-dedup' to deduplicate "
                f"(keep MIN(rowid)) and retry. "
                f"Affected tuples: {duplicates[:10]}",
                duplicates=duplicates,
                count=dup_count,
            )

        if dup_count > 0 and force_dedup:
            # Explicit opt-in: deduplicate keeping MIN(rowid).
            conn.execute(
                "DELETE FROM documents "
                "WHERE origin_system IS NOT NULL "
                "AND rowid NOT IN ("
                "  SELECT MIN(rowid) FROM documents "
                "  WHERE origin_system IS NOT NULL "
                "  GROUP BY vault_id, origin_system, origin_id"
                ")"
            )

        # UNIQUE partial index: safe after conformance pass.
        # Partial scope (WHERE origin_system IS NOT NULL) means NULL
        # origin_system rows (locally created docs) are excluded from
        # dedup.
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_origin_unique "
            "ON documents(vault_id, origin_system, origin_id) "
            "WHERE origin_system IS NOT NULL"
        )
        conn.execute(
            "INSERT OR REPLACE INTO schema_migrations(version, applied_at) "
            "VALUES (4, datetime('now'))"
        )
        conn.execute("RELEASE SAVEPOINT notion_prov")
    except Exception:
        # Roll back ALL changes (ALTER TABLE, CREATE INDEX, version row)
        # so no partial v4 state persists.  This is the transactional
        # guarantee: either all steps commit or none do.
        try:
            conn.execute("ROLLBACK TO SAVEPOINT notion_prov")
            conn.execute("RELEASE SAVEPOINT notion_prov")
        except Exception:
            pass  # Best-effort rollback; original error is re-raised
        raise


def _get_connection_file_path(conn) -> str:
    """Extract the on-disk path for the 'main' database from an open connection.

    Returns empty string for in-memory databases. Deriving the migration lock
    path from the connection itself (rather than trusting a caller-supplied
    path argument) means the lock always targets the file the connection is
    actually writing to.
    """
    rows = conn.execute("PRAGMA database_list").fetchall()
    for row in rows:
        if row[1] == "main":
            return row[2]
    raise RuntimeError("No 'main' database found in connection's database list")


def _acquire_migration_lock(lock_fd):
    """Cross-platform exclusive lock: fcntl.flock on POSIX, msvcrt.locking on Windows.

    Mirrors CheckpointManager's platform split (notion_checkpoint.py). LK_LOCK
    blocks until the lock is acquired (up to 10 one-second retries on Windows,
    then raises OSError); flock blocks until acquired on POSIX. No busy-loop
    needed on either platform.
    """
    if platform.system() == "Windows":
        import msvcrt
        lock_fd.seek(0)
        msvcrt.locking(lock_fd.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl
        fcntl.flock(lock_fd, fcntl.LOCK_EX)


def _release_migration_lock(lock_fd):
    if platform.system() == "Windows":
        import msvcrt
        lock_fd.seek(0)
        msvcrt.locking(lock_fd.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(lock_fd, fcntl.LOCK_UN)


def _run_migrations_locked(conn, force_dedup=False):
    """Run versioned migrations using the schema_migrations tracking table.

    Bootstrap assigns versions 1-3 based on column existence when
    schema_migrations is absent.  After bootstrap, apply any missing
    migrations in version order.
    """
    has_migrations_table = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='schema_migrations'"
    ).fetchone() is not None
    if not has_migrations_table:
        _bootstrap_schema_migrations(conn)
    applied = {
        row[0] for row in conn.execute(
            "SELECT version FROM schema_migrations"
        )
    }
    if 4 not in applied:
        _migrate_notion_provenance(conn, force_dedup=force_dedup)


def _migrate_db(db_path: Path) -> None:
    """Apply incremental schema migrations that are safe to run repeatedly."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    row = conn.execute("PRAGMA journal_mode").fetchone()
    actual_mode = row[0] if row else "unknown"
    if actual_mode != "wal" and not _is_in_memory_db(db_path):
        logger.warning(
            "Database at '%s' is in journal mode '%s' (WAL expected); continuing "
            "in fallback mode. This is expected on network/FUSE filesystems or "
            "other environments without shared-memory support. Concurrent write "
            "throughput may be reduced until WAL mode can be established.",
            db_path, actual_mode,
        )

    # v0.2: add label column to doc_links if missing
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(doc_links)")}
    if "label" not in existing_cols:
        conn.execute("ALTER TABLE doc_links ADD COLUMN label TEXT DEFAULT 'related'")

    # v0.3: add FTS sync triggers for doc_fts (MEG-00073)
    conn.executescript("""
        CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
            UPDATE doc_fts SET
                vault_id = new.vault_id,
                name = new.name,
                tags = new.tags,
                notes = new.notes
            WHERE doc_id = new.id;
        END;

        CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
            DELETE FROM doc_fts WHERE doc_id = old.id;
        END;
    """)

    # v0.4: add doc_cooccurrences table for relationship layer (RON-00067)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS doc_cooccurrences (
            term    TEXT NOT NULL,
            doc_id  TEXT NOT NULL,
            frequency INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (term, doc_id)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_doc_cooccurrences_doc ON doc_cooccurrences(doc_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_doc_cooccurrences_term ON doc_cooccurrences(term)"
    )

    # Populate doc_cooccurrences for existing documents if table is empty
    count = conn.execute("SELECT COUNT(*) FROM doc_cooccurrences").fetchone()[0]
    if count == 0:
        _reindex_all_docs(conn, db_path.parent / VAULTS_DIR)

    # v0.5: add workspace_path to vaults for directory-scoped auto-vault (GINA-00018)
    vault_cols = {row[1] for row in conn.execute("PRAGMA table_info(vaults)")}
    if "workspace_path" not in vault_cols:
        conn.execute("ALTER TABLE vaults ADD COLUMN workspace_path TEXT DEFAULT NULL")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_vaults_workspace ON vaults(workspace_path)"
    )

    # v0.6: Phase 2a embedding autolink schema (SH-10529)
    # Add archived_at column to doc_links (row-level visibility for downgraded users)
    link_cols = {row[1] for row in conn.execute("PRAGMA table_info(doc_links)")}
    if "archived_at" not in link_cols:
        conn.execute("ALTER TABLE doc_links ADD COLUMN archived_at TEXT DEFAULT NULL")
    # Dedup any pre-existing auto-generated link duplicates before creating the unique index.
    # Manual links are never touched. Order matters: dedupe MUST run before CREATE UNIQUE INDEX,
    # otherwise SQLite raises IntegrityError on the existing duplicate rows.
    conn.execute("""
        DELETE FROM doc_links
        WHERE label LIKE 'auto:%'
          AND id NOT IN (
            SELECT MIN(id) FROM doc_links
            WHERE label LIKE 'auto:%'
            GROUP BY source_vault_id, source_doc_id, target_vault_id, target_doc_id, label
          )
    """)
    # SQLite doesn't support ADD CONSTRAINT on existing tables; recreate is too disruptive.
    # Use a unique index instead -- enforces the same constraint without recreation.
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_doc_links_unique_key
        ON doc_links(source_vault_id, source_doc_id, target_vault_id, target_doc_id, label)
    """)

    # v0.7: Phase 2b cross-product linking (SH-10727)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cross_product_links (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            source_product  TEXT NOT NULL,
            source_id       TEXT NOT NULL,
            target_product  TEXT NOT NULL,
            target_id       TEXT NOT NULL,
            similarity_score REAL,
            embedding_model  TEXT NOT NULL,
            embedding_dim    INTEGER NOT NULL,
            link_type        TEXT NOT NULL DEFAULT 'auto',
            tier_required    TEXT NOT NULL DEFAULT 'pro',
            created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            UNIQUE(source_product, source_id, target_product, target_id)
        );
        CREATE INDEX IF NOT EXISTS idx_cross_links_source
            ON cross_product_links(source_product, source_id);
        CREATE INDEX IF NOT EXISTS idx_cross_links_target
            ON cross_product_links(target_product, target_id);
    """)

    # Privacy: vault-level opt-out column
    vault_cols_v7 = {row[1] for row in conn.execute("PRAGMA table_info(vaults)")}
    if "cross_link_opt_out" not in vault_cols_v7:
        conn.execute(
            "ALTER TABLE vaults ADD COLUMN cross_link_opt_out INTEGER NOT NULL DEFAULT 0"
        )

    # Debounce: last_cross_linked_at on documents
    doc_cols_v7 = {row[1] for row in conn.execute("PRAGMA table_info(documents)")}
    if "last_cross_linked_at" not in doc_cols_v7:
        conn.execute(
            "ALTER TABLE documents ADD COLUMN last_cross_linked_at TEXT DEFAULT NULL"
        )

    # v0.8: injection cap per vault (SH-12014, r4 proposal SH-13602)
    # [r4/T6a] SQLite version floor check -- fail LOUD, never assume.
    # ALTER TABLE ADD COLUMN with inline CHECK requires SQLite >= 3.25.0.
    _SQLITE_FLOOR = (3, 25, 0)
    if sqlite3.sqlite_version_info < _SQLITE_FLOOR:
        raise RuntimeError(
            f"[LOREDOCS-MIGRATE-ERROR] SQLite {sqlite3.sqlite_version} is below the "
            f"minimum {'.'.join(map(str, _SQLITE_FLOOR))} required for the "
            f"injection_cap_tokens migration. Upgrade Python/SQLite before starting."
        )

    # The vaults CREATE TABLE now includes injection_cap_tokens; only existing
    # installs need ALTER.  Fresh installs never need the ALTER at all.
    vault_cols_v8 = {row[1] for row in conn.execute("PRAGMA table_info(vaults)")}

    # Check if vaults table exists (fresh install: the CREATE TABLE above
    # already includes the col)
    tbl = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='vaults'"
    ).fetchone()

    if "injection_cap_tokens" not in vault_cols_v8:
        if tbl:
            logger.info(
                "[LOREDOCS-MIGRATE] Adding injection_cap_tokens column to vaults table"
            )
            conn.execute(
                "ALTER TABLE vaults ADD COLUMN injection_cap_tokens INTEGER DEFAULT NULL "
                "CHECK(injection_cap_tokens IS NULL OR injection_cap_tokens > 0)"
            )
    else:
        # [r4/T6c] Column already present: verify the CHECK constraint came
        # with it.  A prior crashed/partial migration attempt (or a manual
        # ALTER) can leave the column present WITHOUT the constraint -- a
        # half-migrated state with no clean re-entry.  DETECT + hard-fail +
        # documented runbook entry.  NO auto-heal (ratified decision).
        #
        # [r4/T6b] Pre-detection cleanup diagnostics: if the column exists
        # without CHECK, report any invalid values (non-integer or <= 0)
        # that would violate the constraint if it were present.  This is
        # diagnostic only -- the hard-fail below prevents starting with
        # an unconstrained column.  Recovery is via the TROUBLESHOOTING.md
        # runbook (table rebuild).
        if tbl:
            create_sql_row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='vaults'"
            ).fetchone()
            if create_sql_row:
                create_sql = create_sql_row[0] or ""
                # Check for the CHECK constraint in the CREATE TABLE SQL.
                # Normalize whitespace for the comparison.
                normalized = create_sql.replace(" ", "").replace("\n", "")
                if (
                    "injection_cap_tokens" in create_sql
                    and "CHECK(injection_cap_tokens" not in normalized
                ):
                    # [r4/T6b] Diagnostic: count invalid values before hard-fail
                    try:
                        invalid_count = conn.execute(
                            "SELECT COUNT(*) FROM vaults WHERE "
                            "injection_cap_tokens IS NOT NULL AND "
                            "(typeof(injection_cap_tokens) != 'integer' "
                            "OR injection_cap_tokens <= 0)"
                        ).fetchone()[0]
                    except sqlite3.OperationalError:
                        invalid_count = 0
                    raise RuntimeError(
                        "[LOREDOCS-MIGRATE-ERROR] vaults.injection_cap_tokens exists "
                        "WITHOUT its CHECK constraint (half-migrated schema, likely "
                        "from a crashed migration). Manual recovery required -- see "
                        "the 'Half-migrated injection_cap_tokens schema' runbook entry "
                        "in TROUBLESHOOTING.md. Refusing to start with an unconstrained "
                        f"cap column. ({invalid_count} invalid value(s) detected.)"
                    )

    # v0.9: Notion import bridge provenance (SH-13220, proposal r5)
    # Schema-migrations-tracked migration: origin_system, origin_id,
    # UNIQUE partial index, conformance pass.  Runs via the versioned
    # migration system (_run_migrations_locked), guarded by a cross-process
    # exclusive lock so two processes upgrading the same v0.1.7 DB at once
    # cannot both attempt the v4 migration (SH-13223, PART:migration).
    # Lock path is derived from the connection's actual file path, not
    # db_path directly, so the lock always targets what the connection
    # is really writing to.
    file_path = _get_connection_file_path(conn)
    if file_path:
        lock_path = file_path + ".migrationlock"
        with open(lock_path, "w") as lock_fd:
            _acquire_migration_lock(lock_fd)
            try:
                _run_migrations_locked(conn)
            finally:
                _release_migration_lock(lock_fd)
        # SH-101414: a leftover .migrationlock file is litter, not a blocker.
        # flock is released by the OS when the fd closes -- even on a crash --
        # so a stale lock FILE never blocks the next startup. Remove it after
        # a clean run to keep the data dir tidy. (Unlink-after-release has a
        # narrow race where a third process could open a fresh lock file while
        # a second is still blocked on the old inode; migrations are versioned
        # and idempotent, and SQLite serializes the writes, so the worst case
        # is redundant work, not corruption.)
        try:
            Path(lock_path).unlink()
        except OSError:
            pass
    else:
        # In-memory database: no file for a second process to contend on.
        _run_migrations_locked(conn)

    conn.commit()
    conn.close()


_COOCCURRENCE_CANDIDATE_POOL = 60
_COOCCURRENCE_TERMS_PER_DOC = 30


def _cooccurrence_candidates(name: str, content: str) -> List[Tuple[str, int]]:
    """Candidate (term, frequency) pool for one document's co-occurrence index."""
    text = " ".join(filter(None, [name, content]))
    return _extract_keywords(text, top_n=_COOCCURRENCE_CANDIDATE_POOL)


def _insert_doc_cooccurrences(
    conn: sqlite3.Connection,
    doc_id: str,
    name: str,
    tags: List[str],
    content: str,
    candidates: Optional[List[Tuple[str, int]]] = None,
    vault_doc_freq: Optional[Dict[str, int]] = None,
) -> None:
    """(Re)index keyword co-occurrences for one document. Replaces prior index.

    SH-104433: raw in-document term frequency alone picks the same boilerplate
    words (report headers, status labels) out of every document in a templated
    vault (QA Reports, PM Dashboards, Editorial Reviews), so near-identical
    report pairs share >= min_shared_terms terms regardless of topic -- that
    inflates auto:cooccurrence link coverage without relevance (WG-32 D-10:
    60% top-5 relevance, capped at the 15-result ceiling, well under the 70%
    floor). Candidates are now re-ranked by TF * within-vault IDF (using the
    doc_cooccurrences rows already written for other docs in the vault as the
    document-frequency source) before the top 30 are kept, so a term common to
    most reports in the vault scores lower than one distinctive to this doc.

    SH-105175: relink_autolinks passes ``vault_doc_freq`` (term -> number of
    vault docs whose candidate pool contains it, self included) computed up
    front from every doc's text, so the IDF does not read a partially rebuilt
    doc_cooccurrences table. Incremental saves omit it and keep reading the
    rows already written for the vault's other docs.
    """
    conn.execute("DELETE FROM doc_cooccurrences WHERE doc_id = ?", (doc_id,))
    if candidates is None:
        candidates = _cooccurrence_candidates(name, content)
    if candidates:
        vault_row = conn.execute(
            "SELECT vault_id FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        vault_id = vault_row[0] if vault_row else None
        doc_freq: Dict[str, int] = {}
        vault_doc_count = 0
        if vault_id:
            vault_doc_count = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE vault_id = ? AND deleted = 0",
                (vault_id,)
            ).fetchone()[0]
            terms = [t for t, _ in candidates]
            placeholders = ",".join("?" * len(terms))
        if vault_id and vault_doc_freq is not None:
            # Precomputed counts include this doc; exclude it like the query does.
            doc_freq = {t: vault_doc_freq.get(t, 1) - 1 for t in terms}
        elif vault_id:
            doc_freq = dict(conn.execute(
                f"""SELECT dc.term, COUNT(DISTINCT dc.doc_id)
                    FROM doc_cooccurrences dc
                    JOIN documents d ON d.id = dc.doc_id
                    WHERE d.vault_id = ? AND dc.doc_id != ?
                      AND dc.term IN ({placeholders})
                    GROUP BY dc.term""",
                [vault_id, doc_id] + terms
            ).fetchall())
        scored = []
        for term, freq in candidates:
            if vault_id and vault_doc_count > 0:
                idf = math.log((vault_doc_count + 1) / (1 + doc_freq.get(term, 0)))
            else:
                idf = 1.0
            scored.append((term, freq, freq * idf))
        # Tie-break on the term so equal weights keep the same top 30 every run.
        scored.sort(key=lambda row: (-row[2], row[0]))
        for term, freq, _weighted in scored[:_COOCCURRENCE_TERMS_PER_DOC]:
            conn.execute(
                "INSERT OR REPLACE INTO doc_cooccurrences (term, doc_id, frequency) VALUES (?, ?, ?)",
                (term, doc_id, freq)
            )
    # Boost tags as explicit terms
    for tag in tags:
        if isinstance(tag, str):
            tag_term = re.sub(r'[^a-z]', '', tag.lower())
            if len(tag_term) >= 3 and tag_term not in _STOPWORDS:
                conn.execute(
                    "INSERT OR REPLACE INTO doc_cooccurrences (term, doc_id, frequency) VALUES (?, ?, ?)",
                    (tag_term, doc_id, 5)
                )


def _auto_link_doc_cooccurrences(
    conn: sqlite3.Connection,
    doc_id: str,
    min_shared_terms: int = 5,
) -> None:
    """Create bidirectional auto-links in doc_links for docs sharing >= min_shared_terms terms.

    Uses label='auto:cooccurrence'. INSERT OR IGNORE preserves manual links.
    Scoped to same-vault only to reduce noise. Threshold raised from 3 to 5
    to avoid linking unrelated docs with minimal term overlap.
    Caps at 20 new links per document.
    """
    src_row = conn.execute(
        "SELECT vault_id FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    if not src_row:
        return
    source_vault_id = src_row[0]

    candidates = conn.execute(
        """SELECT dc2.doc_id, COUNT(*) as shared_count
           FROM doc_cooccurrences dc1
           JOIN doc_cooccurrences dc2 ON dc1.term = dc2.term
           JOIN documents d2 ON dc2.doc_id = d2.id
           WHERE dc1.doc_id = ?
             AND dc2.doc_id != ?
             AND d2.vault_id = ?
           GROUP BY dc2.doc_id
           HAVING COUNT(*) >= ?
           ORDER BY shared_count DESC, dc2.doc_id
           LIMIT 20""",
        (doc_id, doc_id, source_vault_id, min_shared_terms)
    ).fetchall()

    now = datetime.now(timezone.utc).isoformat()
    for row in candidates:
        other_doc_id = row[0]
        tgt_row = conn.execute(
            "SELECT vault_id FROM documents WHERE id = ? AND deleted = 0",
            (other_doc_id,)
        ).fetchone()
        if not tgt_row:
            continue
        target_vault_id = tgt_row[0]
        # Deterministic link IDs (SH-104432): required for relink_autolinks
        # idempotency. The UNIQUE INDEX is on the 5-tuple logical key, so
        # INSERT OR IGNORE dedups regardless; but deterministic IDs make a
        # purge+regenerate cycle produce byte-identical rows on rerun.
        fwd_id = _make_link_id(
            source_vault_id, doc_id, target_vault_id, other_doc_id,
            "auto:cooccurrence",
        )
        rev_id = _make_link_id(
            target_vault_id, other_doc_id, source_vault_id, doc_id,
            "auto:cooccurrence",
        )
        try:
            conn.execute(
                """INSERT OR IGNORE INTO doc_links
                   (id, source_vault_id, source_doc_id, target_vault_id, target_doc_id,
                    created_at, label)
                   VALUES (?, ?, ?, ?, ?, ?, 'auto:cooccurrence')""",
                (fwd_id, source_vault_id, doc_id,
                 target_vault_id, other_doc_id, now)
            )
            conn.execute(
                """INSERT OR IGNORE INTO doc_links
                   (id, source_vault_id, source_doc_id, target_vault_id, target_doc_id,
                    created_at, label)
                   VALUES (?, ?, ?, ?, ?, ?, 'auto:cooccurrence')""",
                (rev_id, target_vault_id, other_doc_id,
                 source_vault_id, doc_id, now)
            )
        except sqlite3.IntegrityError:
            pass


def _get_doc_text_for_embedding(conn: sqlite3.Connection, doc_id: str) -> str:
    """Get document text for embedding query. Reads extracted.txt file."""
    try:
        row = conn.execute(
            "SELECT vault_id FROM documents WHERE id = ? AND deleted = 0", (doc_id,)
        ).fetchone()
        if not row:
            return ""
        vault_id = row[0]
        # Document text is stored in extracted.txt in the vaults directory
        # The VaultStorage instance can read it via get_document_content,
        # but we're in a module function with only a connection, so read directly.
        # Derive root from the database path via PRAGMA (ground truth for open
        # connection), fall back to LOREDOCS_ROOT env var if PRAGMA fails.
        import os
        from pathlib import Path
        db_row = conn.execute("PRAGMA database_list").fetchone()
        if db_row and db_row[2]:
            db_path = Path(db_row[2]).resolve()
            loredocs_root = db_path.parent
        else:
            root_override = os.environ.get("LOREDOCS_ROOT")
            if root_override:
                loredocs_root = Path(root_override).resolve()
            else:
                loredocs_root = (Path.home() / ".loredocs").resolve()
        extracted_path = loredocs_root / "vaults" / vault_id / "docs" / doc_id / "extracted.txt"
        if extracted_path.exists():
            return extracted_path.read_text(encoding="utf-8", errors="replace")
        return ""
    except Exception:
        return ""


def _auto_link_doc_embeddings(
    conn: sqlite3.Connection,
    doc_id: str,
    lance_index: Any,
    cap: int = 10,
    is_pro: bool = True,
) -> None:
    """Create bidirectional embedding-based links in doc_links. Pro tier only.

    Queries the Lance chunk index for semantically similar documents in the same
    vault. Confirms vault membership against SQLite before writing (Lance metadata
    is advisory). Uses INSERT WHERE EXISTS to atomically validate both doc IDs at
    write time. Caps at cap bidirectional pairs per document.
    """
    if not is_pro:
        return
    if os.environ.get("LOREDOCS_EMBEDDING_LINKS", "1") == "0":
        return

    src_row = conn.execute(
        "SELECT vault_id FROM documents WHERE id = ? AND deleted = 0", (doc_id,)
    ).fetchone()
    if not src_row:
        return
    source_vault_id = src_row[0]

    if not _embd_check_circuit(source_vault_id):
        return

    try:
        table = lance_index._open_table()
        # Use actual document content for the query, not the name.
        # The Lance index chunks document text; we embed the actual text
        # for semantic similarity, not the title (which would only match similar titles).
        query_text = _get_doc_text_for_embedding(conn, doc_id)
        if not query_text:
            return
        q_vec = lance_index._embed_one(query_text)

        # SH-101414: pre-filter by vault BEFORE ranking. A global top-50
        # followed by a Python-side vault filter is the same post-filter
        # defect that broke scoped semantic search -- on a multi-vault store
        # the global top-k is dominated by other vaults and the filter
        # discards everything, so no embedding links are ever created.
        # LanceDB 0.30.2 has no parameterized filter API; vault ids are
        # truncated UUIDs from SQLite, but escape single quotes anyway.
        safe_vault = source_vault_id.replace("'", "''")
        raw = table.search(
            q_vec,
            vector_column_name="vector",
            query_type="vector",
        ).where(f"vault_id = '{safe_vault}'", prefilter=True).limit(50).to_list()

        # Dedup to best distance per doc_id, filter by threshold + same vault
        best: Dict[str, float] = {}
        for r in raw:
            cand_doc_id = r.get("doc_id") or r.get("session_id")
            cand_vault_id = r.get("vault_id")
            dist = r.get("_distance", 999)
            if cand_doc_id == doc_id:
                continue
            if dist > 0.5:  # squared L2 > 0.5 means cosine < 0.75
                continue
            if cand_vault_id != source_vault_id:
                continue
            if cand_doc_id not in best or dist < best[cand_doc_id]:
                best[cand_doc_id] = dist

        # SQLite confirmation: verify vault membership against DB (Lance metadata advisory)
        confirmed: List[str] = []
        for cand_doc_id in best:
            row = conn.execute(
                "SELECT vault_id FROM documents WHERE id = ? AND deleted = 0",
                (cand_doc_id,)
            ).fetchone()
            if row and row[0] == source_vault_id:
                confirmed.append(cand_doc_id)

        now = datetime.now(timezone.utc).isoformat()
        inserted = 0
        for other_doc_id in confirmed:
            if inserted >= cap:
                break
            existing = conn.execute(
                "SELECT 1 FROM doc_links WHERE "
                "(source_doc_id=? AND target_doc_id=?) OR "
                "(source_doc_id=? AND target_doc_id=?)",
                (doc_id, other_doc_id, other_doc_id, doc_id)
            ).fetchone()
            if existing:
                continue

            fwd_id = _make_link_id(source_vault_id, doc_id, source_vault_id, other_doc_id, "auto:embedding")
            rev_id = _make_link_id(source_vault_id, other_doc_id, source_vault_id, doc_id, "auto:embedding")
            try:
                # INSERT WHERE EXISTS validates both docs exist atomically
                conn.execute(
                    """INSERT OR IGNORE INTO doc_links
                       (id, source_vault_id, source_doc_id, target_vault_id,
                        target_doc_id, created_at, label)
                       SELECT ?, ?, ?, ?, ?, ?, 'auto:embedding'
                       WHERE EXISTS (SELECT 1 FROM documents WHERE id=? AND vault_id=? AND deleted=0)
                         AND EXISTS (SELECT 1 FROM documents WHERE id=? AND vault_id=? AND deleted=0)
                    """,
                    (fwd_id, source_vault_id, doc_id, source_vault_id, other_doc_id, now,
                     doc_id, source_vault_id, other_doc_id, source_vault_id)
                )
                conn.execute(
                    """INSERT OR IGNORE INTO doc_links
                       (id, source_vault_id, source_doc_id, target_vault_id,
                        target_doc_id, created_at, label)
                       SELECT ?, ?, ?, ?, ?, ?, 'auto:embedding'
                       WHERE EXISTS (SELECT 1 FROM documents WHERE id=? AND vault_id=? AND deleted=0)
                         AND EXISTS (SELECT 1 FROM documents WHERE id=? AND vault_id=? AND deleted=0)
                    """,
                    (rev_id, source_vault_id, other_doc_id, source_vault_id, doc_id, now,
                     other_doc_id, source_vault_id, doc_id, source_vault_id)
                )
                inserted += 1
            except sqlite3.IntegrityError:
                pass
        _embd_record_success(source_vault_id)
    except Exception as exc:
        _embd_record_failure(source_vault_id)
        import logging
        logging.getLogger(__name__).error(
            "auto_link_doc_embeddings failed for doc %s: %s", doc_id, exc
        )


def _reindex_all_docs(conn: sqlite3.Connection, vaults_dir: Path) -> None:
    """Populate doc_cooccurrences for all existing documents (first-run migration)."""
    rows = conn.execute(
        "SELECT id, vault_id, name, tags FROM documents WHERE deleted = 0"
    ).fetchall()
    for row in rows:
        doc_id = row["id"]
        vault_id = row["vault_id"]
        name = row["name"]
        tags = json.loads(row["tags"] or "[]")

        extracted_path = vaults_dir / vault_id / "docs" / doc_id / "extracted.txt"
        content = ""
        if extracted_path.exists():
            try:
                content = extracted_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass

        _insert_doc_cooccurrences(conn, doc_id, name, tags, content)


def _extract_frontmatter_tags(content: bytes) -> List[str]:
    """Extract tags from YAML frontmatter in a markdown file (stdlib only, no PyYAML)."""
    try:
        text = content.decode("utf-8", errors="ignore")
        if not text.startswith("---"):
            return []
        end = text.find("\n---", 3)
        if end == -1:
            return []
        block = text[3:end]
        in_tags = False
        tags: List[str] = []
        for line in block.splitlines():
            if line.startswith("tags:"):
                raw = line[5:].strip()
                if raw.startswith("[") and raw.endswith("]"):
                    return [t.strip().strip("'\"") for t in raw[1:-1].split(",") if t.strip()]
                if raw:
                    return [raw.strip()]
                in_tags = True
            elif in_tags:
                stripped = line.strip()
                if stripped.startswith("- "):
                    tags.append(stripped[2:].strip().strip("'\""))
                elif stripped and not stripped.startswith("#"):
                    break
        return tags
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Storage class
# ---------------------------------------------------------------------------

def _parse_json_list(value) -> list:
    """Parse a JSON list field that may be None, empty string, or valid JSON."""
    if not value:
        return []
    try:
        result = json.loads(value)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _parse_json_list_tolerant(value) -> list:
    """Parse JSON list field tolerating bare strings (WG-32 D-26).

    Handles: None, '', JSON array, or bare string (treated as one-element list).
    Always returns a list.
    """
    if not value:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            result = json.loads(value)
            return result if isinstance(result, list) else []
        except json.JSONDecodeError:
            return [value] if value.strip() else []
    return []


def _normalize_vault_name(name: str) -> str:
    """Normalize vault name for case-insensitive comparison using Unicode casefold."""
    return name.casefold()


class VaultStorage:
    """Manages the local filesystem and SQLite database for LoreDocs."""

    def __init__(self, root: Optional[Path] = None):
        self.root = root or DEFAULT_ROOT
        self.db_path = self.root / DB_FILE
        self.vaults_dir = self.root / VAULTS_DIR

        # Ensure directories exist
        self.root.mkdir(parents=True, exist_ok=True)
        self.vaults_dir.mkdir(parents=True, exist_ok=True)

        # Initialize database
        _init_db(self.db_path)
        _migrate_db(self.db_path)

        # Tier enforcer (reads config.json from root)
        self.enforcer = TierEnforcer(self.root)

        # Lance index: lazy init, Pro only
        self._lance_index = None

        # r6/SH-100432: DocContextManager -- the choke point for all
        # document operations (read and write).  It acquires per-document
        # locks, replays stale intent journals, computes the 5-source
        # version allocator, and checks divergence.
        tier = get_tier(self.root)
        self._ctx_mgr = DocContextManager(
            self.vaults_dir, self.db_path, tier, self.enforcer,
        )

        # r6/C2: one-time startup warning if the vault root is under a
        # known cloud-sync directory.  Path-prefix match only -- nothing
        # branches on the result.
        sub = _should_warn_substrate(self.root)
        if sub is not None:
            logger.warning(
                "LoreDocs vault root (%s) is under a cloud-sync directory "
                "(%s). Cloud-sync substrates can split writes, roll back "
                "version history, and cause divergence. Consider moving "
                "the vault root to a non-synced directory. This is a "
                "one-time advisory; no functionality is changed.",
                self.root, sub,
            )

    @contextmanager
    def _db(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        # Wait up to 5s for a competing writer instead of failing instantly
        # with "database is locked" under transient contention.
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _now(self) -> str:
        """Current UTC timestamp as ISO string."""
        return datetime.now(timezone.utc).isoformat()

    # -------------------------------------------------------------------
    # LanceDB hybrid search (Pro tier)
    # -------------------------------------------------------------------

    def _get_lance_index(self):
        """Return the DocLanceIndex instance, creating it lazily on first call."""
        if self._lance_index is None:
            from .semantic_search import DocLanceIndex
            lance_dir = self.root / 'docs.lance'
            self._lance_index = DocLanceIndex(lance_dir)
        return self._lance_index

    def relink_autolinks(self, include_embeddings: bool = True) -> Dict[str, int]:
        """Purge all auto-generated doc_links and regenerate them with current logic.

        SH-104427 / SH-104432: the SH-103637 autolink quality fix (same-vault
        cooccurrence, threshold 5, embedding-on-text-not-name) was forward-only.
        Existing stores still held pre-fix auto:cooccurrence / auto:embedding
        rows (including cross-vault noise). This method purges every
        ``label LIKE 'auto:%'`` row and regenerates them for all non-deleted
        documents. Explicit links (any label not matching ``auto:%``) are
        untouched.

        Idempotent (a fixed point, SH-105175): a second run produces the same
        doc_cooccurrences rows and the same auto-link set (ids, endpoints,
        labels) as the first. Term indexes are rebuilt for every doc before
        any linking, IDF comes from document frequencies computed up front,
        ties sort deterministically, and both autolink writers emit
        deterministic IDs via ``_make_link_id``. ``created_at`` is refreshed
        each run.

        Args:
            include_embeddings: when True and the store is Pro with a usable
                Lance index, regenerate ``auto:embedding`` links too. When
                False, or on Free tier, or when the Lance index is missing,
                only ``auto:cooccurrence`` links are regenerated.

        Returns:
            Dict with keys ``purged``, ``regenerated``, ``docs_processed``,
            ``embedding_skipped`` (bool).
        """
        is_pro = get_tier(self.root) == TIER_PRO
        lance_index = None
        embedding_skipped = True
        if include_embeddings and is_pro:
            try:
                lance_index = self._get_lance_index()
                # Probe the index is actually openable; fall back to cooccurrence-only.
                lance_index._open_table()
                embedding_skipped = False
            except Exception as exc:
                logger.warning(
                    "relink_autolinks: Lance index unavailable, "
                    "skipping embedding links: %s", exc,
                )
                lance_index = None
                embedding_skipped = True

        with self._db() as conn:
            # 1. Purge every auto-generated link. Explicit links (label NOT
            #    LIKE 'auto:%') are preserved.
            purged = conn.execute(
                "DELETE FROM doc_links WHERE label LIKE 'auto:%'"
            ).rowcount

            # 2. Regenerate. Process docs in deterministic id order so the
            #    created_at timestamps (one per doc) are stable across reruns.
            doc_rows = conn.execute(
                "SELECT id, vault_id, name, tags FROM documents "
                "WHERE deleted = 0 ORDER BY id"
            ).fetchall()
            # SH-105175: two phases. Reindexing and linking each doc inside
            # one loop made both order-dependent -- the within-vault IDF read
            # other docs' half-rebuilt term rows, and linking doc N compared
            # against docs N+1.. still holding their old term sets -- so the
            # result shifted on every rerun. Phase 1 rebuilds every term index
            # from document frequencies computed up front from each doc's own
            # text; phase 2 links against the finished index.
            #
            # SH-104433: phase 1 also backfills doc_cooccurrences for docs saved
            # via the pre-fix query_loredocs.py cmd_add_doc fallback, which
            # never got a term index; _insert_doc_cooccurrences
            # deletes-then-rebuilds, so it is safe to run on every doc.
            prepared = []
            vault_doc_freq: Dict[str, Dict[str, int]] = {}
            for drow in doc_rows:
                doc_id = drow["id"]
                try:
                    doc_tags = json.loads(drow["tags"]) if drow["tags"] else []
                except (json.JSONDecodeError, TypeError):
                    doc_tags = []
                extracted_path = (
                    self.vaults_dir / drow["vault_id"] / "docs" / doc_id
                    / "extracted.txt"
                )
                extracted = ""
                if extracted_path.exists():
                    try:
                        extracted = extracted_path.read_text(encoding="utf-8")
                    except OSError:
                        extracted = ""
                candidates = _cooccurrence_candidates(drow["name"], extracted)
                freq = vault_doc_freq.setdefault(drow["vault_id"], {})
                for term in {t for t, _ in candidates}:
                    freq[term] = freq.get(term, 0) + 1
                prepared.append((drow, doc_tags, extracted, candidates))

            for drow, doc_tags, extracted, candidates in prepared:
                try:
                    _insert_doc_cooccurrences(
                        conn, drow["id"], drow["name"], doc_tags, extracted,
                        candidates=candidates,
                        vault_doc_freq=vault_doc_freq[drow["vault_id"]],
                    )
                except Exception as exc:
                    logger.error(
                        "relink_autolinks: cooccurrence reindex failed for "
                        "doc %s: %s", drow["id"], exc,
                    )

            regenerated = 0
            for drow, _tags, _extracted, _candidates in prepared:
                doc_id = drow["id"]
                before = conn.execute("SELECT COUNT(*) FROM doc_links").fetchone()[0]
                try:
                    _auto_link_doc_cooccurrences(conn, doc_id)
                except Exception as exc:
                    logger.error(
                        "relink_autolinks: cooccurrence failed for doc %s: %s",
                        doc_id, exc,
                    )
                if lance_index is not None:
                    try:
                        _auto_link_doc_embeddings(
                            conn, doc_id, lance_index, is_pro=True,
                        )
                    except Exception as exc:
                        logger.error(
                            "relink_autolinks: embedding failed for doc %s: %s",
                            doc_id, exc,
                        )
                after = conn.execute("SELECT COUNT(*) FROM doc_links").fetchone()[0]
                regenerated += max(0, after - before)

        return {
            "purged": purged,
            "regenerated": regenerated,
            "docs_processed": len(doc_rows),
            "embedding_skipped": embedding_skipped,
        }

    def _bulk_index_and_link(self, doc_ids: List[str]) -> None:
        """Batched co-occurrence indexing + auto-linking for newly imported docs.

        Companion to add_document(defer_links=True). Runs the deferred index and
        link steps in two phases (the SH-105175 relink_autolinks pattern): rebuild
        every new doc's term index from document frequencies computed up front, then
        link against the finished index. Avoids the O(n^2) per-file IDF queries and
        per-file auto-linking that make import_directory slow on large trees.

        Errors are logged, never raised (best-effort, matching add_document).
        """
        if not doc_ids:
            return
        prepared: List[Tuple[Any, List[str], str, List[Tuple[str, int]]]] = []
        with self._db() as conn:
            rows = conn.execute(
                "SELECT id, vault_id, name, tags FROM documents "
                "WHERE id IN (%s) AND deleted = 0" % ",".join("?" * len(doc_ids)),
                doc_ids,
            ).fetchall()
            doc_rows = {r["id"]: r for r in rows}

            # Existing per-vault term frequencies (docs already in the store).
            vault_freqs: Dict[str, Dict[str, int]] = {}
            for vid in {r["vault_id"] for r in doc_rows.values()}:
                freq: Dict[str, int] = {}
                for term, cnt in conn.execute(
                    "SELECT dc.term, COUNT(DISTINCT dc.doc_id) "
                    "FROM doc_cooccurrences dc JOIN documents d ON d.id = dc.doc_id "
                    "WHERE d.vault_id = ? AND d.deleted = 0 GROUP BY dc.term",
                    (vid,),
                ).fetchall():
                    freq[term] = cnt
                vault_freqs[vid] = freq

            # Phase 1: compute candidates and fold new terms into the freq map.
            for doc_id in doc_ids:
                drow = doc_rows.get(doc_id)
                if not drow:
                    continue
                try:
                    doc_tags = json.loads(drow["tags"]) if drow["tags"] else []
                except (json.JSONDecodeError, TypeError):
                    doc_tags = []
                extracted_path = (
                    self.vaults_dir / drow["vault_id"] / "docs" / doc_id
                    / "extracted.txt"
                )
                extracted = ""
                if extracted_path.exists():
                    try:
                        extracted = extracted_path.read_text(encoding="utf-8")
                    except OSError:
                        extracted = ""
                candidates = _cooccurrence_candidates(drow["name"], extracted)
                freq = vault_freqs[drow["vault_id"]]
                for term in {t for t, _ in candidates}:
                    freq[term] = freq.get(term, 0) + 1
                prepared.append((drow, doc_tags, extracted, candidates))

            # Phase 2-3: rebuild each doc's term index then link it (interleaved per-doc
            # to avoid O(N²) join work in linking phase). The pre-computed vault_freqs
            # dict prevents the per-file IDF query cost (the original batching benefit).
            # Interleaving ensures each link operation only sees already-indexed docs.
            for drow, doc_tags, extracted, candidates in prepared:
                try:
                    _insert_doc_cooccurrences(
                        conn, drow["id"], drow["name"], doc_tags, extracted,
                        candidates=candidates,
                        vault_doc_freq=vault_freqs[drow["vault_id"]],
                    )
                except Exception as exc:
                    logger.error(
                        "_bulk_index_and_link: cooccurrence reindex failed for "
                        "doc %s: %s", drow["id"], exc,
                    )
                try:
                    _auto_link_doc_cooccurrences(conn, drow["id"])
                except Exception as exc:
                    logger.error(
                        "_bulk_index_and_link: cooccurrence link failed for "
                        "doc %s: %s", drow["id"], exc,
                    )

        # Phase 4: Lance write + embedding links (Pro only, best-effort).
        is_pro = get_tier(self.root) == TIER_PRO
        if is_pro:
            lance_index = None
            try:
                lance_index = self._get_lance_index()
            except Exception:
                lance_index = None
            for drow, _tags, extracted, _candidates in prepared:
                try:
                    self._lance_write_safe(
                        drow["id"], drow["vault_id"], drow["name"], extracted,
                    )
                except Exception:
                    pass
                if lance_index is not None:
                    with self._db() as conn:
                        try:
                            _auto_link_doc_embeddings(
                                conn, drow["id"], lance_index, is_pro=True,
                            )
                        except Exception:
                            pass

        # Phase 5: cross-product linking (best-effort).
        for drow, _tags, _extracted, _candidates in prepared:
            try:
                self.cross_link_doc(drow["id"], drow["vault_id"])
            except Exception:
                pass

    def release_idle_resources(self) -> None:
        """Drop the cached Lance index handle while idle (SH-13610).

        Called by the idle watchdog instead of exiting the process. VaultStorage
        already opens/closes a fresh sqlite connection per operation (see _db()),
        so there is no held DB lock to release here; this only drops the cached
        Lance index reference so a long-idle process is not pinning it. The next
        Pro search/index call recreates it lazily via _get_lance_index().
        """
        self._lance_index = None

    def _lance_write_safe(self, doc_id: str, vault_id: str, name: str, text: str) -> None:
        """Index a document in Lance (Pro only). Errors are logged, never raised."""
        if get_tier(self.root) != TIER_PRO:
            return
        try:
            self._get_lance_index().index_document(doc_id, vault_id, name, text)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error(
                "Lance write failed for doc %s: %s", doc_id, exc
            )

    def _lance_delete_safe(self, doc_id: str) -> None:
        """Remove a document's chunks from Lance (best-effort)."""
        if get_tier(self.root) != TIER_PRO:
            return
        try:
            self._get_lance_index().delete_document(doc_id)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error(
                "Lance delete failed for doc %s: %s", doc_id, exc
            )

    def search_semantic(
        self,
        query: str,
        vault_id: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """Hybrid semantic search via LanceDB (Pro only).

        Returns the same dict structure as search(). Falls back to FTS5 if
        the Lance index is unavailable (index not built or search error).
        Callers must check tier before calling; this does not enforce tier.

        The result carries index_coverage (and coverage_warning when the
        derived Lance index holds fewer documents than SQLite says are
        indexable in scope) -- SH-101414: a partial index must never degrade
        silently into confident wrong answers.
        """
        indexed, indexable = self._lance_coverage(vault_id)
        coverage_warning = None
        if indexed < indexable:
            coverage_warning = (
                f"Semantic index covers {indexed} of {indexable} indexable "
                f"documents in this scope; results may silently omit the "
                f"missing ones. Run vault_rebuild_index to re-sync."
            )

        doc_ids = self._get_lance_index().search(query, vault_id=vault_id, limit=limit)
        if not doc_ids:
            fallback = self.search(query, vault_id=vault_id, limit=limit)
            fallback["index_coverage"] = {"indexed_docs": indexed,
                                          "indexable_docs": indexable}
            if coverage_warning:
                fallback["coverage_warning"] = coverage_warning
            return fallback

        results = []
        with self._db() as conn:
            for doc_id in doc_ids:
                row = conn.execute(
                    """SELECT d.id, d.vault_id, d.name, d.file_size_bytes,
                              v.name as vault_name
                       FROM documents d
                       JOIN vaults v ON d.vault_id = v.id
                       WHERE d.id = ? AND d.deleted = 0""",
                    (doc_id,)
                ).fetchone()
                if not row:
                    continue
                if vault_id and row["vault_id"] != vault_id:
                    continue

                # Read a snippet from extracted text
                doc_dir = self.vaults_dir / row["vault_id"] / "docs" / doc_id
                extracted_path = doc_dir / "extracted.txt"
                snippet = ""
                if extracted_path.exists():
                    try:
                        snippet = extracted_path.read_text(encoding="utf-8")[:200].strip()
                    except Exception:
                        pass

                results.append({
                    "doc_id": doc_id,
                    "vault_id": row["vault_id"],
                    "vault_name": row["vault_name"],
                    "doc_name": row["name"],
                    "snippet": snippet,
                    "relevance_rank": None,
                })

        out = {
            "query": query,
            "scope": vault_id or "all_vaults",
            "count": len(results),
            "results": results,
            "semantic": True,
            "index_coverage": {"indexed_docs": indexed,
                               "indexable_docs": indexable},
        }
        if coverage_warning:
            out["coverage_warning"] = coverage_warning
        return out

    def _lance_coverage(self, vault_id: Optional[str] = None) -> tuple:
        """(indexed_docs, indexable_docs) for a scope.

        Indexable mirrors rebuild_lance_index eligibility: non-deleted docs
        with a non-empty extracted.txt. Docs with no extractable text can
        never be indexed and must not trigger a false coverage warning.
        Best-effort: returns (0, 0) on any error so search never breaks.
        """
        try:
            indexed = self._get_lance_index().indexed_doc_count(vault_id)
            indexable = 0
            with self._db() as conn:
                if vault_id:
                    rows = conn.execute(
                        "SELECT id, vault_id FROM documents "
                        "WHERE deleted = 0 AND vault_id = ?", (vault_id,)
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT id, vault_id FROM documents WHERE deleted = 0"
                    ).fetchall()
            for row in rows:
                extracted = (self.vaults_dir / row["vault_id"] / "docs"
                             / row["id"] / "extracted.txt")
                try:
                    if not extracted.exists():
                        continue
                    size = extracted.stat().st_size
                    if size == 0:
                        continue
                    # Whitespace-only files are never indexed (rebuild checks
                    # text.strip()); read tiny files to avoid a permanent
                    # false coverage warning.
                    if size <= 16 and not extracted.read_text(
                            encoding="utf-8", errors="ignore").strip():
                        continue
                    indexable += 1
                except OSError:
                    continue
            return indexed, indexable
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("Lance coverage check failed: %s", exc)
            return 0, 0

    def rebuild_lance_index(self, progress_cb=None, state_dict=None) -> Dict[str, Any]:
        """Rebuild the LanceDB index from all non-deleted documents. Pro only.

        Reads extracted.txt for each document. Returns a summary dict.
        progress_cb, if given, is called as progress_cb(done, total) after
        each document is embedded (SH-101414: long rebuilds must report
        progress instead of blocking silently).
        state_dict, if given, is updated with progress during the scan phase.
        """
        import sys

        docs = []
        skipped_docs = {}  # {reason: [{id, vault_id, name}, ...]}

        with self._db() as conn:
            rows = conn.execute(
                "SELECT id, vault_id, name FROM documents WHERE deleted = 0"
            ).fetchall()

            total_count = len(rows)
            if state_dict is not None:
                state_dict['total'] = total_count
                state_dict['phase'] = 'scanning'

            for idx, row in enumerate(rows):
                doc_dir = self.vaults_dir / row["vault_id"] / "docs" / row["id"]
                extracted_path = doc_dir / "extracted.txt"

                skip_reason = None

                if not extracted_path.exists():
                    # WG-32 D-16b: extracted.txt should always exist (every
                    # add_document call writes it), but can go missing out of
                    # band -- e.g. lost in a manual file-level backup/restore.
                    # The source document (current{ext}) is still on disk in
                    # that case, so re-derive extracted.txt from it instead of
                    # permanently dropping the doc from the semantic index.
                    current_files = sorted(doc_dir.glob("current.*"))
                    text = None
                    if current_files:
                        try:
                            text = extract_text(current_files[0])
                        except Exception:
                            text = None
                    if text and text.strip():
                        try:
                            extracted_path.write_text(text, encoding="utf-8")
                        except Exception:
                            pass
                        docs.append({
                            "doc_id": row["id"],
                            "vault_id": row["vault_id"],
                            "name": row["name"],
                            "text": text,
                        })
                    else:
                        skip_reason = 'missing_extracted_txt'
                else:
                    try:
                        text = extracted_path.read_text(encoding="utf-8")
                    except Exception:
                        skip_reason = 'read_error'
                    else:
                        if not text.strip():
                            skip_reason = 'empty_text'
                        else:
                            docs.append({
                                "doc_id": row["id"],
                                "vault_id": row["vault_id"],
                                "name": row["name"],
                                "text": text,
                            })

                if skip_reason:
                    if skip_reason not in skipped_docs:
                        skipped_docs[skip_reason] = []
                    skipped_docs[skip_reason].append({
                        'id': row['id'],
                        'vault_id': row['vault_id'],
                        'name': row['name']
                    })

                # Update state and progress
                if state_dict is not None:
                    state_dict['progress'] = idx + 1
                    if total_count > 0:
                        state_dict['progress_pct'] = int((idx + 1) * 100 / total_count)

                # Log every 10 docs
                if (idx + 1) % 10 == 0:
                    sys.stderr.write(f"[LoreDocs] Scanned {idx+1}/{total_count} docs\n")
                    sys.stderr.flush()

        if state_dict is not None:
            state_dict['phase'] = 'indexing'

        def _phase_cb(phase):
            if state_dict is not None:
                state_dict['phase'] = phase

        chunk_count = self._get_lance_index().rebuild(
            docs, progress_cb=progress_cb, phase_cb=_phase_cb)
        return {
            "docs_indexed": len(docs),
            "total_in_db": total_count,
            "chunks_indexed": chunk_count,
            "docs_skipped": skipped_docs,
        }

    # -------------------------------------------------------------------
    # Vault operations
    # -------------------------------------------------------------------

    def get_total_storage_bytes(self) -> int:
        """Return total bytes used across all non-deleted documents."""
        with self._db() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(file_size_bytes), 0) as total FROM documents WHERE deleted = 0"
            ).fetchone()
            return int(row["total"])

    def create_vault(self, name: str, description: str = "",
                     tags: Optional[List[str]] = None,
                     linked_projects: Optional[List[str]] = None,
                     workspace_path: Optional[str] = None) -> Dict[str, Any]:
        """Create a new vault. Returns vault metadata dict.

        Raises TierLimitError if the Free tier vault limit would be exceeded.
        """
        # Tier check: count active (non-archived) vaults
        with self._db() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM vaults WHERE archived = 0"
            ).fetchone()
            current_count = int(row["cnt"])
        self.enforcer.check_vault_count(current_count)

        # Check for duplicate vault name. Matching is case-insensitive and
        # includes archived vaults (an archived vault still reserves its name)
        # -- SH-105511 F20: duplicate checks were case-sensitive while
        # find_vault_by_name is case-insensitive, so "App" and "app" could
        # coexist and make name lookups ambiguous. Use casefold() for Unicode
        # case-insensitivity (SH-105860).
        with self._db() as conn:
            rows = conn.execute("SELECT name FROM vaults").fetchall()
            if any(_normalize_vault_name(r["name"]) == _normalize_vault_name(name) for r in rows):
                raise ValueError(f"Vault name '{name}' already exists. Please choose a unique name.")

        vault_id = str(uuid.uuid4())[:12]
        now = self._now()
        tags = tags or []
        linked_projects = linked_projects or []

        vault_dir = self.vaults_dir / vault_id / "docs"
        vault_dir.mkdir(parents=True, exist_ok=True)

        with self._db() as conn:
            conn.execute(
                """INSERT INTO vaults
                   (id, name, description, created_at, updated_at, tags, linked_projects, workspace_path)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (vault_id, name, description, now, now,
                 json.dumps(tags), json.dumps(linked_projects), workspace_path)
            )

        return {
            "id": vault_id,
            "name": name,
            "description": description,
            "created_at": now,
            "updated_at": now,
            "tags": tags,
            "linked_projects": linked_projects,
            "workspace_path": workspace_path,
            "doc_count": 0,
            "total_size_bytes": 0,
        }

    def list_vaults(self, include_archived: bool = False) -> List[Dict[str, Any]]:
        """List all vaults with summary statistics."""
        with self._db() as conn:
            if include_archived:
                rows = conn.execute("SELECT * FROM vaults ORDER BY updated_at DESC").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM vaults WHERE archived = 0 ORDER BY updated_at DESC"
                ).fetchall()

            result = []
            for row in rows:
                vault_id = row["id"]
                stats = conn.execute(
                    """SELECT COUNT(*) as doc_count, COALESCE(SUM(file_size_bytes), 0) as total_size
                       FROM documents WHERE vault_id = ? AND deleted = 0""",
                    (vault_id,)
                ).fetchone()

                result.append({
                    "id": vault_id,
                    "name": row["name"],
                    "description": row["description"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "archived": bool(row["archived"]),
                    "tags": _parse_json_list(row["tags"]),
                    "linked_projects": _parse_json_list(row["linked_projects"]),
                    "workspace_path": row["workspace_path"] if "workspace_path" in row.keys() else None,
                    "doc_count": stats["doc_count"],
                    "total_size_bytes": stats["total_size"],
                })
            return result

    def get_vault(self, vault_id: str) -> Optional[Dict[str, Any]]:
        """Get a single vault by ID. Returns None if not found."""
        with self._db() as conn:
            row = conn.execute("SELECT * FROM vaults WHERE id = ?", (vault_id,)).fetchone()
            if not row:
                return None

            stats = conn.execute(
                """SELECT COUNT(*) as doc_count, COALESCE(SUM(file_size_bytes), 0) as total_size
                   FROM documents WHERE vault_id = ? AND deleted = 0""",
                (vault_id,)
            ).fetchone()

            docs = conn.execute(
                """SELECT id, name, category, tags, updated_at, file_size_bytes
                   FROM documents WHERE vault_id = ? AND deleted = 0
                   ORDER BY updated_at DESC""",
                (vault_id,)
            ).fetchall()

            return {
                "id": row["id"],
                "name": row["name"],
                "description": row["description"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "archived": bool(row["archived"]),
                "tags": _parse_json_list(row["tags"]),
                "linked_projects": _parse_json_list(row["linked_projects"]),
                "workspace_path": row["workspace_path"] if "workspace_path" in row.keys() else None,
                "doc_count": stats["doc_count"],
                "total_size_bytes": stats["total_size"],
                "documents": [
                    {
                        "id": d["id"],
                        "name": d["name"],
                        "category": d["category"],
                        "tags": json.loads(d["tags"]),
                        "updated_at": d["updated_at"],
                        "file_size_bytes": d["file_size_bytes"],
                    }
                    for d in docs
                ],
            }

    def unique_vault_name(self, base: str) -> str:
        """Return base, or "base (N)" for the lowest N >= 2 not already taken.

        Matching is case-insensitive and includes archived vaults, mirroring
        create_vault's duplicate check, so the result is always accepted
        (SH-105506, SH-105511 F20). Vault names are unique case-insensitively:
        "App" and "app" are the same name. Uses Unicode casefold for consistency
        (SH-105860).
        """
        with self._db() as conn:
            taken = {_normalize_vault_name(r["name"]) for r in conn.execute(
                "SELECT name FROM vaults WHERE LOWER(name) = LOWER(?) OR name LIKE ?",
                (base, base + " (%)"),
            )}
        if _normalize_vault_name(base) not in taken:
            return base
        n = 2
        while _normalize_vault_name(f"{base} ({n})") in taken:
            n += 1
        return f"{base} ({n})"

    def find_vault_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Find a vault by name (case-insensitive). Returns first match.
        Uses Unicode casefold for consistency (SH-105860).
        """
        with self._db() as conn:
            rows = conn.execute("SELECT id, name FROM vaults WHERE archived = 0").fetchall()
            normalized_name = _normalize_vault_name(name)
            for row in rows:
                if _normalize_vault_name(row["name"]) == normalized_name:
                    return self.get_vault(row["id"])
            return None
