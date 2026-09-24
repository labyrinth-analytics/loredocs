# LoreDocs Fallback Contract

`scripts/query_loredocs.py` is a direct-SQLite fallback for when the LoreDocs
MCP server is unreachable (e.g. scheduled tasks, batch scripts, an MCP client
outage). This document is the canonical, per-product statement of what the
fallback guarantees relative to the MCP server -- read it before relying on
the fallback in place of the MCP tools.

## Tier-(a) operations (the "emergency read path")

These fallback flags cover the read path an agent needs to keep working
while the MCP server is down:

| MCP tool | Fallback | Notes |
|---|---|---|
| `vault_list` | `--list` | |
| `vault_inject_summary` | `--info VAULT` | Vault-level metadata, not a document's content. |
| `vault_search` (keyword) | `--search QUERY` | FTS5, same as MCP. |
| `vault_search` (semantic) | `--search QUERY --semantic` | Pro tier only. |
| `vault_get_doc` | `--get-doc DOC_ID` | One document's full metadata + content. |
| `vault_doc_history` | `--doc-history DOC_ID` | Version history list (SH-102198; extends the read path). |

The delegating ops (`--get-doc`, `--search --semantic`, `--doc-history`)
call the same `VaultStorage` methods the MCP server calls
(`get_document()` / `get_document_content()` / `search_semantic()` /
`get_doc_history()`) -- the
fallback is a second caller of that logic, never a second implementation of
it. If the on-disk layout or search ranking ever changes, both surfaces pick
up the change identically because they share the call, not just a convention.

## Guaranteed invariants

1. **A set-but-unresolvable `LOREDOCS_ROOT` is a hard error, never a silent
   fall-through.** If `LOREDOCS_ROOT` is set but contains no `loredocs.db`,
   every operation exits `1` with an error on stderr and **no rows on
   stdout** -- it will not silently answer from another corpus (auto-discovery
   of a Cowork mount or `~/.loredocs/`). Fix the path, unset the variable, or
   pass `--db-path` explicitly.
2. **`--semantic` degrades, it never crashes.** Without Pro extras (or off
   the Pro tier), `--semantic` prints an upgrade tip to stderr and falls
   through to an ordinary keyword search on stdout. Tip and results are
   never interleaved on the same stream.
3. **DB discovery precedence:** `--db-path` (explicit) > `LOREDOCS_ROOT` (env
   override) > Cowork VM mount (`/sessions/*/mnt/.loredocs/loredocs.db`) >
   `~/.loredocs/loredocs.db`. This matches the MCP server's own resolution.

## Drift guard

`tests/test_fallback_mcp_parity.py` asserts the fallback and the MCP server
agree on every tier-(a) operation against the same corpus, plus both
invariants above. Run per-product:

```
.venv/bin/python -m pytest ron_skills/loredocs/tests/test_fallback_mcp_parity.py
```

## Out of scope

Write operations (`--add-doc`, `--create-vault`, `--update-doc`,
`--delete-doc`, `--archive`, `--restore`, `--migrate-tags`) are not part of
this contract -- they predate it and are not covered by the parity guard.
`--doc-restore DOC_ID --version N` (SH-102198) joins that write-side group:
it is a second caller of `VaultStorage.restore_document_version()` (the
extracted shared core the MCP tool `vault_doc_restore` delegates to), not
part of the emergency read path.
