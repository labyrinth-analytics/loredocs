# LoreDocs Quickstart

Get LoreDocs running in under 5 minutes. By the end, you will have a searchable knowledge base for your AI projects.

---

## Prerequisites

- Python 3.10 or newer
- [uv](https://docs.astral.sh/uv/getting-started/installation/) package manager (recommended) or pip
- Claude Code or Cowork installed

Check your Python version:

```
$ python3 --version
Python 3.10.12
```

If you see 3.10 or higher, you are good to go.

---

## Step 1: Get the Source

Clone or download LoreDocs:

```bash
git clone https://github.com/labyrinth-analytics/loredocs.git
cd loredocs
```

---

## Step 2: Install

Using uv (recommended):

```bash
uv venv
uv pip install -e .
```

Or using pip:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

---

## Step 3: Connect to Claude Code

Add LoreDocs as an MCP server:

```bash
claude mcp add loredocs -- /path/to/loredocs/.venv/bin/python -m loredocs.server
```

Replace `/path/to/loredocs` with the actual path where you cloned the repo.

Or add it manually to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "loredocs": {
      "command": "/path/to/loredocs/.venv/bin/python",
      "args": ["-m", "loredocs.server"]
    }
  }
}
```

---

## Step 4: Verify It Works

Start Claude Code and ask:

> "Run vault_list and show me the results."

You should see either a list of vaults (if you have used LoreDocs before) or an empty list. Either result means LoreDocs is connected.

---

## Step 5: Create Your First Vault

Ask Claude:

> "Create a new vault called 'Tax Reference 2025' with tags tax and 2025"

You should see a confirmation with the new vault ID.

---

## Step 6: Add a Document

Ask Claude:

> "Add a document to the Tax Reference 2025 vault called 'Filing Deadlines' with this content: April 15 is the federal filing deadline. October 15 is the extension deadline."

---

## Step 7: Search Your Vault

Ask Claude:

> "Search my vaults for 'deadline'"

You should see the document you just created in the results.

---

## Where Are My Files?

LoreDocs stores everything locally on your computer:

```
~/.loredocs/
    loredocs.db         (search index and metadata)
    vaults/
        {vault-id}/
            docs/
                {doc-id}/
                    current.md          (your document)
                    extracted.txt       (searchable text)
                    metadata.json       (tags, category, notes)
                    history/            (previous versions)
```

Your documents are plain files on disk. You can back them up, version them with git, or copy them to another computer.

---

## Troubleshooting

**"No matching distribution found for loredocs"** -- LoreDocs is not published to PyPI yet. Use the developer install (Step 2 above).

**MCP tools not showing up?** -- Make sure the path in your settings.json points to the correct `.venv/bin/python` inside the LoreDocs directory.

**PDF or DOCX files not searchable?** -- Install the extraction libraries: `uv pip install pdfplumber python-docx openpyxl python-pptx`

---

## Free Tier Limits

LoreDocs is free for up to 3 vaults. If you need more, upgrade to Pro with a license key. Check your status anytime by asking Claude:

> "What tier am I on in LoreDocs?"

---

## Next Steps

- Read the [MCP Tool Catalog](mcp_tool_catalog.md) for a full list of all 34 tools
- Read the [INSTALL Guide](../INSTALL.md) for detailed installation options
- Read the [Changelog](CHANGELOG.md) for recent updates
