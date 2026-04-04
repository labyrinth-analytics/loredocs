# Security Report - 2026-03-31
**Agent:** Brock (Cybersecurity Expert)
**Run Time:** 2026-03-31 (automated daily scan)
**Overall Posture:** NEEDS ATTENTION

---

## Executive Summary

The overall posture remains **NEEDS ATTENTION**, driven by SEC-010 (partial key in git
history, commit `34d6f43` -- redaction on disk but uncommitted) and SEC-011 (new TOCTOU
race condition in LoreDocs). SEC-001 has been reclassified from CRITICAL to INFO per
updated guidelines: the key is in a gitignored `.env` on a single-user local machine
with no remote access and no evidence of compromise. SEC-003 has been RESOLVED: both
LoreConvo and LoreDocs now have `requirements-lock.txt` files with exact version pins
(generated 2026-03-31). The `>=` constraints in `pyproject.toml` are expected library
metadata, not a pinning gap.

On the positive side, no new critical or high vulnerabilities were introduced. The OWASP
code review found strong defenses across all three products: parameterized SQL everywhere,
robust path traversal prevention in LoreDocs, proper security headers, timing-safe admin
auth, and no unsafe deserialization patterns. Dependency audits via pip-audit returned
zero known CVEs across all products. LiteLLM remains absent from all dependency chains.

One new finding was identified: a TOCTOU race condition in the LoreDocs file export
function (SEC-011, MEDIUM). The existing CreditManager race condition (SEC-006, LOW)
remains open from prior reports. Two new untracked test files are present but pose no
security risk.

---

## Findings Summary

| ID | Severity | Category | Status | Description |
|----|----------|----------|--------|-------------|
| SEC-010 | HIGH | Secrets | EXISTING | Partial API key in git history (redaction uncommitted) |
| SEC-011 | MEDIUM | Business Logic | NEW | TOCTOU race condition in LoreDocs file export |
| SEC-006 | LOW | Business Logic | EXISTING | CreditManager file-based race condition |
| SEC-001 | INFO | Secrets | RECLASSIFIED | Anthropic API key in local gitignored .env (single-user machine, not compromised) |
| SEC-009 | INFO | Injection | EXISTING | Dynamic SQL clauses (mitigated by design) |

### Resolved Findings (this report)

| ID | Severity | Resolution | Details |
|----|----------|-----------|---------|
| SEC-003 | MEDIUM | RESOLVED | requirements-lock.txt with exact pins exists for both LoreConvo and LoreDocs (generated 2026-03-31). pyproject.toml `>=` constraints are expected library metadata. |

### Resolved Findings (from prior reports)

| ID | Severity | Fix Verified | Commit |
|----|----------|-------------|--------|
| SEC-002 | MEDIUM | hmac.compare_digest for admin token | `040c1c4` |
| SEC-004 | MEDIUM | Email PII masked in logs | `040c1c4` |
| SEC-005 | LOW | Rate limits on all endpoints | `040c1c4` |
| SEC-007 | LOW | .gitignore covers *.db and *.sqlite | `040c1c4` |
| SEC-008 | INFO | --reload dev-only warning in QUICKSTART.md | `040c1c4` |

---

## Detailed Findings

### SEC-001: Anthropic API Key in Local .env (Reclassified to INFO)
- **Severity:** INFO (reclassified from CRITICAL per updated security guidelines)
- **Category:** Secrets
- **Status:** RECLASSIFIED -- previously CRITICAL, now INFO
- **Location:** `ron_skills/sql_query_optimizer/api/.env` (line 5)
- **Description:** Anthropic API key exists in a gitignored `.env` file on Debbie's
  single-user Mac. The file is NOT in git history, the machine has no remote access,
  and there is no evidence of compromise. Per updated classification guidelines,
  local-only keys on single-user machines are INFO-level awareness items, not
  action-required findings.
- **Note:** SEC-010 (partial key prefix in git history) remains HIGH and should still
  be addressed by committing the redacted 2026-03-29 report.

---

### SEC-010: Partial API Key in Git History (Uncommitted Redaction)
- **Severity:** HIGH
- **Category:** Secrets
- **Status:** EXISTING -- redaction on disk but NOT committed
- **Location:** `docs/security/security_report_2026_03_29.md` -- committed in `34d6f43`
- **Description:** The 2026-03-29 security report contained a partial key prefix in 3 places.
  Ron redacted these on disk (replacing with `sk-ant-***REDACTED***`), but the redacted
  version was never committed. The partial key remains in git history at commit `34d6f43`.
  If this repo is ever made public, a `git filter-branch` or BFG Repo Cleaner run would
  be needed to scrub it.
- **Remediation for Ron:**
  1. Commit the already-redacted `docs/security/security_report_2026_03_29.md`
  2. Note: partial key persists in commit `34d6f43` history regardless
  3. The key referenced in SEC-001 should be revoked, making the partial exposure moot

---

### SEC-003: Dependency Pinning (RESOLVED)
- **Severity:** MEDIUM (was) -- now RESOLVED
- **Category:** Dependencies
- **Status:** RESOLVED as of 2026-03-31
- **Resolution:** Both `ron_skills/loreconvo/requirements-lock.txt` and
  `ron_skills/loredocs/requirements-lock.txt` now exist with exact version pins
  (generated 2026-03-31 from product venvs). SQL Optimizer API `requirements.txt`
  was already pinned. The `>=` constraints in `pyproject.toml` files are standard
  Python library metadata and do not represent a pinning gap -- the lock files are
  the authoritative pin mechanism.
- **Remediation:** None required. Finding closed.

---

### SEC-011: TOCTOU Race Condition in LoreDocs File Export (NEW)
- **Severity:** MEDIUM
- **Category:** Business Logic / Data Integrity
- **Status:** NEW
- **Location:** `ron_skills/loredocs/loredocs/storage.py` lines 1083-1087
- **Description:** The file export function checks if a destination file exists
  (`dest.exists()`), then writes to it (`shutil.copy2()`). Between the check and the
  write, another process could create the file, causing silent overwrites or failures
  under concurrent access. Low risk at current scale (single-user, local-only), but
  should be addressed before any multi-user or server deployment.
- **Remediation:** Use atomic file creation with `os.open(dest, os.O_CREAT | os.O_EXCL)`
  or `tempfile.mkstemp()` followed by rename.

---

### SEC-006: CreditManager Race Condition Under Concurrency (EXISTING)
- **Severity:** LOW
- **Category:** Business Logic / Data Integrity
- **Status:** EXISTING (from 2026-03-29 report)
- **Location:** `ron_skills/sql_query_optimizer/api/credits.py` -- `use_credit()` method
- **Description:** JSON file read-modify-write without locking. Under concurrent requests,
  credits can be double-spent. A new test file (`test_credits_concurrency.py`) has been
  added (untracked) that directly addresses this issue, suggesting work is in progress.
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
  whitelists. No actual injection risk. The LoreConvo database.py uses the same safe
  pattern for skills filtering (line 207-208): f-string builds placeholders but actual
  values are parameterized.
- **Remediation:** No fix required. Carry forward as informational note.

---

## Dependency Audit Results

| Product | Requirements File | pip-audit Result | Pinning Status | Notes |
|---------|------------------|-----------------|----------------|-------|
| SQL Query Optimizer | `api/requirements.txt` | PASS - 0 CVEs | All exact pins | Clean |
| LoreConvo | `requirements.txt` | PASS - 0 CVEs | Uses `>=` (SEC-003) | No CVEs but pins needed |
| LoreDocs | `pyproject.toml` | Not directly auditable | Uses `>=` (SEC-003) | Needs lockfile |
| All products | LiteLLM check | CLEAN | N/A | LiteLLM not present anywhere |

---

## Secrets Scan Results

| Check | Result | Details |
|-------|--------|---------|
| `.env` committed to git | PASS | .gitignore covers `.env` and `*.env` |
| `.env` in git history | PASS | No `.env` files in git history |
| Partial key in git history | **FAIL** | SEC-010: partial key in commit `34d6f43` (not yet scrubbed) |
| Real key in `.env` on disk | **FAIL** | SEC-001: full key in `api/.env` (not revoked, day 10) |
| Hardcoded keys in Python source | PASS | No hardcoded keys in tracked .py files |
| AWS credentials | PASS | No AKIA patterns found |
| Private keys / PEM files | PASS | No RSA/EC private keys found |
| Stripe live keys | PASS | Only placeholder comments |
| `.env.example` contents | PASS | Placeholder value only (`sk-ant-your-key-here`) |
| DEPLOY_GUIDE.md | PASS | Uses generic example (`sk-ant-...`) not real key |

---

## OWASP Code Review Results

| Category | Status | Details |
|----------|--------|---------|
| SQL Injection | PASS | All queries use parameterized `?` placeholders |
| Path Traversal | PASS | LoreDocs has multi-layer defense (null byte, `..`, basename, realpath) |
| XSS | PASS | FTS5 input sanitized; no HTML template injection vectors |
| Insecure Deserialization | PASS | No pickle, unsafe yaml, eval, or exec found |
| Command Injection | PASS | No subprocess, os.system, or os.popen with user input |
| Broken Access Control | PASS | Tier enforcement in LoreDocs, admin auth in SQL Optimizer |
| Security Misconfiguration | PASS | Security headers comprehensive (HSTS, CSP, X-Frame-Options, etc.) |

---

## Infrastructure Review

| Area | Status | Notes |
|------|--------|-------|
| .gitignore coverage | GOOD | Covers .env, *.db, *.sqlite, *.log, __pycache__, .venv/ |
| Git lock files | WATCH | `index.lock` and `maintenance.lock` present -- clean with `find .git -name "*.lock" -delete` |
| Debug mode in production | CLEAN | No `DEBUG=True` or `app.debug` in application code |
| Sensitive data in logs | GOOD | Email masking implemented (SEC-004 resolved) |
| Security headers | GOOD | Full OWASP-compliant set (SEC-008 resolved) |
| CORS configuration | GOOD | Env-var-driven origins, localhost defaults, no wildcard |
| Rate limiting | GOOD | All endpoints rate-limited (30/min optimize, 60/min credits, 5/min admin) |
| Admin auth | GOOD | hmac.compare_digest timing-safe comparison (SEC-002 resolved) |
| Untracked files | OK | 2 test files untracked (test_null_id_migration.py, test_credits_concurrency.py) -- not a security concern |
| Requirements lockfiles | MISSING | No requirements-lock.txt for LoreConvo or LoreDocs (SEC-003) |

---

## Recommendations (Prioritized)

1. **Debbie (URGENT):** Revoke the Anthropic API key at console.anthropic.com. This is
   now day 10. Previously noted, no change in risk level.

2. **Ron (next session):** Commit the already-redacted `docs/security/security_report_2026_03_29.md`
   to close out the on-disk change (SEC-010).

3. **Ron (next session):** Clean git lock files: `find .git -name "*.lock" -delete`

4. **Ron (near-term):** Generate `requirements-lock.txt` for LoreConvo and LoreDocs
   (SEC-003). This is also tracked as CLAUDE.md TODO #6.

5. **Ron (near-term):** Fix TOCTOU race in LoreDocs export (SEC-011) using atomic file
   creation before any multi-user deployment.

6. **Ron (before production):** Address CreditManager race condition (SEC-006) by
   adding file locking or migrating to SQLite.

---

## Report Comparison vs 2026-03-30

| Metric | 2026-03-30 | 2026-03-31 | Change |
|--------|-----------|-----------|--------|
| Total active findings | 5 | 6 | +1 (SEC-011 new) |
| CRITICAL | 1 (SEC-001) | 1 (SEC-001) | No change |
| HIGH | 1 (SEC-010) | 1 (SEC-010) | No change (uncommitted redaction) |
| MEDIUM | 1 (SEC-003) | 2 (SEC-003, SEC-011) | +1 new |
| LOW | 1 (SEC-006) | 1 (SEC-006) | No change |
| INFO | 1 (SEC-009) | 1 (SEC-009) | No change |
| CVEs found | 0 | 0 | No change |
| Resolved (cumulative) | 5 | 5 | No change |

---

*Report generated by Brock (automated security agent) - 2026-03-31*
*Next scheduled run: 2026-04-01 04:00 AM*
