# LoreDocs Changelog

What changed in each release, written for users (not developers).

---

## 2026-04-06

### Bug Fixes

- **`cryptography` package is now a listed dependency.** Pro license key validation requires the `cryptography` package. Previously it was accidentally missing from the dependency list, which meant a fresh `pip install` could fail to validate your license key with a "module not found" error. This is now fixed -- the package installs automatically. The workaround noted in the 2026-04-03 known issues section is no longer needed.

- **License validation hardened against edge case.** An edge case was fixed where the developer bypass could theoretically be triggered when the `LOREDOCS_PRO` environment variable was set but empty. Free-tier users were not affected. Pro users are not affected. This only closed a gap in internal test environments.

- **Hook scripts now work after a fresh install.** Same fix as LoreConvo: the install script now sets correct execute permissions on the SessionStart and SessionEnd hook scripts. Auto-save and auto-load now work correctly after cloning and running `install.sh`.

---

## 2026-04-03

### New Features

- **License key validation for Pro tier.** Pro access now uses Ed25519-signed license keys instead of a simple environment variable. Free users are unaffected. If you have a license key, set it as your `LOREDOCS_PRO` environment variable and LoreDocs validates it locally (no internet needed).

### Improvements

- **Plugin defaults fixed.** The public plugin `.mcp.json` now ships with an empty `LOREDOCS_PRO` value (not "1"), so new users start on the free tier as intended.

### Known Issues

- **SEC-014 (resolved in 2026-04-06):** The `cryptography` package was missing from pyproject.toml dependencies, which could cause Pro license validation to fail on fresh installs. Fixed. No workaround needed -- reinstall with `bash install.sh` to get the corrected dependencies.

---

## 2026-04-01

### Improvements

- **README and documentation updates.** Cleaned up references to the old "ProjectVault" name. All user-facing docs now consistently use "LoreDocs."

- **Plugin onboarding UX.** Improved first-run experience for new plugin installs.

---

## 2026-03-31

### New Features

- **BSL 1.1 license.** LoreDocs is now licensed under the Business Source License 1.1. Free for personal and non-commercial use (up to 3 vaults). Converts to Apache 2.0 on 2030-03-31.

- **3-vault free tier enforcement.** Free accounts can create up to 3 vaults. After that, `vault_create` returns a friendly message explaining how to upgrade. Existing vaults are never deleted.

- **Tier management tools.** Two new MCP tools: `vault_tier_status` (check your tier and usage) and `vault_set_tier` (activate Pro with a license key).

---

## 2026-03-29

### Improvements

- **Dependency pinning.** All dependencies are now pinned to exact versions in `requirements-lock.txt` for reproducible installs.

- **Security hardening.** Improved path traversal protections, database discovery restrictions, log PII masking, file size limits, and FTS5 input validation.

---

## 2026-03-25

### New Features

- **Renamed from ProjectVault to LoreDocs.** The product has a new name. All tool names, database paths, and documentation have been updated. If you were using ProjectVault, your existing data at `~/.loredocs/` is preserved.

---

## Earlier Releases

LoreDocs v0.1.0 established the core architecture: SQLite+FTS5 storage, 34 MCP tools for vault and document management, file import/export, full-text search, version history, tagging, and context injection.
