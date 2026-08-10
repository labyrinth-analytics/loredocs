# LoreDocs Changelog

What changed in each release, written for users (not developers).

---

## v0.1.20 (2026-08-09)

### New: Clear your Pro license from the bundled fallback CLI

```
python -m loredocs.cli license clear
```

Removes the stored Pro license key from this machine. If you have suite-wide
Pro shared with LoreConvo, add `--suite` to clear it from both. The command
reports anything it could not clear rather than failing quietly.

This is part of the bundled fallback CLI, which is there for when the MCP
server is not available. Invoke it with `python -m loredocs.cli` -- the
`loredocs` command itself starts the MCP server, not the CLI. (The separate
`loredocs-cli` package is a different product and does not include this
command.) LoreConvo v0.10.0 gained the matching
`python -m loreconvo.cli license clear`.

### Fixed: Diagnostic messages pointed at commands that do not run

Several messages told you to run `loredocs check-notion`, `loredocs ui`, or
`python3 -m loredocs set-notion-token`. None of those work: `loredocs` is the
MCP server entry point, and the package has no `__main__`, so the second form
errors with "cannot be directly executed". All now give the working form,
`python -m loredocs.cli <command>`.

### Fixed: Security update

Updated the `cryptography` dependency from 49.0.0 to 50.0.0 to pick up a fix
for CVE-2026-69247.

## v0.1.19 (2026-08-04)

### Added: Import from Notion

A new `vault_import_notion` MCP tool (and matching `loredocs import notion` CLI
command) imports Notion pages and databases into a vault. This is an
import-once-and-own model: pages are fetched and stored as LoreDocs documents
at import time, and there is no live sync -- changes made in Notion afterward
do not propagate automatically. Large imports are resumable from a checkpoint
file if interrupted partway through. Requires a Notion integration token,
which can be stored securely in your OS keychain with `loredocs
set-notion-token` (and removed with `clear-notion-token`); `loredocs
check-notion` reports whether your setup is ready to import.

### Changed: Safer startup and logging for the optional admin cap tools

If you run LoreDocs with `LOREDOCS_ENABLE_CAP_TOOLS=1` (the optional admin
tooling, off by default), the server now refuses to start if the required
admin token is missing or weak, instead of running with that protection
silently absent. The admin token is also now redacted from any logging path.
Separately, the schema migration that added per-vault injection caps is more
defensive: it detects and hard-fails on a half-migrated database (documented
in the new `TROUBLESHOOTING.md`) rather than risking silent data corruption.
None of this changes default `vault_inject`/`vault_prime`/`vault_inject_by_tag`
behavior for the normal (non-admin-tooling) usage path.

### Fixed: Free-tier upgrade messages now link to a working checkout page

Hitting a Free-tier limit, or calling `get_tier`/`get_license_tier`, used to
point you at a bare domain or an email address instead of a working upgrade
link. Both now link directly to the Stripe checkout page, and a bug that
silently dropped the upgrade link from three tier-limit error messages is
fixed.

## v0.1.18 (2026-07-31)

### Changed: Tool output format change -- recalled-content trust boundary

`vault_inject`, `vault_prime`, and `vault_inject_by_tag` now wrap the
returned document text in an explicit untrusted-data delimiter (HTML
comment, with a per-call nonce) before returning it, with a provenance
line per document ("vault doc -- unverified authorship", identical
regardless of the document's `priority`).

This is a framing/boundary-integrity fix (SH-13436), not a claim to solve
prompt injection. The injected text format has never been a documented,
stable contract for these tools; any external tooling parsing it
structurally should expect this and future format changes.

## v0.1.17 (2026-07-28)

### Fixed: Idle-watchdog now releases resources cleanly instead of killing the server

The idle-watchdog timeout (30 minutes with no MCP messages) would force-exit the
stdio server process when the timeout fired. Some clients (Claude Desktop, early
Claude Code versions) park stdio servers open while they're idle instead of
closing the pipe when they're done, causing the process to stay open, lock the
database, and leak system resources.

Starting in v0.1.17, the watchdog closes its database connection and drops its
cached Lance semantic-search index, then returns cleanly instead of exiting the
process. The server stays parked, but releases the resources it was holding.
Clients that do close the pipe promptly are not affected. Clients that park the
connection will now stay stable and will not block other Claude instances from
accessing the database.

If you were using the workaround environment variable `LOREDOCS_IDLE_TIMEOUT=86400`
(1 day) to avoid the server exit, you can remove it — the fix handles the timeout
without needing a workaround.

## v0.1.16 (2026-07-26)

### Installs and updates now work the way you would expect

LoreDocs used to run from a Python virtual environment created in the source
tree, or from `uvx loredocs@latest`. Neither pinned what actually ran: `@latest`
resolves against a cache that can be stale, so a server could keep running an
old version indefinitely, and the venv's interpreter is a symlink to a system
Python that breaks if that Python is upgraded or removed.

The plugin now ships a configuration pinned to an exact version, and the server
runs through `uvx` with its own managed Python. Installing or updating the
plugin is what changes your version, and nothing else does. There is no virtual
environment to create, break, or repair.

Leftover packages from an older pip install are harmless and can be ignored.

### Fixed: semantic search and index rebuild were broken for Pro users

`vault_search` with `semantic=true` and `vault_rebuild_index` both failed
outright for anyone on Pro, returning an internal error instead of results.
This affected every Pro user of those two tools and had been present since
v0.1.4. Both work now.

If you are on Pro and semantic search has never returned anything useful, this
is why. Run `vault_rebuild_index` once after upgrading (see below) and it will
start working.

### Fixed: diagnostics no longer hide the reason for a failure

`get_server_info` and the `loredocs-compat-check` command reported that
something was wrong without saying what: the underlying error text was being
discarded. It is now included in the output. A missing `packaging` dependency
was also causing the compatibility check to disable itself silently; that
dependency is now declared, so the check runs and reports a real version.

### One install, every tier: semantic search now works out of the box

Semantic search used to be a separate install step. It needed the `[pro]`
extra, which pulled in PyTorch: a large download, a second environment to keep
up to date, and a common source of "why isn't semantic search working?"

Semantic search now ships in the standard install. The same embedding model as
before (BAAI/bge-small-en-v1.5) runs on ONNX Runtime instead of PyTorch, which
is roughly a third of the download size. There is one install path and one
environment for everyone. Pro is now purely a license flag: nothing extra to
install to unlock it.

`pip install loredocs[pro]` still works and is now equivalent to a plain
install, so existing scripts do not break.

**Recommended one-time step:** run `vault_rebuild_index` after upgrading. The
new runtime produces very slightly different vectors than the old one, so an
index built before this release will gradually drift out of step with documents
added afterwards. Rebuilding brings everything back onto the same footing.
Keyword search is unaffected and needs nothing.

The first semantic search after upgrading downloads the model (about 90MB) and
may take a minute. After that it is cached.

### Updated: MCP SDK

The bundled MCP SDK moves to 1.28.1, which carries fixes for three advisories in
the versions LoreDocs previously pinned (CVE-2026-52870, CVE-2026-52869,
CVE-2026-59950). None of them could affect LoreDocs: all three concern network
transports and a multi-client task feature that LoreDocs does not use, since it
runs over stdio as a single-client local server. The update means a security
scan of your install comes back clean.

## v0.1.15

### Improved: free-tier saves no longer fail at the version-history cap

On the free tier, saving a document that had already reached its version-history
limit used to fail. Now the save always succeeds: LoreDocs removes the oldest
stored version to make room, keeps your latest change, and returns a note that a
version was rotated out. Your current document is never lost. Upgrade to Pro for
unlimited version history.

### Docs: accurate MCP tool listing

The documentation now lists the correct number of MCP tools LoreDocs provides
(46, previously shown as 42), including several that were already available but
missing from the reference, such as previewing the token cost of a vault
injection before spending context on it and reporting the server's injection
capabilities. This part of the release updates documentation only; nothing
changes in how LoreDocs runs.

---

## v0.1.14

### Added: Durable Pro license persistence

Your Pro license is now stored durably in a per-user file
(`~/.loredocs/license.json`, owner-only permissions) instead of depending on an
environment variable being present in every shell. Once activated, Pro persists
across restarts and new sessions. The license is resolved in a stable order: an
environment variable takes precedence, then the file store, and a key supplied
via the environment is written through to the file store automatically so it
survives after the variable goes away. A short grace-period cache keeps Pro
working through brief license-validation outages.

Legacy installs that were granting Pro from an unverified local tier flag now
get a bounded 30-day grace window instead of indefinite access; after that a
verified key is required. (SH-13079)

### Bug Fixes

- **Fixed a false MCP compatibility warning.** The startup compatibility guard
  compared against the wrong pinned version (1.27.0 vs the 1.27.2 constant),
  which could surface a spurious version-mismatch warning on load. The pin and
  the constant now agree. (SH-12969)

---

## v0.1.13

### Security

- **Updated click to 8.3.3 (CVE-2026-7246).** Bumped the `click` dependency
  from 8.3.1 to 8.3.3 to pick up the fix for CVE-2026-7246. No functional or
  API changes; this is a security-only patch release.

---

## v0.1.12

### Bug Fixes

- **Cross-product linking to LoreConvo now works.** Database discovery used a
  single default filename convention (`~/.{product}/{product}.db`) for every
  product, which is correct for LoreDocs (`loredocs.db`) but wrong for LoreConvo
  (which uses `sessions.db`). As a result, every cross-product linking tool
  silently reported "Cross-product linking unavailable" on real installs. Fixed.
  (SH-12757)

- **Stale auto-discovered links are cleaned up automatically.** If a document's
  embedding model changes between saves, cross-product links (LoreDocs <->
  LoreConvo) auto-discovered under the old model are now removed before fresh
  links are written, instead of accumulating alongside them. Manually created
  links are unaffected. (SH-10784)

---

## v0.1.11

### New Features

- **Token-budget injection tools.** `vault_inject`, `vault_prime`, and `vault_inject_by_tag`
  now accept `max_tokens`, `safety_factor`, `cap_behavior`, `session_token`, and
  `max_single_doc_tokens` parameters. Documents are ranked by FTS5 relevance and priority,
  then packed greedily within an effective token cap (`max_tokens * safety_factor`). The
  default cap is 100,000 tokens (configurable via `LOREDOCS_INJECTION_DEFAULT_CAP_TOKENS`).
  Use `cap_behavior="strict"` to error rather than truncate; default is `"best_effort"`.
  (SH-12014 / SH-11800)

- **Per-session injection cache.** Each call to an injection tool with a `session_token`
  uses an in-process LRU cache so repeated calls with the same parameters return
  instantly. Cache entries are invalidated whenever a document in the vault is updated.
  Disabled automatically in multi-worker deployments.

- **Token estimation preview.** New `vault_estimate_tokens` tool shows the estimated
  token count for each document in a vault before you inject, helping you choose a
  suitable `max_tokens` budget. Uses tiktoken (if installed via `loredocs[token-count]`)
  or a char-based fallback.

- **Vault-level injection cap.** New `vault_get_injection_cap` and (admin-gated)
  `vault_set_injection_cap` tools let operators store a per-vault default token cap
  that applies to all injection calls for that vault. Admin operations require
  `LOREDOCS_ENABLE_CAP_TOOLS=1` and a strong `LOREDOCS_ADMIN_TOKEN`.

- **Session token helper.** New `vault_get_session_token` tool returns a UUID to use
  as the `session_token` parameter across injection calls, enabling cache scoping.

- **Server capabilities report.** New `vault_get_server_capabilities` tool reports
  the active token estimator, session cache state, cap settings, and admin token
  configuration.

### Optional dependency

- `loredocs[token-count]` installs `tiktoken==0.7.0` for improved token estimation
  accuracy (+-15% vs +-50% for the char-based fallback).

---

## v0.1.10

### Security

- **Dependency security updates.** `cryptography` is upgraded from 46.0.7 to 49.0.0,
  clearing an OpenSSL advisory (GHSA-537c-gmf6-5ccf). `starlette` is now pinned to
  1.3.1, which clears five advisories. All runtime dependencies are exact-pinned.

### Bug Fixes

- **MCP tools accept flat arguments correctly.** Several LoreDocs MCP tools required a
  nested `{"params": {...}}` wrapper and rejected the flat arguments some clients send.
  Tool signatures are now explicit, so flat arguments work as expected. (SH-11722)

### Reliability

- **WAL journal-mode guardrail.** LoreDocs now detects and refuses to mix SQLite
  journal modes on the same database, avoiding a class of "database is locked" and
  integrity errors. In-memory databases (which cannot use WAL) are exempt.

### Packaging

- License metadata migrated to SPDX form (`BUSL-1.1`).

---

## v0.1.9

Internal packaging release: prepared plugin metadata for the MCP plugin registry
submission (supersedes the brief 0.1.8 packaging build). No user-facing functional
changes.

---

## 2026-05-28 -- v0.1.7

### New Features

- **Cross-product session linking with LoreConvo (Pro).** LoreDocs Pro can now discover and display the LoreConvo sessions most relevant to any vault document, and vice versa. When you save a session in LoreConvo or add a document in LoreDocs, the two products automatically compare content and link the most similar items. Three new MCP tools support this workflow: `vault_link_session` (manually link a session to a document), `vault_get_session_links` (see which sessions relate to a document), and `vault_get_linked_sessions` (see which documents relate to a session). Requires both LoreConvo Pro and LoreDocs Pro to be installed. Cross-product linking can be disabled per-vault via opt-out.

---

## 2026-05-25 -- v0.1.6

### Bug Fixes

- **Upgrading to v0.1.5 could prevent the server from starting if your vault had auto-discovered related-document links.** The v0.1.5 schema migration introduced a UNIQUE constraint on `doc_links` but applied it before deduplicating the pre-existing rows, so vaults that already had keyword co-occurrence links (added in v0.1.2) crashed with a SQLite integrity error on startup. The migration now runs the dedupe pass first and covers all auto-generated link types, not just embedding links. If you hit the v0.1.5 crash, upgrading to v0.1.6 resolves it automatically -- no manual cleanup needed.

---

## 2026-05-22 -- v0.1.5

### New Features

- **Auto-discovered embedding-based document relationships for Pro users.** LoreDocs Pro now builds `auto:embedding` links between documents whose semantic embeddings are similar above a configurable threshold, in addition to the keyword co-occurrence links from v0.1.2. Surfaced through `vault_find_related`. (SH-10529 Phase 2a)

---

## 2026-05-16 -- v0.1.4

### New Features

- **Open any project folder as a vault with `vault_open_workspace`.** You can now point LoreDocs at a directory on your filesystem and it will automatically create or locate the vault associated with that workspace. This makes it easier to work across multiple projects: instead of managing vault names manually, tell LoreDocs where your project lives and it handles the mapping. The workspace path is stored so future sessions in the same directory pick up the right vault automatically.

---

## 2026-05-15 -- v0.1.3

### New Features

- **Semantic search for Pro users.** LoreDocs Pro now supports hybrid semantic search: documents are indexed using BGE-small embeddings in a chunk-aware LanceDB index, and searched using a combination of vector similarity and BM25 full-text with RRF fusion. Documents are split at paragraph boundaries (up to 256 tokens per chunk) before indexing, so a query for a specific concept finds the right document even if that concept only appears in one section. If the semantic index is not available, search falls back to FTS5 automatically. Install with `pip install loredocs[pro]` to enable.

- **`vault_rebuild_index` tool.** Build or rebuild the semantic search index on demand. Run this after installing the Pro dependencies for the first time, or after importing a large batch of documents that were added before Pro was enabled. Progress is logged so you can see which documents are being indexed.

---

## 2026-05-14 -- v0.1.2

### New Features

- **LoreDocs now automatically discovers related documents.** When you save or update a document, LoreDocs analyzes keyword co-occurrence across your vault to identify documents that are topically related. The `vault_find_related` tool surfaces these connections without any manual linking required -- useful for discovering relevant context you might have forgotten was there.

- **`vault_import_dir` now imports entire directory trees recursively.** Previously, `vault_import_dir` only imported files directly inside the specified folder. It now traverses subdirectories, so you can point it at the root of a project and import your entire documentation tree in one operation. Files with YAML frontmatter (such as Obsidian notes or Jekyll posts) have their `tags` field extracted automatically and applied to the imported document.

---

## 2026-04-18

### Bug Fixes

- **Vault and document info no longer crashes when tags contain commas.** If a vault or document was saved with tags in the older comma-separated format (for example, `"python,sqlite"` instead of a proper list), running `query_loredocs.py --info` would crash with a parse error. This is now fixed. Both the new JSON list format and the legacy comma-separated format are handled automatically.

### New Features

- **One-time tag migration utility for legacy data.** If you have vaults or documents with comma-separated tags from an older version of LoreDocs, you can now convert them to the current format in one step. Run the admin script with the `--migrate-tags` flag:

  ```
  python ron_skills/loredocs/scripts/query_loredocs.py --migrate-tags
  ```

  The script reports how many tags it converted. You only need to run this once if you used LoreDocs before the tag format was standardized. New installs are not affected.

### Improvements

- **Search index stays in sync when you update or delete documents.** Previously, if a document was updated or deleted outside of normal LoreDocs usage (for example, by a direct database write or a future sync tool), the internal search index could silently fall out of date -- meaning searches might return stale results or results for documents that no longer exist. LoreDocs now uses database-level triggers to keep the search index consistent whenever a document changes, matching the approach already used by LoreConvo. This is an internal reliability improvement and is transparent to all users.

---

## 2026-04-13

### Improvements

- **Bulk tagging is now faster and more reliable.** When you tag multiple documents at once using `vault_bulk_tag`, LoreDocs now applies all changes in a single database transaction instead of opening and committing one transaction per document. This makes bulk operations noticeably faster when tagging large sets of documents and ensures that all changes succeed or fail together -- no partial updates if something goes wrong mid-operation.

- **Faster document link lookups.** A new database index speeds up queries that follow document-to-document links. If your vault has many linked documents, operations like `vault_find_related` now return faster.

---

## 2026-04-08

### Bug Fixes

- **Vault queries now work reliably in Cowork.** Previously, when running inside a Cowork VM, the fallback query script (`query_loredocs.py`) could look for your vault database in a temporary directory that disappears when the VM ends -- meaning queries returned no results even though your vaults existed on your Mac. The script now checks your persistent mounted data path first and only falls back to the local VM directory if no persistent path is found. If you have been running agents in Cowork and queries seemed to return nothing, update to this version to resolve it.

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

LoreDocs v0.1.0 established the core architecture: SQLite+FTS5 storage, 36 MCP tools for vault and document management, file import/export, full-text search, version history, tagging, and context injection.
