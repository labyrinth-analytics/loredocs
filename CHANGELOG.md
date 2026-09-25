# LoreDocs Changelog

The technical record: what moved, in which module, and why. Customer-facing
release notes live in `docs/CHANGELOG.md`.

This file starts at v0.1.23. Earlier releases have customer-facing notes in
`docs/CHANGELOG.md` only; no technical record was kept before this point and
none has been reconstructed.

## v0.1.28 (2026-09-24)

### Added: doc history/restore on fallback and CLI (SH-102198)

Restore logic moved out of `server.py:vault_doc_restore` into
`VaultStorage.restore_document_version()` in `loredocs/storage.py`;
`server.py` now thin-delegates, matching the existing `get_doc_history`
pattern. `scripts/query_loredocs.py` gains `--doc-history DOC_ID` and
`--doc-restore DOC_ID --version N` (rejects version < 1); the CLI gains
`doc history` and `doc restore`. `FALLBACK_CONTRACT.md` documents the ops.

### Added: MCP Server Registry metadata

New `server.json` (name `io.github.labyrinth-analytics/loredocs`, PyPI
package over stdio via `uvx`). `README.md` carries the registry's
`mcp-name:` ownership marker as its final line; the registry validates it
against the PyPI README of this exact version.

### Changed: license-delivery wording

`README.md` and `INSTALL.md` now state automatic key delivery within minutes
(Stripe webhook Lambda) instead of one business day.

## v0.1.27 (2026-09-15)

No module changes. See `docs/CHANGELOG.md` for this release's documentation
correction.

## v0.1.26 (2026-09-08)

### Fixed

- `version_storage.py`: rotation now runs under the document lock after content
  validation and successful replacement, so budget, lock, divergence, and
  `current.new` hash rejections all preserve retained history instead of
  deleting it first.
- `version_storage.py`: history-budget accounting charges outgoing archived
  bytes rather than the incoming replacement, and credits space freed by a
  planned rotation. Rotation validates the `current.new` hash before the
  destructive step, and replays the `rotated_at` stamp idempotently after an
  unlink/stamp interruption.
- `server.py`: the document-history MCP tool renders the structured
  versions/divergence result, including retention status, instead of raising.
- `storage.py`: an explicit empty-content update is a versioned update; an
  omitted content field still leaves content unchanged.
- `server.py`: vault-prime cache identity includes the selection controls and
  resolved caps, and a cache hit reconsiders the full ranked candidate list, so
  omission reporting stays consistent with current injection settings.
- `notion_import.py`: root and nested block pagination is exhausted; page-limit
  continuations retain ordered pending IDs across workspace-saturation exits and
  pending databases. Malformed and cyclic cursors fail explicitly.
- `semantic_search.py`: blank replacement removes stale chunks and an empty
  rebuild clears the derived index.
- `semantic_search.py`: the advertised cosine >= 0.75 auto-link threshold is
  applied as a LanceDB squared distance <= 0.5 on normalized vectors, verified
  against real index operations.
- `feature_manifest.yml`: storage and portability descriptions distinguish the
  SQLite metadata/keyword index from vault content/history, and require the
  complete data directory rather than promising single-file portability.

## v0.1.25 (2026-09-05)

### Added: fallback contract tier -- `--semantic` and `--get-doc` on `query_loredocs.py` (SH-101553)

`scripts/query_loredocs.py` gains `--semantic` on `--search` (Pro; degrades
to keyword search with a stderr tip, never a hard crash) and `--get-doc
DOC_ID` (equivalent to `vault_get_doc`), both delegating to the existing
`VaultStorage.search_semantic()`/`get_document()`/`get_document_content()`
methods -- no hand-composed file paths. `_find_loredocs_db()` now checks
`LOREDOCS_ROOT` ahead of the Cowork-mount/home-dir fallbacks; a set-but-
unresolvable override hard-fails (`sys.exit(1)`, no stdout rows) instead of
silently querying a different corpus (SH-101500). New canonical contract
doc: `FALLBACK_CONTRACT.md`. New drift guard:
`tests/test_fallback_mcp_parity.py` (6 tests), asserting the fallback and
the MCP server agree on every tier-(a) read operation, including both hard
invariants above. Shared `unwrap_result()` helper extracted to
`internal_tools/loremcp_fixtures/fixtures.py` (fixes a FastMCP
string-wrapped-JSON unwrapping bug surfaced while writing this test) so
both products' parity tests import one implementation instead of each
redefining `_payload()`.

### Fixed: test-integrity gap in `test_mcp_tools.py` -- `assert_ok()` never raised (SH-101598)

The file's custom assertion helper only incremented a module-level `FAIL`
counter and printed `[FAIL] ...` on a false condition; it never raised, so
pytest (the repo's actual execution path for this file) reported every one
of the 8 affected test functions as PASSED regardless of whether their
`assert_ok` checks held. 62 of 63 assertions across the file were affected.
`assert_ok` now raises `AssertionError`, verified by a mutation test
(flip an assertion to a guaranteed-false condition, confirm pytest now
reports FAILED, revert). Fixing this unmasked 3 previously-invisible
failures, triaged separately in SH-101601.

### Internal: trust-framing signature alignment for three-way sync (SH-101476)

`derive_session_nonce()` and `wrap_untrusted()` gain backward-compatible
`=None` defaults so this file's signatures align with the LoreConvo hook
and MCP-tool copies now that `scripts/check_trust_framing_sync.py` checks
all three pairwise. No behavior change for LoreDocs callers.

### Documentation: Pro key-issuance runbook note (follow-up to SH-100131)

`README.md`/`INSTALL.md` set the post-checkout expectation for manual Pro
key issuance.

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
