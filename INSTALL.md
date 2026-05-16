# LoreDocs Installation Guide

**LoreDocs** gives you a searchable, organized, version-tracked knowledge base for your AI projects. Works with Claude Code and Cowork.

---

## Prerequisites

- **Python 3.10 or newer** (macOS/Linux)
- Claude Code or Cowork installed

Check your Python version:

```bash
python3 --version
```

If you see 3.10 or higher, you are good to go.

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
1. Create a Python virtual environment at `.venv/`
2. Install the LoreDocs package and all dependencies
3. Verify the entry point binary was created
4. Create the database directory at `~/.loredocs/`

You should see output ending with `Installation complete!`.

### Manual install (if you prefer):

```bash
python3 -m venv .venv
.venv/bin/pip install .
```

---

## Connecting to Claude Code

After installation, register LoreDocs with Claude Code using the `claude mcp add` command:

```bash
claude mcp add --scope user \
  "--env=LOREDOCS_PRO=<your-license-key>" \
  loredocs -- \
  /path/to/loredocs/.venv/bin/python \
  -m loredocs.server
```

Replace `/path/to/loredocs` with the actual path to your LoreDocs installation. To find it, run `pwd` from inside the loredocs directory.

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

## Troubleshooting

**"Module not found" or "command not found" error**

This means the install did not complete correctly. Delete the `.venv/` folder and
reinstall:

```bash
cd /path/to/loredocs
rm -rf .venv
bash install.sh
```

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
- [MCP Tool Catalog](docs/mcp_tool_catalog.md) -- all 37 tools explained in plain English
- [Changelog](docs/CHANGELOG.md) -- what changed in each release
