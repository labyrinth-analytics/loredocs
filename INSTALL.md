# LoreDocs Installation Guide

**LoreDocs** gives you a searchable, organized, version-tracked knowledge base for your AI projects. Works with Claude Code, Cursor, OpenAI Codex, and Hermes Agent.

---

## Prerequisites

- **uv** (which provides `uvx`) -- this is the only thing you need to install
- One of: Claude Code, Cursor, OpenAI Codex, or Hermes Agent installed

LoreDocs runs through `uvx`, which downloads a pinned copy of the server and
manages its own Python. You do not need to create a virtual environment, and you
do not need a particular system Python.

Install uv if you do not have it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Check it is available:

```bash
uvx --version
```

If that prints a version, you are good to go.

---

## Option A: Install as a Cowork Plugin (Recommended)

The LoreDocs plugin is ready to install locally. First register the local marketplace,
then install from it -- this is the same flow as the eventual public marketplace install:

```
/plugin marketplace add ~/projects/side_hustle/marketplace/claude-plugins
/plugin install loredocs@labyrinth-analytics-claude-plugins
```

Then restart Cowork. LoreDocs MCP tools will be available in your next session.

> **Anthropic marketplace:** Once the plugin is listed on the Anthropic marketplace,
> the `/plugin marketplace add` step will not be needed -- install directly with the
> second command.

---

## Option B: Developer Install

Clone the repo and run the one-command installer:

```bash
git clone https://github.com/labyrinth-analytics/loredocs.git
cd loredocs
bash install.sh
```

The installer will:
1. Check that `uv` is available (nothing is pip-installed)
2. Install the LoreDocs package and all dependencies
3. Verify the entry point binary was created
4. Create the database directory at `~/.loredocs/`

You should see output ending with `Installation complete!`.

### Manual install (if you prefer):

```bash
uv run --with . loredocs
```

---

## Connecting to Claude Code

After installation, register LoreDocs with Claude Code using the `claude mcp add` command:

```bash
claude mcp add --scope user \
  "--env=LOREDOCS_PRO=<your-license-key>" \
  loredocs -- \
  uvx loredocs==<version>
```

Replace `<version>` with the version you want to pin to (for example `0.1.15`). There is no path to substitute: uvx resolves the package itself.

The `--env=LOREDOCS_PRO=<your-license-key>` flag is optional -- omit it if you are using the free tier. The `--scope user` flag registers LoreDocs for all Claude Code sessions (not just the current project).

> **Why `claude mcp add` instead of editing settings.json?** Claude Code reads
> user-level MCP servers from `~/.claude.json`, managed by `claude mcp add --scope user`.
> Adding `mcpServers` entries to `~/.claude/settings.json` is silently ignored --
> the server will not load. (GitHub issue #4976.)

### Environment variables

| Variable | What it is for | How to set it |
|----------|---------------|--------------|
| `LOREDOCS_PRO` | Your Pro license key (optional) | `--env=LOREDOCS_PRO=<key>` in the `claude mcp add` command |

If `LOREDOCS_PRO` is not set, LoreDocs runs on the free tier (limited vaults and documents).

### Verify the connection

After running `claude mcp add`, restart Claude Code. Run the `/mcp` command to verify
LoreDocs is connected. You should see `loredocs` listed with a green status.

---

## Connecting to Cowork

Install via the `.plugin` file in the cloned directory:

1. Open Cowork settings
2. Click "Add plugin from file"
3. Select `loredocs-dev.plugin` from the cloned repo
4. Restart Cowork

---

## Connecting to Cursor IDE

Cursor uses the same MCP protocol as Claude Code. Configure it by creating a `.cursor/mcp.json` file in your project root:

```json
{
  "mcpServers": {
    "loredocs": {
      "command": "uvx",
      "args": ["loredocs==<version>"],
      "env": {
        "LOREDOCS_PRO": "your-license-key"
      }
    }
  }
}
```

Or copy `.mcp.json` as `.cursor/mcp.json` if you already have a working Claude Code setup.

Restart Cursor after adding the configuration. LoreDocs MCP tools will be available in the next Cursor session.

---

## Connecting to OpenAI Codex

Codex uses a TOML config file at `~/.codex/config.toml`. Add a `[mcp_servers.loredocs]` section:

```toml
[mcp_servers.loredocs]
command = "uvx"
args = ["loredocs==<version>"]

[mcp_servers.loredocs.env]
CODEX_HOME = "/Users/your-username/.codex"  # Required by Codex to locate its own config when running MCP servers as subprocesses
LOREDOCS_PRO = "your-license-key"
```

Replace `<version>` with the version you want to pin to, `your-username` with your macOS username, and `your-license-key` with your Pro license key. Omit the `LOREDOCS_PRO` line if you are using the free tier. There is no install path to substitute -- uvx resolves the package itself.

**macOS note:** `~/.Codex/config.toml` (capital C) resolves to the same location on a case-insensitive filesystem. The canonical path is lowercase `~/.codex/config.toml`.

Restart Codex after saving the file. LoreDocs MCP tools will be available in the next Codex session.

---

## Connecting to Hermes Agent

Hermes Agent uses its own YAML config file at `~/.hermes/config.yaml` -- it does **not** use `.mcp.json`. Add an entry under `mcp_servers:`:

```yaml
mcp_servers:
  loredocs:
    command: uvx
    args:
      - loredocs==<version>
    enabled: true
    env:
      LOREDOCS_PRO: your-license-key
```

Replace `<version>` with the version you want to pin to and `your-license-key` with your Pro license key. Omit the `LOREDOCS_PRO` line if you are using the free tier.

Restart Hermes Agent after saving the file. LoreDocs MCP tools will be available in the next Hermes session.

> **Note:** Hermes Agent was verified compatible with LoreDocs on 2026-06-18.

---

## Verifying the Installation

After connecting LoreDocs to Claude Code, verify it is working:

**In Claude Code**, run:

```
/mcp
```

You should see `loredocs` listed. Then ask Claude:

```
Call the vault_list tool
```

If LoreDocs is working, Claude will respond with a list of your vaults (or an empty
list if this is your first time). A successful empty response looks like:

```
Vaults (0):
(no vaults yet)
```

If you see an error, check the Troubleshooting section below.

---

## Adding Documents to Your Vault

LoreDocs provides two ways to add documents:

**Inline content:** Pass the text directly to Claude. Use this for short notes, summaries, or content you already have in your context.

**File-based ingest:** Use the `path` parameter to read documents directly from your disk. This is useful for large documents, PDFs, or files you want to import without loading them into your Claude context. Ask Claude:

```
Add the file ~/my-project/docs/architecture.md to my vault
```

Claude will use the file-based ingest feature to load the document directly from disk and store it in LoreDocs.

---

## Importing Existing Notes

### Obsidian vault import

1. Open Claude with LoreDocs connected. Create a vault for the notes:

   ```
   Create a vault called "my-notes"
   ```

2. Call `vault_import_dir` with the path to your Obsidian vault directory:

   ```
   Import my Obsidian vault at /Users/yourname/Documents/MyVault into the "my-notes" vault
   ```

   LoreDocs imports all nested folders recursively. Notes with tags in YAML frontmatter (`tags: [a, b, c]`) have those tags preserved in LoreDocs.

3. Verify the import succeeded:

   ```
   Search the "my-notes" vault for a term you know appears in your notes
   ```

**Limitations:** Obsidian aliases, created dates, and backlinks are not imported. The document title is taken from the filename if no `title` key exists in frontmatter.

---

### Notion export import

1. In Notion, open the page or database you want to export. Click the `...` menu, choose **Export**, and select **Markdown & CSV** format. Download and extract the ZIP file to a local directory.

2. Call `vault_import_dir` with the path to the extracted directory:

   ```
   Import the Notion export at /Users/yourname/Downloads/My-Notion-Export into my "my-notes" vault
   ```

   All Markdown content is imported and becomes full-text searchable.

3. After import, manually add tags to key documents to make them easier to find later:

   ```
   Tag the document "Project Overview" with ["project", "overview"]
   ```

**Limitations:** Notion properties (Status, Owner, etc.) are not mapped to LoreDocs tags. Only the text content is imported. For databases, each row exports as a separate Markdown file.

---

## Supported Storage Substrates

LoreDocs stores document content as plain files on disk with atomic write
ordering (temp + rename, never writing into a destination path).

| Vault root location | Support | Guarantee |
|---|---|---|
| Local disk (APFS, ext4, NTFS on a local volume) | Supported | A substrate that misreports writes can lose the most recent save, but can never destroy or corrupt a version already on disk. |
| Cloud-sync folder (Dropbox, iCloud Drive, OneDrive, Google Drive) | Best-effort | Newest save may be lost or resurrected by the sync client. |
| Network mount (SMB, NFS, sshfs) | Best-effort | Advisory locks may be no-ops, so concurrent clients can lose an update. |
| Container bind mount / WSL cross-OS path | Best-effort | Same guarantees as the underlying filesystem. |

A one-time warning is emitted when a vault root is detected under a known
cloud-sync directory. Suppress with `LOREDOCS_SUPPRESS_SUBSTRATE_WARNING=1`.

The `metadata.json` file in each document directory is strictly derived from
the SQLite database. The database is the source of truth. Do not edit
`metadata.json` directly.

## Pre-Upgrade Verification

Before upgrading LoreDocs, run a read-only integrity scan to check for
legacy vault anomalies:

```
vault_verify --pre-upgrade
```

This checks every document for version-number divergence, gaps in the version
sequence, and unrecognized files. It writes `.upgrade_scan.json` (a report,
not state) and does not modify any data. Anomalous documents are write-refused
after upgrade until you acknowledge them with `vault_verify --repair`.

## Mixed-Version Client Warning

Sharing a `~/.loredocs` directory between a pre-0.1.18 and a 0.1.21+ client
is **unsupported**. The older client does not take the per-document lock and
retains the pre-fix version-write bug, so concurrent mixed-version operation
can lose one archived version. Run `vault_verify` to detect any resulting
divergence.

---

## Troubleshooting

**"Module not found" or "command not found" error**

Usually the pinned environment is incomplete or stale. Refresh it -- uvx rebuilds
the environment from scratch:

```bash
uvx --refresh loredocs==<version>
```

Use the same version your client is configured with (see `.mcp.json`). There is
no `.venv/` to delete: since the unified-uvx release, nothing is pip-installed
into the source tree.

**`$HOME` or `~` not expanding in settings.json**

Claude Code does not expand shell variables in `settings.json`. Replace any `~` or
`$HOME` with the full absolute path to your home directory
(e.g., `/Users/yourname` instead of `~`).

**Free tier limit reached**

The free tier limits the number of vaults and documents. When you reach the limit,
tools return a message explaining how to upgrade. Contact Labyrinth Analytics for a
Pro license key, then re-run `claude mcp add --scope user` with `--env=LOREDOCS_PRO=<your-key>` included.

---

## Data Storage

All vault data is stored locally at `~/.loredocs/`. Nothing is sent to any cloud service.

---

## Backing up your data

**Back up the entire `~/.loredocs/` directory.** A backup of the database file alone
(`loredocs.db`) is not enough -- it restores an index that points at missing files.

### What lives where

```
~/.loredocs/
    loredocs.db          <- index, search metadata, and version counts only
    config.json          <- server configuration
    docs.lance/          <- semantic index (Pro tier only)
    vaults/
        {vault-id}/
            docs/
                {doc-id}/
                    current.md      <- live document content
                    metadata.json
                    extracted.txt   <- full-text search extraction
                    history/
                        v1.md       <- previous versions (filesystem only)
                        v2.md
```

- `loredocs.db` holds the index, tags, search metadata, and counts of how many
  versions a document has. It does NOT hold the document text itself.
- `vaults/{vault-id}/docs/{doc-id}/current.*` holds the actual content of each document.
- `vaults/{vault-id}/docs/{doc-id}/history/` holds every previous version. Version
  history is filesystem-only -- it is not stored in the database. If you restore the
  database without the filesystem, history is gone.

### How to back up

**Simplest: tar the directory**

```zsh
tar -czf loredocs-backup-$(date +%Y%m%d).tar.gz ~/.loredocs
```

**Incremental: rsync to another location**

```zsh
rsync -a --delete ~/.loredocs/ /Volumes/Backup/loredocs/
```

**Time Machine (macOS):** Time Machine backs up `~/.loredocs/` automatically if your
home directory is included in the backup. No extra configuration is needed.

**Important -- back up cold when possible.** LoreDocs uses SQLite WAL mode.
While the server is running, there may be `-shm` and `-wal` sidecar files next
to `loredocs.db`. Copying those files while they are in use can produce a
corrupt backup. To back up safely:

1. Stop your AI client (Claude Code, Cursor, etc.) to close the MCP connection.
2. Wait a few seconds for SQLite to checkpoint and remove the sidecar files.
3. Run your backup command.
4. Restart your client.

Alternatively, use the CLI export (see below) -- it produces a portable archive
that is always safe to copy.

### Supported migration path: CLI export and import

The safest way to move or restore your vault data is with the built-in export and
import tools. Ask Claude to run them, or use the `loredocs-cli` command:

**Export a vault to a directory:**

```
Export my "my-notes" vault to ~/loredocs-export/my-notes
```

This calls `vault_export`, which writes each document to a file you can read
without LoreDocs installed.

**Export a manifest (all vaults, machine-readable):**

```
Export a manifest of all my vaults to ~/loredocs-export/manifest.json
```

This calls `vault_export_manifest`, which writes a JSON file listing every vault,
document, tag, and category. Use this to audit or migrate your data.

**Import from a directory:**

```
Import the directory ~/loredocs-export/my-notes into a vault called "my-notes"
```

This calls `vault_import_dir`, which reads every file in the directory and creates
documents in the target vault.

### Version history

Each time you update a document, LoreDocs saves the previous version to the
`history/` folder under that document's directory. You can view and restore
versions using:

- `vault_doc_history` -- lists all saved versions of a document
- `vault_doc_restore` -- restores a document to a specific previous version

Version history lives only on the filesystem. It is not replicated in the database
and is not included in a `vault_export`. To preserve history, back up the full
`~/.loredocs/` directory.

---

## Security note for Pro users

When you enable the Pro tier and build the semantic index, LoreDocs creates a
`docs.lance/` directory under your data root (default: `~/.loredocs/`). This
directory stores vector representations (embeddings) of your document content.
The directory is protected with mode 700 (owner-only access on POSIX systems).

If you back up your data root, include this directory in your backup -- and treat
the backup with the same sensitivity as the source data, since the vectors encode
the semantic content of your documents.

---

## How LoreDocs Accesses Your Data

LoreDocs provides two ways to read and write your vault data:

**MCP tools** are the primary method. Claude uses these automatically during sessions -- tools
like `vault_add_doc`, `vault_search`, and `vault_inject` connect through the MCP server.

**CLI commands** let you manage vault documents from your terminal independent of any Claude session.
After installation, run `loredocs-cli --help` to see available commands.

**Bundled scripts** are the automatic fallback. If the MCP server is unavailable (for example,
after a startup timeout or a rejected tool call), LoreDocs switches to these scripts silently.
The plugin skill handles this; no action is needed on your part.

All three methods read and write the same files at `~/.loredocs/`. Switching between them never
causes data loss.

---

## Upgrading

To upgrade LoreDocs to the latest version:

```bash
cd /path/to/loredocs
git pull
bash install.sh
```

The installer detects the existing venv and updates it in place.

---

## More Documentation

- [Quickstart Guide](docs/quickstart.md) -- get up and running in 5 minutes
- [MCP Tool Catalog](docs/mcp_tool_catalog.md) -- all 42 tools explained in plain English
- [Changelog](docs/CHANGELOG.md) -- what changed in each release
