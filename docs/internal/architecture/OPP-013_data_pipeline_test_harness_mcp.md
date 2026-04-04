# Architecture Proposal: OPP-013 - Data Pipeline Test Harness MCP

**Gina (Enterprise Architect)**
**Date:** 2026-04-04
**Status:** architecture-proposed
**Priority:** P2

---

## Summary

Data Pipeline Test Harness MCP is an MCP server that validates ETL pipeline outputs by
comparing source vs. target databases: row counts, column statistics, referential integrity,
and data drift detection. Answers the question "I changed my ETL -- did it break anything?"

**Revenue model:** Free (3 table comparisons/run) / Pro ($15/mo, unlimited) / Enterprise ($49/mo, multi-DB team)

**Scout priority:** P2 -- strong Debbie fit, real pain point, but more complexity than P1.

---

## Architectural Assessment

### Fit with Existing Lore Architecture

MODERATE COMPATIBILITY. This product introduces a new pattern: it needs to hold two
simultaneous database connections (source and target) and run comparison queries. This
differs from LoreConvo/LoreDocs which manage their own internal SQLite only.

The storage layer (comparison history, baselines) uses the standard SQLite + FTS5 pattern.
Tier enforcement follows the TierEnforcer model. The new element is the multi-connection
comparison engine.

### Proposed Architecture

```
loreharness/
  src/
    core/
      config.py          -- Config (DB path, max comparisons per tier)
      database.py        -- HarnessDatabase (stores comparison history in SQLite)
      connections.py     -- ConnectionManager (holds named connections, resolves DSNs)
      comparator.py      -- ComparisonEngine (runs source/target queries, computes stats)
      models.py          -- ComparisonResult, ColumnStats, DriftReport dataclasses
      tiers.py           -- TierEnforcer (max 3 comparisons free tier)
      license.py         -- Ed25519 validation (same as LoreConvo)
    server.py            -- FastMCP server
  tests/
  pyproject.toml
```

### Core Design: ComparisonEngine

The heart of the product. Two phases:

**Phase 1 - Row count comparison:**
```python
source_count = SELECT COUNT(*) FROM source_db.table
target_count = SELECT COUNT(*) FROM target_db.table
delta_pct = abs(source_count - target_count) / source_count
```

**Phase 2 - Column statistics comparison (per numeric column):**
```python
# Per column: MIN, MAX, AVG, COUNT(DISTINCT), COUNT(NULL)
source_stats = SELECT MIN(col), MAX(col), AVG(col), COUNT(DISTINCT col), SUM(CASE WHEN col IS NULL THEN 1 ELSE 0 END) FROM source
target_stats = same query against target
# Compare and flag deviations > threshold (default 1%)
```

**Phase 3 - Referential integrity spot check (V2):**
```python
# Verify FK values in target exist in referenced table
# E.g., all order.customer_id values appear in customers.id
```

### SQLite History Schema

```sql
CREATE TABLE comparisons (
    id          TEXT PRIMARY KEY,
    source_dsn  TEXT NOT NULL,  -- env var reference
    target_dsn  TEXT NOT NULL,
    table_name  TEXT NOT NULL,
    run_at      TEXT DEFAULT (datetime('now')),
    row_delta_pct REAL,
    column_failures TEXT,  -- JSON: [{column, stat, source_val, target_val}]
    passed      INTEGER,
    notes       TEXT
);

CREATE TABLE baselines (
    id          TEXT PRIMARY KEY,
    table_name  TEXT NOT NULL,
    dsn         TEXT NOT NULL,
    captured_at TEXT,
    stats       TEXT  -- JSON snapshot of column stats
);
```

### MCP Tool Surface (MVP)

| Tool | Description |
|------|-------------|
| harness_compare | Compare source vs. target for a named table; return pass/fail report |
| harness_baseline | Capture current stats as a baseline for future drift detection |
| harness_check_drift | Compare current DB state to stored baseline |
| harness_history | Return comparison run history (with optional table filter) |
| harness_get_status | Return tier, comparison count this period |
| harness_set_tier | Activate Pro license |

### Credential Management Architecture

Same risk as OPP-015. DSNs for source and target databases must be handled securely.
Same recommendation: MVP uses env var references only ("env:SOURCE_DB_DSN").

BROCK-REVIEW: Two-database credential pattern creates a larger attack surface than
LoreCatalog. Both source and target DSNs are in-process simultaneously. If the MCP
server process is compromised, both sets of credentials are exposed. Recommend Brock
assess whether stdio transport mitigates this sufficiently in the local install context,
or whether connection objects should be pooled with explicit open/close per comparison.

### Tier Design

| Dimension | Free | Pro ($15/mo) |
|-----------|------|--------------|
| Comparisons per run | 3 tables | Unlimited |
| Baseline capture | No | Yes |
| Drift detection | No | Yes |
| Comparison history | Last 10 | Full history |
| Scheduled validation | No | Yes |
| Slack/email alerts | No | Yes (V2) |

Note: "Enterprise" tier at $49/mo requires team sharing, which implies cloud sync --
deferred until Team tier is built into the broader Lore platform. Recommend removing
Enterprise from MVP documentation and offering only Free + Pro for v1.

### Dependencies

- `mcp[cli]>=1.0.0`
- `pyodbc>=4.0.35` (SQL Server)
- `psycopg2-binary>=2.9.0` (PostgreSQL, optional)
- `cryptography>=41.0.0` (license validation)
- No pandas/numpy required for MVP statistics (pure SQL aggregation is sufficient)

### Scalability Assessment

For tables with 100M+ rows, running full-column statistics (MIN/MAX/AVG) may be slow
(minutes on SQL Server without appropriate indexes). This is acceptable for a validation
tool -- users expect it to take time. Recommend:
- Adding a `sample_rate` parameter (default 1.0, can be set to 0.01 for large tables)
- Running comparisons asynchronously with a progress indicator

At 1K comparison runs in history: SQLite handles this trivially.

---

## Effort Estimate

**Total effort: 5-6 days (Effort 5)**

| Phase | Effort | Description |
|-------|--------|-------------|
| DB schema + models | 0.5 days | |
| ConnectionManager + DSN resolution | 0.5 days | |
| ComparisonEngine (row count + col stats) | 1.5 days | Most complex logic |
| SQLite history storage | 0.5 days | |
| MCP tool surface (6 tools) | 1 day | |
| Tier enforcement | 0.5 days | |
| License validation | 0.25 days | |
| Tests | 0.75 days | Multi-DB testing harder to stub |
| README + INSTALL | 0.25 days | |
| Plugin packaging | 0.25 days | |

---

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Two-DB credential exposure | HIGH | Env var references only in MVP |
| Long-running comparisons blocking MCP | MEDIUM | Add async execution + sample_rate param |
| pyodbc install friction (system DLL) | MEDIUM | Document SQL Server ODBC driver prereq |
| false confidence from partial checks | LOW | Prominently document what IS and IS NOT checked |
| Enterprise tier requires cloud sync | MEDIUM | Drop Enterprise from v1; add to roadmap |

---

## Recommendation

**CONDITIONAL APPROVE.** Strong product-market fit and excellent Debbie fit. Approve
for development AFTER OPP-015 (LoreCatalog) is shipped. Rationale:

1. OPP-015 is lower risk and higher P1 priority
2. Both share the credential management pattern -- solving it once for LoreCatalog
   informs the implementation for this product
3. The two-DB comparison engine is the most complex new code in the current pipeline

Proposed product name: **LoreHarness**
Suggested development slot: Q2 2026 after LoreCatalog MVP ships.

Also recommend: remove Enterprise tier from v1 scope. Build Free + Pro only.
Enterprise (multi-user, cloud sync) belongs in the roadmap for after Team tier
is established across the Lore platform.
