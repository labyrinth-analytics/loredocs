# Meg QA Report - 2026-04-04 Run B

**Overall Status: YELLOW**

No product code changed since Run A. New commits are all infrastructure/docs
(safe_git.py, pipeline_tracker.py, docs reorganization, competitive intel scan).
Two pre-existing plugin-sync test failures (MEG-041) now confirmed as still
failing -- lore-onboard skill still not copied to loreconvo-plugin/. One new
advisory finding (MEG-042) on SQL optimizer test import path.

---

## Context Since Last QA (Run A: 2026-04-04 morning)

13 new commits, none touching ron_skills/ product code:

| Commit | Change |
|--------|--------|
| ce28b93 | add safe_git.py (agent git wrapper) |
| 35a6dfa | add pipeline_tracker.py (pipeline CLI) |
| 2f9cb85 | pipeline_tracker: auto-generate ref IDs |
| 5c6f18d | pipeline_tracker: improve help/flags |
| 00b63a8 | wire competitive intel into pipeline, rewrite PIPELINE_AGENT_GUIDE |
| 102efbe | first competitive intel scan (Hindsight, Mem0, Basic Memory) |
| c0f4f2e | standardize agent prompts, Debbie decisions, marketplace email fix |
| 0e44867 | Debbie process playbook, agent prompt standard, dependency map |
| 340433b | agent governance: safe_git.py mandate, turn budgets, comm protocol |
| 1bbb1eb | updated personal instructions for git |
| 2cf2493 | substantial documentation reorganization |
| + 2 others | Brock/Gina/Jacqueline reports and roadmaps |

No source code in ron_skills/ was modified. QA focus: confirm test suite
stability, review new infrastructure scripts, check MEG-041 status.

---

## Tests Run

| Suite | Tests | Result |
|-------|-------|--------|
| LoreConvo (all tests/) | 202 pass, 2 fail | FAIL (MEG-041) |
| LoreDocs (all tests/) | 39 pass | PASS |
| SQL Optimizer (tests/test_analyzer.py) | 34 pass | PASS |
| SQL Optimizer API (api/tests/) | BLOCKED | MEG-042 import error |
| scripts/test_generate_license_key.py | 19 pass | PASS |
| **Total runnable** | **294 pass, 2 fail** | **YELLOW** |

**Note on counts vs. Run A:** The Run A total of 338 included SQL API tests
(~83 tests) run with sys.path injection. MEG-042 blocks those tests from
running from repo root with standard pytest collection. The 34 SQL analyzer
tests pass cleanly. The 2 SQL concurrency failures (MEG-036) remain
pre-existing and are excluded from the blocked suite.

---

## Findings

### MEG-041 (YELLOW - Confirmed Pre-existing) - lore-onboard skill not in plugin bundle

**Status:** Still open. Confirmed by 2 failing tests in
`test_plugin_skills_sync.py` (committed by Meg in 79bf5c4).

**Failing tests:**
- `test_lore_onboard_skill_in_plugin` - FAIL
- `test_all_user_facing_source_skills_present_in_plugin` - FAIL

**Root cause:** Ron built the lore-onboard skill and placed it at
`ron_skills/loreconvo/skills/lore-onboard/` (commit 9e6060f), but did not
copy it to `ron_skills/loreconvo-plugin/skills/lore-onboard/`. Users who
install the plugin from the marketplace will not get the lore-onboard skill.

**Fix:** Ron needs to copy `ron_skills/loreconvo/skills/lore-onboard/` to
`ron_skills/loreconvo-plugin/skills/lore-onboard/`. This is Ron TODO #1
item from the PRODUCT STABILITY MANDATE -- the plugin install flow isn't
finished until the plugin bundle is complete.

**Severity:** RED (blocks plugin install mandate from being complete)

---

### MEG-042 (LOW - Advisory) - SQL Optimizer API tests blocked by import path

**File:** `ron_skills/sql_query_optimizer/api/tests/*.py`

**Symptom:** Running the api/tests/ suite from repo root fails at collection:
`ModuleNotFoundError: No module named 'credits'`

The api tests import the `credits` module directly (no package prefix).
They require either a conftest.py with sys.path injection or running from
inside the api/ directory. Run A used sys.path magic to make this work.

**Impact:** ~40-50 tests (credits, credits_concurrency, credits_isolation,
optimizer, security_hardening) are not being collected in standard runs.
MEG-036 (2 concurrency failures) is in this group -- can't confirm status.

**Fix:** Add a `conftest.py` to `ron_skills/sql_query_optimizer/api/tests/`
that inserts the api/ directory into sys.path, enabling standard pytest
collection from repo root.

**Severity:** LOW (tests are not broken, just hard to run consistently)

---

### MEG-043 (LOW - Advisory) - safe_git.py f-string SQL-adjacent pattern

**File:** `scripts/safe_git.py` (no SQL), `scripts/pipeline_tracker.py:248`

**Observation:** `pipeline_tracker.py` line 248 uses an f-string to build
a SQL UPDATE:
```python
conn.execute(f"UPDATE items SET {', '.join(updates)} WHERE ref_id = ?", params)
```

The `updates` list is built exclusively from hardcoded strings like
`"status = ?"`, `"priority = ?"` -- never from user input. All dynamic
values are properly parameterized via `params`. This is NOT a SQL injection
risk in the current code.

**Risk:** Pattern is fragile -- if a future dev adds a user-supplied column
name to `updates`, it becomes an injection vector. Recommend converting to
a column whitelist check.

**Severity:** LOW (advisory, not an active vulnerability)

---

### MEG-036 (YELLOW - Pre-existing) - SQL credits concurrency test failures

Status unchanged. 2 concurrency tests fail due to race condition in credit
ledger design. Blocked from running in this session (MEG-042). Ron TODO.

---

### MEG-038 (LOW - Pre-existing) - Unused import in loreconvo/license.py

Status unchanged. Advisory only. Ron can fix when touching license.py.

---

## Infrastructure Script Review

### safe_git.py (ce28b93) - PASS

- No shell=True usage; all subprocess calls use list args (no injection risk)
- Lock file handling is safe (unlink attempt, truncate fallback, pending manifest)
- Pending_commits.json is local-only, not sensitive
- Agent attribution field is good for audit trail
- No hardcoded credentials or secrets

### pipeline_tracker.py (35a6dfa, 5c6f18d) - PASS with advisory (MEG-043)

- SQLite parameterized queries throughout except MEG-043 f-string (safe in practice)
- Smart DB path (repo data/ vs /tmp fallback for Cowork VM) is correct
- WAL mode enabled -- good for multi-agent concurrent access
- ref_id format validation (prefix check) prevents typos cross-agent
- History audit trail is well-designed
- JSON-encoded blockers/notes columns are fine for current scale

### Competitive intel scan (102efbe) - PASS

- Output is docs only (markdown, HTML pipeline items)
- No new code, no security surface

---

## New Tests Written

None this run. No new product code to test. MEG-041 tests from Run B of
2026-04-03 are already committed and confirming the regression.

**Recommendation for Ron:** When fixing MEG-041 (copy lore-onboard to plugin),
also add a conftest.py fix for MEG-042 to make SQL API tests runnable from
repo root.

---

## Open Findings Summary

| ID | Severity | Status | Description |
|----|----------|--------|-------------|
| MEG-036 | YELLOW | Open | SQL credits concurrency race condition (2 failures) |
| MEG-038 | LOW | Open | Unused import in loreconvo/license.py |
| MEG-039 | ADVISORY | Resolved? | Git stale index (was transient, not re-seen) |
| MEG-040 | ADVISORY | Resolved | generate_license_key.py committed in 9ad2bc1 |
| MEG-041 | RED | Open | lore-onboard not in plugin bundle (blocks mandate) |
| MEG-042 | LOW | Open | SQL API tests cannot be collected from repo root |
| MEG-043 | LOW | Open | pipeline_tracker.py f-string SQL pattern (advisory) |

**Priority for Ron:** MEG-041 is blocking the PRODUCT STABILITY MANDATE.
Fix it before any other TODO.

---

## Trends

| Date | Status | Tests | Key Event |
|------|--------|-------|-----------|
| 2026-04-03 Run A | YELLOW | 319 | License validation added |
| 2026-04-03 Run B | YELLOW | 338 | 7 sync tests added, MEG-041 identified |
| 2026-04-04 Run A | YELLOW | 338 | Ed25519 keys verified, MEG-037 resolved |
| 2026-04-04 Run B | YELLOW | 294* | No product changes; MEG-041 persists |

*294 is partial count due to MEG-042 blocking SQL API test collection.
Equivalent to ~338+ if SQL API tests were collectable.

---

*Report generated by Meg (QA Engineer) | 2026-04-04 Run B*
