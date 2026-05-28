# LoreDocs Changelog

What changed in each release, written for users (not developers).

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
