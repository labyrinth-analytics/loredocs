"""
LoreDocs Notion Import Bridge -- checkpoint management and security primitives.

This module provides:
- _SecretStr: a string wrapper that redacts on all string-conversion paths,
  preventing accidental token leakage in logs, exceptions, or MCP responses.
- redact_secrets: a text redactor covering both regex (defense-in-depth) and
  literal substring replacement (authoritative, format-agnostic).
- resolve_notion_token: token resolution from env var or OS keychain.
- CheckpointManager: file-based resume-state manager with cross-platform locking
  (POSIX flock / Windows msvcrt.locking) and a _locked reentrancy signal.

Security model:
- _SecretStr is the structural guard -- the raw token never reaches a
  string-conversion path unredacted.
- redact_secrets(raw_token=...) is the format-agnostic guard -- a literal
  substring replace catches tokens embedded in URLs, repr output, etc.
- _NOTION_TOKEN_PATTERN is defense-in-depth only -- it catches token-shaped
  strings when the raw token is not in hand.

Binding reopen condition (SH-13143 H5):
  If Notion introduces a third token prefix beyond secret_ / ntn_, the
  _NOTION_TOKEN_PATTERN regex must be updated in the SAME release that adds
  support for it.
"""

import os
import json
import uuid
import platform
import re
import sys

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class NotionTokenMissingError(Exception):
    """Raised when NOTION_TOKEN is not found in env or keychain."""


class NotionTokenRevokedError(Exception):
    """Raised when a token that was valid becomes invalid mid-import."""


class NotionAPIError(Exception):
    """Raised when the Notion API returns an error response."""


class NotionImportError(Exception):
    """Raised for unexpected errors during Notion import."""


class VaultNotFoundError(Exception):
    """Raised when a vault name or ID cannot be resolved."""


class VaultAmbiguousError(Exception):
    """Raised when a vault name matches multiple vaults."""


# ---------------------------------------------------------------------------
# _SecretStr -- enforced redaction boundary (r4 HIGH-09, r5/H5)
# ---------------------------------------------------------------------------


class _SecretStr:
    """
    Wrapper for secret string values.
    Redacts on all string-conversion paths. Raw value accessible only via
    .secret_value.

    Redacts on:
    - str() / print()
    - repr()
    - f-strings / format()
    - bytes()

    The raw value is accessible ONLY via .secret_value property. Code that
    needs the raw token for Notion SDK calls uses .secret_value. The CI
    boundary check (scripts/ci/grep_notion_token.py) flags any use of
    .secret_value outside notion_import.py and redact_secrets().
    """

    __slots__ = ('_value',)

    def __init__(self, value):
        if not isinstance(value, str):
            raise TypeError("_SecretStr requires a str value")
        self._value = value

    def __str__(self):
        return '[NOTION_TOKEN_REDACTED]'

    def __repr__(self):
        return '_SecretStr([REDACTED])'

    def __format__(self, spec):
        return '[NOTION_TOKEN_REDACTED]'

    def __bytes__(self):
        # Prevents encoding tricks: bytes(token) -> b'[NOTION_TOKEN_REDACTED]'
        return b'[NOTION_TOKEN_REDACTED]'

    @property
    def secret_value(self):
        """Access raw value. Callers must NOT log or format this property directly."""
        return self._value

    def __eq__(self, other):
        if isinstance(other, _SecretStr):
            return self._value == other._value
        return NotImplemented

    def __hash__(self):
        return hash(self._value)


# ---------------------------------------------------------------------------
# Token redaction (r4 HIGH-09/HIGH-10, r5/H5)
# ---------------------------------------------------------------------------

# [r5/H5] covers both legacy secret_ and current ntn_ internal-integration
# token prefixes. Defense-in-depth only -- authoritative guards are
# _SecretStr (structural) and literal raw_token replacement in redact_secrets
# (format-agnostic).
#
# Binding reopen condition: if Notion introduces a third token prefix beyond
# secret_ / ntn_, this regex must be updated in the SAME release.
_NOTION_TOKEN_PATTERN = re.compile(r'\b(?:secret_|ntn_)[A-Za-z0-9_-]{16,}')


def redact_secrets(text, raw_token=None):
    """
    Redact Notion tokens from text.

    Always receives the raw string value, never a _SecretStr wrapper
    (which would self-redact trivially).

    Two mechanisms:
    1. Regex substitution (_NOTION_TOKEN_PATTERN) -- defense-in-depth, catches
       token-shaped strings when the raw token is not in hand.
    2. Literal raw_token replacement -- authoritative, format-agnostic. A
       literal substring replace is position- and context-independent, so it
       also covers tokens embedded in URLs, repr output, or exception strings.
    """
    result = _NOTION_TOKEN_PATTERN.sub('[NOTION_TOKEN_REDACTED]', text)
    if raw_token and len(raw_token) > 8:
        result = result.replace(raw_token, '[NOTION_TOKEN_REDACTED]')
    return result


# ---------------------------------------------------------------------------
# Token resolution (r4 HIGH-09)
# ---------------------------------------------------------------------------


def resolve_notion_token():
    """
    Resolve NOTION_TOKEN at invocation time. Returns _SecretStr wrapper.

    Resolution order: env var -> OS keychain -> NotionTokenMissingError.

    Token is resolved at EVERY invocation (not cached at startup). Live
    reload is automatic when the env var or keychain entry changes.

    notion_token is NOT an MCP parameter -- it is never passed through the
    MCP tool interface, so it never appears in MCP host tool-call logs.
    """
    raw = os.environ.get("NOTION_TOKEN", "").strip()
    if raw:
        return _SecretStr(raw)
    try:
        import keyring
        stored = keyring.get_password("loredocs", "notion_token")
        if stored:
            return _SecretStr(stored)
    except Exception:
        pass
    raise NotionTokenMissingError(
        "NOTION_TOKEN not found in environment or OS keychain.\n"
        "  Option 1: export NOTION_TOKEN=secret_xxx\n"
        "  Option 2: python3 -m loredocs.cli set-notion-token  (stores in OS keychain)"
    )


# ---------------------------------------------------------------------------
# CheckpointManager -- cross-platform locking with reentrancy signal (r4 HIGH-08, r5/H12)
# ---------------------------------------------------------------------------


class CheckpointManager:
    """
    File-based checkpoint manager with cross-platform locking.

    POSIX: fcntl.flock (exclusive lock).
    Windows: msvcrt.locking (LK_LOCK -- blocks up to 10 retries).

    The _locked flag [r5/H12] signals whether the main thread currently holds
    the lock. The SIGTERM/SIGINT signal handler checks this flag to avoid
    contending for a lock the main thread already holds, which would deadlock
    on flock or raise OSError after 10s on Windows msvcrt.locking.

    os.replace in save() is atomic, so the on-disk checkpoint is never torn.
    The corruption risk being closed is the in-flight double-write, not the
    on-disk file.
    """

    def __init__(self, path):
        self.path = path
        self._lock_fd = None
        self._locked = False  # [r5/H12] reentrancy signal for the signal handler

    def __enter__(self):
        self._lock_fd = open(self.path + ".lock", "w")
        if platform.system() == "Windows":
            import msvcrt
            self._lock_fd.seek(0)
            msvcrt.locking(self._lock_fd.fileno(), msvcrt.LK_LOCK, 1)
            # LK_LOCK blocks until the lock is acquired (up to 10 one-second
            # retries on Windows, then raises OSError). No busy-loop needed.
        else:
            import fcntl
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX)
        self._locked = True  # [r5/H12]
        return self

    def __exit__(self, *args):
        self._locked = False  # [r5/H12]
        if platform.system() == "Windows":
            import msvcrt
            self._lock_fd.seek(0)
            msvcrt.locking(self._lock_fd.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
        self._lock_fd.close()

    def load(self):
        """Load checkpoint data. Returns empty structure if file is absent or invalid."""
        try:
            with open(self.path) as f:
                return json.load(f)
        except (FileNotFoundError, ValueError):
            return {"schema_version": 1, "run_id": str(uuid.uuid4()), "entries": {}}

    def save(self, data):
        """Atomically save checkpoint data via tmp + os.replace."""
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.path)