# LoreDocs Architecture Review

**Product:** LoreDocs v0.1.0 (ALPHA)
**Reviewer:** Gina, Enterprise Architect
**Date:** 2026-04-04
**Scope:** Full architecture review -- code structure, database design, API surface, security architecture, scalability, CLI design, tier/licensing, test coverage

---

## Executive Summary

LoreDocs is an ambitious knowledge management product with a well-designed architecture that is more mature than its v0.1.0 version number suggests. The codebase is substantial (~2,800 lines across server.py and storage.py) and demonstrates strong engineering practices: Pydantic input validation on every MCP tool, connection-per-operation database access, proper async lifespan management, comprehensive tier enforcement, and FTS5 query sanitization.

The architecture is built for growth -- the vault/document/version hierarchy maps naturally to both local storage and future cloud sync. The dual storage model (SQLite for metadata + filesystem for document content) is a pragmatic choice that makes backups trivial and keeps the database lean.

The main concerns are: (1) the vault_set_tier tool can bypass license validation entirely, (2) the import_directory function accepts user-provided filesystem paths with limited traversal protection, (3) some MCP tools duplicate functionality unnecessarily, and (4) no CLI exists yet (critical for agent workflows). None are blockers for the alpha release.

**Overall Assessment:** STRONG -- well-architected for growth, with a few security items to address before public release.

---

## Strengths

1. **Pydantic input validation on every tool.** Every MCP tool uses a BaseModel input class with Field validators: min_length, max_length, regex patterns, enum constraints, and strip_whitespace. This is exemplary and should be the standard for all Lore products. (server.py throughout)

2. **Connection-per-operation pattern.** The `_db()` context manager (storage.py, lines 250-263) opens and closes connections per operation with proper commit/rollback. This is correct for a multi-client SQLite database and prevents the lock contention issues that plague LoreConvo.

3. **Comprehensive tier enforcement.** TierEnforcer (tiers.py) checks four dimensions (vault count, doc count, storage bytes, version count) with clear error messages and upgrade hints. The enforcer is called at every write path in storage.py. The `status_dict()` method provides a clean dashboard view.

4. **FTS5 query sanitization.** `_sanitize_fts_query` (storage.py, line 798-803) wraps user queries in double quotes to force phrase matching, preventing FTS5 operator injection. LoreConvo should adopt this pattern.

5. **Proper async lifespan.** The `app_lifespan` context manager (server.py, lines 32-38) initializes VaultStorage once and shares it across all tools via lifespan context. This is the correct FastMCP pattern.

6. **MCP tool annotations.** Every tool has readOnlyHint, destructiveHint, idempotentHint, and openWorldHint annotations (server.py throughout). These help LLMs make better tool selection decisions.

7. **Dual storage model.** SQLite for metadata + filesystem for document content (storage.py, lines 6-18). This means the database stays small (just metadata and FTS index), documents can be any format (including binary), and backups are as simple as copying a directory.

8. **Path traversal protection.** The `add_document` method (storage.py, lines 476-480) validates filenames against path traversal attacks: rejects `..`, null bytes, absolute paths, and directory separators. This was tagged OPP-006, indicating it came from the security review pipeline.

9. **Rich text extraction.** The `extract_text` helper (storage.py, lines 58-136) supports PDF, DOCX, XLSX, PPTX, and many text formats. The try/except pattern around each library import means missing optional dependencies degrade gracefully.

10. **Schema migrations.** `_migrate_db` (storage.py, lines 213-224) applies incremental, idempotent migrations on every startup. This is the right approach for a local-first product that doesn't have a formal migration framework.

---

## Concerns

### HIGH Severity

#### H1: vault_set_tier bypasses license validation entirely
**File:** `loredocs/server.py`, lines 1386-1418 and `loredocs/tiers.py`, lines 126-132
**Issue:** The `vault_set_tier` MCP tool calls `set_tier(storage.root, params.tier)` which directly writes `{"tier": "pro"}` to config.json. There is NO license key validation in this path. The docstring even acknowledges this: "Note: In a future release this will verify a license key. For now it trusts the caller."

This means any user (or any LLM invoking the tool) can call `vault_set_tier(tier='pro')` and instantly unlock Pro features without a license key.

The get_tier() function (tiers.py, line 99-123) does check `is_pro_licensed()` first, but if that returns False, it falls back to reading config.json -- which vault_set_tier writes to directly. So the flow is: vault_set_tier writes "pro" to config.json -> get_tier reads config.json -> returns "pro" -> all limits removed.
**Risk:** Complete bypass of the revenue model. Any free-tier user can unlock Pro by calling one MCP tool.
**Recommendation:** vault_set_tier must validate a license key before persisting "pro" to config.json. Either:
  (a) Add a `license_key` parameter to vault_set_tier and validate it before calling set_tier, or
  (b) Remove vault_set_tier entirely and make tier determination solely based on the LOREDOCS_PRO environment variable (which is the pattern LoreConvo uses).

Option (b) is simpler and eliminates the attack surface. **BROCK-REVIEW:** This is the highest-priority security finding in either product. Tier bypass means free users get Pro features.

#### H2: import_directory accepts arbitrary filesystem paths
**File:** `loredocs/server.py`, lines 1004-1038 and `loredocs/storage.py` (import_directory method)
**Issue:** The `vault_import_dir` MCP tool accepts an absolute directory path from the LLM and reads all files from it. While individual filenames are validated against traversal, the directory path itself is not restricted. An LLM could be prompted to call `vault_import_dir(directory="/etc")` or `vault_import_dir(directory="/Users/debbie/.ssh")`.
**Risk:** An LLM with access to this tool could exfiltrate sensitive files by importing them into a vault, where they become searchable and readable via other vault tools. This is a trust boundary issue -- MCP tools receive input from LLMs, which can be manipulated by prompt injection.
**Recommendation:** Add an allowlist of importable directories (e.g., only paths under the user's home directory or project directories). Or add a `confirm` parameter like vault_delete has, requiring explicit confirmation before importing from a directory. **BROCK-REVIEW:** Evaluate the risk of filesystem traversal via import_directory in a prompt injection scenario.

#### H3: vault_export writes to arbitrary filesystem paths
**File:** `loredocs/server.py`, lines 1048-1068
**Issue:** Similar to H2, `vault_export` accepts an absolute path for the output directory. An LLM could be directed to export to sensitive locations (e.g., overwriting files in ~/.ssh/ or ~/projects/).
**Risk:** File overwrite attacks via prompt injection.
**Recommendation:** Same mitigations as H2: allowlist directories or require confirmation.

### MEDIUM Severity

#### M1: No CLI exists yet
**File:** N/A (missing)
**Issue:** LoreDocs has 34 MCP tools but no CLI. The CLAUDE.md notes this is planned but not yet implemented. For agent workflows (scheduled tasks, scripts), the only access path is via MCP tools, which requires a running Claude session.
**Risk:** Agents like Ron and Meg that need to interact with LoreDocs outside of MCP context (e.g., in scheduled tasks) must fall back to scripts that use raw SQLite access, bypassing all the nice tier enforcement and validation.
**Recommendation:** This is the #1 TODO in the repo CLAUDE.md for good reason. Use LoreConvo's CLI (Click-based, 6 commands) as the template. Priority commands: vault-list, vault-info, vault-add-doc, vault-search, vault-export.

#### M2: Tool count is large (34 tools) -- potential for LLM confusion
**File:** `loredocs/server.py`, all 34 @mcp.tool definitions
**Issue:** 34 MCP tools is a large surface area for an LLM to navigate. Some tools have overlapping or subtly different purposes:
- `vault_info` vs `vault_inject_summary` -- both return vault metadata in markdown
- `vault_search` vs `vault_search_by_tag` -- both search, one by text and one by tag
- `vault_inject` vs `vault_inject_by_tag` vs `vault_inject_summary` -- three inject variants
- `vault_categorize` vs updating category via `vault_update_doc`
- `vault_set_priority` vs updating priority via `vault_update_doc`
**Risk:** LLMs may choose the wrong tool or be confused by similar options. Each additional tool adds latency to tool selection.
**Recommendation:** Consider consolidating:
  - Merge vault_categorize and vault_set_priority into vault_update_doc (they already delegate to it)
  - Merge vault_inject_by_tag and vault_inject_summary into vault_inject with optional parameters
  - This would reduce the tool count to ~29-30 without losing any functionality

#### M3: Soft-deleted documents remain on disk
**File:** `loredocs/storage.py`, lines 671-681
**Issue:** `remove_document` sets `deleted=1` in the database and removes the FTS entry, but does NOT delete the files from disk (the vault/{id}/docs/{doc_id}/ directory with current file, metadata.json, extracted.txt, and version history). This is a soft delete by design (the docstring says "can be recovered"), but there is no "hard delete" or "purge" command for individual documents.
**Risk:** Storage leak -- users who soft-delete many documents will see no storage reduction. The free-tier storage check (`check_storage`) only counts non-deleted documents in the DB, but the files remain on disk.
**Recommendation:** Either (a) add a `vault_purge_doc` tool that physically removes files for soft-deleted documents, or (b) have vault_delete (which does remove files) also clean up soft-deleted docs. At minimum, document the behavior so users know soft-delete doesn't free disk space.

#### M4: bulk_tag opens N separate database connections
**File:** `loredocs/storage.py`, lines 938-946
**Issue:** `bulk_tag` iterates over doc_ids and calls `tag_document` for each one. Each `tag_document` call opens its own database connection via `_db()` context manager. For 100 documents, that's 100 separate connect/commit/close cycles.
**Risk:** Slow performance for batch operations. Each connection open/close has overhead.
**Recommendation:** Refactor bulk_tag to open one connection and process all documents within a single transaction.

#### M5: FTS content_rowid configuration may be incorrect
**File:** `loredocs/storage.py`, lines 190-198
**Issue:** The doc_fts FTS5 table is created with `content_rowid='rowid'` but it is NOT a content= table (it stores its own content). This means the content_rowid parameter is misleading -- it doesn't actually reference the documents table's rowid. The FTS table has its own doc_id, vault_id, name, content, tags, notes columns and manages its own content independently.

Additionally, FTS entries are managed manually (INSERT/DELETE in add_document, update_document, remove_document, tag_document) rather than via triggers. This means any direct SQL access to the documents table (e.g., from a future CLI) that doesn't also update doc_fts will leave the index stale.
**Risk:** FTS index could become out of sync with the documents table if any code path modifies documents without updating doc_fts.
**Recommendation:** Either (a) switch to a content= table with triggers (like LoreConvo does), which auto-syncs, or (b) extract all FTS operations into a single helper method that both storage.py and any future CLI must call.

### LOW Severity

#### L1: Vault IDs are truncated UUIDs
**File:** `loredocs/storage.py`, line 296
**Issue:** `vault_id = str(uuid.uuid4())[:12]` truncates UUIDs to 12 characters. Similarly, doc IDs are truncated to 12 characters (line 492). While 12 hex characters provide ~2^48 unique values (280 trillion), this is less collision-resistant than full UUIDs.
**Risk:** Negligible for local use. Could become an issue with cloud sync across many users.
**Recommendation:** Low priority. Keep truncated IDs for now (they're more user-friendly in CLI output) but use full UUIDs when implementing cloud sync.

#### L2: No rate limiting on vault_import_dir
**File:** `loredocs/server.py`, lines 1004-1038
**Issue:** A single import_directory call can import an unlimited number of files. If pointed at a large directory (thousands of files), it will attempt to process all of them.
**Recommendation:** Add a max_files parameter (default 100) to prevent accidental bulk imports.

#### L3: extract_text silently swallows exceptions
**File:** `loredocs/storage.py`, lines 58-136
**Issue:** Each format handler wraps its extraction in a try/except that returns empty string on any error. This means extraction failures are invisible -- a corrupted PDF or a DOCX that requires a newer python-docx will silently produce no searchable text.
**Recommendation:** Log extraction failures to stderr or a diagnostic log so users can identify documents that weren't properly indexed.

---

## Security Architecture

### Transport Security
**Assessment: ADEQUATE**
Same as LoreConvo -- stdio transport, no network exposure. The `mcp.run()` call (line 1427) uses default stdio transport.

### Data at Rest
**Assessment: ADEQUATE for current deployment, NEEDS ATTENTION for cloud sync**
Documents are stored as plaintext files on disk. The SQLite database contains metadata in plaintext. For a local-first single-user product, this is fine -- the OS file permissions provide sufficient protection.

**BROCK-REVIEW:** LoreDocs stores actual document content (which could include sensitive business documents, contracts, financial data). If cloud sync is added, at-rest encryption of the vaults/ directory becomes important. Consider AES-256 encryption of document files with a key derived from the user's license key or a separate encryption passphrase.

### Data Access Patterns
**Assessment: GOOD**
All access goes through VaultStorage, which enforces tier limits, validates inputs, and manages transactions. There is no hook or script that bypasses this layer (unlike LoreConvo). This is the correct architecture.

**Future CLI concern:** When the CLI is built, it MUST use VaultStorage (not raw SQLite) to maintain this property.

### Tier Enforcement
**Assessment: COMPROMISED by vault_set_tier (see H1)**
The TierEnforcer class is well-designed and enforced at every write path in storage.py. However, the vault_set_tier MCP tool allows any caller to set tier=pro without license validation, completely bypassing the enforcement.

If vault_set_tier is fixed (either removed or gated behind license validation), the tier enforcement architecture is sound.

### License Key Architecture
**Assessment: SOUND (identical to LoreConvo)**
Same Ed25519 signing scheme, same public key, same dev bypass mechanism. See LoreConvo review for details.

### Input Trust Boundaries
**Assessment: GOOD with exceptions**
- MCP tools: Excellent Pydantic validation on all inputs.
- Filesystem paths: import_directory and vault_export accept arbitrary paths (see H2, H3).
- FTS5: Properly sanitized (see Strength #4).
- Document content: No validation on content size at the MCP layer (only MAX_FILE_SIZE check in storage.py).

### Future Cloud Sync Risk
The vault/document/version hierarchy is well-suited for sync:
- Vault IDs and doc IDs are globally unique (even if truncated)
- Version history is file-based and append-only
- Metadata is in SQLite (would need CRDT or vector clock for conflict resolution)
- The _db() context manager pattern means connections are short-lived (good for sync)

**Key risk:** The FTS index is local-only and cannot be synced. It would need to be rebuilt on each device after sync. This is fine but should be planned for.

---

## Scalability

**Vault/document limits:** Free tier caps at 3 vaults / 50 docs each. Pro is unlimited. SQLite can handle thousands of documents per vault without issue.

**FTS5 performance:** The manual FTS management (INSERT/DELETE per operation) works but is slower than trigger-based auto-sync for bulk operations. For import_directory with 100+ files, FTS indexing is done per-file in separate transactions.

**File system:** At 10,000+ documents, the flat docs/{doc_id}/ directory structure under each vault could slow down directory listings on some filesystems. Consider a two-level hash structure (e.g., docs/ab/abc123/) for future scalability.

**Database size:** With document content stored on disk (not in SQLite), the database stays lean. The FTS index stores extracted text, which could grow large for vaults with many PDFs/DOCXs. No immediate concern.

---

## Tier/Licensing UX

**Strengths:**
- Clear error messages with upgrade hints on every tier limit
- `vault_tier_status` tool provides a clean dashboard view with percentages
- `status_dict()` returns structured data for programmatic use

**Concerns:**
- The vault_set_tier tool's comment "In a future release this will verify a license key. For now it trusts the caller" should not ship in a public release (see H1)
- There is no CLI command to check tier status (blocked on CLI not existing yet)
- The upgrade path is not documented from the user's perspective (how do they purchase? where do they set the key?)

---

## Cross-Product Consistency

| Aspect | LoreConvo | LoreDocs | Winner |
|--------|-----------|----------|--------|
| Input validation | Raw Python types | Pydantic BaseModel | LoreDocs |
| DB connections | Single long-lived | Context manager per-op | LoreDocs |
| FTS5 sanitization | Basic escaping | Phrase-wrapping | LoreDocs |
| MCP annotations | None | Full set on all tools | LoreDocs |
| Tier enforcement | Database-layer only | TierEnforcer class + storage-layer | LoreDocs |
| Async | Sync tools | Async tools | LoreDocs |
| Lifespan | Global instance | Proper lifespan context | LoreDocs |
| CLI | 6 commands | None | LoreConvo |
| Hooks (auto-save/load) | Yes (2 hooks) | None | LoreConvo |
| FTS sync | Trigger-based (auto) | Manual (per-operation) | LoreConvo |
| License module | Near-identical | Near-identical | Tie (should be shared) |
| Test files | 14 files | 5 files | LoreConvo |

**Divergences that should be standardized:**
1. License modules are near-identical -- extract shared package
2. Error return format differs (dicts vs strings)
3. Logging approach differs (stderr in hooks vs silent in server)
4. Both products should use Pydantic input validation
5. Both products should use connection-per-operation pattern

---

## Test Coverage Assessment

**5 test files:**
- test_mcp_tools.py -- 43 tests covering MCP tool layer (vault CRUD, doc CRUD, search, tags, tiers, inject, linking)
- test_tier_integration.py -- 29 tests covering tier enforcement end-to-end
- test_storage.py -- storage layer unit tests
- test_tiers.py -- tier limit calculations and enforcement
- test_phase2.py -- phase 2 features (doc linking, suggestions, export manifest)

**Strengths:**
- MCP tool tests actually invoke the async tool handlers with mock contexts
- Tier integration tests verify enforcement at every write path
- Good coverage of edge cases (empty vaults, missing documents, duplicate tags)

**Missing test coverage:**
- License key validation (no test_license.py -- LoreConvo has one)
- Path traversal in import_directory / vault_export
- FTS5 search with special characters
- Large vault performance (100+ documents)
- Concurrent access patterns
- Text extraction from various formats (PDF, DOCX, XLSX, PPTX)
- Soft-delete and recovery workflows
- vault_set_tier tier bypass (see H1)

---

## Prioritized Recommendations

1. **[HIGH] Fix vault_set_tier tier bypass (H1)** -- Either remove the tool or gate it behind license key validation. This is the single most important fix before any public release.

2. **[HIGH] Restrict filesystem paths in import/export (H2, H3)** -- Add directory allowlisting or confirmation prompts to vault_import_dir and vault_export.

3. **[MEDIUM] Build CLI (M1)** -- Use LoreConvo's Click-based CLI as template. Priority commands: list, info, add-doc, search, export.

4. **[MEDIUM] Consolidate overlapping MCP tools (M2)** -- Reduce from 34 to ~29-30 by merging categorize/set_priority into update_doc and consolidating inject variants.

5. **[MEDIUM] Fix bulk_tag connection overhead (M4)** -- Single-transaction batch processing.

6. **[MEDIUM] Add purge mechanism for soft-deleted docs (M3)** -- Physical file cleanup.

7. **[MEDIUM] Switch FTS to trigger-based sync (M5)** -- Adopt LoreConvo's trigger pattern for consistency and reliability.

8. **[LOW] Add license key tests** -- Port LoreConvo's test_license.py with appropriate product name changes.

9. **[LOW] Add extraction failure logging (L3)** -- Log to stderr when text extraction fails for a document.

10. **[LOW] Extract shared license module** -- Deduplicate the near-identical license.py files.
