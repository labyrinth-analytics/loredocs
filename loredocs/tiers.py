"""
LoreDocs Tier System

Defines Free and Pro tier limits and enforces them through TierEnforcer.
Tier is stored in ~/.loredocs/config.json as {"tier": "free"|"pro"}.

Free tier limits (enforced):
  - Max 3 vaults
  - Max 50 documents per vault
  - Max 500 MB total storage
  - Max 5 versions per document

Pro tier: unlimited on all dimensions.
"""

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Tier definitions
# ---------------------------------------------------------------------------

TIER_FREE = "free"
TIER_PRO = "pro"

VALID_TIERS = {TIER_FREE, TIER_PRO}


@dataclass
class TierLimits:
    """Numeric limits for a tier. None means unlimited."""
    max_vaults: Optional[int]
    max_docs_per_vault: Optional[int]
    max_storage_bytes: Optional[int]
    max_versions_per_doc: Optional[int]
    tier_name: str

    def is_unlimited(self) -> bool:
        return all(
            v is None for v in [
                self.max_vaults,
                self.max_docs_per_vault,
                self.max_storage_bytes,
                self.max_versions_per_doc,
            ]
        )


FREE_LIMITS = TierLimits(
    max_vaults=3,
    max_docs_per_vault=50,
    max_storage_bytes=500 * 1024 * 1024,   # 500 MB
    max_versions_per_doc=5,
    tier_name=TIER_FREE,
)

PRO_LIMITS = TierLimits(
    max_vaults=None,
    max_docs_per_vault=None,
    max_storage_bytes=None,
    max_versions_per_doc=None,
    tier_name=TIER_PRO,
)

TIER_LIMITS = {
    TIER_FREE: FREE_LIMITS,
    TIER_PRO: PRO_LIMITS,
}


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

CONFIG_FILE = "config.json"


def _load_config(root: Path) -> dict:
    """Load config.json from root. Returns empty dict if missing."""
    path = root / CONFIG_FILE
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_config(root: Path, config: dict) -> None:
    """Write config.json to root."""
    path = root / CONFIG_FILE
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


_LEGACY_TIER_GRACE_DAYS = 30
_legacy_warned = set()  # dedupe the structured WARN per (root, expired) per process


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _legacy_grace_expired(started_at: str) -> bool:
    try:
        ts = datetime.fromisoformat(started_at)
    except (ValueError, TypeError):
        return True  # unparseable timestamp -- fail closed to Free, not indefinite Pro
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age_days = (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0
    return age_days > _LEGACY_TIER_GRACE_DAYS


def get_tier(root: Path) -> str:
    """Return the current tier ('free' or 'pro'). See get_tier_detail() for the
    resolution source (license vs. the bounded legacy config.json fallback)."""
    tier, _source = get_tier_detail(root)
    return tier


def get_tier_detail(root: Path) -> tuple:
    """Return (tier, source). source is one of:
        'license'               -- signature-verified (env var or durable file store)
        'legacy_config_grace'   -- config.json['tier']=='pro', no verified key yet,
                                    within the SH-13079 bounded grace window
        'legacy_config_expired' -- same, but the grace window has elapsed -- Free
        'free'                  -- no Pro grant of any kind

    Pro mode requires a valid Labyrinth Analytics license key set in the
    LOREDOCS_PRO environment variable (format: LAB-...) or durably persisted
    to ~/.loredocs/license.json (see license_store.py).

    For internal agents: set both LOREDOCS_PRO=1 and LAB_DEV_MODE=1 in the
    internal .mcp.json to bypass key validation.  The public plugin .mcp.json
    files must NOT include LAB_DEV_MODE.

    Legacy fallback (SH-13079 r4 CRITICAL disposition -- FIXED IN IMPLEMENTATION):
    if no verified key resolves Pro, config.json['tier']=='pro' still grants Pro,
    but only for a bounded, monitored grace window measured from the first time
    this code observes the flag with no verified key present -- not indefinitely.
    A signature-less flag hand-edited into config.json by anyone with filesystem
    write access can no longer grant permanent, unauthenticated Pro. The window is
    an absolute per-install wall-clock timestamp (not a global ship-date/version
    cutover), so there is nothing ambiguous to compute at expiry, closing the
    round-3 "ambiguous cutover" objection without reopening the round-4 "indefinite
    bypass" one. See docs/agent-reports/architecture/proposals/
    loreconvo_loredocs_durable_license_persistence_20260713.md PART:migration for
    the proposal's own (rejected-by-this-disposition) "never removed" design.
    """
    # Support both package import (relative) and direct module import (absolute).
    try:
        from .license import is_pro_licensed
    except ImportError:
        from license import is_pro_licensed  # noqa: F401 -- direct import fallback

    if is_pro_licensed():
        return TIER_PRO, "license"

    config = _load_config(root)
    tier = config.get("tier", TIER_FREE)
    if tier not in VALID_TIERS:
        return TIER_FREE, "free"
    if tier != TIER_PRO:
        return tier, "free"

    started = config.get("legacy_tier_grace_started_at")
    if not started:
        config["legacy_tier_grace_started_at"] = _now_iso()
        _save_config(root, config)
        started = config["legacy_tier_grace_started_at"]

    if _legacy_grace_expired(started):
        _log_legacy_tier_once(root, expired=True)
        return TIER_FREE, "legacy_config_expired"

    _log_legacy_tier_once(root, expired=False)
    return TIER_PRO, "legacy_config_grace"


def _log_legacy_tier_once(root: Path, *, expired: bool) -> None:
    """Structured WARN, deduped per (root, expired) per process -- SH-13079
    PART:migration's 'logs a structured WARN ... useful for support diagnosis'."""
    key = (str(root), expired)
    if key in _legacy_warned:
        return
    _legacy_warned.add(key)
    if expired:
        print(
            f"[warn] loredocs tiers: {root}/config.json legacy tier='pro' grace period "
            f"expired (> {_LEGACY_TIER_GRACE_DAYS}d with no verified license key) -- "
            "reverted to Free. Run `loredocs-cli license set LAB-...` or set "
            "LOREDOCS_PRO and restart to restore Pro.",
            file=sys.stderr,
        )
    else:
        print(
            f"[warn] loredocs tiers: {root}/config.json relies on the deprecated, "
            "unsigned tier fallback (no verified license key found). Run "
            "`loredocs-cli license set LAB-...` or set LOREDOCS_PRO and restart to "
            "upgrade to durable, signature-verified Pro persistence.",
            file=sys.stderr,
        )


def legacy_tier_notice(root: Path) -> Optional[str]:
    """User-facing remediation message (SH-13079 PART:migration) for CLI/MCP
    surfaces to display. None unless the account is currently on, or was just
    dropped from, the legacy config.json fallback."""
    _tier, source = get_tier_detail(root)
    if source == "legacy_config_grace":
        return (
            "Your Pro status is currently tracked by an older, unsigned method. Run "
            "`loredocs-cli license set LAB-...`, or set LOREDOCS_PRO via your MCP "
            "client's server configuration and restart it, to upgrade to durable, "
            "signature-verified Pro persistence before your grace period ends. If you "
            "don't have your key, contact support@labyrinthanalyticsconsulting.com."
        )
    if source == "legacy_config_expired":
        return (
            "Your previous Pro status (tracked by an older, unsigned method) has "
            f"expired after {_LEGACY_TIER_GRACE_DAYS} days with no verified license "
            "key. Run `loredocs-cli license set LAB-...`, or set LOREDOCS_PRO via your "
            "MCP client's server configuration and restart it. If you don't have your "
            "key, contact support@labyrinthanalyticsconsulting.com."
        )
    return None


def set_tier(root: Path, tier: str) -> None:
    """Persist a tier change to config.json."""
    if tier not in VALID_TIERS:
        raise ValueError(f"Invalid tier '{tier}'. Valid values: {sorted(VALID_TIERS)}")
    config = _load_config(root)
    config["tier"] = tier
    _save_config(root, config)


def get_limits(root: Path) -> TierLimits:
    """Return the TierLimits object for the current tier."""
    return TIER_LIMITS[get_tier(root)]


# ---------------------------------------------------------------------------
# TierEnforcer
# ---------------------------------------------------------------------------

class TierLimitError(Exception):
    """Raised when an operation would exceed a tier limit."""

    def __init__(self, message: str, upgrade_hint: str = ""):
        self.upgrade_hint = upgrade_hint
        super().__init__(message)


class TierEnforcer:
    """Checks tier limits before write operations.

    All check_* methods raise TierLimitError if the limit would be exceeded.
    They are no-ops for Pro tier (all limits are None).
    """

    def __init__(self, root: Path):
        self.root = root

    def limits(self) -> TierLimits:
        return get_limits(self.root)

    def _upgrade_hint(self) -> str:
        return (
            "Upgrade to Pro for unlimited usage. "
            "Use vault_set_tier with tier='pro' to activate your license."
        )

    def check_vault_count(self, current_vault_count: int) -> None:
        """Raise if adding one more vault would exceed the limit."""
        lim = self.limits()
        if lim.max_vaults is None:
            return
        if current_vault_count >= lim.max_vaults:
            raise TierLimitError(
                f"Free tier allows at most {lim.max_vaults} vaults "
                f"(currently have {current_vault_count}). "
                "Archive or delete an existing vault, or upgrade to Pro.",
                upgrade_hint=self._upgrade_hint(),
            )

    def check_doc_count(self, current_doc_count: int, vault_name: str = "") -> None:
        """Raise if adding one more document would exceed per-vault limit."""
        lim = self.limits()
        if lim.max_docs_per_vault is None:
            return
        vault_label = f" in vault '{vault_name}'" if vault_name else ""
        if current_doc_count >= lim.max_docs_per_vault:
            raise TierLimitError(
                f"Free tier allows at most {lim.max_docs_per_vault} documents per vault "
                f"(currently have {current_doc_count}{vault_label}). "
                "Delete some documents or upgrade to Pro.",
                upgrade_hint=self._upgrade_hint(),
            )

    def check_storage(self, current_bytes: int, new_file_bytes: int) -> None:
        """Raise if adding new_file_bytes would exceed total storage limit."""
        lim = self.limits()
        if lim.max_storage_bytes is None:
            return
        if current_bytes + new_file_bytes > lim.max_storage_bytes:
            limit_mb = lim.max_storage_bytes // (1024 * 1024)
            current_mb = current_bytes / (1024 * 1024)
            new_mb = new_file_bytes / (1024 * 1024)
            raise TierLimitError(
                f"Free tier allows at most {limit_mb} MB total storage "
                f"(currently using {current_mb:.1f} MB, trying to add {new_mb:.1f} MB). "
                "Delete documents or upgrade to Pro.",
                upgrade_hint=self._upgrade_hint(),
            )

    def check_version_count(self, current_version_count: int, doc_name: str = "") -> None:
        """Raise if adding one more version would exceed per-document limit."""
        lim = self.limits()
        if lim.max_versions_per_doc is None:
            return
        doc_label = f" for '{doc_name}'" if doc_name else ""
        if current_version_count >= lim.max_versions_per_doc:
            raise TierLimitError(
                f"Free tier allows at most {lim.max_versions_per_doc} versions per document "
                f"(currently have {current_version_count}{doc_label}). "
                "Delete old versions or upgrade to Pro.",
                upgrade_hint=self._upgrade_hint(),
            )

    def status_dict(self, vault_count: int, total_bytes: int) -> dict:
        """Return a dict describing current tier status and usage vs. limits."""
        lim = self.limits()
        tier = get_tier(self.root)

        def _pct(used, limit):
            if limit is None or limit == 0:
                return None
            return round(100.0 * used / limit, 1)

        storage_limit_mb = (
            lim.max_storage_bytes // (1024 * 1024)
            if lim.max_storage_bytes is not None
            else None
        )
        storage_used_mb = round(total_bytes / (1024 * 1024), 2)

        return {
            "tier": tier,
            "vault_count": vault_count,
            "vault_limit": lim.max_vaults,
            "vault_usage_pct": _pct(vault_count, lim.max_vaults),
            "storage_used_mb": storage_used_mb,
            "storage_limit_mb": storage_limit_mb,
            "storage_usage_pct": _pct(total_bytes, lim.max_storage_bytes),
            "docs_per_vault_limit": lim.max_docs_per_vault,
            "versions_per_doc_limit": lim.max_versions_per_doc,
            "is_pro": tier == TIER_PRO,
        }
