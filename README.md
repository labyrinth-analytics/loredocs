# LoreDocs v0.1.12

Your AI project's knowledge base. Organized, searchable, version-tracked.

LoreDocs gives Claude persistent access to your project documentation -- specs, guides, architecture decisions, reference docs -- so it never loses context between sessions. Works with Claude Code, Cursor, OpenAI Codex, and Hermes Agent.

> **Available on the Anthropic Marketplace.** Install directly from Claude, or via PyPI: `uvx loredocs`

## Quick Start

**Prerequisites:** [uv](https://docs.astral.sh/uv/getting-started/installation/) (fast Python package manager).

```bash
# Install uv (one time)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and install
cd /path/to/loredocs
uv sync
```

For detailed installation instructions, see [INSTALL.md](INSTALL.md).

## Using LoreDocs

### Claude Code (Terminal)

```bash
claude --plugin-dir /path/to/loredocs
```

Or inside an existing session:

```
/plugin add /path/to/loredocs
```

Once loaded, Claude has access to all 42 LoreDocs MCP tools automatically. Ask Claude to "create a vault for this project" or "find the architecture doc" and it uses the tools on its own.

### Cowork (Desktop App)

1. Click **+** next to the prompt box
2. Select **Plugins** > **Add plugin**
3. Browse to the `loredocs` source folder

**Shared Database Access:** Cowork runs in a sandboxed VM. To access docs saved from Claude Code, ask Claude:

> "Mount my ~/.loredocs folder"

## How It Works

LoreDocs organizes knowledge into **vaults** -- named containers for related documents. Each vault can hold specs, guides, decisions, checklists, or any text you want Claude to remember.

```
~/.loredocs/loredocs.db          <-- SQLite database (metadata, search index)
~/.loredocs/vaults/<vault-id>/   <-- Document files on disk
```

**Key concepts:**

- **Vaults** group related docs by project or topic
- **Documents** are text files with metadata (tags, categories, priority, notes)
- **Version history** tracks every change to every document
- **Full-text search** via SQLite FTS5 finds anything instantly
- **Injection** loads vault content into Claude's context on demand

## Your Data is Always Available

LoreDocs works through MCP tools when they are available and falls back to bundled scripts automatically when they are not. Your vault documents are safe regardless of MCP status -- the same add, search, and retrieve operations work either way. You do not need to configure anything; the plugin skill handles the switch silently.

## Verify Installation

After installing, verify LoreDocs is working by asking Claude:

> "Run `vault_list` and show me the results."

If you see a list of vaults (or an empty list if this is your first time), LoreDocs is connected. If you get an error about missing tools, re-run `uv sync` and reload the plugin.

## Recommended CLAUDE.md Setup

For the best experience, add the following snippet to your `~/.claude/CLAUDE.md` (global) or your project's `CLAUDE.md`. This tells Claude how to use LoreDocs consistently across sessions.

```markdown
## LoreDocs (persistent project knowledge)

At session start:
1. Call `vault_list` to see available knowledge vaults.
2. Call `vault_inject_summary` for any vaults relevant to the current project.
3. Use this context to understand project architecture, decisions, and reference docs.

During the session:
- If you create significant documentation, add it to LoreDocs with `vault_add_doc`.
- Tag documents for easy cross-vault discovery with `vault_tag_doc`.

At session end:
- If new docs were created or updated, ensure they are stored in LoreDocs for future sessions.
```

**For Cowork users:** Cowork does not run hooks automatically. Add instructions to call `vault_list` and `vault_inject_summary` at session start in your project CLAUDE.md.

## Canonical Project Knowledge

In multi-agent environments, different tools and agents often create improvised mirrors
of shared skill or configuration content -- playbooks, style guides, shared reference
docs. Those mirrors drift. One agent updates the source; the other keeps reading the
stale copy. Two agents in the same project end up operating from divergent knowledge
with no visible signal that anything is wrong.

LoreDocs prevents this by making the vault the single canonical source that every agent
reads. Instead of each agent loading a local file copy, every agent calls
`vault_inject_by_tag` at session start and gets the same vault-managed version.

### Recommended pattern

Store shared content (playbooks, team guidelines, shared specs) as vault documents
rather than as local files that agents copy or mirror.

Agents load the content at session start:

```
vault_inject_by_tag: team-playbook
```

All agents -- regardless of surface (Claude Code, Cowork, CLI, or any future AI tool)
-- call the same vault and receive the same current version. Updating the content
requires editing the vault document once; all agents pick up the change on their next
session start.

Local files (`.claude/skills/`, `.agents/`, or any surface-specific config) become
pointers or bootstrap stubs only -- not the authoritative content. The vault is the
source of truth.

### Example: sharing a playbook across an agent team

```python
# Session start for any agent on the team:
# 1. Inject the shared playbook by tag
vault_inject_by_tag("team-playbook")

# 2. Inject any project-specific reference docs
vault_inject_by_tag("project-architecture")

# Working context is now current -- no local file copies needed.
```

To store the shared content in the vault (one time, or on each update):

```python
# Store (or update) the shared playbook:
vault_update_doc(vault="team-knowledge", doc_id="playbook-id", content=open("PLAYBOOK.md").read())

# Or add it fresh (path= reads directly from disk -- no need to load into context):
vault_add_doc(vault="team-knowledge", name="Team Playbook", path="/absolute/path/to/PLAYBOOK.md", tags=["team-playbook"])
```

Any agent that calls `vault_inject_by_tag("team-playbook")` reads the same document.
No copies, no mirrors, no drift.

## Plans: Free vs Pro

LoreDocs is local-first and free to use. Pro ($9/mo) removes the storage limits and
unlocks semantic (meaning-based) retrieval. Everything runs on your machine on either
plan -- Pro does not add any cloud component.

| | Free | Pro ($9/mo) |
|---|---|---|
| Vaults | 3 | Unlimited |
| Documents per vault | 50 | Unlimited |
| Storage | 500 MB | Unlimited |
| Version history per document | 5 versions | Unlimited |
| Full-text search (FTS5) | Yes | Yes |
| Core MCP tools (create, search, version, tag, inject, import/export) | Yes | Yes |
| Local-first, no cloud, no telemetry | Yes | Yes |
| Semantic search (`vault_search semantic=true`, `vault_rebuild_index`) | -- | Yes |
| Embedding-based document relationships (`vault_find_related`) | Keyword co-occurrence only | Keyword + embedding auto-links |
| Cross-product session linking (`vault_link_session` + 2 more) | -- | Yes (also requires LoreConvo Pro) |

Free tier limits are enforced before writes; Pro removes them. Check your current tier
and usage anytime with `vault_tier_status`. Activate a Pro license with `vault_set_tier`.

> The Pro semantic features use a local embedding model (BGE-small-en-v1.5) and the
> LanceDB index -- still no data leaves your machine.

## Features

- **Vault organization**: Group docs by project with linked project metadata
- **Document versioning**: Full history with rollback to any prior version
- **Tagging and categorization**: Tag docs for cross-vault discovery
- **Priority levels**: Mark docs as critical, high, normal, or low priority
- **Full-text search**: Fast keyword search across all vaults and documents
- **Context injection**: Load specific docs, tags, or vault summaries into Claude's context
- **Bulk operations**: Import directories, bulk-tag, export manifests
- **Document linking**: Connect related docs across vaults
- **Embedding-based document relationships (Pro)**: `vault_find_related` returns both keyword co-occurrence and embedding-based auto-links for Pro users. Uses BGE-small-en-v1.5, cosine >= 0.75, same-vault scoped. Embedding links are archived if you downgrade from Pro to Free.
- **Cross-product session linking (Pro)**: Automatically links vault documents to the most relevant LoreConvo sessions, and vice versa. Three tools: `vault_link_session`, `vault_get_session_links`, `vault_get_linked_sessions`. Requires both LoreDocs Pro and LoreConvo Pro.
- **Tier management**: Free/Pro tiers with configurable limits
- **Local-first**: SQLite database, no cloud dependency, zero API costs

## MCP Tools

LoreDocs provides 47 MCP tools organized by function:

### Vault Management (8 tools)
| Tool | What it does |
|------|-------------|
| `vault_create` | Create a new vault with name and description |
| `vault_list` | List all vaults with doc counts and sizes |
| `vault_info` | Get detailed vault information |
| `vault_archive` | Archive a vault (preserves data, hides from listing) |
| `vault_delete` | Permanently delete a vault and all its documents |
| `vault_link_project` | Link a vault to a project directory |
| `vault_open_workspace` | Open or create the vault scoped to a directory path |
| `loredocs_onboard` | Set up workspace with starter vaults on first install |

### Document Operations (10 tools)
| Tool | What it does |
|------|-------------|
| `vault_add_doc` | Add a new document to a vault (inline content or from file path) |
| `vault_update_doc` | Update document content (creates version history) |
| `vault_remove_doc` | Remove a document from a vault |
| `vault_get_doc` | Retrieve a document with full content |
| `vault_list_docs` | List documents in a vault with filtering and sorting |
| `vault_copy_doc` | Copy a document to another vault |
| `vault_move_doc` | Move a document to another vault |
| `vault_doc_history` | View version history of a document |
| `vault_doc_restore` | Restore a document to a previous version |

### Search and Discovery (5 tools)
| Tool | What it does |
|------|-------------|
| `vault_search` | Full-text search across all vaults |
| `vault_search_by_tag` | Find documents by tag across all vaults |
| `vault_find_related` | Discover documents related to a given doc (Pro only) |
| `vault_suggest` | Proactive suggestions for relevant docs to load |
| `vault_rebuild_index` | Rebuild the LanceDB semantic search index (Pro only; run once after installing Pro deps) |

### Organization (5 tools)
| Tool | What it does |
|------|-------------|
| `vault_tag_doc` | Add tags to a document |
| `vault_bulk_tag` | Tag multiple documents at once |
| `vault_categorize` | Set document category (spec, guide, decision, etc.) |
| `vault_set_priority` | Set document priority level |
| `vault_add_note` | Add a note or annotation to a document |

### Context Injection (9 tools)
| Tool | What it does |
|------|-------------|
| `vault_inject` | Load ranked vault documents into context, packed within a token budget |
| `vault_inject_by_tag` | Load all documents matching a tag, packed within a token budget |
| `vault_inject_summary` | Load a vault summary with doc titles and descriptions |
| `vault_prime` | Pre-load all vault documents by priority order (equivalent to `vault_inject` with no query) |
| `vault_get_injection_cap` | Get the configured token cap for a vault's injection tools |
| `vault_set_injection_cap` | Set a vault's injection token cap (requires `LOREDOCS_ENABLE_CAP_TOOLS=1`) |
| `vault_get_session_token` | Generate a per-session cache key for injection tools |
| `vault_estimate_tokens` | Estimate the token count an injection call would use before running it |
| `vault_get_server_capabilities` | Report which injection/token-budget features this server build supports |

### Import/Export (3 tools)
| Tool | What it does |
|------|-------------|
| `vault_import_dir` | Import a directory of files into a vault |
| `vault_export` | Export a document to a file on disk |
| `vault_export_manifest` | Export vault metadata as a JSON manifest |

### Document Links (2 tools)
| Tool | What it does |
|------|-------------|
| `vault_link_doc` | Create a link between two documents |
| `vault_unlink_doc` | Remove a link between documents |

### Administration (3 tools)
| Tool | What it does |
|------|-------------|
| `vault_tier_status` | Check current tier limits and usage |
| `vault_set_tier` | Set the active tier (free or pro) |
| `get_license_tier` | Check current tier and license key status |

### Cross-product Session Links (3 tools, Pro)
| Tool | What it does |
|------|-------------|
| `vault_link_session` | Create a manual link from a LoreConvo session to a LoreDocs document |
| `vault_get_session_links` | Return LoreConvo sessions linked to a LoreDocs document |
| `vault_get_linked_sessions` | Return LoreDocs documents linked to a given LoreConvo session |

## Portable Project Workspace

LoreDocs and [LoreConvo](https://github.com/labyrinth-analytics/loreconvo) together form
a portable project workspace for all of Claude -- session memory AND structured knowledge,
entirely on your machine.

- **LoreConvo** remembers what you discussed, decided, and left open (episodic + semantic memory)
- **LoreDocs** stores the reference docs, specs, and guides Claude needs (durable knowledge)

Where cloud AI workspaces tie you to one ecosystem, LoreConvo + LoreDocs works across
Claude Code, Cursor, OpenAI Codex, Hermes Agent, and Cowork. Both store data locally in
SQLite. Neither sends anything to an external server.

## Requirements

- Python 3.10+
- macOS or Linux
- [uv](https://docs.astral.sh/uv/getting-started/installation/) package manager
- `mcp` and `pydantic` (auto-installed by `uv sync`)

## Data and Privacy

LoreDocs is **local-first**. All data lives in `~/.loredocs/` on your machine.

- **Data collected:** Document names, content, tags, categories, and vault names you provide when storing documents. No telemetry, usage analytics, or identifiers are collected automatically.
- **Storage:** SQLite database at `~/.loredocs/loredocs.db`; document files in `~/.loredocs/vaults/`. No cloud storage. Override the root directory with the `LOREDOCS_ROOT` environment variable.
- **Third-party sharing:** None. Data never leaves your machine.
- **Retention:** Data is retained until you delete it via `vault_remove_doc`, `vault_delete`, or remove the database files manually. No automatic expiry.
- **Contact:** info@labyrinthanalyticsconsulting.com

Full privacy policy: https://labyrinthanalyticsconsulting.com/privacy

## Troubleshooting

**MCP tools not showing up in Claude Code?**
Make sure you ran `uv sync` first. The virtual environment must exist with dependencies installed.

**"No module named 'mcp'" error?**
The `.mcp.json` points to the virtual environment's Python. If you moved the folder, re-run `uv sync`.

**Cowork can't see docs saved in Code?**
Ask Claude to "mount my ~/.loredocs folder" so Cowork can access the shared database.

## Fallback Script (Direct DB Access)

If the MCP server is unreachable (e.g., in scheduled tasks or automation scripts), `scripts/query_loredocs.py` provides the same core operations directly against the SQLite database.

```bash
# List all vaults
python scripts/query_loredocs.py --list

# Show vault details and document manifest
python scripts/query_loredocs.py --info "My Project Docs"

# Search documents across all vaults
python scripts/query_loredocs.py --search "architecture"

# Add a document to a vault
python scripts/query_loredocs.py --add-doc \
    --vault "My Project Docs" \
    --name "Architecture Overview" \
    --file docs/architecture.md \
    --tags '["architecture", "design"]'

# Add a document from stdin
echo "# Quick Note" | python scripts/query_loredocs.py --add-doc \
    --vault "My Project Docs" \
    --name "Quick Note" \
    --stdin
```

The script auto-discovers the database at `~/.loredocs/loredocs.db` (or pass `--db-path` explicitly). It writes the same schema as the MCP tools, including FTS indexing and on-disk file storage.

## What's New

<!-- WHATS_NEW:START -->

## v0.1.12

### Bug Fixes

- **Cross-product linking to LoreConvo now works.** Database discovery used a
  single default filename convention (`~/.{product}/{product}.db`) for every
  product, which is correct for LoreDocs (`loredocs.db`) but wrong for LoreConvo
  (which uses `sessions.db`). As a result, every cross-product linking tool
  silently reported "Cross-product linking unavailable" on real installs. Fixed.
  (SH-12757)

- **Stale auto-discovered links are cleaned up automatically.** If a document's
  embedding model changes between saves, cross-product links (LoreDocs <->
  LoreConvo) auto-discovered under the old model are now removed before fresh
  links are written, instead of accumulating alongside them. Manually created
  links are unaffected. (SH-10784)

<!-- WHATS_NEW:END -->

See the full [changelog](docs/CHANGELOG.md) for the complete release history.

## License

Business Source License 1.1 (BSL 1.1) - Labyrinth Analytics Consulting

Free for personal/non-commercial use (up to 3 vaults). Commercial use requires
a paid license. Converts to Apache 2.0 on 2030-03-31. See [LICENSE](LICENSE) for details.
