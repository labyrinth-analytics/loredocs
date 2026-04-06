# LoreDocs MCP Tool Catalog

LoreDocs provides 35 MCP tools that Claude calls during your sessions. You do not need to call these directly -- Claude uses them when you ask it to manage your project knowledge base.

This catalog explains what each tool does and when Claude uses it. Tools are grouped by function.

---

## Vault Management (6 tools)

### `vault_create`

Create a new knowledge vault for organizing project documents. A vault is like a folder for a specific project or topic.

**When Claude uses it:** When you say "create a vault for my tax documents" or "start a new vault called X."

**Key parameters:** `name` (required), `description`, `tags`

---

### `vault_list`

List all your vaults with summary stats: document count, total size, and last modified date. Archived vaults are hidden by default.

**When Claude uses it:** When you say "show my vaults" or at the start of a session to see what knowledge bases exist.

**Key parameters:** `include_archived` (optional, default false)

---

### `vault_info`

Get detailed information about a specific vault, including its full document manifest.

**When Claude uses it:** When you ask "what is in my tax vault?" or when Claude needs details before adding documents.

**Key parameters:** `vault_id` (required)

---

### `vault_archive`

Archive a vault (soft delete). Archived vaults are hidden from `vault_list` by default but can be restored. No documents are deleted.

**When Claude uses it:** When you say "archive the old project vault" or "hide this vault."

**Key parameters:** `vault_id` (required)

---

### `vault_delete`

Permanently delete a vault and ALL its documents. This cannot be undone.

**When Claude uses it:** When you explicitly ask to permanently delete a vault. Claude will confirm before proceeding.

**Key parameters:** `vault_id` (required)

---

### `vault_link_project`

Associate a Claude Project name with a vault. This lets LoreDocs automatically suggest the right vault when you are working in a specific project.

**When Claude uses it:** When you say "link this vault to my side_hustle project."

**Key parameters:** `vault_id` (required), `project_name` (required)

---

## Document Operations (10 tools)

### `vault_add_doc`

Add a text document to a vault. LoreDocs automatically extracts searchable text and stores the document with metadata (tags, category, priority, notes).

**When Claude uses it:** When you say "add this document to my vault" or "save these notes."

**Key parameters:** `vault_id` (required), `name` (required), `content` (required), `tags`, `category`, `priority`, `notes`

---

### `vault_get_doc`

Retrieve a document's metadata and optionally its text content.

**When Claude uses it:** When you ask "show me the depreciation schedule document" or when Claude needs to read a specific document.

**Key parameters:** `doc_id` (required), `include_content` (optional, default true)

---

### `vault_list_docs`

List documents in a vault with sorting and filtering options.

**When Claude uses it:** When you say "what documents are in this vault?" or "show me all documents tagged 'schedule-e'."

**Key parameters:** `vault_id` (required), `sort_by`, `category`, `priority`

---

### `vault_update_doc`

Update a document's content or metadata. LoreDocs automatically saves the previous version to history (so you can restore it later).

**When Claude uses it:** When you say "update the depreciation schedule with these new numbers."

**Key parameters:** `doc_id` (required), `content`, `tags`, `category`, `priority`, `notes`

---

### `vault_remove_doc`

Soft-delete a document. The document is hidden but can be recovered.

**When Claude uses it:** When you say "remove that document" or "delete the old draft."

**Key parameters:** `doc_id` (required)

---

### `vault_copy_doc`

Copy a document from one vault to another, including all metadata.

**When Claude uses it:** When you say "copy this document to my other vault."

**Key parameters:** `doc_id` (required), `target_vault_id` (required)

---

### `vault_move_doc`

Move a document to a different vault. Removes it from the source vault.

**When Claude uses it:** When you say "move this document to the tax vault."

**Key parameters:** `doc_id` (required), `target_vault_id` (required)

---

### `vault_link_doc`

Create a link between two documents across any vault. Use this to connect related documents with a descriptive label (e.g., "references", "supersedes").

**When Claude uses it:** When you say "link these two documents" or "this document references that one."

**Key parameters:** `from_doc_id` (required), `to_doc_id` (required), `label`

---

### `vault_unlink_doc`

Remove a link between two documents (both directions).

**Key parameters:** `from_doc_id` (required), `to_doc_id` (required)

---

### `vault_find_related`

Find all documents linked to a given document. Shows linked documents from any vault.

**When Claude uses it:** When you ask "what documents are related to this one?"

**Key parameters:** `doc_id` (required)

---

## Search and Context Injection (6 tools)

### `vault_search`

Full-text search across document contents using SQLite FTS5. Searches across all vaults or a specific one.

**When Claude uses it:** When you say "search my vaults for depreciation" or "find documents about rental income."

**Key parameters:** `query` (required), `vault_id` (optional)

---

### `vault_search_by_tag`

Find all documents with a specific tag, across one vault or all vaults.

**When Claude uses it:** When you say "find all documents tagged 'schedule-e'."

**Key parameters:** `tag` (required), `vault_id` (optional)

---

### `vault_inject`

Load specific documents into the current conversation context. Use this when you want Claude to have the full text of certain documents available.

**When Claude uses it:** When you say "load the depreciation schedule into this conversation."

**Key parameters:** `doc_ids` (required, list of IDs)

---

### `vault_inject_by_tag`

Load all documents matching a tag into the current conversation context.

**When Claude uses it:** When you say "load all my tax documents."

**Key parameters:** `tag` (required), `vault_id` (optional)

---

### `vault_inject_summary`

Generate a summary overview of a vault's contents for conversation orientation. This gives Claude a birds-eye view of what knowledge is available without loading every document.

**When Claude uses it:** At session start, or when you say "give me an overview of this vault."

**Key parameters:** `vault_id` (required)

---

### `vault_suggest`

Get suggestions for documents that may need attention: outdated documents, documents missing tags, recently updated items.

**When Claude uses it:** When you ask "what needs attention in my vault?" or "any documents I should review?"

**Key parameters:** `vault_id` (optional)

---

## Tagging and Organization (6 tools)

### `vault_tag_doc`

Add or remove tags on a document.

**When Claude uses it:** When you say "tag this with 'schedule-e'" or "remove the 'draft' tag."

**Key parameters:** `doc_id` (required), `add_tags` (list), `remove_tags` (list)

---

### `vault_bulk_tag`

Apply tag changes to multiple documents at once.

**When Claude uses it:** When you say "tag all these documents with 'Q1-2026'."

**Key parameters:** `doc_ids` (required, list), `add_tags` (list), `remove_tags` (list)

---

### `vault_categorize`

Set a document's category. Categories are: `general`, `reference`, `config`, `report`, `template`, `archive`, `imported`.

**When Claude uses it:** When you say "mark this as a reference document."

**Key parameters:** `doc_id` (required), `category` (required)

---

### `vault_set_priority`

Mark a document's priority/status: `authoritative`, `normal`, `draft`, or `outdated`.

**When Claude uses it:** When you say "this is the authoritative version" or "mark that as outdated."

**Key parameters:** `doc_id` (required), `priority` (required)

---

### `vault_add_note`

Attach a contextual note to a document. Notes are timestamped and can be used to annotate changes or add commentary.

**When Claude uses it:** When you say "add a note to this document."

**Key parameters:** `doc_id` (required), `note` (required)

---

### `vault_doc_history`

View the version history for a document. Shows when each version was created and what changed.

**When Claude uses it:** When you ask "show me the history of this document" or "what changed?"

**Key parameters:** `doc_id` (required)

---

## Versioning and Bulk Operations (4 tools)

### `vault_doc_restore`

Restore a document to a previous version. The current version is saved to history first.

**When Claude uses it:** When you say "restore the previous version of this document."

**Key parameters:** `doc_id` (required), `version` (required)

---

### `vault_import_dir`

Bulk import all supported files from a directory into a vault. Supported file types include text files, markdown, PDF, DOCX, XLSX, and PPTX (with automatic text extraction).

**When Claude uses it:** When you say "import all files from this folder into my vault."

**Key parameters:** `vault_id` (required), `directory_path` (required)

---

### `vault_export`

Export all documents from a vault to a local directory.

**When Claude uses it:** When you say "export this vault to a folder."

**Key parameters:** `vault_id` (required), `output_directory` (required)

---

### `vault_export_manifest`

Export a complete manifest of a vault's contents. Useful for sharing, versioning, or pasting into Claude Chat (which does not support plugins).

**When Claude uses it:** When you need a portable snapshot of your vault.

**Key parameters:** `vault_id` (required)

---

## Tier Management (2 tools)

### `vault_tier_status`

Show your current tier (Free or Pro) and usage vs. limits. Free tier allows up to 3 vaults.

**When Claude uses it:** When you ask "what tier am I on?" or "how many vaults can I create?"

**Key parameters:** none required

---

### `vault_set_tier`

Activate a tier (free or pro) for LoreDocs. Pro tier requires a valid license key.

**When Claude uses it:** When you say "upgrade to Pro" or "activate my license key."

**Key parameters:** `tier` (required)

---

## Quick Reference

| # | Tool | One-line summary |
|---|------|-----------------|
| 1 | `vault_create` | Create a new vault |
| 2 | `vault_list` | List all vaults with stats |
| 3 | `vault_info` | Get vault details and manifest |
| 4 | `vault_archive` | Soft-delete a vault |
| 5 | `vault_delete` | Permanently delete a vault |
| 6 | `vault_link_project` | Link a vault to a Claude Project |
| 7 | `vault_add_doc` | Add a document to a vault |
| 8 | `vault_get_doc` | Retrieve a document |
| 9 | `vault_list_docs` | List documents in a vault |
| 10 | `vault_update_doc` | Update document content or metadata |
| 11 | `vault_remove_doc` | Soft-delete a document |
| 12 | `vault_copy_doc` | Copy a document to another vault |
| 13 | `vault_move_doc` | Move a document to another vault |
| 14 | `vault_link_doc` | Link two documents |
| 15 | `vault_unlink_doc` | Remove a link between documents |
| 16 | `vault_find_related` | Find linked documents |
| 17 | `vault_search` | Full-text search across vaults |
| 18 | `vault_search_by_tag` | Search by tag |
| 19 | `vault_inject` | Load documents into conversation |
| 20 | `vault_inject_by_tag` | Load tagged documents into conversation |
| 21 | `vault_inject_summary` | Generate vault summary for context |
| 22 | `vault_suggest` | Suggestions for documents needing attention |
| 23 | `vault_tag_doc` | Add or remove tags |
| 24 | `vault_bulk_tag` | Bulk tag multiple documents |
| 25 | `vault_categorize` | Set document category |
| 26 | `vault_set_priority` | Set document priority |
| 27 | `vault_add_note` | Add a note to a document |
| 28 | `vault_doc_history` | View version history |
| 29 | `vault_doc_restore` | Restore a previous version |
| 30 | `vault_import_dir` | Import files from a directory |
| 31 | `vault_export` | Export vault to a directory |
| 32 | `vault_export_manifest` | Export vault manifest |
| 33 | `vault_tier_status` | Check tier and usage |
| 34 | `vault_set_tier` | Activate a tier |
| 35 | `get_license_tier` | Check current tier and license key status |
