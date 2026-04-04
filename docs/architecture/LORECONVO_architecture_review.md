# LoreConvo Architecture Review

**Product:** LoreConvo v0.3.0 (PRODUCTION)
**Reviewer:** Gina, Enterprise Architect
**Date:** 2026-04-04
**Scope:** Full architecture review -- code structure, database design, API surface, security architecture, scalability, CLI design, tier/licensing, test coverage

---

## Executive Summary

LoreConvo is a well-architected, focused product that does one thing and does it well: persistent session memory for Claude. The codebase is clean, compact (~600 lines of core logic across 4 modules), and follows sound local-first design principles. The separation between MCP server, CLI, database, and hooks is clear and maintainable.

The architecture is solid for its current scale and single-user deployment. The main concerns center around: (1) the auto_save hook bypassing the core database layer and duplicating schema definitions, (2) no shared data access layer between MCP server, CLI, and hooks, (3) FTS5 query injection risk in search_sessions, and (4) missing input validation on MCP tool parameters. None of these are critical for the current local-only deployment, but several become important as the product grows toward multi-user or cloud scenarios.

**Overall Assessment:** SOLID -- ready for production use in its current single-user local context. The architecture needs targeted hardening before cloud sync or team features.

---

## Strengths

1. **Clean module structure.** Four core modules (server.py, database.py, models.py, config.py) with clear single responsibilities. The server is a thin MCP adapter over the database layer. No circular dependencies.

2. **Effective FTS5 integration.** The sessions_fts virtual table with triggers for auto-indexing on INSERT/UPDATE/DELETE is textbook correct. The content= and content_rowid= configuration keeps the FTS table in sync with the source table automatically.

3. **Smart auto-load hook.** The scoring system in auto_load.py (open_questions +3, decisions +2, artifacts +1, recency bonuses) is well-designed. The 4000-char context cap prevents system prompt bloat. Filtering noise sessions (score <= 0) while keeping at least some results is a good UX decision.

4. **Robust JSON field parsing.** The `_parse_json_field` method in database.py (lines 546-574) gracefully handles three storage formats: JSON arrays, legacy comma-separated strings, and plain text blobs. This backward compatibility is important for a product that has real user data.

5. **Good deduplication in auto_save.** Using Claude's session_id as the primary key (line 191) and checking for existing records before insert prevents duplicate hook fires from creating ghost sessions. The comment on lines 189-191 even documents the previous bug and fix.

6. **Dataclass models with sensible defaults.** UUID auto-generation, ISO timestamps, empty list defaults -- all reduce the surface area for bugs in callers.

7. **Comprehensive test suite.** 14 test files covering: database operations, CLI commands, auto-load/auto-save hooks, license validation, session limits, gitignore safety, plugin JSON structure, onboarding, and skills sync. This is unusually thorough for a v0.3 product.

8. **Ed25519 license key design.** Offline-verifiable, cryptographically signed, with product scoping and expiry. The dev bypass (LAB_DEV_MODE=1) is properly gated behind a second environment variable that is excluded from public .mcp.json files.

---

## Concerns

### HIGH Severity

#### H1: auto_save.py duplicates schema and bypasses the core database layer
**File:** `hooks/scripts/auto_save.py`, lines 150-177 vs `src/core/database.py`, lines 22-89
**Issue:** auto_save.py defines its own `ensure_tables()` function with a CREATE TABLE schema that diverges from database.py's SCHEMA_SQL. The auto_save schema is missing columns (`created_at` has a different default, no `session_skills.skill_source`, no `session_skills.invocation_count`, different PRIMARY KEY definitions on session_skills). It also creates its own FTS table with a slightly different definition. When auto_save writes to the database, it bypasses all validation in SessionDatabase (e.g., the session limit check, the id-not-None guard).
**Risk:** Schema drift between the two codepaths can cause subtle bugs. The BSL free-tier session limit (50 sessions) is NOT enforced by auto_save -- a free-tier user accumulating sessions via hooks will silently exceed the limit.
**Recommendation:** Refactor auto_save.py to import and use `SessionDatabase` from `core.database` (or a shared lightweight write path). If import weight is a concern for the hook timeout, extract a minimal `save_session_fast()` function in core that both paths can use. At minimum, the session limit check must be present in auto_save.

#### H2: FTS5 query injection in search_sessions
**File:** `src/core/database.py`, line 209
**Issue:** The search query is passed to FTS5 MATCH with only double-quote escaping (`query.replace('"', '""')`). FTS5 supports operators like AND, OR, NOT, NEAR, column filters (e.g., `title:secret`), and prefix matching (*). A malicious or accidental query like `title:* OR summary:*` could return all sessions. While this is a single-user local product, it's still a correctness issue -- users typing natural queries with AND/OR will get unexpected results.
**Risk:** Unexpected search results, potential information disclosure if the product ever becomes multi-user.
**Recommendation:** Apply the same sanitization strategy LoreDocs uses: wrap the query in double quotes to force phrase matching (`_sanitize_fts_query` in LoreDocs storage.py, line 798-803). This is a one-line fix that makes search behavior predictable. **BROCK-REVIEW:** Evaluate whether FTS5 operator injection could be exploited in a future multi-tenant scenario.

#### H3: No input validation on MCP tool parameters
**File:** `src/server.py`, all @mcp.tool functions
**Issue:** MCP tool parameters are accepted as raw Python types (str, int, list) with no validation. There are no length limits on title, summary, or tags. There is no validation that surface is one of the expected values ('cowork', 'code', 'chat'). There is no check that session_id is a valid UUID format. Compare this to LoreDocs, which uses Pydantic BaseModel with Field validators, min_length, max_length, and enum constraints for every tool.
**Risk:** An LLM could pass arbitrarily long strings (consuming storage), invalid surface values (breaking analytics), or malformed UUIDs (causing confusing errors). This is especially relevant because MCP tools receive input from LLMs, which can hallucinate parameter values.
**Recommendation:** Add Pydantic input models to all MCP tools, matching LoreDocs' pattern. At minimum: validate surface against an enum, add max_length to title (200) and summary (10000), validate session_id format in get_session/tag_session/link_sessions.

### MEDIUM Severity

#### M1: Single long-lived database connection (no connection pooling or context manager)
**File:** `src/core/database.py`, line 96-97
**Issue:** SessionDatabase opens one connection in `__init__` and keeps it for the entire server lifetime. Every method uses `self.conn` directly. There is no connection context manager, no retry logic, and no protection against SQLite "database is locked" errors from concurrent access.
**Risk:** If the CLI, auto_save hook, and MCP server all access the same SQLite database concurrently (which they do), WAL mode helps but does not eliminate all lock contention. A long-running MCP query could block a time-sensitive hook from saving. Compare to LoreDocs, which uses a `_db()` context manager that opens/closes connections per operation.
**Recommendation:** Adopt LoreDocs' connection-per-operation pattern with a `_db()` context manager. This is the single most impactful cross-product consistency improvement. It also makes the code more resilient to connection corruption and simplifies future connection pooling.

#### M2: auto_load.py opens a raw SQLite connection instead of using the core database layer
**File:** `hooks/scripts/auto_load.py`, line 107
**Issue:** Like auto_save, auto_load opens its own raw sqlite3 connection and writes raw SQL. It does not use `SessionDatabase` or even import from core.
**Risk:** Any change to the sessions table schema requires updating three places: database.py, auto_save.py, and auto_load.py. This is a maintenance burden and a source of bugs.
**Recommendation:** Either import core.database (preferred) or extract a shared read-only query helper that both auto_load and CLI can use.

#### M3: No WAL checkpoint management
**File:** `src/core/database.py`, line 98
**Issue:** WAL mode is enabled (`PRAGMA journal_mode=WAL`) but there is no periodic checkpoint. SQLite auto-checkpoints at 1000 pages by default, but if the process is long-running (as an MCP server is), the WAL file can grow large.
**Risk:** Over months of use, the WAL file could grow to tens of MB, slowing down reads and consuming disk space unnecessarily.
**Recommendation:** Add a periodic `PRAGMA wal_checkpoint(TRUNCATE)` -- either on server startup or after every N writes (e.g., every 100 session saves).

#### M4: get_session_chain has no depth limit
**File:** `src/core/database.py`, lines 316-339
**Issue:** The BFS traversal in `get_session_chain` has cycle detection (`chain_ids` set) but no depth limit. If a user creates a long chain of linked sessions (hundreds of links), this will follow the entire chain, loading every session individually via `get_session()` (one query per session).
**Risk:** Performance degradation with large link chains. Each `get_session()` call is a separate query.
**Recommendation:** Add a `max_depth` parameter (default 50) and a `LIMIT` on the initial link query. Consider fetching all linked sessions in a single query rather than N+1 individual queries.

#### M5: Suggestions sorting is inverted
**File:** `src/core/database.py`, line 520
**Issue:** `suggestions.sort(key=lambda s: (s["priority"], s["date"]))` sorts by priority ascending (1 before 2) which is correct, but then by date ascending, meaning older sessions appear first within the same priority tier. This is counterintuitive -- within open_questions (priority 1), you'd want the most recent unresolved questions first.
**Risk:** Users see stale open questions before recent ones, reducing the usefulness of vault_suggest.
**Recommendation:** Change to `suggestions.sort(key=lambda s: (s["priority"], s["date"]), reverse=False)` for priority but reverse date within each priority group. Or use a tuple key: `(s["priority"], -timestamp)`.

### LOW Severity

#### L1: Hardcoded "code" surface in auto_save
**File:** `hooks/scripts/auto_save.py`, line 225
**Issue:** All auto-saved sessions are tagged with surface="code" regardless of where they actually ran. If the hook fires from a Cowork session, the surface will be wrong.
**Recommendation:** Try to detect the actual surface from hook metadata, or default to "auto" rather than "code".

#### L2: No graceful handling of missing cryptography library
**File:** `src/core/license.py`, line 57
**Issue:** `_load_public_key()` imports `cryptography.hazmat.primitives.asymmetric.ed25519` at call time. If the cryptography package is not installed, this raises an ImportError that propagates as an unhandled exception.
**Recommendation:** Wrap the import in a try/except and return a clear error message ("Install the 'cryptography' package to validate license keys") or gracefully degrade to free tier.

#### L3: list_projects does N+1 queries
**File:** `src/core/database.py`, lines 389-402
**Issue:** `list_projects()` fetches all projects, then issues one COUNT query per project. With many projects, this is O(N) queries.
**Recommendation:** Use a single query with LEFT JOIN and GROUP BY.

---

## Security Architecture

### Transport Security
**Assessment: ADEQUATE for current deployment**
stdio transport is the right choice for a local MCP server. There is no network exposure -- the server communicates only with the host Claude Code/Cowork process via standard pipes. No TLS configuration is needed.

**Future risk:** If SSE transport is added for remote access, TLS and authentication would need to be implemented. The current architecture has no auth layer at all (expected for stdio).

### Data at Rest
**Assessment: ADEQUATE for single-user local deployment**
The SQLite database at ~/.loreconvo/sessions.db contains all session data in plaintext. File permissions are inherited from the user's home directory (typically 700). There is no encryption.

**BROCK-REVIEW:** Evaluate whether session data (which may contain code snippets, architectural decisions, and internal project details) warrants at-rest encryption for users in regulated industries. For the current single-user local deployment, the OS-level file permissions are sufficient, but this should be revisited before cloud sync.

### Data Access Patterns
**Assessment: NEEDS IMPROVEMENT**
Three separate code paths access the same SQLite database:
1. MCP server (via SessionDatabase class with full validation)
2. CLI (via SessionDatabase class with full validation)
3. Hooks (via raw sqlite3 connections with no validation)

The hooks bypass all business logic (session limits, id validation). This is the most significant architectural gap in the product.

### Tier Enforcement
**Assessment: PARTIALLY ENFORCED**
The BSL 1.1 free-tier session limit (50 sessions) is enforced in `SessionDatabase.save_session()` but NOT in `auto_save.py`'s `save_to_db()`. A free-tier user who never manually saves sessions but relies on auto-save hooks will accumulate unlimited sessions.

### License Key Architecture
**Assessment: SOUND**
Ed25519 signing with an embedded public key is a good choice for offline-verifiable license keys. The key format (LAB-{payload}.{signature}) is clean and parseable. The dev bypass requires a second env var (LAB_DEV_MODE) that is excluded from public distributions.

**Minor concern:** Both LoreConvo and LoreDocs embed the same public key (`_LAB_PUBLIC_KEY_B64 = "2Y++SKM6ZVAz1T8f0EGinoLWlQ9wdZFwEelAYDb1hT0="`). This means a single private key signs licenses for both products. The product field in the payload differentiates them, which is fine, but it means a compromise of the signing key affects both products simultaneously. This is acceptable for the current scale.

### Input Trust Boundaries
**Assessment: MIXED**
- MCP tools: No input validation (see H3). LLM-generated inputs are trusted without sanitization.
- CLI: Click handles basic type coercion and required fields, but no length limits or format validation.
- Hooks: Parse JSONL transcripts with basic error handling but trust file paths from hook metadata.
- FTS5: Vulnerable to operator injection (see H2).

### Future Cloud Sync Risk
If Team tier adds cloud sync:
- Session data will need encryption in transit and at rest
- The single SQLite file model will need conflict resolution (CRDT or last-write-wins)
- The hook's direct database access will become a race condition hazard
- Session IDs (UUIDs) are already globally unique, which is good for sync

---

## Scalability

**Current limits:** SQLite with WAL mode and FTS5 is well-suited for single-user session memory. Performance should be excellent through 10,000+ sessions.

**Concern at scale:** The `get_suggestions()` method (lines 406-541) runs multiple full-table scans filtered by date. At 10,000+ sessions, these queries may become noticeable. Adding a composite index on `(start_date, project)` would help.

**FTS5 at scale:** FTS5 handles hundreds of thousands of documents well. The sessions_fts table with auto-sync triggers is the right approach. No concerns here.

---

## CLI Architecture

The CLI (src/cli.py) is well-designed using Click with 6 commands (save, list, search, export, skill-history, skills list, stats). It shares the same SessionDatabase instance as the MCP server, which ensures consistent behavior.

**Strengths:**
- Clean Click group structure with --version
- Sensible defaults for all optional parameters
- Good output formatting (date, surface, project, skills)
- Export supports both markdown and JSON formats

**Concern:** The CLI creates a `SessionDatabase(Config())` at module import time (line 14). This means the database connection is opened when the CLI module is imported, even if the user is just running `--help`. This is a minor issue but could cause errors if the database directory doesn't exist yet.

**Recommendation for LoreDocs CLI:** Use this CLI as a template but add lazy initialization (create the database connection only when a command that needs it actually runs).

---

## Cross-Product Consistency

| Aspect | LoreConvo | LoreDocs | Recommendation |
|--------|-----------|----------|----------------|
| Input validation | Raw Python types | Pydantic BaseModel with Field validators | LoreConvo should adopt Pydantic models |
| DB connections | Single long-lived connection | Context manager per operation | LoreConvo should adopt context manager pattern |
| FTS5 sanitization | Double-quote escaping only | Full phrase-wrapping sanitization | LoreConvo should adopt LoreDocs' approach |
| MCP annotations | Not used | Full readOnlyHint/destructiveHint annotations | LoreConvo should add annotations |
| License module | Nearly identical | Nearly identical | Extract shared lore_license package |
| Tier enforcement | In database layer only | In storage layer + TierEnforcer class | LoreConvo should add TierEnforcer |
| Async/sync | Sync MCP tools | Async MCP tools | LoreConvo should migrate to async |
| Lifespan | None (global db instance) | Proper async lifespan context | LoreConvo should adopt lifespan pattern |
| Error returns | Python dicts | String messages with "Error:" prefix | Standardize error format |
| CLI | 6 commands via Click | No CLI yet | LoreDocs should use LoreConvo CLI as template |

---

## Test Coverage Assessment

**14 test files** covering:
- Core database operations (test_database_new.py)
- Auto-load hook scoring and formatting (test_auto_load.py)
- Auto-save hook transcript parsing (test_auto_save.py)
- CLI commands (test_cli.py)
- License key validation (test_license.py)
- Session limit enforcement (test_session_limit.py)
- Vault suggest / suggestions engine (test_vault_suggest.py)
- Null ID migration (test_null_id_migration.py)
- Plugin JSON structure (test_plugin_json_structure.py)
- MCP JSON pro defaults (test_mcp_json_pro_defaults.py)
- Gitignore safety (test_gitignore_safety.py)
- Onboarding verification (test_onboard.py)
- Save script fallback (test_save_script.py)
- Plugin skills sync (test_plugin_skills_sync.py)

**Missing test coverage:**
- MCP tool layer (server.py) -- no tests call the MCP tools directly
- Concurrent database access (CLI + hook + MCP server simultaneously)
- FTS5 search with special characters / operator injection
- Session linking and chain traversal
- Error paths in save_session (e.g., database locked, disk full)

---

## Prioritized Recommendations

1. **[HIGH] Unify database access** -- Refactor auto_save.py and auto_load.py to use core.database.SessionDatabase (or a shared minimal write path). This fixes H1, M2, and the tier enforcement gap in one change.

2. **[HIGH] Add Pydantic input validation** -- Add BaseModel input classes to all MCP tools in server.py, matching LoreDocs' pattern. This fixes H3 and improves cross-product consistency.

3. **[HIGH] Sanitize FTS5 queries** -- Apply phrase-wrapping to search_sessions, matching LoreDocs' _sanitize_fts_query. One-line fix for H2.

4. **[MEDIUM] Adopt connection context manager** -- Replace the single long-lived self.conn with a _db() context manager pattern (from LoreDocs). Fixes M1.

5. **[MEDIUM] Add MCP tool annotations** -- Add readOnlyHint, destructiveHint, idempotentHint to all tools. Improves LLM tool selection and matches LoreDocs.

6. **[MEDIUM] Add async lifespan** -- Migrate to FastMCP lifespan pattern for proper storage initialization. Removes the global db instance.

7. **[LOW] Add composite index** -- `CREATE INDEX idx_sessions_date_project ON sessions(start_date, project)` for query performance at scale.

8. **[LOW] Extract shared license module** -- Both products have near-identical license.py files. Extract a shared `lore_license` package to eliminate duplication.
