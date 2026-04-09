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

> **Public marketplace (coming soon):** Once the marketplace launches publicly, the
> `/plugin marketplace add` step will not be needed -- the second command will work on its own.

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

After installation, add LoreDocs to your `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "loredocs": {
      "command": "/Users/YOUR_USERNAME/projects/loredocs/.venv/bin/loredocs",
      "env": {
        "LOREDOCS_PRO": "your-pro-license-key-here"
      }
    }
  }
}
```

Replace `YOUR_USERNAME` with your Mac username. To find it, open a terminal and run:

```bash
whoami
```

> **Important:** Do not use `$HOME` or `~` in `settings.json`. Claude Code does not
> expand shell variables in this file. Use the full absolute path with your actual
> username instead.

The `env` block is optional -- remove it if you are using the free tier and do not
have a Pro license key. Without it, LoreDocs runs on the free tier.

### Environment variables

| Variable | What it is for | Where to find the value |
|----------|---------------|------------------------|
| `LOREDOCS_PRO` | Your Pro license key (optional) | Provided when you purchase a Pro license |

If `LOREDOCS_PRO` is not set, LoreDocs runs on the free tier (limited vaults and documents).

### Restart Claude Code

After editing `settings.json`, restart Claude Code. Run the `/mcp` command to verify
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
Pro license key, then set it as `LOREDOCS_PRO` in your `settings.json` env block.

---

## Data Storage

All vault data is stored locally at `~/.loredocs/`. Nothing is sent to any cloud service.

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
- [MCP Tool Catalog](docs/mcp_tool_catalog.md) -- all 34 tools explained in plain English
- [Changelog](docs/CHANGELOG.md) -- what changed in each release
