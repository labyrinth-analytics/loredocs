# Security Report -- 2026-04-05
**Agent:** Brock (Cybersecurity Expert)
**Posture:** NEEDS ATTENTION
**Prior posture (2026-04-04):** NEEDS ATTENTION

---

## Executive Summary

One previously open finding resolved today (SEC-017). No new critical or high findings
introduced. New code reviewed -- local model preprocessing script and pipeline tracker
enhancement -- both assessed as safe. Dependency audit clean (0 CVEs). Overall posture
unchanged at NEEDS ATTENTION. The highest-priority open issue (SEC-011 TOCTOU) is
low-urgency for local-only deployment; no blockers for current Stability Mandate work.

---

## Session Context

**Key events since 2026-04-04 report:**
- Debbie fixed plugin install flow: LoreConvo + LoreDocs now working in Cowork (confirmed 2026-04-05)
- Ron fixed GINA-001/SEC-017: vault_set_tier now validates license before persisting Pro tier (commit b6e65ec)
- Pipeline tracker updated: 'enhancement' type added, Debbie-direct flow added (commit 1e5d882)
- New code: local_model_preprocess.py (Ollama orchestration), scripts/install_dev_plugins.sh
- Meg QA reports: MEG-046/047 new (test regression and doc gap in LoreDocs) -- not security-relevant
- 7 pending commits in pending_commits.json (git push blocked from Cowork VM, expected)

---

## Resolved Since Last Report

### SEC-017 -- RESOLVED (vault_set_tier license bypass)
**Resolved by:** Ron (commit b6e65ec, 2026-04-05)
**Code review:** CONFIRMED FIX. The fix correctly adds a license validation gate before
persisting Pro tier to config.json. Key observations:
- get_license_status() is called before set_tier() when upgrading to Pro
- Both "free" and "invalid_key" modes return clear error messages with instructions
- Downgrade to free does NOT require a license (correct -- no gate on downgrade)
- Dev bypass mode (LOREDOCS_DEV=true) is preserved as expected
- 7 targeted tests added in test_vault_set_tier_license.py covering: no-license rejection,
  invalid-key rejection, valid-license success, dev-bypass success, downgrade-always-allowed
- All 39 LoreDocs tests pass per Ron's commit note
**Assessment:** Fix is correct and well-tested. SEC-017 is fully resolved.

---

## New Findings -- 2026-04-05

### SEC-020 -- INFO: pipeline_tracker.py f-string SQL pattern
**Severity:** INFO
**File:** scripts/pipeline_tracker.py, line 250
**Finding:** cmd_update() builds a dynamic SET clause using an f-string:
  `conn.execute(f"UPDATE items SET {', '.join(updates)} WHERE ref_id = ?", params)`
**Assessment:** SAFE in current implementation. The `updates` list contains only hardcoded
column name strings ("status = ?", "priority = ?", "description = ?", etc.) -- no user
input is interpolated into column names. All actual values are passed through the `params`
list with proper parameterization. Status values are validated against VALID_STATUSES
before being appended.
**Risk:** LOW (pattern risk only). If a future developer adds a new field where a
user-controlled value flows into `updates` instead of `params`, this would become an
injection vector. The pattern is safe today but fragile.
**Recommendation:** Add a comment marking the f-string as intentionally safe and
listing the hardcoded column names. Or refactor to a whitelist-validated pattern.
No immediate action required.

### SEC-021 -- INFO: local_model_preprocess.py subprocess usage
**Severity:** INFO
**File:** scripts/local_model_preprocess.py
**Finding:** Two subprocess.run() calls -- one for Ollama, one for save_to_loreconvo.py.
**Assessment:** SAFE. Both calls use list form (not shell=True), which prevents shell
injection. Arguments are passed as discrete list items, not string concatenation.
Ollama model argument is restricted to the 'choices' allowlist in argparse
('qwen3.5:9b' or 'gemma4'), preventing arbitrary model injection.
The --input file path is user-supplied but validated via Path().exists() before use.
No secrets or credentials are passed through these calls.
**Recommendation:** No action required.

---

## BROCK-REVIEW Item: Competitive Intel Scan (competitive_scan_2026_04_04.md)

**Task:** Assess whether Brock's open security findings would block official Claude
marketplace approval.

**Assessment:**

The official Claude marketplace review criteria are not publicly documented in detail,
but based on standard plugin/extension store guidelines and Anthropic's general security
posture, the following analysis applies:

**Would likely block marketplace submission:**
- CRITICAL vulnerabilities (none open)
- HIGH severity findings (none open)
- Hardcoded secrets in public repo code (none found)
- Known CVEs in dependencies (none found -- pip-audit clean)

**Would NOT block (but should be fixed pre-launch):**
- SEC-011 (MEDIUM): TOCTOU race in LoreDocs export -- acceptable for v0.1.0 alpha
- SEC-016 (LOW): auto_save hook session limit bypass -- limits-enforcement gap only
- SEC-018 (INFO): vault_import_dir/export path restriction -- deferred per 2026-04-04 report
- SEC-019 (LOW): Duplicated license.py -- code quality concern, not security blocker

**Priority fix before marketplace submission:**
- SEC-016 is the only one that could attract scrutiny from a marketplace reviewer
  specifically looking at tier/billing enforcement completeness. Low severity but
  relevant to trust: a user on the free tier could exceed session limits via auto-save
  if the hook does not check the count. Fix it before paying customers are onboarded.
- SEC-011 (TOCTOU) is standard for local file tools and unlikely to block submission.

**Verdict:** Current security posture would NOT block official marketplace submission.
No CRITICAL or HIGH findings. Dependency audit clean. The two MEDIUM/LOW marketplace-
relevant items (SEC-016, SEC-011) are acceptable for an initial listing but should
appear in the "Known Limitations" section of the marketplace listing, or be fixed before
submission. Recommend fixing SEC-016 as part of the pre-launch sprint.

---

## Dependency Audit

**LoreConvo requirements-lock.txt:** pip-audit result: No known vulnerabilities found
**LoreDocs requirements-lock.txt:** pip-audit result: No known vulnerabilities found
**CVE count this run:** 0

---

## Secrets Scan

**Recent commits (HEAD~5..HEAD) scanned for hardcoded secrets:** No secrets found
**API key patterns in source:** Only expected pattern found:
  `ron_skills/sql_query_optimizer/api/optimizer.py` reads ANTHROPIC_API_KEY from env
  (not hardcoded). Safe. Previously noted as SEC-001 (INFO, local .env only).
**New install scripts:** No secrets embedded.
**Git history for .env files:** Clean.

---

## Open Findings Registry

| ID     | Owner | Severity | Status     | Description                                      |
|--------|-------|----------|------------|--------------------------------------------------|
| SEC-001 | Debbie | INFO     | Open       | Anthropic API key in sql_optimizer .env (local, gitignored) |
| SEC-006 | Ron   | LOW      | Open       | CreditManager race condition (LoreConvo)         |
| SEC-011 | Ron   | MEDIUM   | Open       | TOCTOU race in LoreDocs export                   |
| SEC-016 | Ron   | LOW      | Open       | auto_save hook bypasses session limit (LoreConvo) |
| SEC-017 | Ron   | MEDIUM   | RESOLVED   | vault_set_tier no license validation -- fixed b6e65ec |
| SEC-018 | Ron   | INFO     | Open       | vault_import_dir/export: no path restriction (deferred) |
| SEC-019 | Ron   | LOW      | Open       | Duplicated license.py consistency test missing   |
| SEC-020 | Ron   | INFO     | Open       | pipeline_tracker.py f-string SQL pattern (safe, note only) |
| SEC-021 | --    | INFO     | Closed     | local_model_preprocess.py subprocess -- assessed SAFE |

**Closed (cumulative):** SEC-002 through SEC-010, SEC-012, SEC-013, SEC-014, SEC-015, SEC-017, SEC-021

---

## Recommendations (Prioritized)

1. **Ron (before paying customers -- LOW):** Fix SEC-016 (auto_save session limit bypass).
   This is the one open finding most relevant to marketplace trust and tier enforcement
   completeness. Close it before LoreConvo Pro goes live.

2. **Ron (before v0.2.0 -- MEDIUM):** Fix SEC-011 (TOCTOU race in LoreDocs export).
   Not urgent for local use but clean it up before the next minor version.

3. **Ron (before marketplace -- LOW):** Fix SEC-019 (duplicated license.py). Add a
   cross-product consistency test asserting both public key constants are equal.
   Consider extracting to a shared lore_licensing library long-term.

4. **Ron (advisory -- INFO):** Add a comment to pipeline_tracker.py line 250 noting
   the f-string SQL is safe because column names are hardcoded (SEC-020 pattern risk).

5. **Debbie (low urgency):** Rotate Anthropic API key in sql_query_optimizer/api/.env
   at next opportunity (SEC-001). File is gitignored and not in history. Good hygiene.

6. **Ron (near-term -- LOW):** Address CreditManager race condition SEC-006 before
   LoreConvo Pro goes live.

---

## Report Comparison vs 2026-04-04

| Metric              | 2026-04-04 | 2026-04-05 | Change          |
|---------------------|-----------|-----------|-----------------|
| Total active findings | 8        | 7         | -1 (SEC-017 resolved) |
| CRITICAL            | 0         | 0         | No change       |
| HIGH                | 0         | 0         | No change       |
| MEDIUM              | 3         | 2         | -1 (SEC-017 resolved) |
| LOW                 | 2         | 3         | +1 (SEC-020 added, INFO not LOW -- corrected) |
| INFO                | 3         | 4         | +1 (SEC-020) |
| CVEs found          | 0         | 0         | No change       |
| Resolved (cumulative) | 10      | 11        | +1 (SEC-017)    |

**Trend:** Steady improvement. SEC-017 (highest-priority pre-launch item) is now closed.
No new MEDIUM or higher findings. Plugin install flow now working on both platforms --
attack surface unchanged (no new network exposure). Posture: NEEDS ATTENTION (stable).

---

*Report generated by Brock (automated security agent) -- 2026-04-05*
*Next scheduled run: 2026-04-06 03:00 AM*
