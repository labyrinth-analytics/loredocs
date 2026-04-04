# Meg QA Report - 2026-04-03 (run B)

**Overall Status: YELLOW**

202 LoreConvo tests (2 expected NEW failures for MEG-041), 39 LoreDocs tests pass. The lore-onboard skill and onboard_verify.py script are solid -- all 23 new tests pass. One HIGH finding: the skill was not copied to the user-facing loreconvo-plugin. Seven new sync tests added to catch this class of omission going forward.

---

## Coverage

This run covers commits since the 2026-04-03 (run A) Meg report:
- `9e6060f` -- ron: build /lore-onboard skill for LoreConvo plugin (TODO #1)

The `c392738` (bug fixes for licensing behavior) commit was already covered in the misdate qa_report_2026_04_04.md run by Brock/Ron (see that report). MEG-038 (unused import in license.py) is CONFIRMED FIXED in this commit.

---

## Summary

Ron built the `/lore-onboard` skill as committed TODO #1. The deliverables are high quality:

1. **SKILL.md** (5-step guided wizard): Steps cover MCP server connectivity, database
   access, save/load/FTS5 search cycle, hooks configuration, and CLAUDE.md integration.
   Instructions are clear and use correct MCP tool names. Error messages include
   actionable remediation steps. Cleanup note (do not delete the test session) is a
   nice UX touch.

2. **onboard_verify.py** (CLI verification script): Clean dataclass-based design with
   CheckResult and OnboardReport. Lazy imports for src/ dependencies (good pattern for
   a script that must first configure sys.path). Parameterized SQL in the cleanup
   path. ASCII-only. Supports --json and --cleanup flags. All imports used.

3. **test_onboard.py** (23 tests): Good coverage across all check functions, report
   formatting, ASCII compliance, and a full integration run with a temp database.
   Test count in the commit message (23) matches actual test method count.

4. **MEG-038 FIXED**: The unused `Encoding, PublicFormat` import in
   `loreconvo/license.py` is gone. Verified in commit diff.

---

## Tests Run

| Suite | Files | Tests | Result |
|---|---|---|---|
| LoreConvo core | test_auto_load, test_vault_suggest | 41 | PASS |
| LoreConvo auto_save | test_auto_save | 17 | PASS |
| LoreConvo database | test_database_new | 21 | PASS |
| LoreConvo CLI | test_cli | 14 | PASS |
| LoreConvo NULL-id migration | test_null_id_migration | 10 | PASS |
| LoreConvo session limit | test_session_limit | 12 | PASS |
| LoreConvo gitignore safety | test_gitignore_safety | 6 | PASS |
| LoreConvo save script | test_save_script | 12 | PASS |
| LoreConvo plugin.json | test_plugin_json_structure | 9 | PASS |
| LoreConvo PRO defaults | test_mcp_json_pro_defaults | 3 | PASS |
| **LoreConvo onboard (NEW)** | **test_onboard** | **23** | **PASS** |
| **LoreConvo plugin sync (NEW)** | **test_plugin_skills_sync** | **7 (2 FAIL - MEG-041)** | **FAIL** |
| LoreDocs core | test_storage, test_tiers | 42 | PASS |
| LoreDocs license | test_license | 14 | PASS |
| LoreDocs phase2 | test_phase2 | 6 | PASS |
| LoreDocs README tools | test_readme_tools | 7 | PASS |
| LoreDocs gitignore safety | test_loredocs_gitignore | 6 | PASS |
| LoreDocs env override | test_tiers_env_override | 10 | PASS |
| LoreDocs MCP tools | test_mcp_tools | skipped | Missing `mcp` module in system Python |
| LoreDocs tier integration | test_tier_integration | skipped | Missing `mcp` module in system Python |

**Total: 202 LoreConvo + 39 LoreDocs = 241 tests (2 intentional failures for MEG-041)**

---

## Findings

### MEG-041 -- HIGH -- lore-onboard skill missing from loreconvo-plugin

**Location**: `ron_skills/loreconvo/skills/lore-onboard/` exists but
`ron_skills/loreconvo-plugin/skills/lore-onboard/` does not.

**Impact**: Users who install the LoreConvo plugin cannot invoke `/lore-onboard`.
The skill only exists in the dev source, not the distributable artifact. This
completely defeats the purpose of building the onboarding wizard.

**Fix (Ron)**: Copy the skill to the user-facing plugin:
```
cp -r ron_skills/loreconvo/skills/lore-onboard \
      ron_skills/loreconvo-plugin/skills/lore-onboard
```
Then verify the new tests pass: `python3 -m pytest tests/test_plugin_skills_sync.py -v`

**Regression guard**: `test_plugin_skills_sync.py` now catches this going forward.
Two tests will fail until Ron applies the fix.

---

### MEG-042 -- LOW -- onboard_verify.py cleanup uses db.conn directly

**Location**: `ron_skills/loreconvo/scripts/onboard_verify.py`, lines 361-362

**Code**:
```python
db.conn.execute("DELETE FROM sessions WHERE id = ?", (report.test_session_id,))
db.conn.commit()
```

**Issue**: Accesses the private `conn` attribute of `SessionDatabase` directly
instead of going through a public API. The SQL is parameterized (not an injection
risk), but it bypasses the abstraction layer. If `SessionDatabase` ever changes
its connection handling (e.g., adds a context manager, connection pooling, or
WAL mode handling), this could break silently.

**Fix (Ron, low priority)**: Add a `delete_session(session_id: str)` method to
`SessionDatabase` and use it here. Note that `cleanup=True` is an optional flag
used mainly for testing (the default keeps the test session as a record of install
date), so this path is rarely exercised.

---

### MEG-043 -- ADVISORY -- loreconvo-plugin README does not mention /lore-onboard

**Location**: `ron_skills/loreconvo-plugin/README.md`

**Issue**: The user-facing plugin README has no mention of `/lore-onboard`. Once
MEG-041 is fixed and the skill is deployed, users should know it exists. This
is the primary discovery path for new users.

**Fix (Ron)**: After resolving MEG-041, add a "Getting Started" or "Quick Setup"
section to the README pointing users to `/lore-onboard` as the first step after
installation.

---

## Prior Finding Status

| ID | Severity | Status | Notes |
|---|---|---|---|
| MEG-036 | LOW | OPEN (pre-existing) | Unchanged |
| MEG-037 | HIGH | RESOLVED | PRO defaults verified clean in prev run |
| MEG-038 | LOW | RESOLVED | Unused import removed in 9e6060f |
| MEG-039 | ADVISORY | RESOLVED | Stale git index (prev session artifact) |
| MEG-040 | ADVISORY | RESOLVED | generate_license_key.py committed in c392738 |

---

## New Test Files Added

- `ron_skills/loreconvo/tests/test_plugin_skills_sync.py` (7 tests)
  - Checks that all user-facing skills in source also exist in loreconvo-plugin
  - Exclusion list for intentionally dev-only skills (currently: `loreconvo`)
  - Regression test for MEG-041 (lore-onboard)
  - Self-validating: checks exclusion list doesn't contain stale entries

---

## Security Spot Check

- **onboard_verify.py**: No hardcoded secrets. SQL in cleanup path is parameterized.
  ASCII-only. Path handling uses `pathlib.Path` throughout.
- **SKILL.md**: No secrets. Bash command in Step 4 uses env var `${CLAUDE_PLUGIN_ROOT}`
  correctly.
- **test_onboard.py**: No secrets. Uses `tempfile.TemporaryDirectory()` for isolation.
  All env var patches use `mock.patch.dict`.

No new security concerns from this commit.

---

## Doc Verification

| File | Version | Status |
|---|---|---|
| loreconvo/pyproject.toml | 0.3.0 | OK |
| loreconvo/.claude-plugin/plugin.json | 0.3.0 | OK |
| loreconvo-plugin/.claude-plugin/plugin.json | 0.3.0 | OK |
| lore-onboard/SKILL.md metadata | 0.3.0 | OK |
| loreconvo README | not checked this run | -- |

No version drift detected in changed files.

---

_Report generated by Meg (QA agent) -- 2026-04-03_
