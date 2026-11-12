# LoreDocs

LoreDocs is a searchable, organized, version-tracked knowledge base for your AI
projects. Store documents, tag them, search across them, and inject context
into any agent session.

## What this plugin installs

Hermes runs `uvx loredocs==0.1.34` as a local stdio MCP server. The package
includes 51 MCP tools for vault management, document CRUD, full-text
and semantic search, context injection, and import/export.

## Storage

All data is stored locally at `~/.loredocs/` (or override with the
`LOREDOCS_ROOT` environment variable). Nothing is sent to any cloud service.

## Pro license

A Pro license ($9/month) unlocks semantic search, auto-discovered document
relationships, and other Pro-only tools. Semantic search downloads a Hugging
Face embedding model (BGE-small-en-v1.5, ~130 MB) once on first use. The
server reads its own durable license store at `~/.loredocs/license.json` --
this is LoreDocs' own data, not another tool's credentials.

If `LOREDOCS_PRO` is not set, LoreDocs runs on the free tier (limited vaults
and documents).

## No telemetry

LoreDocs does not send any telemetry or analytics. All processing is local.

## License

The loredocs package is licensed under BUSL-1.1 (Business Source License 1.1).

## Long tool calls

By default Hermes reaches MCP tools through its tool-search bridge. With some
models, a call carrying long multi-line text, such as a document body for
`vault_add_doc`, fails with `tool_call 'calls' is not valid JSON` (Hermes
issues #119640 and #122711). The model may then retry with shorter, one-line
content, so the document is saved with less detail. To avoid this, turn tool
search off in `~/.hermes/config.yaml`:

```yaml
tools:
  tool_search:
    enabled: "off"
```

With tool search off, Hermes sends every tool definition to the model on each
turn, which uses more of the context window.
