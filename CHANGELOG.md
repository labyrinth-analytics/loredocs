# LoreDocs Changelog

The technical record: what moved, in which module, and why. Customer-facing
release notes live in `docs/CHANGELOG.md`.

This file starts at v0.1.23. Earlier releases have customer-facing notes in
`docs/CHANGELOG.md` only; no technical record was kept before this point and
none has been reconstructed.

## v0.1.24 (2026-09-01)

### Fixed: Notion import preserves block structure (SH-101419)

`loredocs/notion_import.py::_render_block_text` had an early return on
`rich_text` that made every structural handler below it dead code: headings,
bulleted/numbered lists, to-dos and code blocks all flattened to bare text,
and quote/callout/toggle had no handlers at all. Handlers now run before the
generic fallback, heading level is parsed from the trailing digit (the old
`count("_")` math could not distinguish heading levels), and quote/callout/
toggle render as markdown. A committed fixture of realistic Notion block
payloads (`tests/fixtures/notion_blocks.json`) plus table-driven and
round-trip tests lock the exact output per block type.

### Added: semantic index coverage is visible (SH-101414)

The silent-degradation half of SH-101414. `_lance_write_safe` skips index
writes whenever the tier is not Pro and swallows errors by design, so the
derived Lance index can drift below SQLite without any signal -- the state
that produced the original wrong-answer report.

`VaultStorage.search_semantic` now computes per-scope coverage via a new
`_lance_coverage` helper and attaches `index_coverage`
(`indexed_docs`/`indexable_docs`) to both the semantic and FTS-fallback
result dicts, plus a `coverage_warning` string when the index holds fewer
documents than SQLite says are indexable. `vault_search` renders the warning
in both markdown and JSON; `vault_tier_status` gains a
`semantic_index_coverage` block (`indexed_docs`, `indexable_docs`,
`in_sync`), Pro only, so drift is inspectable without running a search.
`DocLanceIndex.indexed_doc_count(vault_id)` backs the count.

`_lance_coverage` mirrors rebuild eligibility exactly -- non-deleted docs
with a non-empty, non-whitespace `extracted.txt` -- so documents with no
extractable text cannot raise a permanent false warning.

Two deliberate non-changes, documented here because both look like
omissions: `prefilter=True` is stated explicitly on the search `.where()`
calls purely as insurance against a future LanceDB default flip (0.30.2
already pre-filters, so removing it is a no-op on the pinned version), and
`rebuild()` deliberately creates NO ANN index -- IVF_PQ cannot train under
256 rows and degrades recall, while the exact flat scan is correct at any
size.

### Fixed: semantic index rebuild is atomic and reports progress (SH-101414)

`loredocs/semantic_search.py::DocLanceIndex.rebuild` dropped the live `docs`
table before building the replacement, so a client-abandoned or crashed
rebuild left the index empty -- the state that produced the silent
partial-index degradation. The rebuild now builds a staging table and swaps
it in with `mode='overwrite'` only after the build succeeds; a failure
mid-build leaves the previous index intact. `rebuild()` accepts a
`progress_cb(done, total)` callback, and `vault_rebuild_index` runs the
rebuild in a worker thread, reporting MCP progress notifications per
document and touching the idle watchdog so a long rebuild is neither silent
nor reaped mid-work. `_auto_link_doc_embeddings` in `loredocs/storage.py`
now pre-filters its similarity search by vault (`prefilter=True`) -- the
same post-filter defect class that broke scoped semantic search. A stale
`loredocs.db.migrationlock` file is removed after a clean migration run
(flock is released by the OS even on crash, so the leftover file was litter,
not a blocker).

## v0.1.23 (2026-08-30)

### Fixed: metadata-only `vault_update_doc` no longer bumps `updated_at` (SH-101146)

`loredocs/storage.py update_document` fell through to the metadata-update
branch even when no updatable field was supplied, rewriting `updated_at` on a
call that changed nothing. A no-op then read as a real edit to
`sync_vault_docs.py`, surfacing as false sync conflicts. The branch now
guards on `name/tags/category/priority/notes` all being `None` and returns the
current row untouched.

Known residue: `history_dir.mkdir(...)` still runs earlier in the function, so
a no-op on a doc with no `history/` directory creates an empty one. Tracked as
SH-101191 (LOW); the database and `updated_at` are unaffected.

### Fixed: no-op update path returns a `divergence` field (SH-101190)

The guard added above returned a meta dict without `divergence`, so its shape
disagreed with `get_document()` and a client reading `result["divergence"]`
raised `KeyError` on no-op updates only. The no-op path now performs the same
non-blocking divergence read as `get_document()`, reporting `None` on any
lock or divergence error rather than failing the read.

### Fixed: `vault_update_doc` rejects unknown parameters at the MCP layer (SH-101189, SH-101253)

Unknown parameters sent by an MCP client were silently dropped: FastMCP's
`ArgModelBase` defaults to pydantic's `extra="ignore"`, so a misspelled field
never reached the tool body and the call reported success having done nothing.

`extra="forbid"` on `DocUpdateInput` (SH-101146) did not fix this -- that model
is constructed inside the function, after FastMCP has already discarded the
unknown key. A second attempt (SH-101189) added `**kwargs` plus a manual
`ValueError`; because `func_metadata()` does not special-case `VAR_KEYWORD`,
`kwargs` became a bogus REQUIRED field in the generated tool schema, breaking
every real call to `vault_update_doc` for as long as it was in tree. Both the
attempt and the fix landed inside this release window, so no published version
ever carried the break.

Resolved by `_forbid_unknown_tool_params("vault_update_doc")`, which sets
`extra="forbid"` on the tool's generated `arg_model` after registration and
rebuilds it -- scoped to this one tool rather than FastMCP's shared
`ArgModelBase`. Verified against the real dispatch path: the schema exposes
`required: ["doc_id"]` with `extra: forbid`, an unknown param raises, and a
valid update succeeds through `mcp.call_tool()`.

### Documentation: Agent SDK local-load note in README (SH-101152)

`README.md` gained a note covering direct Claude Agent SDK consumption:
`git clone` the public repo and point the SDK's local-directory plugin loader
at the repo root, which is already a self-contained plugin directory
(`.claude-plugin/plugin.json` + `.mcp.json`).

### Packaging: Agent Plugins 1.0 manifests tracked at the product root

`plugin.json` and `mcp.json` at the product root are generated by
`scripts/release.sh` and were previously untracked. They are now committed and
carried in `BUMP_FILES`, so their version pins move with each release.
