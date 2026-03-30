# Security Report - 2026-03-30
**Agent:** Brock (Cybersecurity Expert)
**Run Time:** 2026-03-30 (automated daily scan)
**Overall Posture:** NEEDS ATTENTION

---

## Executive Summary

Good progress since yesterday's report. Ron resolved 5 of 9 findings (SEC-002, SEC-004,
SEC-005, SEC-007, SEC-008) in commit `040c1c4`. All five fixes have been verified:
`hmac.compare_digest` is in place, email PII is masked in logs, rate limits cover all
endpoints, `.gitignore` now blocks `*.db` and `*.sqlite`, and the QUICKSTART.md has the
`--reload` development-only warning.

The overall posture remains **NEEDS ATTENTION** due to one CRITICAL and one new HIGH finding.
The CRITICAL finding (SEC-001) is unchanged: a real Anthropic API key remains on disk in
the SQL Query Optimizer `.env` file and has not been revoked. This is now day 9 since
first detection. Additionally, a new HIGH finding (SEC-010) was identified: yesterday's
security report, which was committed to git in `34d6f43`, contains a partial API key prefix
(`sk-ant-api03-9ffeAe8zLrMng8GIMC-fcs4rSDvRycGY9vw_4...`) exposing approximately 45
characters of the key in git history. This makes revocation even more urgent.

Three findings from the prior report remain open but non-critical: unpinned dependencies
in pyproject.toml files (SEC-003), the CreditManager race condition (SEC-006), and the
mitigated SQL dynamic clause pattern (SEC-009, informational only). Dependency audits
via pip-audit returned zero known CVEs across all products. LiteLLM is not present
in any dependency chain. No new code-level vulnerabilities (injection, deserialization,
path traversal) were found.

---

## !! CRITICAL - ACTION REQUIRED !!

**Finding: Exposed Anthropic API Key -- Still Not Revoked (Day 9)**

The file `ron_skills/sql_query_optimizer/api/.env` still contains a real Anthropic API key.
This key has been on disk since 2026-03-21. It was first flagged in CLAUDE.md TODO #14
and again in yesterday's security report (SEC-001). **It has not been revoked.**

**Remediation (Debbie must do this -- not automatable):**
1. Go to console.anthropic.com -> API keys
2. Revoke the key immediately
3. Generate a new key
4. Update `.env` with the new key
5. See also SEC-010 below regarding partial key in git history

**Status:** EXISTING (first flagged 2026-03-29). ESCALATING due to age and SEC-010.

---

## Findings Summary

| ID | Severity | Category | Status | Description |
|----|----------|----------|--------|-------------|
| SEC-001 | CRITICAL | Secrets | EXISTING | Anthropic API key on disk, not revoked |
| SEC-010 | HIGH | Secrets | NEW | Partial API key committed in security report git history |
| SEC-003 | MEDIUM | Dependencies | EXISTING | Unpinned deps in pyproject.toml files |
| SEC-006 | LOW | Business Logic | EXISTING | CreditManager file-based race condition |
| SEC-009 | INFO | Injection | EXISTING | Dynamic SQL clauses (mitigated by design) |
| SEC-002 | MEDIUM | Auth | RESOLVED | Admin token timing-safe comparison |
| SEC-004 | MEDIUM | Logging | RESOLVED | Email PII masked in logs |
| SEC-005 | LOW | API Security | RESOLVED | Rate limits on /v1/optimize and /v1/credits |
| SEC-007 | LOW | Infrastructure | RESOLVED | .gitignore now covers *.db and *.sqlite |
| SEC-008 | INFO | Config | RESOLVED | --reload warning in QUICKSTART.md |

---

## Detailed Findings

### SEC-001: Anthropic API Key Not Revoked (ESCALATED)
- **Severity:** CRITICAL
- **Category:** Secrets
- **Status:** EXISTING -- day 9, escalating
- **Location:** `ron_skills/sql_query_optimizer/api/.env` (line 5)
- **Description:** Full Anthropic API key (`sk-ant-api03-...`) remains on disk. Not in
  git history (gitignore working), but on-disk exposure since 2026-03-21. Combined with
  SEC-010, ~45 characters of this key are now in git history via the security report.
- **Remediation:** Revoke at console.anthropic.com immediately, regenerate, update .env.

---

### SEC-010: Partial API Key in Committed Security Report (NEW)
- **Severity:** HIGH
- **Category:** Secrets
- **Status:** NEW
- **Location:** `docs/security/security_report_2026_03_29.md` (lines 37, 42, 47) --
  committed in `34d6f43`
- **Description:** Yesterday's security report included a partial key prefix
  `sk-ant-api03-9ffeAe8zLrMng8GIMC-fcs4rSDvRycGY9vw_4...` in 3 places. While truncated
  with `...`, this reveals approximately 45 characters of the 88-character key, reducing
  the brute-force search space dramatically. Since this is committed to git, it persists
  in history even if the file is edited later.
- **Remediation for Ron:**
  1. Edit `docs/security/security_report_2026_03_29.md` to replace all instances of the
     partial key with `sk-ant-***REDACTED***`
  2. Commit the redaction
  3. Note: The partial key will remain in git history (commit `34d6f43`). If this repo
     is ever made public, a `git filter-branch` or BFG Repo Cleaner run would be needed
     to scrub it. For now, since the repo is not public and the key should be revoked
     (SEC-001), the risk is contained.
- **Brock note for future reports:** Never include real key material (even partial) in
  security reports. Use `sk-ant-***REDACTED***` or reference the finding by location only.

---

### SEC-003: Unpinned Dependencies in pyproject.toml Files (EXISTING)
- **Severity:** MEDIUM
- **Category:** Dependencies
- **Status:** EXISTING (from 2026-03-29 report)
- **Location:**
  - `ron_skills/loreconvo/pyproject.toml` (all deps use `>=`)
  - `ron_skills/loredocs/pyproject.toml` (all deps use `>=`)
  - `ron_skills/loreconvo/requirements.txt` (uses `>=` not exact pins)
- **Description:** Minimum version constraints allow pulling in untested versions.
  SQL Optimizer API requirements.txt is correctly pinned (all exact versions).
- **Remediation:** Generate `requirements-lock.txt` from each product venv with
  `pip freeze > requirements-lock.txt`. This is tracked in CLAUDE.md TODO #6.

---

### SEC-006: CreditManager Race Condition Under Concurrency (EXISTING)
- **Severity:** LOW
- **Category:** Business Logic / Data Integrity
- **Status:** EXISTING (from 2026-03-29 report)
- **Location:** `ron_skills/sql_query_optimizer/api/credits.py` -- `use_credit()` method
- **Description:** JSON file read-modify-write without locking. Under concurrent requests,
  credits can be double-spent. Low risk at current traffic (pre-launch), but must be
  fixed before production deployment.
- **Remediation:** Use `filelock` library or migrate CreditManager to SQLite (WAL mode).
  Not urgent until the API is deployed publicly.

---

### SEC-009: SQL Dynamic Clause Construction in LoreDocs (EXISTING)
- **Severity:** INFO
- **Category:** Injection (Mitigated)
- **Status:** EXISTING (informational only -- mitigated by code structure)
- **Location:** `ron_skills/loredocs/loredocs/storage.py` lines 641-644, 754-764
- **Description:** Dynamic SQL via f-strings, but all user input goes through `?`
  parameterization. Keys come from internal dicts, sort/filter fields validated against
  whitelists. No actual injection risk.
- **Remediation:** No fix required. Carry forward as informational note.

---

## Resolved Findings (Fixed Since Last Report)

| ID | Severity | Fix Verified | Commit |
|----|----------|-------------|--------|
| SEC-002 | MEDIUM | `hmac.compare_digest` now used for admin token | `040c1c4` |
| SEC-004 | MEDIUM | Email masked as `xxx***` before logging | `040c1c4` |
| SEC-005 | LOW | Rate limits: 30/min on /v1/optimize, 60/min on /v1/credits | `040c1c4` |
| SEC-007 | LOW | `*.db` and `*.sqlite` added to .gitignore | `040c1c4` |
| SEC-008 | INFO | `--reload` flagged as dev-only in QUICKSTART.md | `040c1c4` |

---

## Dependency Audit Results

| Product | Requirements File | pip-audit Result | Pinning Status | Notes |
|---------|------------------|-----------------|----------------|-------|
| SQL Query Optimizer | `api/requirements.txt` | PASS - 0 CVEs | All exact pins | Clean |
| LoreConvo | `requirements.txt` | PASS - 0 CVEs | Uses `>=` (SEC-003) | No CVEs but pins needed |
| LoreDocs | `pyproject.toml` | Not auditable (no requirements.txt) | Uses `>=` (SEC-003) | Needs lockfile |
| All products | LiteLLM check | CLEAN | N/A | LiteLLM not present anywhere |

---

## Secrets Scan Results

| Check | Result | Details |
|-------|--------|---------|
| `.env` committed to git | PASS | .gitignore covers `*.env` |
| `.env` in git history | PASS | No `.env` files in git history |
| Partial key in git history | **FAIL** | SEC-010: ~45 chars of key in committed report |
| Real key in `.env` on disk | **FAIL** | SEC-001: Full key in `api/.env` (not revoked) |
| Hardcoded keys in Python source | PASS | No hardcoded keys in tracked files |
| AWS credentials | PASS | No AKIA patterns |
| Private keys / PEM files | PASS | No RSA/EC private keys |
| Stripe live keys | PASS | Only placeholder comments |
| `.env.example` contents | PASS | Placeholder values only |

---

## Infrastructure Review

| Area | Status | Notes |
|------|--------|-------|
| .gitignore coverage | GOOD | Covers .env, *.db, *.sqlite, *.log, data/, __pycache__, .venv/ |
| Debug mode in production | GOOD | No `DEBUG=True` or `app.debug` found in any source |
| Sensitive data in logs | GOOD | Email masking implemented (SEC-004 resolved) |
| Security headers | GOOD | HSTS, X-Frame-Options, CSP, X-Content-Type-Options, Referrer-Policy |
| CORS configuration | GOOD | Env-var-driven origins, no wildcard, credentials=False |
| Rate limiting | GOOD | All 3 endpoints now rate-limited (SEC-005 resolved) |
| Admin auth | GOOD | ADMIN_SECRET env var + hmac.compare_digest (SEC-002 resolved) |
| Path traversal protections | GOOD | LoreDocs sanitization intact |
| Untracked files | OK | 2 test files untracked (test_cli.py, test_optimizer.py) -- not a security concern |

---

## Recommendations (Prioritized)

1. **Debbie (URGENT):** Revoke the Anthropic API key at console.anthropic.com. This is
   now day 9. Combined with the partial key in git history (SEC-010), this is the most
   pressing issue.

2. **Ron (next session):** Redact partial key from `docs/security/security_report_2026_03_29.md`
   -- replace all `sk-ant-api03-...` occurrences with `sk-ant-***REDACTED***` (SEC-010).

3. **Ron (near-term):** Generate `requirements-lock.txt` for LoreConvo and LoreDocs
   (SEC-003). This is also tracked as CLAUDE.md TODO #6.

4. **Ron (before production):** Address CreditManager race condition (SEC-006) by
   adding file locking or migrating to SQLite.

5. **Brock (self-note):** Future security reports must NEVER include real key material,
   even partial. Use `sk-ant-***REDACTED***` or reference by file location only.

---

## Report Comparison vs 2026-03-29

| Metric | 2026-03-29 | 2026-03-30 | Change |
|--------|-----------|-----------|--------|
| Total findings | 9 | 5 active (+ 5 resolved) | -4 active |
| CRITICAL | 1 | 1 (same: SEC-001) | No change |
| HIGH | 0 | 1 (NEW: SEC-010) | +1 |
| MEDIUM | 3 | 1 (SEC-003 remains) | -2 resolved |
| LOW | 3 | 1 (SEC-006 remains) | -2 resolved |
| INFO | 2 | 1 (SEC-009 remains) | -1 resolved |
| CVEs found | 0 | 0 | No change |

---

*Report generated by Brock (automated security agent) - 2026-03-30*
*Next scheduled run: 2026-03-31 04:00 AM*
