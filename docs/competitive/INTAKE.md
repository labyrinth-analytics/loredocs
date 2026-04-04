# Competitive Intelligence Intake

Drop competitor tips, links, and observations here. The competitive intel agent
reads this file at session startup and incorporates entries into the next scan.

After processing, the agent moves entries to the "Processed" section with a date
and reference to the competitive scan report or pipeline item created.

## Format

```
### [Product/Tool Name]
- **Source:** where you found it (Reddit, LinkedIn, email, etc.)
- **URL:** link to repo, product page, or conversation
- **Notes:** why it matters, what caught your attention
- **Date added:** YYYY-MM-DD
```

---

## Pending Review

(none)

---

## Processed

### Hindsight (vectorize-io/hindsight)
- **Source:** Reddit -- someone shared their repo in response to a Lore post
- **URL:** https://github.com/vectorize-io/hindsight
- **Notes:** Agent memory system with retain/recall/reflect operations. Biomimetic approach using entity-relationship graphs, semantic + BM25 hybrid search, cross-encoder reranking. Claims SOTA on LongMemEval benchmarks. Substantial overlap with LoreConvo on persistent conversational memory. Key differences: LoreConvo is Claude-native plugin (SQLite+FTS5, local-first), Hindsight is standalone infrastructure with optional cloud. Hindsight targets enterprise "AI employees", LoreConvo targets individual Claude users. Open source with cloud tier.
- **Date added:** 2026-04-04
- **Processed:** 2026-04-04 -- see competitive_scan_2026_04_04.md (HIGH threat analysis, 3 pipeline items created)
