# Personal Knowledge Architecture (PKA) — Implementation Proposal

**Author:** Gina (Enterprise Architect)
**Date:** 2026-04-08
**Status:** Proposal — awaiting Debbie review
**Scope:** Internal `side_hustle` reorganization + shippable LoreDocs starter kit
**Inspiration:** MyICOR ("Claude and a folder, that's it"), PKA philosophy, Perplexity competitive analysis (Apr 2026)

---

## 1. Vision & Principles

**Personal Knowledge Architecture (PKA)** is a deliberate inversion of traditional Personal Knowledge Management (PKM). PKM tools (Obsidian, Notion, Roam) optimize for *capturing inputs* — every article, every meeting note, every fleeting thought becomes a node in an ever-growing graph. The user becomes a librarian of their own raw material, and the cost of finding a conclusion grows with the size of the corpus.

PKA flips this. **Store conclusions, not inputs.** Raw material is a means to an end; the end is a decision, a spec, a playbook, an ADR — a *durable artifact* that future-you (or future-agents) can act on without re-deriving it. Inputs are transient. Conclusions compound.

### Core principles

1. **Conclusions over inputs.** The archive is for things you concluded, not things you read. If it can't be summarized in a decision, spec, ADR, or playbook, it doesn't graduate.
2. **Three inboxes, one direction.** Raw → processing → archive. Things only move forward. Nothing lingers in raw indefinitely; if it's still raw after N days, it gets archived or deleted.
3. **Both filesystem AND vault.** The filesystem is the source of truth for humans and git. The LoreDocs vault is the source of truth for AI agents. They mirror each other through a sync step. Eat our own dogfood.
4. **Agents draft, humans conclude.** Ron, Meg, Brock, Madison, Jacqueline, John, Scout, Gina drop reports into `inbox/raw/`. Debbie (or a delegate agent) decides what graduates to `knowledge/`. The agents do not promote their own work.
5. **Reversible at every step.** Every migration phase ends in a git tag so we can roll back.
6. **Findable in <10 seconds.** If a conclusion takes longer than 10 seconds to locate, the structure has failed.

### Why this differs from current `docs/`

The current `docs/internal/` is organized **by producer** (qa/, security/, pm/, marketing/, architecture/). That made sense when we had three agents. With ten agents producing dated reports daily, the structure has become a write-only archive: agents drop reports in their folder, nobody reads the old ones, conclusions are never extracted, and the same questions get re-asked because the answers are buried in a 12-day-old QA report nobody opened.

PKA reorganizes **by lifecycle stage and conclusion type**, not by producer.

---

## 2. Current State Audit

### Inventory (as of 2026-04-08)

- **117 files** under `docs/`
- **`docs/internal/qa/`** — 15 dated QA reports (Meg)
- **`docs/internal/security/`** — 12 dated security reports (Brock)
- **`docs/internal/pm/`** — 13 daily executive dashboards + roadmaps (Jacqueline)
- **`docs/internal/architecture/`** — 11 mixed: product reviews, OPP- proposals, session notes (Gina)
- **`docs/internal/marketing/`** — content calendar + blog drafts + promo (Madison)
- **`docs/internal/competitive/`** — 4 scans + INTAKE.md
- **`docs/internal/loredocs/`** — 4 internal product docs (PUBLISHING, specs, marketplace listing)
- **`docs/internal/loreconvo/`** — 6 internal product docs
- **`docs/internal/other documentation/`** — 12 miscellaneous (legacy diagrams, IP strategy, exploration plan, agent prompts subfolder)
- **Top-level:** `DEBBIE_DASHBOARD.md`, `DEBBIE_PROCESS.md`, `COMPLETED.md`, `PIPELINE_AGENT_GUIDE.md`, `AGENT_METRICS_ANALYSIS.txt`, `stability_mandate_2026_04_05.md`
- **`docs/superpowers/plans/`** — exists but contents not audited here
- **`docs/architecture/proposals/`** — this proposal lives here (currently empty otherwise)

### Pain points

1. **Producer-centric folders mean nothing graduates.** A QA report identifying a bug stays in `qa/`. The fix lands in code, but the *conclusion* ("we now require integration tests for X because of incident Y") never makes it into a durable knowledge file.
2. **Daily dashboards accumulate.** 8 executive_dashboard_*.html files in 8 days. Yesterday's dashboard is dead weight by today.
3. **`other documentation/` is a black hole.** 12 files including IP strategy docs, legacy diagrams, exploration plans. No one knows what's still relevant.
4. **No decision log.** Decisions like "BSL 1.1 for both products" or "Mr. Cooper not BECU" live in CLAUDE.md, memory files, or LoreConvo session summaries — three places, no canonical home.
5. **No ADR repository.** Architectural decisions (SQLite over Postgres, stdio transport, monorepo layout) are scattered across product CLAUDE.mds and Gina session notes.
6. **Specs and product docs mix internal-only and shippable content** in `loreconvo/` and `loredocs/` subfolders, which creates the public-repo-leak risk that's already been called out.
7. **Stale items aren't archived, they're just buried.** Nothing has a graduation or expiration mechanism.

### What's working

- **Dated reports from agents** are easy to scan chronologically and the naming convention is consistent.
- **Top-level dashboards** (`DEBBIE_DASHBOARD.md`, `COMPLETED.md`) are well-loved and well-used.
- **`docs/internal/` vs public separation** is enforced by the public-repo hygiene rules and works.
- **`PIPELINE_AGENT_GUIDE.md`** is the right *kind* of doc — a playbook — and should be a model for the new `knowledge/playbooks/`.

---

## 3. Target Structure

```
docs/
  README.md                          # navigation map; what lives where, how to find things
  inbox/
    raw/                             # agent reports land here; nothing else
      qa/
      security/
      pm/
      architecture/
      marketing/
      competitive/
      technical/
      scout/
    processing/                      # Debbie is actively reviewing or refining
      <freeform — short-lived working files>
    triage.md                        # running list of what's in raw/, status, next action

  knowledge/                         # the durable archive — only conclusions live here
    decisions/                       # decision log (one file per decision OR a single rolling log)
      LOG.md                         # rolling chronological log (recommended)
      2026-03-31-bsl-license.md      # for decisions big enough to need a full doc
      2026-04-04-stability-mandate.md
    architecture/                    # ADRs and durable system design
      ADR-001-sqlite-over-postgres.md
      ADR-002-stdio-transport.md
      ADR-003-monorepo-layout.md
      system-overview.md
    specs/                           # feature specs, PRDs (internal versions only)
      loreconvo/
      loredocs/
      pka/
    playbooks/                       # SOPs, runbooks, how-tos (the active ones)
      pipeline-agent-guide.md        # moved from docs/PIPELINE_AGENT_GUIDE.md
      git-safe-workflow.md           # extract from CLAUDE.md
      session-workflow.md            # extract from CLAUDE.md
      public-repo-hygiene.md         # extract from CLAUDE.md
      lore-script-paths.md
    roadmap/
      current.md                     # the live roadmap; one file, always current
      changelog.md                   # what changed and when
      debbie-dashboard.md            # moved from docs/DEBBIE_DASHBOARD.md
    products/                        # internal product knowledge (NOT shippable)
      loreconvo/
      loredocs/
      sql-query-optimizer/

  archive/                           # superseded, historical, kept for traceability
    by-year/
      2026/
        Q1/
        Q2/
    decisions-superseded/
    reports-old/                     # raw reports past their useful life

  architecture/proposals/            # KEEP — this is where new proposals like this one land
    pka_implementation_2026_04_08.md
```

### Why this layout

- **`inbox/` is the only place agents write.** They never touch `knowledge/`. This is enforced by convention and by per-agent prompt updates.
- **`knowledge/` is the only place humans (and review agents) curate.** Everything in here is presumed current and actionable.
- **`archive/` is the graveyard.** Things move here when superseded. Nothing here is presumed current.
- **Conclusion types are first-class folders.** Decisions, ADRs, specs, playbooks, roadmap — these are the four units Debbie said matter. Each gets a home.
- **`products/` is for internal product knowledge** (revenue, GTM, internal CLAUDE.md) so we never re-leak to public repos.
- **`README.md` at the top** answers "where does X live?" in <10 seconds. This is the trailhead.

---

## 4. Agent Handoff Flow

### Today (broken)

```
Agent runs → drops report in docs/internal/<producer>/ → end
```

### Proposed

```
Agent runs
   ↓
drops report in docs/inbox/raw/<producer>/<dated-file>
   ↓
appends one-line entry to docs/inbox/triage.md
   ↓
Jacqueline's daily dashboard reads triage.md and surfaces "Untriaged: N"
   ↓
Debbie reviews items in raw/ → marks each as:
   - PROMOTE → file (or its conclusion) moves to knowledge/<type>/
   - PROCESSING → moves to inbox/processing/ for further refinement
   - ARCHIVE → moves to archive/reports-old/
   - DELETE → gone
   ↓
For PROMOTED items, Debbie (or a delegate) writes the conclusion as
a decision/ADR/spec/playbook update. The original report stays linked
from the conclusion as evidence.
```

### Who moves what, when

| Step | Actor | Action | Cadence |
|---|---|---|---|
| 1. Drop raw report | Agent (Ron, Meg, Brock, Jacqueline, Madison, John, Scout, Gina, Competitive Intel) | Write to `inbox/raw/<producer>/`, append to `triage.md` | Each agent run |
| 2. Surface untriaged | Jacqueline | Show "Untriaged: N" + oldest item age in daily dashboard | Daily |
| 3. Triage decision | Debbie | Mark each raw item: PROMOTE / PROCESSING / ARCHIVE / DELETE | Daily or 2x weekly |
| 4. Promote to knowledge | Debbie OR a "Curator" agent (new role, optional Phase 3) | Write/update the decision, ADR, spec, or playbook. Link source report. | On promote |
| 5. Move file out of raw | Curator agent OR a tiny bash script | Move file to its destination folder | On promote |
| 6. Archive sweep | Scheduled task (new) | Anything in `inbox/raw/` older than 14 days → `archive/reports-old/` | Weekly |

### Agent prompt updates required

Each agent's scheduled-task prompt and CLAUDE.md needs **one line changed**:

> Old: `Output: docs/internal/qa/qa_report_YYYY_MM_DD.md`
> New: `Output: docs/inbox/raw/qa/qa_report_YYYY_MM_DD.md` and append a one-line entry to `docs/inbox/triage.md`

Ron, Meg, Brock, Jacqueline, Madison, John, Scout, Gina, Competitive Intel — nine agents, nine one-line edits. Plus the central CLAUDE.md updates.

### Curator agent (optional, Phase 3)

A new lightweight agent — call it **Quill** — that runs after Debbie's review window and:
1. Reads `triage.md` for items Debbie marked PROMOTE
2. Drafts the decision/ADR/spec entry
3. Moves the source file to its new home
4. Updates `triage.md`

Phase 3 only. Phase 1 is human-driven.

---

## 5. LoreDocs Vault Structure

The filesystem is the source of truth for git. The LoreDocs vault is the source of truth for AI agents that need to query knowledge by topic, not by path.

### Recommended: one vault per knowledge type, plus an inbox vault

| Vault name | Contents | Tags |
|---|---|---|
| `lore-decisions` | Everything in `knowledge/decisions/` | `decision`, `<topic>` |
| `lore-architecture` | Everything in `knowledge/architecture/` | `adr`, `system-design` |
| `lore-specs` | Everything in `knowledge/specs/` | `<product>`, `prd` |
| `lore-playbooks` | Everything in `knowledge/playbooks/` | `sop`, `<workflow>` |
| `lore-roadmap` | `knowledge/roadmap/` | `roadmap`, `dashboard` |
| `lore-products-internal` | `knowledge/products/` | `<product>`, `internal` |
| `lore-inbox` | `inbox/raw/` (auto-synced, ephemeral) | `<producer>`, `untriaged` |

**Why split vaults instead of one big vault with tags:** queries like "what's our position on X" should hit `lore-decisions` only, not return raw reports. Vault scoping is the cleanest filter. Tags handle cross-cuts within a vault.

**Sync mechanism:** a small script (`scripts/sync_pka_to_loredocs.py`) walks `docs/knowledge/` and `docs/inbox/raw/`, calls `vault_add_document` / `vault_update_document` for changed files. Run it as a Cowork hook on commit, or as a scheduled task every hour. The filesystem stays the source of truth; LoreDocs is a derived index.

**Inbox vault is ephemeral by design.** When a file is archived from `inbox/raw/`, the sync script removes it from `lore-inbox`. The archive vault (if we want one) gets a separate `lore-archive` for historical queries.

---

## 6. Migration Plan

### Principle: phased, reversible, with a git tag at every checkpoint

Each phase ends with a `git tag pka-phase-N` so we can `git checkout pka-phase-1` if anything goes wrong.

### Phase 0 — Approval & prep (1 day)
- Debbie reviews this proposal, approves or requests changes
- Create the empty PKA folder skeleton in `docs/` alongside the existing structure
- Write `docs/README.md` navigation map
- **Tag:** `pka-phase-0-skeleton`
- **Reversible:** trivially — just delete the new empty folders

### Phase 1 — Knowledge bootstrapping (2-3 days)
- Hand-write the seed conclusions:
  - `knowledge/decisions/LOG.md` populated from CLAUDE.md decisions, memory files, recent LoreConvo decisions
  - 5-10 ADRs for the architectural decisions already made (SQLite, stdio, monorepo, BSL, three-inbox)
  - Move `docs/PIPELINE_AGENT_GUIDE.md` → `knowledge/playbooks/pipeline-agent-guide.md`
  - Move `docs/DEBBIE_DASHBOARD.md` → `knowledge/roadmap/debbie-dashboard.md`
  - Extract session-workflow, git-safe-workflow, public-repo-hygiene playbooks from CLAUDE.md
- Update CLAUDE.md to point at the new playbook locations rather than inlining
- **Tag:** `pka-phase-1-knowledge-seeded`
- **Reversible:** old paths still exist; new paths are additive

### Phase 2 — Inbox cutover (1 day, then 1 week soak)
- Update all 9 agent prompts to write to `docs/inbox/raw/<producer>/` instead of `docs/internal/<producer>/`
- Update `triage.md` template
- Update Jacqueline's dashboard to surface untriaged count
- Old `docs/internal/<producer>/` folders stay frozen — nothing new lands there
- Soak for one week to confirm all agents are landing in the right place
- **Tag:** `pka-phase-2-inbox-live`
- **Reversible:** revert agent prompts; old folders still work

### Phase 3 — Historical archive (1 day)
- Move existing `docs/internal/qa/`, `security/`, `pm/`, `architecture/` (the dated reports), `marketing/`, `competitive/`, `technical/` into `docs/archive/by-year/2026/Q1/` and `Q2/`
- Move `docs/internal/loreconvo/` and `docs/internal/loredocs/` into `knowledge/products/loreconvo/` and `loredocs/` (these are internal product knowledge, not reports)
- Move `docs/internal/other documentation/` into `archive/by-year/<appropriate>/` after triaging which (if any) should graduate to `knowledge/`
- Delete `docs/internal/` once empty
- **Tag:** `pka-phase-3-archived`
- **Reversible:** git revert the moves

### Phase 4 — LoreDocs sync (1-2 days)
- Build `scripts/sync_pka_to_loredocs.py`
- Create the 7 vaults
- Run initial bulk sync
- Add a Cowork hook (or scheduled task) to keep it current
- **Tag:** `pka-phase-4-vaults-live`
- **Reversible:** delete vaults; filesystem unchanged

### Phase 5 — Curator agent (optional, 2 days)
- Build Quill agent to auto-draft conclusion entries from PROMOTE-marked raw items
- Run in dry-run mode for one week before going live
- **Tag:** `pka-phase-5-curator-live`

### Phase 6 — Starter kit publication (1 day)
- Package the structure as a LoreDocs starter kit (see Section 7)
- Madison drafts the "three-inbox workflow" content artifact
- **Tag:** `pka-phase-6-starter-kit-shipped`

**Total: 8-12 working days** for Phases 0-4 (the must-haves). Phases 5-6 can wait.

---

## 7. Starter Kit for Customers

The shippable version. This becomes a LoreDocs install option ("starter kit: PKA") and Madison's content artifact.

### What ships

A `loredocs-starter-kit-pka/` directory bundled with LoreDocs (or downloadable from the marketplace listing). Contents:

```
loredocs-starter-kit-pka/
  README.md                          # the pitch + how to use
  CLAUDE.md.template                 # drop-in CLAUDE.md snippet for the user's project
  setup.sh                           # creates folder structure + initial vaults
  folders/
    inbox/
      raw/.gitkeep
      processing/.gitkeep
      triage.md.template
    knowledge/
      decisions/LOG.md.template
      architecture/.gitkeep
      specs/.gitkeep
      playbooks/.gitkeep
      roadmap/current.md.template
    archive/.gitkeep
  templates/
    decision-entry.md
    adr.md
    spec.md
    playbook.md
    weekly-triage.md
  vaults/
    lore-decisions.json              # vault manifests for one-shot creation
    lore-architecture.json
    lore-specs.json
    lore-playbooks.json
    lore-inbox.json
  docs/
    philosophy.md                    # the "store conclusions not inputs" pitch
    workflow.md                      # daily/weekly workflow
    examples/                        # sample populated decisions, ADRs, specs
```

### CLAUDE.md.template (the drop-in)

A 40-50 line snippet the user pastes into their own CLAUDE.md that tells Claude:
- Where to find conclusions (`knowledge/`)
- Where raw work goes (`inbox/raw/`)
- Never to write directly to `knowledge/` — always propose conclusions for human promotion
- The triage workflow (read `inbox/triage.md`, propose actions)

### setup.sh

Idempotent. Creates the folder structure, copies templates, initializes the LoreDocs vaults, and writes a starter `triage.md` and `LOG.md`. Safe to re-run.

### What Madison ships alongside it

A blog post + landing page section: "Stop hoarding notes. Start shipping decisions. The three-inbox workflow for AI-assisted knowledge work." Pulls quotes from MyICOR, links to the starter kit install, demos a before/after.

This is the **first concrete LoreDocs upgrade tied to a customer-facing narrative** — exactly the kind of thing that converts free tier users to Pro.

---

## 8. Success Metrics

### Quantitative

| Metric | Baseline (today) | Target (90 days post-launch) |
|---|---|---|
| Time to find a known conclusion | Unknown — likely 2-5 min via grep | <10 sec via README + knowledge/ tree |
| Files in `inbox/raw/` older than 14 days | N/A | <5 |
| Decisions logged in `LOG.md` per month | 0 (no log exists) | 8-15 |
| ADRs written per quarter | 0 (none formal) | 3-5 |
| Stale dashboards/reports floating in top-level docs/ | ~12 daily HTML files | 0 (all in archive or knowledge) |
| Agent reports promoted to `knowledge/` per week | 0 | 2-4 |

### Qualitative

- Debbie can answer "what did we decide about X" without re-asking an agent
- New agent onboarding (next time we add an agent) takes <30 min instead of "read three CLAUDE.mds and hope"
- A LoreDocs starter-kit user can describe the philosophy in one sentence after reading `philosophy.md`
- Madison's blog post on the three-inbox workflow gets shared/linked externally

### Anti-metrics (things we should NOT see)

- `knowledge/` folders growing uncontrolled (>50 files in any one folder)
- `inbox/processing/` becoming a permanent home for items
- Re-emergence of producer-named subfolders inside `knowledge/`

---

## 9. Open Questions for Debbie

1. **Decision log format:** one rolling `LOG.md` (low ceremony, easy to append) or one file per decision (better git diffs, more discoverable)? Recommendation: rolling LOG.md for small/medium decisions, separate file for "big" ones (BSL license, stability mandate, PKA itself).
2. **Curator agent (Quill):** build it in Phase 5, or stay human-driven indefinitely? Recommendation: stay human-driven for 60 days, then evaluate.
3. **Archive retention:** keep raw reports forever (full traceability) or prune `archive/reports-old/` after 12 months? Recommendation: keep forever — disk is cheap, traceability is valuable.
4. **`docs/superpowers/` folder:** I didn't audit it deeply. Should it move into `knowledge/playbooks/` or stay separate?
5. **Public starter kit timing:** ship the starter kit before or after we've used PKA internally for 30 days? Recommendation: after — eat the dogfood, then sell it.
6. **Sync direction:** filesystem → LoreDocs only (recommended), or bidirectional? Bidirectional is harder and creates merge-conflict surface area.
7. **Triage cadence:** daily (more disciplined, more burden) or 2x weekly (looser, raw/ accumulates more)? Recommendation: 2x weekly to start, daily only if raw/ overflows.
8. **Naming `inbox/`:** "inbox" is the MyICOR term but could be confused with email. Alternatives: `intake/`, `staging/`. Recommendation: keep `inbox/` for cultural alignment with the source material.

---

## 10. Effort Estimate

| Phase | T-shirt | Working days | Who |
|---|---|---|---|
| 0. Approval & skeleton | XS | 1 | Debbie + Ron |
| 1. Knowledge bootstrapping | M | 2-3 | Debbie (decisions) + Gina (ADRs) + Ron (playbook extraction) |
| 2. Inbox cutover | S | 1 + 1 week soak | Ron (prompt edits) + Jacqueline (dashboard update) |
| 3. Historical archive | S | 1 | Ron |
| 4. LoreDocs sync | M | 1-2 | Ron |
| 5. Curator agent (optional) | M | 2 | Ron + Gina |
| 6. Starter kit (optional, ships externally) | M | 1-2 | Ron + Madison |
| **Total (must-haves, Phases 0-4)** | **L** | **8-12 days** | |
| **Total (with optional 5-6)** | **XL** | **12-16 days** | |

Recommendation: commit to Phases 0-4. Treat 5 and 6 as separate decisions after we've lived in the new structure for 30 days.

---

## Appendix A — Why MyICOR's "Claude and a folder" is the right north star

MyICOR's claim is that you don't need Obsidian, Notion, or any PKM tool — just a folder Claude can read. The insight is that **the LLM is the index**. You don't need backlinks, graph views, or tags if the agent can read the whole folder and answer "what did we decide about X."

This is exactly what LoreDocs already provides (vault search, summary injection) — we just haven't been organizing the *underlying folder* in a way that rewards conclusion-first thinking. PKA is the missing organizational layer that turns LoreDocs from a clever search tool into an opinionated knowledge architecture.

Shipping PKA as a LoreDocs starter kit is how we **productize the philosophy**, not just the tool.

---

**End of proposal. Awaiting Debbie's review.**
