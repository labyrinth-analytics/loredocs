# Architecture Proposal: OPP-015 - Data Catalog Lite MCP

**Gina (Enterprise Architect)**
**Date:** 2026-04-04
**Status:** architecture-proposed
**Priority:** P1

---

## Summary

Data Catalog Lite MCP is a local-first MCP server that crawls database metadata
(INFORMATION_SCHEMA) and builds a searchable, annotated catalog stored in SQLite.
Users can describe tables and columns, add tags, and ask Claude questions like
"what tables do we have and what do they mean?" entirely within their local environment.

**Revenue model:** Free (1 DB, 50 tables) / Pro ($10/mo, unlimited) / Team ($25/mo, shared catalog)

**Scout priority:** P1 -- strong market gap, excellent Debbie fit.

---

## Architectural Assessment

### Fit with Existing Lore Architecture

HIGH COMPATIBILITY. This product follows the exact same architectural template as LoreConvo
and LoreDocs: SQLite + FTS5 for local-first storage, MCP server via FastMCP, tier gating
via TierEnforcer pattern, env var for Pro unlock. Debbie can reuse:
- The TierEnforcer pattern from LoreDocs (vault_count -> table_count, doc_count -> column_count)
- The FTS5 search pattern from LoreConvo (full-text on table names, column names, descriptions)
- The license.py validation module (shared across all Lore products via lore_suite key)
- The BSL 1.1 licensing structure

The product fits naturally into the Lore family as "LoreCatalog" -- the data catalog member
of the suite.

### Proposed Architecture

```
lorecatalog/
  src/
    core/
      config.py          -- Config dataclass (DB path, max tables per tier)
      database.py        -- CatalogDatabase (SQLite + FTS5)
      crawler.py         -- INFORMATION_SCHEMA crawler (SQL Server, SQLite, Postgres)
      models.py          -- TableEntry, ColumnEntry, ConnectionEntry dataclasses
      tiers.py           -- TierEnforcer (max 1 connection free, max 50 tables free)
      license.py         -- Ed25519 validation (copy from LoreConvo, change _VALID_PRODUCTS)
    server.py            -- FastMCP server (catalog_crawl, catalog_search, catalog_annotate, etc.)
  tests/
  pyproject.toml
  README.md
  INSTALL.md
```

### SQLite Schema

```sql
CREATE TABLE connections (
    id        TEXT PRIMARY KEY,
    name      TEXT NOT NULL UNIQUE,
    driver    TEXT NOT NULL,  -- 'sqlite', 'sqlserver', 'postgresql'
    dsn       TEXT NOT NULL,  -- encrypted or environment variable reference
    last_crawl TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE catalog_tables (
    id            TEXT PRIMARY KEY,
    connection_id TEXT NOT NULL REFERENCES connections(id),
    schema_name   TEXT,
    table_name    TEXT NOT NULL,
    table_type    TEXT,  -- 'TABLE', 'VIEW'
    description   TEXT,  -- user-added annotation
    tags          TEXT,  -- JSON array
    row_count     INTEGER,
    crawled_at    TEXT,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE catalog_columns (
    id            TEXT PRIMARY KEY,
    table_id      TEXT NOT NULL REFERENCES catalog_tables(id),
    column_name   TEXT NOT NULL,
    data_type     TEXT,
    is_nullable   INTEGER,
    description   TEXT,  -- user-added annotation
    pii_flag      INTEGER DEFAULT 0,  -- user flags sensitive columns
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE VIRTUAL TABLE catalog_fts USING fts5(
    table_name, description, tags, content=catalog_tables, content_rowid=rowid
);
```

### MCP Tool Surface (MVP)

| Tool | Description |
|------|-------------|
| catalog_connect | Register a database connection (stores name + DSN) |
| catalog_crawl | Crawl INFORMATION_SCHEMA for a connection, populate tables/columns |
| catalog_search | Full-text search across table names, descriptions, tags |
| catalog_annotate_table | Add or update description/tags for a table |
| catalog_annotate_column | Add or update description for a column (incl. PII flag) |
| catalog_list_tables | List all tables for a connection (with optional filter) |
| catalog_get_table | Get full table details including columns and annotations |
| catalog_get_status | Return tier, connection count, table count |
| catalog_set_tier | Activate Pro license (same pattern as vault_set_tier) |

### Credential Management Architecture

This is the highest-risk architectural element. Database DSNs include passwords.
Recommended approach (in priority order):

1. **Environment variable references (MVP):** Store "env:MY_DB_DSN" as the DSN value.
   The crawler resolves the env var at crawl time. No credential stored in SQLite.

2. **macOS Keychain via keyring library (V2):** Store DSN in system keychain, reference
   by connection name. Needs `keyring` dependency.

3. **Never store plaintext credentials in SQLite.** The catalog DB may be backed up
   to cloud via Time Machine or iCloud -- encrypting DSNs prevents credential exposure.

Recommendation: MVP ships with env var references only. Add a clear warning in the
README that plaintext DSNs should not be used. V2 adds keyring integration.

BROCK-REVIEW: Credential storage architecture for the DSN field. Specifically:
(1) is env var reference pattern sufficient for MVP security posture?
(2) should the catalog.db be encrypted at rest given it may contain sensitive metadata
(table names like 'salary', 'ssn', 'medical_records') even without row data?

### Tier Design

| Dimension | Free | Pro ($10/mo) |
|-----------|------|--------------|
| Connections | 1 | Unlimited |
| Tables cataloged | 50 | Unlimited |
| Column annotations | Yes | Yes |
| Tag search | Yes | Yes |
| PII flagging | No | Yes |
| Export to Markdown/HTML | No | Yes |
| Scheduled auto-crawl | No | Yes |

### Dependencies

- `mcp[cli]>=1.0.0` (FastMCP, already in Lore stack)
- `pyodbc>=4.0.35` (SQL Server connectivity)
- `psycopg2-binary>=2.9.0` (PostgreSQL connectivity -- optional)
- `cryptography>=41.0.0` (license validation -- same as LoreConvo/LoreDocs)
- No new dependencies beyond what LoreConvo already uses

### Cross-Product Integration Points

- **lore_suite license key** works across LoreConvo, LoreDocs, and LoreCatalog -- users
  who buy a bundle key unlock Pro on all three products
- LoreConvo sessions can reference catalog entries via session tags ("catalog:users.orders")
- LoreDocs vaults can store exported catalog snapshots as documents

### Scalability Assessment

At 10K tables (a large database): FTS5 index will remain fast (SQLite FTS5 handles millions
of rows). Crawl time for 10K columns over INFORMATION_SCHEMA is typically under 10 seconds
on SQL Server. No scalability concerns for a single-user local install.

---

## Effort Estimate

**Total effort: 4-5 days (Effort 4)**

| Phase | Effort | Description |
|-------|--------|-------------|
| DB schema + models | 0.5 days | Straightforward, follows LoreDocs pattern |
| Crawler (SQLite + SQL Server) | 1 day | INFORMATION_SCHEMA queries for both dialects |
| MCP tool surface (9 tools) | 1 day | FastMCP, follows LoreConvo pattern |
| Tier enforcement | 0.5 days | Direct copy of LoreDocs TierEnforcer |
| License validation | 0.25 days | Copy license.py, update _VALID_PRODUCTS |
| Tests | 0.5 days | Unit tests for crawler, FTS, tier limits |
| README + INSTALL | 0.25 days | Standard Lore docs |
| Plugin packaging | 0.25 days | .mcp.json + plugin.json |

---

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| DSN credential exposure | HIGH | Env var reference pattern in MVP; Keyring in V2 |
| pyodbc not available via uvx | MEDIUM | Document system-level install; test with uvx |
| SQL Server INFORMATION_SCHEMA queries vary by version | LOW | Pin to SQL Server 2016+ subset |
| Column-level PII flagging creates false confidence | LOW | Add disclaimer in docs |

---

## Recommendation

**APPROVE for development.** This is the strongest P1 opportunity in the pipeline.

- Zero new architectural patterns -- pure application of proven Lore stack
- Highest Debbie fit (INFORMATION_SCHEMA expert, SQL Server shop)
- Clear market gap (no lightweight local-first data catalog in MCP ecosystem)
- Revenue model is well-understood ($10/mo Pro, cross-sells existing Lore products)
- Credential management risk is manageable with env var approach in MVP

Proposed product name: **LoreCatalog**
Suggested development slot: After CLI migration (Ron TODOs #1-5) is complete.

---

## Dependencies on Other Pipeline Items

None for MVP. V2 export feature could leverage LoreDocs vault storage.
