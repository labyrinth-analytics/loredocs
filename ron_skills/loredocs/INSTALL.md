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

## Option A: Install as a Cowork Plugin (Coming Soon)

> **Note:** The Cowork plugin marketplace is not yet live. This option will be available when the marketplace launches. Use Option B (developer install) in the meantime.

Once the marketplace is live, install with:

```
/plugin install loredocs@labyrinth-analytics-claude-plugins
```

---

## Option B: Developer Install (Recommended for Now)

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
      "command": "/absolute/path/to/loredocs/.venv/bin/loredocs",
      "args": []
    }
  }
}
```

Replace `/absolute/path/to/loredocs/` with the full path to your cloned directory
(e.g., `/Users/yourname/projects/loredocs`).

Then restart Claude Code. Run `/mcp` to verify LoreDocs is connected.

---

## Connecting to Cowork

Install via the `.plugin` file in the cloned directory:

1. Open Cowork settings
2. Click "Add plugin from file"
3. Select `loredocs-dev.plugin` from the cloned repo
4. Restart Cowork

---

## Verifying the Installation

Test that LoreDocs is working by calling a tool in Claude:

```
vault_list
```

You should see an empty vault list (or your existing vaults if you have used LoreDocs before).

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
