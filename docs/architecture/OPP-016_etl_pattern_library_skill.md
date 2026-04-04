# Architecture Proposal: OPP-016 - ETL Pattern Library Skill

**Gina (Enterprise Architect)**
**Date:** 2026-04-04
**Status:** architecture-proposed (ON HOLD -- needs scope rethink)
**Priority:** P3

---

## Summary

A Claude Code skill + optional MCP backend providing battle-tested ETL design patterns
with ready-to-use SQL Server and Python implementations: SCD Type 2, incremental loads,
deduplication, merge/upsert, data vault, and more.

**Current hold reason:** "ETL Pattern Library focuses on SQL Server implementations;
needs rethinking for modern/database-agnostic stacks."

---

## Architectural Assessment

### Hold Reason Analysis

The hold reason is valid. A SQL-Server-only pattern library has a narrow addressable
market. However, the core value proposition -- curated, tested, production-grade ETL
patterns as a Claude skill -- remains strong. The fix is to reframe the product:

**Reframe option A: Two-dialect from day one**
Provide every pattern in both T-SQL (SQL Server) and Python (pandas/SQLAlchemy).
Benefit: doubles audience. Cost: doubles initial content effort.

**Reframe option B: "SQL Server specialist" as the positioning**
Lean into SQL Server being underserved in the Claude/MCP ecosystem. dbt MCP exists
for PostgreSQL/Snowflake shops. There is no SQL Server pattern library for Claude.
Benefit: clear differentiation. Risk: smaller TAM.

**Reframe option C: Python-first, dialect as parameters**
Write patterns in Python with SQLAlchemy/pandas. The MCP backend generates
dialect-specific SQL on request. Pattern logic is database-agnostic; SQL output
is parameterized.

**Recommendation: Option C for V2, Option B for MVP.**

Ship the SQL Server specialist skill first (MVP, weekend project as Scout estimated).
V2 adds Python SQLAlchemy implementations and the parameterized MCP backend.
This gets the product out fast while the V2 scope is clearer.

### Architecture (Option B MVP)

This is a pure knowledge product for MVP -- no database connectivity, no MCP server.

```
lorekits/                             # product directory
  skills/
    etl-patterns/
      SKILL.md                        # Claude Code skill definition
      patterns/
        scd_type2/
          README.md                   # What it is, when to use it, anti-patterns
          sqlserver.sql               # Production-grade T-SQL implementation
          test_sqlserver.sql          # Test cases
        incremental_load/
          README.md
          sqlserver.sql
          python_sqlalchemy.py
        dedup/
        merge_upsert/
        data_vault_hub/
        data_vault_satellite/
        slowly_changing_dimension_type1/
        audit_trail/
        surrogate_key_generation/
        change_data_capture/
        full_load_with_truncate/
  pyproject.toml                      # Needed only if MCP backend added in V2
```

The SKILL.md instructs Claude to:
1. Ask the user what pattern they need
2. Read the appropriate pattern files from the skills/ directory
3. Adapt the template to the user's table names and schema

### MCP Backend (Option C, V2)

If V2 adds parameterized code generation, the architecture is:

- FastMCP server with `pattern_generate(pattern_name, dialect, table_name, columns)` tool
- Pattern templates stored as Jinja2 templates
- Supported dialects: `sqlserver`, `postgresql`, `sqlite`
- License key required for Pro (more than 5 patterns, parameterized generation)

### Free vs. Pro Tiers

MVP (skill-only, no MCP):
- Free: 5 basic patterns (INSERT/UPDATE, basic SCD, dedup)
- Pro ($8/mo): All 15+ patterns via MCP parameterized generation

Alternative: sell as one-time purchase ($49, complete pattern library as files).
This avoids the recurring billing infrastructure until Stripe is live.

**Recommendation:** For MVP, ship as a free skill with all patterns included.
Drive awareness and cross-selling to LoreConvo/LoreDocs. Monetize via the Pro
MCP backend in V2 after billing infrastructure is in place.

---

## Effort Estimate

**MVP effort: 1-2 days (Effort 2, down from Effort 3)**

| Phase | Effort | Description |
|-------|--------|-------------|
| SKILL.md definition | 0.25 days | |
| Pattern content (10 SQL Server patterns) | 0.75 days | Core writing work |
| Pattern content (5 Python patterns) | 0.5 days | SQLAlchemy equivalents |
| README + INSTALL | 0.25 days | |
| Plugin packaging | 0.25 days | |

**V2 (MCP backend) effort: 3-4 additional days**

---

## Recommendation

**MODIFY SCOPE then APPROVE.** The hold reason is addressed by reframing as
"Option B MVP" (SQL Server specialist, which is genuinely underserved) shipping
as a free skill first, with V2 parameterized MCP generation as the paid tier.

Immediate action: Update the open_questions in PipelineDB to reflect this
rearchitected scope and set status to 'architecture-proposed'. Do not block
on building the V2 MCP backend -- ship the free skill MVP first to validate
market demand.

The SQL Server specialist positioning is not a liability -- it is Debbie's moat.
No other Claude skill author has 25 years of production SQL Server ETL experience.
