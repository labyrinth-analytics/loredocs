# Gina Architecture Session - 2026-04-04

**Agent:** Gina (Enterprise Architect)
**Run type:** Scheduled (Saturday)
**Session start:** 2026-04-04
**Overall posture:** REVIEW NEEDED

---

## Session Summary

### Part 1: Pipeline Review

Reviewed 3 items with status `approved-for-review`:

**OPP-015 - Data Catalog Lite MCP (P1) --> APPROVED**
- Product name proposed: LoreCatalog
- Architecture: SQLite+FTS5 catalog, INFORMATION_SCHEMA crawler (SQL Server + SQLite),
  9 MCP tools, TierEnforcer (1 DB/50 tables free, unlimited Pro at $10/mo)
- Effort: 5 (4-5 days)
- Zero new architectural patterns -- pure Lore stack reuse
- Main risk: credential management for DSNs (env var reference pattern for MVP)
- BROCK-REVIEW items filed (DSN security, catalog.db at-rest encryption)
- Status set to: architecture-proposed

**OPP-013 - Data Pipeline Test Harness MCP (P2) --> CONDITIONAL APPROVE (after OPP-015)**
- Product name proposed: LoreHarness
- Architecture: ConnectionManager + ComparisonEngine + SQLite history
- Effort: 5 (5-6 days)
- Dependency: build after OPP-015 (credential pattern solved there first)
- Recommendation: remove Enterprise tier from v1 scope (requires cloud sync)
- BROCK-REVIEW items filed (two-DB credential exposure surface)
- Status set to: architecture-proposed

**OPP-016 - ETL Pattern Library Skill (P3) --> MODIFY SCOPE then APPROVE**
- Hold reason addressed: ship as SQL Server specialist free skill MVP (Effort 2)
- SQL Server is genuinely underserved -- this is a moat, not a limitation
- V2 adds parameterized MCP generation as paid tier (after billing infra is live)
- Free skill drives awareness and cross-sells Lore products
- Status set to: architecture-proposed

### Part 2: Product Architecture Review

Reviewed commits 9e6060f, 9ad2bc1, 4b483da, c0a2c46 (LoreConvo + LoreDocs).

**Positive findings:**
- Ed25519 license implementation is architecturally sound (confirmed by Brock)
- Dual-env-var dev bypass correctly designed
- onboard_verify.py is well-structured as a standalone diagnostic tool
- Cross-product license.py pattern is consistent

**Concerns raised (4 items):**

1. MEDIUM: vault_set_tier (LoreDocs server.py:1390) allows Pro activation without
   a license key. The config.json fallback in get_tier() is exploitable.
   Fix: validate LOREDOCS_PRO before writing "pro" to config.

2. MEDIUM: lore-onboard skill NOT included in loreconvo-v0.3.0.plugin bundle.
   Plugin ships only recall + save skills. Marketplace users won't get /lore-onboard.
   Fix: rebuild plugin bundle to include skills/lore-onboard/.

3. MEDIUM: cryptography missing from pyproject.toml in both products.
   Confirms Brock SEC-014. Fresh uvx installs with a Pro key will fail.
   Fix: add cryptography>=41.0.0 to both pyproject.toml files.

4. LOW: onboard_verify.py path discovery fragile in uvx install context.
   _find_src_path() uses script-relative paths that won't work post-install.

### Cross-agent items

- No GINA-REVIEW tags in Brock's latest security reports (clean)
- Filed 4 BROCK-REVIEW items (OPP-015 x2, OPP-013 x2) for credential security review

---

## Files Created/Updated

- docs/architecture/OPP-015_data_catalog_lite_mcp.md (new)
- docs/architecture/OPP-013_data_pipeline_test_harness_mcp.md (new)
- docs/architecture/OPP-016_etl_pattern_library_skill.md (new)
- docs/architecture/product_review_2026_04_04.md (new)
- docs/architecture/gina_session_2026_04_04.md (this file)
- ~/Documents/Claude/Projects/Side Hustle/Opportunities/LATEST_ARCHITECTURE_REVIEW.html (updated)

## Pipeline Status Updates

| OPP ID | Old Status | New Status | Effort |
|--------|-----------|------------|--------|
| OPP-015 | approved-for-review | architecture-proposed | 5 |
| OPP-013 | approved-for-review | architecture-proposed | 5 |
| OPP-016 | approved-for-review | architecture-proposed | 2 |

---

## Recommended Actions for Ron (priority order)

1. Add `cryptography>=41.0.0` to pyproject.toml in both LoreConvo and LoreDocs
2. Fix vault_set_tier in loredocs/server.py to validate license key
3. Rebuild loreconvo-v0.3.0.plugin to include skills/lore-onboard/
4. Low priority: document or fix onboard_verify.py path discovery

## Action for Debbie

- Decide on business contact email for marketplace.json before creating public GitHub repo
  (SEC-015: current value is personal Gmail)
