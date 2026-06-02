---
name: using-loredocs
description: >
  Overview and orientation for LoreDocs. Use this skill when the user asks
  "what is LoreDocs", "how do I use LoreDocs", "how does LoreDocs work",
  "show me what LoreDocs can do", "tour LoreDocs", "intro to LoreDocs",
  or any other overview or orientation request about the product.
  Does NOT trigger on action phrases like "create a vault" or "search the docs"
  -- those go directly to the loredocs action skill.
metadata:
  version: "0.1.7"
  author: "Labyrinth Analytics Consulting"
---

# Using LoreDocs

## What LoreDocs does

LoreDocs is a structured knowledge vault for documents that agents and humans
produce over time -- architecture decisions, product specs, reports, guides,
checklists. Unlike session logs (that is LoreConvo's territory), LoreDocs is for
durable reference material that needs to be organized, versioned, tagged by type,
and retrieved by topic.

You add a document once. Any future Claude session -- or any agent -- can search
for it, inject it into context, or retrieve it by tag. Documents are versioned:
every update keeps the full history, and you can roll back to any prior version.

Data lives locally in `~/.loredocs/loredocs.db` and `~/.loredocs/vaults/`. Nothing
leaves your machine.

## When to reach for LoreDocs

Add a document when:
- You create significant documentation (spec, decision record, guide, architecture doc)
- You want Claude to have access to reference material in future sessions without
  re-reading it from disk
- You want a versioned, searchable copy that outlives any single session

Inject context when:
- Starting a session on a project with a vault
- Claude needs reference material it should not have to re-read from disk
- You want to load a filtered set of docs by tag rather than the full vault

## The action skills

LoreDocs ships these action skills:

| Skill | Trigger phrases | What it does |
|-------|----------------|-------------|
| `loredocs` | "create a vault", "store this document", "add this to the knowledge base", "search the docs", "inject context", "load project docs" | Core action skill: vault management, document add/search/retrieve, context injection, versioning. Start here for all operations. |

Use `using-loredocs` (this skill) for orientation. Use the `loredocs` action skill
for actual operations.

## Key conventions

**One vault per project.** Create a vault named after the project and store all
project-specific docs there. Use `vault_open_workspace("/path/to/project")` to open
or create the workspace-scoped vault automatically.

**Tag liberally.** Tags drive cross-vault discovery (`vault_inject_by_tag`,
`vault_search_by_tag`). Tag every document with at least its topic area and category
(e.g., `architecture`, `decision`, `spec`). Tags are freeform strings -- no
controlled vocabulary required.

**Use `vault_inject_summary` at session start**, not `vault_inject`. A summary
loads titles and descriptions without full content, giving Claude a map of what is
available. Load specific documents on demand with `vault_inject`.

**Categories and priorities.** Categories (`spec`, `guide`, `decision`, `reference`,
`checklist`, `report`, `other`) and priorities (`critical`, `high`, `normal`, `low`)
are for your organization -- they are not enforced. Set them so agents can filter to
the most important material quickly.

**MCP first, fallback second.** LoreDocs works through MCP tools when available.
When the MCP server is unavailable, the bundled script (`query_loredocs.py`) does the
same job silently. You do not need to do anything special -- the `loredocs` action
skill handles the switch transparently.

## Common gotchas

- **DB lives at `~/.loredocs/loredocs.db`** -- not inside the project directory. If
  you moved the plugin or changed the home directory, run `loredocs-cli vault list`
  to verify the DB is accessible.

- **Free tier limits.** Free: 3 vaults, 50 documents per vault, 1 MB per document.
  Pro ($9/mo): unlimited. Check your usage with `vault_tier_status()`.

- **Semantic search requires Pro.** The `vault_find_related` embedding-based links
  and `vault_search` with `semantic=true` require LoreDocs Pro. Free tier uses FTS5
  keyword search, which is fast and covers most use cases.

- **First Pro install requires index build.** After upgrading to Pro, run
  `vault_rebuild_index()` once to build the LanceDB semantic search index. Subsequent
  doc additions are indexed automatically.

- **FTS5 search tips.** Use bare keywords for broad matches (`architecture decisions`).
  Use double quotes for exact phrases (`"session end"`). Avoid special characters in
  search queries.

## Verify install

Ask Claude to run:
```
vault_list()
```

If you see a list of vaults (or an empty list with no error), LoreDocs is connected
and working. If you get a tool-not-found error, the plugin is not loaded. Re-run
`uv sync` and reload the plugin.

## Free vs Pro

Free tier covers 3 vaults with 50 docs each, FTS5 keyword search, full versioning,
and all context injection tools. Pro unlocks unlimited vaults and documents, semantic
search (embedding-based), automatic document relationship discovery, cross-product
session linking with LoreConvo, and the `vault_rebuild_index` tool.

Activate Pro by setting the `LOREDOCS_PRO` environment variable to your license key.
