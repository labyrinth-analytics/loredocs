# LoreDocs Changelog

The technical record: what moved, in which module, and why. Customer-facing
release notes live in `docs/CHANGELOG.md`.

This file starts at v0.1.23. Earlier releases have customer-facing notes in
`docs/CHANGELOG.md` only; no technical record was kept before this point and
none has been reconstructed.

## v0.1.32 (2026-10-28)

### Changed: Python floor 3.11; fastembed 0.9.1 + pillow 13.0.0 (SH-105347)

- `pyproject.toml`: `requires-python >=3.11` (was `>=3.10`); `fastembed==0.9.1`
  (was 0.8.0) and an explicit `pillow==13.0.0` pin on fastembed's transitive
  dependency. pillow 13.0.0 fixes 37 advisories in 12.3.0 and needs Python
  >=3.11. `pip-audit -r requirements.txt`: no known vulnerabilities. fastembed
  pins carry CVE-monitor comments (SH-104652).

### Added: configurable MCP tool groups (SH-104672)

- Core + optional tool-group registry. Optional groups are disabled via the
  `configure_tools` MCP tool, `LOREDOCS_TOOL_GROUPS`, or `tool_groups` in
  `config.json`; disabled tools are removed from the FastMCP registry at
  startup with `remove_tool()` (uncallable, not hidden). Malformed config
  fails closed to core + ALWAYS_ON.

### Added: `vault_rebuild_index_status` (SH-104534, SH-104688, SH-104947 D-38)

- The orphaned status tool is now registered. `storage.rebuild_lance_index`
  returns the real `total_in_db` (all non-deleted docs, not the post-skip
  count), and the ETA no longer extrapolates embedding-phase progress into the
  untimed table-build/FTS step.

### Added: autolink relink tool (SH-104427, SH-104432, SH-105175)

- `_auto_link_doc_cooccurrences` emits deterministic IDs via `_make_link_id`
  (was `uuid4()[:12]`).
- `VaultStorage.relink_autolinks(include_embeddings=True)` purges every
  `label LIKE 'auto:%'` row and regenerates with the SH-103637 logic; explicit
  links are never touched. SH-105175 made it a fixed point: two phases
  (rebuild every term index from up-front document frequencies, then link
  against the finished index) instead of one per-doc loop that read a mix of
  rebuilt and stale `doc_cooccurrences`.
- `scripts/relink_autolinks.py`: admin CLI with `--dry-run`, `--root`,
  `--include-embeddings`; verifies zero cross-vault auto-links afterwards.

### Fixed: find_related ranking and coverage (SH-104433, SH-104947 D-10)

- `find_related_docs` caps at 15 and orders explicit > cooccurrence >
  embedding; within the cooccurrence bucket, by shared-term count computed
  from `doc_cooccurrences` at read time, recency as tiebreak.
- `query_loredocs.py --add-doc` delegates to `VaultStorage.add_document()`
  instead of a hand-rolled INSERT that skipped
  `_insert_doc_cooccurrences`/`_auto_link_doc_cooccurrences`, the cause of
  near-zero link coverage in agent-templated vaults. Consequence: `--add-doc`
  now requires the `loredocs` package importable by the running interpreter;
  the 0.1.31 hand-rolled path worked without it.
- `cross_link_doc` caches one `TextEmbedding` instead of reloading the ONNX
  model per document (SH-104967).

### Fixed: link lifecycle and integrity (SH-104429, SH-104431, SH-104946, SH-104974, SH-104947 D-13x)

- `remove_document` deletes `doc_links` (both directions) and
  `doc_cooccurrences` in the same transaction; `delete_vault` deletes the
  vault's `doc_cooccurrences` and calls `_lance_delete_safe` per doc.
- `vault_verify` detects dangling `doc_links`/`doc_cooccurrences` and drops a
  false "Missing version numbers" finding.
- `move_document`: SQL fix (D-23) and `UPDATE OR IGNORE` on the `vault_id`
  update so a UNIQUE logical-key collision with fresh auto-links no longer
  aborts the move.
- `link_doc`/`unlink_doc`: explicit links coexist with auto-links for the same
  pair.

### Fixed: search (SH-104947 D-14, SH-104538 D-35)

- `sanitize_fts_query` checks for quoted phrases before tokenizing, restoring
  FTS5 phrase search that was flattened to a bare AND query.
- Malformed FTS5 (unbalanced double quote or parentheses) returns an error
  string naming the problem.

### Fixed: semantic index self-heal (SH-104947 D-16b)

- `rebuild_lance_index` re-extracts from `current{ext}` when `extracted.txt`
  is missing instead of skipping the doc (`missing_extracted_txt`).

### Fixed: cross-product session links (SH-104536, SH-104537, SH-104947 D-31)

- `get_cross_product_links()` queries both directions with a UNION, so
  `vault_get_session_links` and `vault_get_linked_sessions` agree.
- `vault_link_session` checks the session exists in LoreConvo (read-only
  connection; degrades open if LoreConvo is unavailable) and caps manual links
  per doc at 500 (`_CROSS_LINK_CAP_PER_DOC`).
- Discovery skips a LoreConvo session whose row is deleted/expired but still
  has a stale vector in `sessions.lance`.

### Fixed: input validation and path safety (SH-104430, SH-104538, SH-104685, SH-104812)

- `vault_export` refuses absolute paths and paths escaping the server's
  working directory.
- `create_vault` refuses a duplicate vault name (`ValueError`; exact match,
  archived vaults included). The `vault_create` tool returns it as an
  `Error: ...` string. `VaultStorage.unique_vault_name()` returns the base
  name or `"base (N)"`; `vault_open_workspace` and `query_loredocs.py
  --workspace` use it, so a folder named like an existing vault no longer
  fails (SH-105506, Meg release QA F1/F10).
- `DocAddInput` no longer sets `str_strip_whitespace`, preserving trailing
  newlines (D-05).
- `loredocs_onboard` is a no-op on a store with vaults but no Config vault
  (D-34); directory import is idempotent (D-27).
- `_is_system_directory` rejects descendants of `_SYSTEM_DIRECTORIES`, not
  only exact matches; `vault_open_workspace` refuses them (D-29). The set
  covers `/`, `/etc`, `/usr`, `/bin`, `/sbin`, `/opt`, `/dev`, `/proc`,
  `/sys`, `/boot`, `/srv`, `/mnt`, `/media`, `/root`, `/System`, `/Library`,
  `/Applications`, `/private/etc`, `/cores`, `/Volumes`, so `/usr/local`,
  external volumes and WSL `/mnt/c` are refused too.
- INSTALL.md export example uses a relative directory and states the
  working-directory rule (SH-105506).

### Fixed: import (SH-104472, SH-104474, SH-104473, SH-104533)

- CLI: `@cli.group(name='import')`. Click 8.3 registered `import_()` as
  `import-`.
- `storage.import_directory` stores each file's relative path in notes and
  takes `skip_config_files` (default on); `vault_import_dir` passes it
  through; `query_loredocs.py --include-config-files`.
- `notion_import.py`: toggle children render inside `<details>`
  (`_flatten_block` appends the closing tag); falsy child text is dropped so
  `table_row` children leave no blank lines; image/file placeholders read
  `block_data["type"]` (`uploaded file` vs `external content`);
  `child_database` blocks render a placeholder with title, id, and the
  `--database-id <id>` hint.

### Changed: packaging and metadata (SH-104371, SH-104686, SH-104850, SH-105439, SH-104538)

- Hermes portable manifests (`plugin.json`, `mcp.json` with `type: stdio`)
  are generated into `integrations/hermes/`; the subdir `pyproject.toml` was
  removed.
- `compat_check.py` reports `loredocs.__version__` as `product_version`;
  version metadata falls back cleanly on `PackageNotFoundError`.
- `server.json` (MCP Registry) version surfaces are synced by the release
  inventory; `glama.json` added for Glama maintainer recognition.
- `check_doc_sync.py` detects every tool-count phrasing in README/INSTALL
  (SH-105036).

## v0.1.31 (2026-10-16)

### Security

- Updated the MCP library (`mcp[cli]`) from 1.28.1 to 1.30.0 to fix
  CVE-2026-59951. The startup compatibility check now expects 1.30.0.

### Improved

- Semantic search loads its embedding model once per process and shares it,
  which cuts memory use and repeat load time.

## v0.1.30 (2026-10-15)

### Added: Hermes Agent portable plugin manifests (SH-103529, SH-103530, SH-103627)

Root `plugin.json` and `mcp.json` (Agent Plugins v1 portable format, with
`$schema`) are now generated outputs of `scripts/generate_runtime_config.py`,
pinned to the release version, so `release.sh` keeps them in step.
`hermes plugins validate ron_skills/loredocs` passes (2026-10-09; findings
are vendored-dependency false positives, spec R6b). Minimum Hermes is 0.21
(`portable_plugin_manifest` first ships in 0.21.1).

### Changed: Hermes install docs (SH-103531)

README and INSTALL.md gain a Hermes section with licensing, storage and
telemetry disclosures (spec R2-R4). Until the Hermes plugin catalog listing
merges, the documented install is a `mcp_servers.loredocs` entry in
`~/.hermes/config.yaml`; the catalog command is restored in a docs-only push
after merge. INSTALL.md's Claude Code/Cowork option now adds the public
marketplace (`labyrinth-analytics/claude-plugins`) instead of a local
monorepo path, and the stale Anthropic-marketplace note is removed.
`pyproject.toml` gains `[project.urls]` (Homepage, Repository, Bug Tracker).

### Changed: vault_find_related autolink quality (SH-103637)

`storage.py`: embedding autolink now queries the Lance index with the
document's extracted text (`_get_doc_text_for_embedding()`) instead of its
name, which only matched similar titles. Co-occurrence linking is scoped to
the source document's vault, and `min_shared_terms` rises from 3 to 5.

### Fixed: embedding autolink created no links outside the default root (SH-104182, SH-104185)

The SH-103637 text lookup hardcoded `~/.loredocs`, so with `LOREDOCS_ROOT`
set (and in tests) it found no `extracted.txt`, returned an empty query and
skipped linking. The root is now derived from the open connection's
`PRAGMA database_list`, then `LOREDOCS_ROOT`, then `~/.loredocs`.

### Fixed: fallback `--doc-restore --version 0` error (SH-102603)

`scripts/query_loredocs.py` treated `--version 0` as a missing argument
(`if not args.version`). It now checks `is None`, so 0 reaches validation,
and the usage error states `N >= 1`.

## v0.1.29 (2026-10-07)

### Added: fallback parity for related-docs, prime, workspace, import (SH-102201, SH-102595, SH-102202, SH-102596)

`scripts/query_loredocs.py` gains `--related DOC_ID` (second caller of
`VaultStorage.find_related_docs()`, Pro-gated like the MCP tool), `--prime
VAULT` with `--max-tokens`, `--cap-behavior`, `--session-token`,
`--max-single-doc-tokens`, `--safety-factor` (calls
`VaultStorage.get_docs_for_injection()` and `server._do_injection()`, the same
two calls `vault_prime` makes; skips the server's per-process injection cache),
`--workspace PATH` (`get_vault_by_workspace_path()` / `create_vault()`, the
`vault_open_workspace` path), `--import-dir --vault V --directory PATH`
(`VaultStorage.import_directory()`, with `--tags`, `--category`,
`--no-recursive`), and `--import-notion-report` (`_notion_extra_available()`,
read-only readiness check). `FALLBACK_CONTRACT.md` documents each op and
its MCP counterpart; `FEATURE_SURFACES` exceptions replaced with introspected
ops.

### Changed: MCP Registry description

`server.json` description shortened to the registry's 100-character limit
(`mcp-publisher validate` passes).

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
