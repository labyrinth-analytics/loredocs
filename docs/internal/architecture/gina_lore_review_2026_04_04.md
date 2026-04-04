# Gina Session Report -- 2026-04-04

**Agent:** Gina (Enterprise Architect)
**Task:** First formal architecture review of Lore product family
**Products Reviewed:** LoreConvo v0.3.0 (PRODUCTION), LoreDocs v0.1.0 (ALPHA)
**Date:** 2026-04-04

---

## Review Dimensions

Nine dimensions evaluated across both products:

1. Code architecture (module structure, separation of concerns)
2. Database design (schema, FTS5, migrations, connection management)
3. API surface (MCP tools, input validation, annotations)
4. Security architecture (transport, data-at-rest, access patterns, tier enforcement, license keys, trust boundaries, cloud sync risks)
5. Scalability (session/document growth, search performance, storage)
6. CLI architecture (entry points, command design)
7. Tier/licensing (free limits, Pro gating, enforcement completeness)
8. Cross-product consistency (shared patterns, divergences, convergence path)
9. Test coverage (existing tests, gaps, recommended additions)

---

## Key Findings Summary

### LoreConvo v0.3.0 -- Overall: SOLID

**Strengths:** Clean session model, FTS5 with trigger-based sync, smart context suggestions (get_suggestions with decay scoring), effective hook system for auto-save/auto-load, Ed25519 license validation.

**HIGH Findings (3):**
- **H1 -- auto_save.py schema divergence:** Hook script defines its own `ensure_tables()` with a schema that may diverge from core database.py SCHEMA_SQL. Bypasses SessionDatabase entirely -- no session limit check, no id validation.
- **H2 -- FTS5 query injection:** `search_sessions` only escapes double quotes in FTS queries. Operators like OR, NOT, NEAR can alter search semantics. Should phrase-wrap user input.
- **H3 -- No MCP input validation:** All 12 tools use raw Python types (str, int, list) with no Pydantic validation, no Field constraints, no MCP annotations.

**MEDIUM Findings (5):** Single long-lived DB connection, module-level db instantiation, no depth limit on session chain BFS, no WAL mode, hook scripts bypass core database layer.

### LoreDocs v0.1.0 -- Overall: STRONG

**Strengths:** Exemplary Pydantic input validation on all 34 tools, MCP annotations, connection-per-operation pattern, async lifespan, path traversal protection, FTS5 phrase-wrapping, rich text extraction (PDF/DOCX/XLSX/PPTX), incremental schema migrations, comprehensive TierEnforcer.

**HIGH Findings (3):**
- **H1 -- vault_set_tier bypass:** Tool writes tier directly to config.json without requiring a valid license key. Any user can call `vault_set_tier(tier="pro")` to get unlimited access.
- **H2 -- vault_import_dir path traversal:** Accepts arbitrary filesystem paths. User can import from any readable directory (e.g., `/etc/`, `~/.ssh/`).
- **H3 -- vault_export path traversal:** Accepts arbitrary output paths. Could overwrite system files if given a path like `/etc/cron.d/`.

**MEDIUM Findings (5):** Duplicated license.py module, no CLI entry point yet, vault_search_global sequential scan, config.json not integrity-protected, no export size limits.

---

## BROCK-REVIEW Items

Four items flagged for deeper security analysis by Brock:

1. **BROCK-REVIEW: LoreConvo auto_save bypass** -- Hook script can create unlimited sessions bypassing free-tier limit. Assess exploitability in scheduled agent context.
2. **BROCK-REVIEW: LoreDocs vault_set_tier** -- Direct tier bypass via MCP tool. Assess whether MCP transport isolation is sufficient mitigation or if key validation is required.
3. **BROCK-REVIEW: LoreDocs import/export paths** -- Arbitrary filesystem access via vault_import_dir and vault_export. Assess whether path allowlisting or chroot-style restriction is needed.
4. **BROCK-REVIEW: Shared license.py duplication** -- Both products embed identical Ed25519 public key and validation logic. Assess whether a shared library or vendored copy is the better security posture.

---

## Cross-Product Standardization Roadmap

| Pattern | Source Product | Target Product | Priority |
|---------|---------------|----------------|----------|
| Pydantic input validation | LoreDocs | LoreConvo | HIGH |
| MCP annotations | LoreDocs | LoreConvo | HIGH |
| Connection-per-operation | LoreDocs | LoreConvo | MEDIUM |
| Async lifespan | LoreDocs | LoreConvo | MEDIUM |
| FTS5 phrase-wrapping | LoreDocs | LoreConvo | HIGH |
| Click CLI | LoreConvo | LoreDocs | MEDIUM |
| Auto-save/load hooks | LoreConvo | LoreDocs | LOW |
| Shared license module | Both | New shared package | MEDIUM |

---

## Deliverables Produced

1. `docs/architecture/LORECONVO_architecture_review.md` -- Full LoreConvo review
2. `docs/architecture/LOREDOCS_architecture_review.md` -- Full LoreDocs review
3. `~/Documents/Claude/Projects/Side Hustle/Opportunities/LATEST_ARCHITECTURE_REVIEW.html` -- Interactive HTML report
4. `docs/architecture/gina_lore_review_2026_04_04.md` -- This session report

---

## Recommendations for Ron (Priority Order)

1. **Fix vault_set_tier bypass** -- Require valid license key before allowing tier="pro". Highest business risk.
2. **Add path validation to import/export** -- Restrict to user home directory or vault parent paths.
3. **Adopt Pydantic validation in LoreConvo** -- Port LoreDocs pattern to all 12 MCP tools.
4. **Fix FTS5 injection in LoreConvo** -- Phrase-wrap user queries like LoreDocs does.
5. **Refactor auto_save.py** -- Import and use SessionDatabase instead of raw sqlite3.
6. **Add CLI to LoreDocs** -- Already on Ron's TODO list; aligns with cross-product consistency.
7. **Extract shared license module** -- Deduplicate license.py into a shared package.
8. **Enable WAL mode** -- Both products benefit from concurrent read/write support.
