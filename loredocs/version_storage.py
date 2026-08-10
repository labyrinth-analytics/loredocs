"""
LoreDocs Version-Storage Integrity -- Core Storage Layer (r6 / SH-100432)

This module implements the version-storage integrity machinery from the r6
proposal (loredocs_version-storage-integrity_20260729.md) as amended by the
SH-13812 manual disposition.  It is imported by storage.py and provides:

- Custom exceptions for history divergence, recovery abort, lock issues, and
  history budget enforcement.
- Constants for sidecar/journal schema versions, file-size limits, lock
  defaults, tombstone multiplier, and cloud-sync directory prefixes.
- Helper functions for atomic writes (temp + os.replace), file hashing,
  sidecar validation, version-number parsing, history globs, highwater
  markers, intent-journal read/write/delete, lock health checks, tier-based
  retention depth / history budget computation, vault history byte totals,
  and path-based substrate warning.
- DocumentLock: a per-document advisory lock (POSIX fcntl / Windows msvcrt)
  with FD_CLOEXEC, bounded retry, and healthy-lock verification.
- DocContext: a dataclass holding all per-document state needed by the
  single-entry-point _doc_context flow.
- DocContextManager: the choke point that acquires the lock, replays stale
  intent journals, computes the 5-source allocator, and checks divergence
  (including the gap-free requirement) for both reads and writes.

Binding constraints (from the r6 proposal and disposition):
1. No trust claim about bytes is ever persisted (no hash in sidecars/markers).
2. No code path branches on annotation field or substrate path match.
3. Nothing is ever deleted or overwritten to resolve a conflict -- rename aside.
4. No new tables, no new columns, no constraint DDL.
5. Do not re-root identity on DB table or append-only index.
6. Do not add another substrate classifier or probe.

All Python source is ASCII-only.  No Unicode characters are used.
"""

import hashlib
import json
import logging
import os
import platform
import re
import stat
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Platform-specific lock primitives.
# fcntl is POSIX-only; msvcrt is Windows-only.  Import defensively.
try:
    import fcntl  # type: ignore
except ImportError:
    fcntl = None  # type: ignore

try:
    import msvcrt  # type: ignore
except ImportError:
    msvcrt = None  # type: ignore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SIDECAR_SCHEMA_VERSION = 1
"""Current schema version for history/v{N}.meta.json sidecars."""

JOURNAL_SCHEMA_VERSION = 1
"""Current schema version for .intent.json intent journals."""

MAX_SIDECAR_SIZE = 64 * 1024
"""Maximum allowed size for a sidecar file (64 KB).  Files exceeding this are
rejected as corrupt during validation."""

DEFAULT_LOCK_TIMEOUT = 5.0
"""Default lock acquisition timeout in seconds."""

TOMBSTONE_MULTIPLIER = 4
"""Tombstone sidecars (rotated_at set, no content file) are capped at
retention_depth * TOMBSTONE_MULTIPLIER.  Oldest tombstones beyond that are
dropped."""

# Cloud-sync directory path prefixes for the one-time startup warning.
# Path-prefix match only -- explicitly NOT a behavioral probe (r6/C2).
CLOUD_SYNC_PREFIXES: List[str] = [
    "/Dropbox",
    "/Library/Mobile Documents/com~apple~CloudDocs",
    "/OneDrive",
    "/Google Drive",
]

# Tier defaults for retention depth and history budget.
FREE_RETENTION_DEPTH = 5
FREE_HISTORY_BUDGET_MB = 1024       # 1 GB
PRO_RETENTION_DEPTH = 100
PRO_HISTORY_BUDGET_MB = 5120        # 5 GB

# Env-var override ranges.
_MIN_RETENTION_DEPTH = 2
_MAX_RETENTION_DEPTH = 100000
_MIN_HISTORY_BUDGET_MB = 1

# Regex patterns for filename parsing.
# Content files: v{N}{ext} where ext is a dot followed by 1-10 alnum chars.
_RE_CONTENT_FILE = re.compile(r"^v([0-9]{1,6})\.([A-Za-z0-9]{1,10})$")
# Sidecar files: v{N}.meta.json
_RE_SIDECAR_FILE = re.compile(r"^v([0-9]{1,6})\.meta\.json$")
# Exclude suffixes that mark non-content files in history/.
_EXCLUDED_SUFFIXES = (
    ".meta.json",
    ".intent.json",
    ".highwater",
    ".partial",
    ".conflict",    # prefix for .conflict-{ts}{ext}
    ".invalid",     # prefix for .invalid-{ts}
    ".superseded",  # prefix for .superseded (no ext after)
)
# Files in history/ that start with a dot are infrastructure, not content.
_INFRA_FILES = {".highwater"}


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class HistoryDivergedError(Exception):
    """Raised when version history divergence is detected.

    The ``kind`` attribute names the specific divergence issue:
    ``history-rollback``, ``history-loss``, ``history-jump``, or
    ``history-holes``.
    """

    def __init__(self, kind: str, detail: str = ""):
        self.kind = kind
        self.detail = detail
        super().__init__(f"history-{kind}: {detail}")


class RecoveryAbortedError(Exception):
    """Raised when replay cannot attribute current.new bytes.

    Blocks writes only -- reads always serve what is on disk, flagged
    (r6/C3).
    """
    pass


class DocumentLockedError(Exception):
    """Raised when a document lock cannot be acquired within the timeout."""
    pass


class LockUnusableError(Exception):
    """Raised when .lock is not a healthy zero-byte regular file.

    Per r6/H7: a malformed .lock (directory, symlink, non-zero size, or
    unopenable) raises this instead of blocking indefinitely.  Consent-gated
    repair renames it aside to .lock.unusable-{ts}.
    """
    pass


class HistoryBudgetExceededError(Exception):
    """Raised when vault history bytes would exceed the hard cap.

    Raised before any mutation so the document is left byte-identical
    (r6/ops-cost).
    """
    pass


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Current UTC timestamp as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _hash_file(path: Path) -> str:
    """SHA-256 hex digest of file content.

    Reads the file in 64 KB chunks to bound memory for large files.
    """
    h = hashlib.sha256()
    with open(str(path), "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _hash_bytes(data: bytes) -> str:
    """SHA-256 hex digest of a bytes object."""
    return hashlib.sha256(data).hexdigest()


def _safe_write_json(path: Path, data: dict, mode: int = 0o600) -> None:
    """Write JSON via temp + os.replace.  Atomic.

    The temp file is created in the same directory as ``path`` (so the
    rename is guaranteed to be on the same filesystem).  The file is written
    with the specified mode, fsync'd, and then os.replace'd into place.
    The parent directory is fsync'd to ensure the rename is durable.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".{path.name}.tmp-{os.getpid()}-{int(time.time() * 1e6)}"
    try:
        # Create the temp file with the desired mode.
        fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        try:
            encoded = json.dumps(data, indent=2).encode("utf-8")
            os.write(fd, encoded)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(str(tmp_path), str(path))
        _fsync_dir(path.parent)
    except Exception:
        # Clean up the temp file on any failure.
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def _safe_write_bytes(path: Path, data: bytes, mode: int = 0o600) -> None:
    """Write bytes via temp + os.replace.  Atomic.

    Same pattern as _safe_write_json but for raw bytes.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".{path.name}.tmp-{os.getpid()}-{int(time.time() * 1e6)}"
    try:
        fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(str(tmp_path), str(path))
        _fsync_dir(path.parent)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def _fsync_dir(dir_path: Path) -> None:
    """fsync a directory to ensure rename operations are durable.

    Best-effort: some platforms/filesystems do not support directory fsync.
    """
    try:
        fd = os.open(str(dir_path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except (OSError, PermissionError):
        # Not all platforms/filesystems support this.  Non-fatal.
        pass


def _parse_version_number(filename: str) -> Optional[int]:
    """Extract version number from v{N}{ext} or v{N}.meta.json filename.

    Returns the integer version number, or None if the filename does not
    match either pattern.
    """
    # Try sidecar pattern first: v{N}.meta.json
    m = _RE_SIDECAR_FILE.match(filename)
    if m:
        return int(m.group(1))
    # Try content file pattern: v{N}.{ext}
    m = _RE_CONTENT_FILE.match(filename)
    if m:
        return int(m.group(1))
    return None


def _content_file_glob(history_dir: Path) -> List[Path]:
    """Glob history/v{N}{ext} content files.

    Excludes .meta.json sidecars, .intent.json, .highwater, .partial,
    .conflict-*, .invalid-*, and .superseded files.
    """
    if not history_dir.is_dir():
        return []
    results: List[Path] = []
    for entry in history_dir.iterdir():
        name = entry.name
        if name.startswith("."):
            # Infrastructure files (.highwater, etc.) are never content.
            continue
        # Skip excluded suffixes.
        if any(name.endswith(suf) for suf in _EXCLUDED_SUFFIXES):
            continue
        # Skip files with .conflict- or .invalid- infixes (r6/C3 rename-aside).
        if ".conflict-" in name or ".invalid-" in name:
            continue
        # Must match v{N}.{ext} pattern.
        if _RE_CONTENT_FILE.match(name):
            results.append(entry)
    return sorted(results, key=lambda p: _parse_version_number(p.name) or 0)


def _sidecar_glob(history_dir: Path) -> List[Path]:
    """Glob history/v{N}.meta.json sidecar files.

    Excludes .superseded and .invalid variants.
    """
    if not history_dir.is_dir():
        return []
    results: List[Path] = []
    for entry in history_dir.iterdir():
        name = entry.name
        if not _RE_SIDECAR_FILE.match(name):
            continue
        # Skip superseded/invalid sidecars (they have different extensions).
        # _RE_SIDECAR_FILE already excludes these because it requires exact
        # .meta.json suffix, but we check defensively.
        if ".superseded" in name or ".invalid" in name:
            continue
        results.append(entry)
    return sorted(results, key=lambda p: _parse_version_number(p.name) or 0)


def _fs_max_version(history_dir: Path) -> int:
    """Max version number from content files.  0 if empty."""
    versions = [_parse_version_number(p.name) for p in _content_file_glob(history_dir)]
    versions = [v for v in versions if v is not None]
    return max(versions) if versions else 0


def _sidecar_max_version(history_dir: Path) -> int:
    """Max version number from sidecars.  0 if empty."""
    versions = [_parse_version_number(p.name) for p in _sidecar_glob(history_dir)]
    versions = [v for v in versions if v is not None]
    return max(versions) if versions else 0


def _all_evidenced_numbers(history_dir: Path) -> Set[int]:
    """Set of version numbers evidenced by content files OR sidecars.

    This is the union used for the gap-free check (r6/H4).  A version number
    is "evidenced" if either a content file or a sidecar exists for it.
    Rotation removes the content file but keeps the sidecar, so the number
    remains evidenced -- which is why the allocator counts sidecars and why
    rotation is not a hole.
    """
    numbers: Set[int] = set()
    for p in _content_file_glob(history_dir):
        v = _parse_version_number(p.name)
        if v is not None:
            numbers.add(v)
    for p in _sidecar_glob(history_dir):
        v = _parse_version_number(p.name)
        if v is not None:
            numbers.add(v)
    return numbers


def _read_highwater(history_dir: Path) -> int:
    """Read history/.highwater file.  Returns 0 if missing/invalid.

    Format: {"schema": 1, "highwater": N, "updated_at": "..."}
    """
    hw_path = history_dir / ".highwater"
    if not hw_path.is_file():
        return 0
    try:
        if hw_path.stat().st_size > MAX_SIDECAR_SIZE:
            return 0
        data = json.loads(hw_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return 0
        hw = data.get("highwater")
        if not isinstance(hw, int) or hw < 0:
            return 0
        return hw
    except (json.JSONDecodeError, OSError, ValueError):
        return 0


def _write_highwater(history_dir: Path, value: int) -> None:
    """Write history/.highwater (temp + os.replace, mode 0600).

    Written BEFORE content creation so it is monotonic by construction
    (r6/C1).  If the content write fails, the highwater still records the
    allocated number, which is correct -- the number was issued and will
    not be reissued.
    """
    history_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "schema": 1,
        "highwater": value,
        "updated_at": _now_iso(),
    }
    _safe_write_json(history_dir / ".highwater", data, mode=0o600)


def _read_reset_floor(doc_dir: Path) -> int:
    """Read .history_reset.json floor.  Returns 0 if missing/invalid.

    Format: {"observed_fs_max": N, "db_version_count": N, "direction": "...",
             "reset_at": "..."}
    The floor used by the allocator is max(observed_fs_max, db_version_count).
    """
    rp_path = doc_dir / ".history_reset.json"
    if not rp_path.is_file():
        return 0
    try:
        data = json.loads(rp_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return 0
        observed = data.get("observed_fs_max")
        db_count = data.get("db_version_count")
        floor = 0
        if isinstance(observed, int) and observed > floor:
            floor = observed
        if isinstance(db_count, int) and db_count > floor:
            floor = db_count
        return floor
    except (json.JSONDecodeError, OSError, ValueError):
        return 0


def _read_intent_journal(doc_dir: Path) -> Optional[dict]:
    """Read and validate .intent.json.  Returns None if missing or invalid.

    Per r6/H8: validates journal_schema, payload_len, and sha256_payload.
    Any journal that fails validation -- including one written by a newer
    client -- is treated as absent: renamed to .intent.json.invalid-{ts}
    and reported.  Replay is skipped.

    The journal format is:
    {"journal_schema": 1, "payload_len": N, "sha256_payload": "...",
     "op": "...", "doc_id": "...", "from_version": N, "to_version": N,
     "ext_old": "...", "ext_new": "...", "sha256_old": "...",
     "sha256_new": "...", "rotate_version": N, "started_at": "..."}
    """
    jp = doc_dir / ".intent.json"
    if not jp.is_file():
        return None
    try:
        raw = jp.read_bytes()
        if len(raw) > 1024 * 1024:
            # Unreasonably large -- treat as corrupt.
            raise ValueError("journal too large")
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("journal is not a JSON object")
        schema = data.get("journal_schema")
        if not isinstance(schema, int):
            raise ValueError("journal_schema absent or non-integer")
        if schema != JOURNAL_SCHEMA_VERSION:
            raise ValueError(f"unknown journal_schema: {schema}")
        payload_len = data.get("payload_len")
        if not isinstance(payload_len, int):
            raise ValueError("payload_len absent or non-integer")
        sha256_payload = data.get("sha256_payload")
        if not isinstance(sha256_payload, str):
            raise ValueError("sha256_payload absent or not a string")
        # Validate payload hash: the payload is the JSON object minus the
        # three validation fields, re-serialized.  This is the integrity
        # check that a torn write cannot pass.
        payload = {k: v for k, v in data.items()
                   if k not in ("journal_schema", "payload_len", "sha256_payload")}
        payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
        if len(payload_bytes) != payload_len:
            raise ValueError(
                f"payload_len mismatch: declared={payload_len}, actual={len(payload_bytes)}"
            )
        actual_hash = hashlib.sha256(payload_bytes).hexdigest()
        if actual_hash != sha256_payload:
            raise ValueError("sha256_payload mismatch")
        return data
    except Exception as exc:
        # r6/H8: rename the invalid journal aside, do not replay.
        ts = _timestamp_suffix()
        invalid_path = doc_dir / f".intent.json.invalid-{ts}"
        try:
            os.replace(str(jp), str(invalid_path))
            logger.warning(
                "Intent journal at %s was invalid (%s); renamed to %s. "
                "Replay skipped per r6/H8.",
                jp, exc, invalid_path,
            )
        except OSError as rename_exc:
            logger.error(
                "Could not rename invalid intent journal at %s: %s",
                jp, rename_exc,
            )
        return None


def _write_intent_journal(doc_dir: Path, payload: dict) -> None:
    """Write .intent.json with journal_schema, payload_len, sha256_payload.

    Uses temp + os.replace (mode 0600).  The payload dict contains the
    operation-specific fields (op, doc_id, from_version, to_version, ext_old,
    ext_new, sha256_old, sha256_new, rotate_version, started_at).  This
    function wraps it with the three validation fields.
    """
    payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
    data = {
        "journal_schema": JOURNAL_SCHEMA_VERSION,
        "payload_len": len(payload_bytes),
        "sha256_payload": hashlib.sha256(payload_bytes).hexdigest(),
    }
    data.update(payload)
    _safe_write_json(doc_dir / ".intent.json", data, mode=0o600)


def _delete_intent_journal(doc_dir: Path) -> None:
    """Unlink .intent.json.  No-op if missing."""
    jp = doc_dir / ".intent.json"
    try:
        jp.unlink(missing_ok=True)
    except Exception:
        pass


def _check_lock_health(lock_path: Path) -> bool:
    """Check if .lock is a healthy zero-byte regular file.

    Returns False if:
    - The path does not exist.
    - The path is not a regular file (directory, symlink, etc.).
    - The file has non-zero size.
    - The file cannot be opened (permissions, etc.).

    Per r6/H7: a malformed .lock should raise LockUnusableError, not
    silently fail.  This helper returns a boolean so the caller can decide
    whether to raise or attempt repair.
    """
    if not lock_path.exists():
        return False
    try:
        st = lock_path.lstat()
    except OSError:
        return False
    if not stat.S_ISREG(st.st_mode):
        return False
    if st.st_size != 0:
        return False
    # Verify it can be opened.
    try:
        with open(str(lock_path), "rb") as f:
            pass
    except OSError:
        return False
    return True


def _compute_retention_depth(tier: str, enforcer=None) -> int:
    """Get retention depth for tier.

    Free = 5, Pro = 100.  Override via LOREDOCS_MAX_VERSIONS env var
    (must be an integer in [2, 100000]).

    The ``enforcer`` parameter is accepted for API compatibility but is
    not used for the override -- the r6 proposal redefines retention depth
    as a fixed-per-tier value with an env override, not as the TierEnforcer's
    max_versions_per_doc (which is None for Pro, meaning "unlimited" in the
    old semantics but "100" in the new retention semantics).
    """
    env_val = os.environ.get("LOREDOCS_MAX_VERSIONS")
    if env_val is not None:
        try:
            depth = int(env_val)
        except ValueError:
            raise ValueError(
                f"LOREDOCS_MAX_VERSIONS={env_val!r} is not an integer. "
                f"Valid range: [{_MIN_RETENTION_DEPTH}, {_MAX_RETENTION_DEPTH}]."
            )
        if depth < _MIN_RETENTION_DEPTH or depth > _MAX_RETENTION_DEPTH:
            raise ValueError(
                f"LOREDOCS_MAX_VERSIONS={depth} is out of range. "
                f"Valid range: [{_MIN_RETENTION_DEPTH}, {_MAX_RETENTION_DEPTH}]."
            )
        return depth
    if tier == "pro":
        return PRO_RETENTION_DEPTH
    return FREE_RETENTION_DEPTH


def _compute_history_budget(tier: str) -> int:
    """Get vault history budget in bytes.

    Free = 1 GB, Pro = 5 GB.  Override via LOREDOCS_HISTORY_BUDGET_MB env
    (must be an integer >= 1).
    """
    env_val = os.environ.get("LOREDOCS_HISTORY_BUDGET_MB")
    if env_val is not None:
        try:
            mb = int(env_val)
        except ValueError:
            raise ValueError(
                f"LOREDOCS_HISTORY_BUDGET_MB={env_val!r} is not an integer. "
                f"Must be >= {_MIN_HISTORY_BUDGET_MB}."
            )
        if mb < _MIN_HISTORY_BUDGET_MB:
            raise ValueError(
                f"LOREDOCS_HISTORY_BUDGET_MB={mb} is too small. "
                f"Must be >= {_MIN_HISTORY_BUDGET_MB}."
            )
        return mb * 1024 * 1024
    if tier == "pro":
        return PRO_HISTORY_BUDGET_MB * 1024 * 1024
    return FREE_HISTORY_BUDGET_MB * 1024 * 1024


def _vault_history_bytes(vaults_dir: Path, vault_id: str) -> int:
    """Total bytes of all history/ content files across all docs in a vault.

    Counts only content files (v{N}{ext}), not sidecars or infrastructure
    files.  Used for the vault history hard cap check (r6/ops-cost).
    """
    vault_docs = vaults_dir / vault_id / "docs"
    if not vault_docs.is_dir():
        return 0
    total = 0
    try:
        for doc_dir in vault_docs.iterdir():
            if not doc_dir.is_dir():
                continue
            history_dir = doc_dir / "history"
            if not history_dir.is_dir():
                continue
            for cf in _content_file_glob(history_dir):
                try:
                    total += cf.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _should_warn_substrate(vault_root: Path) -> Optional[str]:
    """Check if vault root is under a known cloud-sync directory.

    Returns the matched path prefix string, or None if no match.

    This is a path-prefix match against a static list (r6/C2).  It is
    explicitly NOT a behavioral probe -- nothing branches on the result.
    The return value is used only to emit a one-time startup warning.

    The match checks whether any known cloud-sync directory appears as a
    path component in the resolved vault root path.  For example,
    ``/Users/debbieshapiro/Dropbox/loredocs`` matches the ``/Dropbox``
    prefix because ``/Dropbox`` appears as a directory component.
    """
    try:
        resolved = str(vault_root.resolve())
    except Exception:
        resolved = str(vault_root)
    # Normalize trailing separator for consistent matching.
    if not resolved.endswith(os.sep):
        resolved_normalized = resolved + os.sep
    else:
        resolved_normalized = resolved
    for prefix in CLOUD_SYNC_PREFIXES:
        # Check if the prefix appears as a directory component in the path.
        # A prefix like "/Dropbox" should match "/Users/X/Dropbox/loredocs"
        # but not "/Users/X/MyDropbox/loredocs".
        prefix_with_sep = prefix + os.sep
        if resolved.startswith(prefix) or prefix_with_sep in resolved_normalized:
            return prefix
    return None


def _timestamp_suffix() -> str:
    """Generate a filesystem-safe timestamp suffix for rename-aside files.

    Format: YYYYMMDDHHMMSSmmm (millisecond precision, no separators).
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y%m%d%H%M%S") + f"{now.microsecond // 1000:03d}"


def _validate_sidecar(path: Path, expected_version: int) -> Optional[dict]:
    """Read and validate a v{N}.meta.json sidecar.

    Returns the parsed dict if valid, or None if invalid/missing.

    Reject if:
    - File is larger than MAX_SIDECAR_SIZE (64 KB).
    - Content is not a JSON object.
    - ``version`` field is absent or disagrees with the filename.
    - ``schema_version`` is absent or unknown (not an integer).

    Per r6/data-model: an invalid sidecar does not degrade behavior --
    identity comes from the filesystem.  It means that one version's
    annotations are reported unavailable, and siblings are not touched.
    """
    if not path.is_file():
        return None
    try:
        if path.stat().st_size > MAX_SIDECAR_SIZE:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        version = data.get("version")
        if not isinstance(version, int):
            return None
        if version != expected_version:
            return None
        schema_ver = data.get("schema_version")
        if not isinstance(schema_ver, int):
            return None
        # Unknown schema versions are rejected for annotation purposes.
        # Identity is unaffected.  The sidecar is left in place.
        return data
    except (json.JSONDecodeError, OSError, ValueError):
        return None


def _write_sidecar(
    history_dir: Path,
    version: int,
    doc_id: str,
    ext: str,
    size_bytes: int,
    op: str,
    saved_at: Optional[str] = None,
    author: Optional[str] = None,
    session_id: Optional[str] = None,
    note: Optional[str] = None,
    restored_from: Optional[int] = None,
    provenance: str = "recorded",
    rotated_at: Optional[str] = None,
) -> Path:
    """Write a history/v{N}.meta.json sidecar (temp + os.replace, mode 0600).

    This is a write-once operation: the sidecar is created in the same
    locked, journalled operation that creates the version.  The only
    permitted post-creation mutation is setting ``rotated_at`` (via
    _stamp_rotated_at).

    No hash is ever persisted in the sidecar (binding constraint 1).
    """
    history_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": SIDECAR_SCHEMA_VERSION,
        "doc_id": doc_id,
        "version": version,
        "ext": ext,
        "size_bytes": size_bytes,
        "saved_at": saved_at or _now_iso(),
        "provenance": provenance,
        "op": op,
        "author": author,
        "session_id": session_id,
        "note": note,
        "restored_from": restored_from,
        "rotated_at": rotated_at,
    }
    sidecar_path = history_dir / f"v{version}.meta.json"
    _safe_write_json(sidecar_path, data, mode=0o600)
    return sidecar_path


def _stamp_rotated_at(history_dir: Path, version: int) -> None:
    """Set rotated_at on an existing sidecar (the one permitted post-creation mutation).

    Reads the existing sidecar, adds/updates ``rotated_at``, and rewrites it
    via temp + os.replace.  If the sidecar is missing or invalid, this is
    a no-op -- the version will report ``missing`` instead of ``rotated``,
    which is the bias toward reporting drift stated in the data-model.
    """
    sidecar_path = history_dir / f"v{version}.meta.json"
    if not sidecar_path.is_file():
        return
    data = _validate_sidecar(sidecar_path, version)
    if data is None:
        # Invalid sidecar -- do not touch it.  The version reports missing.
        return
    data["rotated_at"] = _now_iso()
    _safe_write_json(sidecar_path, data, mode=0o600)


# ---------------------------------------------------------------------------
# DocumentLock context manager
# ---------------------------------------------------------------------------

class DocumentLock:
    """Per-document advisory lock on docs/{doc_id}/.lock.

    POSIX: fcntl.flock(LOCK_EX | LOCK_NB) with bounded retry.
    Windows: msvcrt.locking(LOCK_NBLCK, 1).
    FD_CLOEXEC on the lock fd (os.set_inheritable(fd, False)).

    Never unlinks a healthy .lock.  Raises LockUnusableError if .lock is
    malformed (r6/H7).  The lock is not load-bearing for correctness --
    integrity comes from the hash-guarded mutation order (r6/interfaces).
    The lock is a contention optimization that prevents lost updates.
    """

    def __init__(self, doc_dir: Path, timeout: Optional[float] = None):
        self.doc_dir = doc_dir
        self.lock_path = doc_dir / ".lock"
        if timeout is not None:
            self.timeout = timeout
        else:
            self.timeout = _get_lock_timeout()
        self._fd: Optional[int] = None
        self._owned = False  # True if we created/opened the lock fd

    def __enter__(self) -> "DocumentLock":
        self._acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._release()

    def _acquire(self) -> None:
        """Acquire the lock with bounded retry."""
        doc_dir = self.doc_dir
        doc_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.lock_path

        # r6/H7: check lock health before attempting to open.
        # If .lock exists but is malformed (not a regular file, non-zero
        # size, or unopenable), raise LockUnusableError.
        if lock_path.exists():
            if not _check_lock_health(lock_path):
                # Determine the specific issue for the error message.
                try:
                    st = lock_path.lstat()
                    if not stat.S_ISREG(st.st_mode):
                        kind = "not a regular file"
                    elif st.st_size != 0:
                        kind = f"non-zero size ({st.st_size} bytes)"
                    else:
                        kind = "unopenable"
                except OSError:
                    kind = "stat failed"
                raise LockUnusableError(
                    f"Lock file at {lock_path} is malformed ({kind}). "
                    f"Run vault_verify(doc_id=..., repair=True, "
                    f"confirm='lock-unusable') to rename it aside and "
                    f"create a fresh one."
                )

        # Open the lock file (create if needed) with FD_CLOEXEC.
        # We use O_RDWR | O_CREAT so the file persists (never unlinked).
        retry_interval = 0.05  # 50ms between retries
        deadline = time.monotonic() + self.timeout
        last_exc: Optional[Exception] = None

        while True:
            try:
                fd = os.open(
                    str(lock_path),
                    os.O_RDWR | os.O_CREAT,
                    0o600,
                )
                # FD_CLOEXEC: child processes do not inherit the lock fd.
                os.set_inheritable(fd, False)

                if fcntl is not None:
                    # POSIX: flock with LOCK_EX | LOCK_NB (non-blocking).
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        self._fd = fd
                        self._owned = True
                        return
                    except OSError as exc:
                        # EAGAIN/EWOULDBLOCK means another process holds it.
                        os.close(fd)
                        last_exc = exc
                        if time.monotonic() >= deadline:
                            break
                        time.sleep(retry_interval)
                        continue
                elif msvcrt is not None:
                    # Windows: byte-range lock with LOCK_NBLCK.
                    try:
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                        self._fd = fd
                        self._owned = True
                        return
                    except OSError as exc:
                        os.close(fd)
                        last_exc = exc
                        if time.monotonic() >= deadline:
                            break
                        time.sleep(retry_interval)
                        continue
                else:
                    # No lock primitive available (should not happen on
                    # supported platforms).  Hold the fd as a best-effort.
                    logger.warning(
                        "No lock primitive available (fcntl and msvcrt both "
                        "absent).  Lock at %s is best-effort only.",
                        lock_path,
                    )
                    self._fd = fd
                    self._owned = True
                    return
            except OSError as exc:
                # Could not open the lock file at all.
                last_exc = exc
                if time.monotonic() >= deadline:
                    break
                time.sleep(retry_interval)
                continue

        # Timed out or exhausted retries.
        raise DocumentLockedError(
            f"Could not acquire lock on {lock_path} within "
            f"{self.timeout:.1f}s. "
            f"Another process may be holding it, or the lock file may be "
            f"stale.  Last error: {last_exc}"
        )

    def _release(self) -> None:
        """Release the lock and close the fd.  Never unlinks .lock."""
        if self._fd is not None and self._owned:
            fd = self._fd
            try:
                if fcntl is not None:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_UN)
                    except OSError:
                        pass
                elif msvcrt is not None:
                    try:
                        # Seek back to 0 before unlocking the 1-byte range.
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
            finally:
                try:
                    os.close(fd)
                except OSError:
                    pass
            self._fd = None
            self._owned = False


def _get_lock_timeout() -> float:
    """Get the lock timeout from the LOREDOCS_LOCK_TIMEOUT env var, or default."""
    env_val = os.environ.get("LOREDOCS_LOCK_TIMEOUT")
    if env_val is not None:
        try:
            return float(env_val)
        except ValueError:
            logger.warning(
                "LOREDOCS_LOCK_TIMEOUT=%r is not a float; using default %.1f",
                env_val, DEFAULT_LOCK_TIMEOUT,
            )
    return DEFAULT_LOCK_TIMEOUT


# ---------------------------------------------------------------------------
# DocContext dataclass
# ---------------------------------------------------------------------------

@dataclass
class DocContext:
    """Returned by DocContextManager.acquire.  Holds all per-document state.

    This is the single object that read and write paths receive from
    _doc_context.  It carries identity (computed from the filesystem),
    divergence info (reported but not branched on), and recovery state.

    Per the binding rule in the proposal data-model: annotation fields are
    NOT present in this object -- annotations are loaded only by the two
    read/report functions that display them (get_doc_history, vault_verify).
    The write path and the tier enforcer never see them.
    """
    doc_dir: Path
    history_dir: Path
    ext: str
    version_count: int           # from DB
    fs_max: int
    sidecar_max: int
    highwater: int
    reset_floor: int
    next_version: int
    divergence: Optional[dict]   # None if clean, else {kind, detail, remedy}
    recovery_aborted: bool       # True if RecoveryAbortedError blocks writes
    recovery_orphan: Optional[str]  # path to orphan file if any
    lock: Optional[DocumentLock] = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# DocContextManager -- the choke point
# ---------------------------------------------------------------------------

class DocContextManager:
    """Manages _doc_context entry/exit for VaultStorage.

    _doc_context is the SINGLE entry point for all document operations
    (read and write).  It is the only way any code obtains a document
    directory handle.  It:

    1. Acquires the per-document lock (LOCK_EX for writes, LOCK_SH for
       reads where supported).
    2. Checks and replays stale intent journals (validated per r6/H8).
    3. Computes the 5-source allocator:
       max(fs_max, sidecar_max, db_count, reset_floor, highwater) + 1
    4. Checks divergence in both directions (r6/H4: gap-free requirement).
    5. Yields DocContext.

    For reads: divergence is reported but does not block (r6/H2).
    For writes: divergence raises HistoryDivergedError.
    """

    def __init__(
        self,
        vaults_dir: Path,
        db_path: Path,
        tier: str,
        enforcer,
    ):
        self.vaults_dir = vaults_dir
        self.db_path = db_path
        self.tier = tier
        self.enforcer = enforcer

    def acquire(
        self,
        doc_id: str,
        vault_id: str,
        ext: str,
        version_count: int,
        write: bool = True,
    ) -> DocContext:
        """Acquire context for a document operation.

        This method:
        1. Resolves the document directory.
        2. Acquires the per-document lock (exclusive for writes, shared
           for reads where supported).
        3. Checks for and replays a stale intent journal.
        4. Computes fs_max, sidecar_max, highwater, reset_floor.
        5. Computes next_version via the 5-source allocator.
        6. Checks divergence in both directions.
        7. For writes: raises HistoryDivergedError if divergence detected.
           For reads: returns divergence info in DocContext (r6/H2).

        Returns a DocContext.  The caller is responsible for releasing the
        lock (via DocContext.lock.__exit__ or an explicit release).
        """
        doc_dir = self.vaults_dir / vault_id / "docs" / doc_id
        history_dir = doc_dir / "history"
        history_dir.mkdir(parents=True, exist_ok=True)

        # 1. Acquire the lock.
        lock = DocumentLock(doc_dir)
        lock.__enter__()

        try:
            # 2. Check for and replay a stale intent journal (r6/H8, r6/H5).
            recovery_aborted = False
            recovery_orphan: Optional[str] = None

            journal = _read_intent_journal(doc_dir)
            if journal is not None:
                try:
                    orphan = self.replay_journal(doc_dir, history_dir, journal)
                    if orphan:
                        recovery_orphan = orphan
                        recovery_aborted = True
                    # Journal is deleted inside replay_journal on success.
                except RecoveryAbortedError:
                    # Step 3d abort: unattributable current.new bytes.
                    # Blocks writes only; reads proceed (r6/C3).
                    recovery_aborted = True
                    # The orphan path should be in the exception message.
                    # We extract it if present, but the journal is already
                    # deleted by replay_journal's abort handler.
                    logger.error(
                        "Recovery aborted for doc %s: unattributable "
                        "current.new bytes.  Writes blocked, reads proceed.",
                        doc_id,
                    )
                except Exception as exc:
                    # Unexpected replay error: log it, treat journal as
                    # stale/absent.  Do not re-raise -- the document should
                    # remain accessible for reads.
                    logger.exception(
                        "Unexpected error during journal replay for doc %s: %s",
                        doc_id, exc,
                    )
                    # Ensure the journal is cleaned up to avoid a loop.
                    _delete_intent_journal(doc_dir)

            # 3. Compute filesystem-derived identity sources.
            fs_max = _fs_max_version(history_dir)
            sidecar_max = _sidecar_max_version(history_dir)
            highwater = _read_highwater(history_dir)
            reset_floor = _read_reset_floor(doc_dir)

            # 4. Compute next_version via the 5-source allocator.
            next_version = self.compute_next_version(
                history_dir, version_count, highwater, reset_floor
            )

            # 5. Check divergence.
            divergence = self.check_divergence(
                history_dir, version_count, highwater, reset_floor
            )

            # 6. Enforce write-blocking rules.
            if write:
                if recovery_aborted:
                    raise RecoveryAbortedError(
                        f"Recovery aborted for document {doc_id}: "
                        f"unattributable current.new bytes. "
                        f"Orphan at: {recovery_orphan or 'unknown'}. "
                        f"Run vault_verify(doc_id='{doc_id}', repair=True) "
                        f"to resolve."
                    )
                if divergence is not None:
                    kind = divergence["kind"]
                    detail = divergence["detail"]
                    remedy = divergence.get("remedy", "")
                    raise HistoryDivergedError(
                        kind,
                        f"{detail}. {remedy}" if remedy else detail,
                    )

            # 7. Build and return DocContext.
            return DocContext(
                doc_dir=doc_dir,
                history_dir=history_dir,
                ext=ext,
                version_count=version_count,
                fs_max=fs_max,
                sidecar_max=sidecar_max,
                highwater=highwater,
                reset_floor=reset_floor,
                next_version=next_version,
                divergence=divergence,
                recovery_aborted=recovery_aborted,
                recovery_orphan=recovery_orphan,
                lock=lock,
            )
        except (HistoryDivergedError, RecoveryAbortedError):
            # Release the lock before propagating write-blocking errors.
            lock.__exit__(None, None, None)
            raise
        except Exception:
            # On any unexpected error, release the lock before propagating.
            lock.__exit__(None, None, None)
            raise

    def replay_journal(
        self,
        doc_dir: Path,
        history_dir: Path,
        journal: dict,
    ) -> Optional[str]:
        """Replay a stale intent journal.  Hash-guarded, idempotent, roll-forward only.

        Implements steps 3a-6 from the proposal write ordering.  Each step
        is guarded so that replaying a partially-completed operation is a
        no-op for already-completed steps.

        Returns the path to an orphan file if step 3d aborts (unattributable
        current.new bytes), or None on success.

        Per r6/C3: on a step 3a hash mismatch, the conflicting destination
        is renamed aside to v{N}.conflict-{ts}{ext} rather than aborting.
        Both byte sequences survive.  RecoveryAbortedError is raised only
        for step 3d (unattributable current.new bytes).
        """
        from_version = journal.get("from_version")
        to_version = journal.get("to_version")
        ext_old = journal.get("ext_old", "")
        ext_new = journal.get("ext_new", "")
        sha256_old = journal.get("sha256_old", "")
        sha256_new = journal.get("sha256_new", "")
        rotate_version = journal.get("rotate_version")
        op = journal.get("op", "update")

        if not isinstance(from_version, int) or not isinstance(to_version, int):
            # Malformed journal -- should have been caught by validation,
            # but defend against it anyway.
            _delete_intent_journal(doc_dir)
            return None

        # Step 3a: Archive current -> history/v{from_version}{ext_old}
        # Guard: skip if the destination already exists with the correct hash.
        dest_path = history_dir / f"v{from_version}{ext_old}"
        need_archive = True
        if dest_path.is_file():
            try:
                if _hash_file(dest_path) == sha256_old:
                    need_archive = False
            except OSError:
                pass

        if need_archive:
            current_old = doc_dir / f"current{ext_old}"
            if current_old.is_file():
                # Stage to .v{N}.partial{ext_old}, verify hash, then replace.
                partial_path = history_dir / f".v{from_version}.partial{ext_old}"
                try:
                    # Copy current to the staging path.
                    content_bytes = current_old.read_bytes()
                    _safe_write_bytes(partial_path, content_bytes, mode=0o600)
                    # Verify the staged file's hash.
                    staged_hash = _hash_file(partial_path)
                    if staged_hash != sha256_old:
                        # The current file's bytes don't match what the
                        # journal recorded.  This is the never-overwrite
                        # guard.  Per r6/C3: rename the conflicting
                        # destination aside (if it exists), then complete.
                        if dest_path.is_file():
                            ts = _timestamp_suffix()
                            conflict_path = history_dir / f"v{from_version}.conflict-{ts}{ext_old}"
                            os.replace(str(dest_path), str(conflict_path))
                            logger.warning(
                                "History conflict at %s: existing file hash "
                                "differs from journal.  Renamed to %s (r6/C3).",
                                dest_path, conflict_path,
                            )
                        # Now place the staged file.
                        os.replace(str(partial_path), str(dest_path))
                        _fsync_dir(history_dir)
                    else:
                        # Hash matches -- safe to replace.
                        os.replace(str(partial_path), str(dest_path))
                        _fsync_dir(history_dir)
                except Exception as exc:
                    # Clean up the partial file on any failure.
                    try:
                        partial_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    logger.error(
                        "Failed to archive current to history during replay: %s",
                        exc,
                    )
                    # Do not delete the journal -- we may retry.
                    raise

        # Step 3b: Write the sidecar for the archived version.
        sidecar_path = history_dir / f"v{from_version}.meta.json"
        if not sidecar_path.is_file():
            try:
                dest_stat = dest_path.stat()
                _write_sidecar(
                    history_dir,
                    version=from_version,
                    doc_id=journal.get("doc_id", ""),
                    ext=ext_old,
                    size_bytes=dest_stat.st_size,
                    op="recovered",
                    saved_at=journal.get("started_at"),
                )
            except Exception as exc:
                logger.warning(
                    "Failed to write sidecar for v%d during replay: %s",
                    from_version, exc,
                )

        # Step 3c: Rotation -- unlink the rotate_version content file if
        # it still exists, and stamp rotated_at on its sidecar.
        if rotate_version is not None and isinstance(rotate_version, int):
            rotate_path = history_dir / f"v{rotate_version}{ext_old}"
            if rotate_path.is_file():
                try:
                    rotate_path.unlink()
                    _stamp_rotated_at(history_dir, rotate_version)
                except Exception as exc:
                    logger.warning(
                        "Failed to rotate v%d during replay: %s",
                        rotate_version, exc,
                    )

        # Step 3d: Replace current.new{ext_new} -> current{ext_new}.
        # Guard: if current{ext_new} already hashes to sha256_new, the
        # replace already happened -- skip.
        current_new_path = doc_dir / f"current.new{ext_new}"
        current_dest_path = doc_dir / f"current{ext_new}"

        replace_done = False
        if current_dest_path.is_file():
            try:
                if _hash_file(current_dest_path) == sha256_new:
                    replace_done = True
            except OSError:
                pass

        if not replace_done:
            if not current_new_path.is_file():
                # current.new is absent.  Check if current{ext_new} already
                # matches -- handled above.  If not, this is an abort:
                # we cannot attribute the bytes.
                if current_dest_path.is_file():
                    # current{ext_new} exists but doesn't match sha256_new,
                    # and current.new is gone.  This is the unattributable
                    # case -- abort (r6/C3).
                    ts = _timestamp_suffix()
                    orphan_path = doc_dir / f"current.new.orphan-{ts}{ext_new}"
                    try:
                        os.replace(str(current_dest_path), str(orphan_path))
                    except OSError:
                        orphan_path = current_dest_path
                    _delete_intent_journal(doc_dir)
                    raise RecoveryAbortedError(
                        f"Replay cannot attribute current.new bytes for "
                        f"to_version={to_version}.  current.new is absent "
                        f"and current{ext_new} does not match the recorded "
                        f"hash.  Orphan preserved at: {orphan_path}. "
                        f"Run vault_verify(doc_id=..., repair=True)."
                    )
                else:
                    # Both current.new and current are absent.  The content
                    # was lost (e.g., substrate dropped the write).  Nothing
                    # to replay -- the save failed.  Clean up the journal.
                    _delete_intent_journal(doc_dir)
                    return None
            else:
                # current.new exists -- verify its hash.
                try:
                    new_hash = _hash_file(current_new_path)
                except OSError:
                    new_hash = ""

                if new_hash != sha256_new:
                    # current.new exists but hashes to something else.
                    # Unattributable bytes -- abort (r6/C3).
                    ts = _timestamp_suffix()
                    orphan_path = doc_dir / f"current.new.orphan-{ts}{ext_new}"
                    try:
                        os.replace(str(current_new_path), str(orphan_path))
                    except OSError:
                        orphan_path = current_new_path
                    _delete_intent_journal(doc_dir)
                    raise RecoveryAbortedError(
                        f"Replay cannot attribute current.new bytes for "
                        f"to_version={to_version}.  Hash mismatch: "
                        f"expected {sha256_new[:16]}..., got {new_hash[:16]}... "
                        f"Orphan preserved at: {orphan_path}. "
                        f"Run vault_verify(doc_id=..., repair=True)."
                    )

                # Hash matches -- safe to replace.
                os.replace(str(current_new_path), str(current_dest_path))
                _fsync_dir(doc_dir)
                replace_done = True

        # Step 3e: If ext_old != ext_new, unlink current{ext_old}.
        # Guard: only if it still exists and the replace is done.
        if ext_old and ext_new and ext_old != ext_new:
            old_current = doc_dir / f"current{ext_old}"
            if old_current.is_file() and replace_done:
                try:
                    old_current.unlink()
                except Exception as exc:
                    logger.warning(
                        "Failed to unlink old current%s during replay: %s",
                        ext_old, exc,
                    )

        # Step 3f: Rewrite extracted.txt.
        # Guard: skip if it doesn't exist or can't be read (non-fatal).
        try:
            from .storage import extract_text  # lazy import to avoid circular
            extracted = extract_text(current_dest_path)
            extracted_path = doc_dir / "extracted.txt"
            _safe_write_bytes(
                extracted_path,
                extracted.encode("utf-8"),
                mode=0o600,
            )
        except Exception as exc:
            logger.warning(
                "Failed to rewrite extracted.txt during replay: %s",
                exc,
            )

        # Step 4: Rewrite metadata.json.
        # This requires DB state, which we don't have here.  The caller
        # (update_document) handles metadata.json and the DB update.
        # In replay, we skip this step -- metadata.json will be updated
        # on the next successful write, and it is strictly derived.

        # Step 5: DB update.
        # Similarly, the DB update is handled by the caller in the normal
        # path.  In replay, the caller will see the updated next_version
        # and handle the DB accordingly.

        # Step 6: Delete the intent journal.
        _delete_intent_journal(doc_dir)

        logger.info(
            "Replay completed for doc %s: from_version=%d, to_version=%d, op=%s",
            journal.get("doc_id", "?"), from_version, to_version, op,
        )
        return None

    def check_divergence(
        self,
        history_dir: Path,
        db_count: int,
        highwater: int,
        reset_floor: int,
    ) -> Optional[dict]:
        """Check for history divergence.  Returns None if clean, or a dict.

        Returns None if the history is clean, or a dict with keys:
        - kind: one of "history-rollback", "history-loss", "history-jump",
          "history-holes"
        - detail: human-readable description
        - remedy: instructions for recovery

        Checks (in order, per r6 proposal):
        1. highwater > max(fs_max, sidecar_max, db_count) -> history-rollback
        2. fs_max < db_count -> history-loss
        3. fs_max > db_count + 1 -> history-jump
        4. Gap-free check: all numbers 1..max must be evidenced -> history-holes

        The reset_floor is an allocator input but is NOT used in divergence
        detection -- it is the result of a previous consented recovery, so
        it would generate false positives if checked.
        """
        fs_max = _fs_max_version(history_dir)
        sidecar_max = _sidecar_max_version(history_dir)
        observed_max = max(fs_max, sidecar_max, db_count)

        # 1. history-rollback: highwater records numbers the restored
        #    evidence no longer shows (r6/C1).
        if highwater > observed_max:
            return {
                "kind": "history-rollback",
                "detail": (
                    f"highwater={highwater} exceeds observed max "
                    f"(fs_max={fs_max}, sidecar_max={sidecar_max}, "
                    f"db_count={db_count}). "
                    f"A backup/restore may have rolled back the version "
                    f"evidence."
                ),
                "remedy": (
                    "Run vault_verify(doc_id=..., repair=True, "
                    "confirm='history-rollback') to resume numbering "
                    "past the marker."
                ),
            }

        # 2. history-loss: filesystem is behind the DB.
        #    version_count (db_count) is the current version's number.
        #    History files should exist for v1..v{db_count-1}.
        #    So fs_evidence should be >= db_count - 1 in the normal case.
        #    fs_evidence < db_count - 1 means at least one version is missing
        #    from both content files and sidecars.
        #    Special case: db_count <= 1 means no history yet (current is v1),
        #    so fs_evidence=0 is correct and not a loss.
        fs_evidence = max(fs_max, sidecar_max)
        if db_count > 1 and fs_evidence < db_count - 1:
            return {
                "kind": "history-loss",
                "detail": (
                    f"Filesystem evidence (fs_max={fs_max}, "
                    f"sidecar_max={sidecar_max}) is behind DB "
                    f"version_count={db_count}. "
                    f"History files may have been deleted."
                ),
                "remedy": (
                    "Run vault_verify(doc_id=..., repair=True, "
                    "confirm='history-loss') to reset the allocator "
                    "floor past the lost range."
                ),
            }

        # 3. history-jump: filesystem is ahead of the DB by more than the
        #    crash window.  The +1 slack is the legitimate post-crash state
        #    (a version file can land before the DB commit).
        if fs_max > db_count + 1:
            return {
                "kind": "history-jump",
                "detail": (
                    f"Filesystem fs_max={fs_max} is ahead of DB "
                    f"version_count={db_count} by more than the crash "
                    f"window (+1). "
                    f"A forged or foreign high-numbered file may be present."
                ),
                "remedy": (
                    "Run vault_verify(doc_id=..., repair=True, "
                    "confirm='history-jump') to resume numbering past "
                    "the foreign range."
                ),
            }

        # 4. history-holes: all numbers 1..max(history evidence) must be
        #    evidenced by either a content file or a sidecar (r6/H4).
        #    Rotation is not a hole because the sidecar survives.
        #    The current version (v{db_count}) is NOT in history/ -- it is
        #    the current{ext} file -- so it is excluded from the gap-free
        #    check.  Only versions 1..max(fs_max, sidecar_max) need to be
        #    gap-free.
        evidenced = _all_evidenced_numbers(history_dir)
        history_evidence_max = max(fs_max, sidecar_max)
        if history_evidence_max > 0:
            missing = [n for n in range(1, history_evidence_max + 1) if n not in evidenced]
            if missing:
                # Limit the detail string for very large gaps.
                if len(missing) <= 20:
                    missing_str = ", ".join(str(n) for n in missing)
                else:
                    missing_str = ", ".join(str(n) for n in missing[:20]) + "..."
                return {
                    "kind": "history-holes",
                    "detail": (
                        f"Version numbers missing from all evidence sources: "
                        f"[{missing_str}]. "
                        f"Checked range 1..{history_evidence_max}."
                    ),
                    "remedy": (
                        "Run vault_verify(doc_id=..., repair=True) to inspect "
                        "and address the gaps."
                    ),
                }

        return None

    def compute_next_version(
        self,
        history_dir: Path,
        db_count: int,
        highwater: int,
        reset_floor: int,
    ) -> int:
        """5-source allocator: max(fs_max, sidecar_max, db_count, reset_floor, highwater) + 1.

        This is the single rule for version number allocation (r6/data-model).
        Version numbers are monotonically increasing because the allocator
        can only move past what exists.  No single source can lower the
        floor.

        The reset_floor is the floor from .history_reset.json, set by a
        previous consented recovery.  It survives further damage to content
        files.
        """
        fs_max = _fs_max_version(history_dir)
        sidecar_max = _sidecar_max_version(history_dir)
        return max(fs_max, sidecar_max, db_count, reset_floor, highwater) + 1

    def release(self, ctx: DocContext) -> None:
        """Release the lock held by a DocContext."""
        if ctx.lock is not None:
            ctx.lock.__exit__(None, None, None)
            ctx.lock = None


# ---------------------------------------------------------------------------
# Context manager wrapper for _doc_context-style usage
# ---------------------------------------------------------------------------

@contextmanager
def doc_context_cm(
    manager: DocContextManager,
    doc_id: str,
    vault_id: str,
    ext: str,
    version_count: int,
    write: bool = True,
):
    """Context manager wrapper around DocContextManager.acquire.

    Usage:
        with doc_context_cm(mgr, doc_id, vault_id, ext, vc, write=True) as ctx:
            ...

    The lock is released on exit, including on exceptions.
    """
    ctx = manager.acquire(doc_id, vault_id, ext, version_count, write=write)
    try:
        yield ctx
    finally:
        manager.release(ctx)