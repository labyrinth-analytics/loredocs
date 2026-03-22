# ProjectVault Plugin

A searchable, organized, version-tracked knowledge base for your AI projects. Store documents, tag them, search across them, and inject context into any Claude conversation.

## What It Does

ProjectVault gives Claude persistent knowledge about your projects. Instead of re-pasting the same reference documents every session, you store them in named vaults and load them on demand.

- **Organize** -- Group documents into vaults by project, client, or topic
- **Search** -- Full-text search across all your vaults instantly
- **Tag & Categorize** -- Label documents with tags and categories for fast retrieval
- **Version History** -- Every update auto-saves the previous version
- **Context Injection** -- Load vault contents into any Claude conversation
- **Free/Pro Tiers** -- Free: 3 vaults, 25 docs each. Pro: unlimited.

## Prerequisites

You need **Python 3.10 or higher** and the `projectvault` package installed:

```bash
pip install projectvault
```

Or install from source:

```bash
git clone https://github.com/labyrinth-analytics/projectvault.git
cd projectvault
pip install -e .
```

## Installation

1. Install the `projectvault` Python package (see Prerequisites above)
2. Install this plugin in Cowork
3. Restart Cowork

The plugin automatically connects to your local ProjectVault server.

## Skills

| Skill | Description |
|-------|-------------|
| `manage` | Create vaults, add and update documents, tag, categorize, search, and organize knowledge |
| `context` | Load vault knowledge into the active conversation for Claude to reference |

## Example Workflows

### Store Project Reference Docs

```
You: Create a vault called "Tax Reference 2025" and add this depreciation schedule: [paste content]
Claude: [Creates vault, adds document, confirms]

You: Tag it with "schedule-e" and mark it as authoritative
Claude: [Tags and prioritizes the document]
```

### Search Across Your Knowledge Base

```
You: Search my vaults for "passive activity loss"
Claude: [Returns matching documents from all vaults with excerpts]
```

### Load Context for a Session

```
You: Load my Tax Reference 2025 vault for this session
Claude: [Injects all documents] Loaded 12 documents from Tax Reference 2025.

You: What does my saved material say about bonus depreciation?
Claude: [Answers using loaded vault content]
```

### Import Files from Disk

```
You: Import all files from ~/Documents/project-docs into my Project X vault
Claude: [Imports text, PDF, Word, Excel, and PowerPoint files]
```

## Where Files Are Stored

All data lives locally on your computer at `~/.projectvault/`. Your documents are plain files on disk -- easy to back up, git-friendly, and portable.

## Available MCP Tools (32 total)

| Tool | What It Does |
|------|-------------|
| `vault_create` | Create a new knowledge vault |
| `vault_list` | List all your vaults |
| `vault_info` | Get details about a vault |
| `vault_archive` | Archive a vault (soft delete) |
| `vault_delete` | Permanently delete a vault |
| `vault_add_doc` | Add a document to a vault |
| `vault_update_doc` | Update a document (auto-saves history) |
| `vault_remove_doc` | Remove a document |
| `vault_get_doc` | Read a document |
| `vault_list_docs` | List documents with sort/filter |
| `vault_search` | Full-text search across all vaults |
| `vault_search_by_tag` | Find documents by tag |
| `vault_tag_doc` | Add/remove tags on a document |
| `vault_bulk_tag` | Tag multiple documents at once |
| `vault_categorize` | Set a document's category |
| `vault_set_priority` | Mark as authoritative/normal/draft/outdated |
| `vault_add_note` | Attach a note to a document |
| `vault_doc_history` | View version history |
| `vault_doc_restore` | Restore a previous version |
| `vault_copy_doc` | Copy a document to another vault |
| `vault_move_doc` | Move a document to another vault |
| `vault_inject` | Load documents into conversation |
| `vault_inject_by_tag` | Load all documents with a tag |
| `vault_inject_summary` | Get a vault overview |
| `vault_import_dir` | Bulk import files from a folder |
| `vault_export` | Export vault files to a folder |
| `vault_link_doc` | Link a related document |
| `vault_unlink_doc` | Remove a document link |
| `vault_find_related` | Find related documents |
| `vault_suggest` | Get context-aware document suggestions |
| `vault_tier_status` | Check your Free/Pro tier status |
| `vault_set_tier` | Upgrade to Pro tier |

## License

MIT -- Labyrinth Analytics Consulting
