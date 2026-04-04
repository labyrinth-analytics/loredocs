# Security Report - 2026-04-02
**Agent:** Brock (Cybersecurity Expert)
**Run Time:** 2026-04-02 (automated daily scan)
**Overall Posture:** NEEDS ATTENTION

---

## Executive Summary

Overall posture remains **NEEDS ATTENTION**, elevated slightly from yesterday by a new
dependency finding: two CVEs in `anthropic==0.86.0` used by the SQL Query Optimizer (SEC-012).
Both vulnerabilities affect the SDK's local filesystem memory tool and are fixed in 0.87.0.
Risk is LOW in the current single-user local environment, but the upgrade is straightforward
and recommended for Ron's next session.

**Changes since 2026-04-01:**

1. **NEW FINDING SEC-012 (MEDIUM):** Two CVEs discovered in `anthropic==0.86.0` --
   CVE-2026-34450 (world-readable memory files) and CVE-2026-34452 (async symlink escape).
   Both fixed in 0.87.0. Low actual risk on Debbie's single-user Mac but should be patched.
2. **SQL Optimizer still lacks product-level .gitignore:** Neither `ron_skills/sql_query_optimizer/`
   nor `ron_skills/sql_query_optimizer/api/` has a `.gitignore`. The root `.gitignore` covers
   `.env` and `*.db`, but a product-level file would add defense-in-depth. Noted as SEC-013 (LOW).
3. **Git lock files persist:** HEAD.lock, index.lock, maintenance.lock still present. These are
   a Cowork VM artifact but can cause git operations to fail.
4. **LoreConvo and LoreDocs dependency audits remain clean** -- 0 CVEs.
5. **Recently changed files** (README updates, COWORK_RESTORE.md, plugin.json, PIPELINE_AGENT_GUIDE.md)
   reviewed -- no secrets or sensitive data introduced.

---

## Findings Summary

| ID | Severity | Category | Status | Description |
|----|----------|----------|--------|-------------|
| SEC-012 | MEDIUM | Dependencies | NEW | Two CVEs in anthropic==0.86.0 (SQL Optimizer) -- upgrade to 0.87.0 |
| SEC-011 | MEDIUM | Business Logic | EXISTING | TOCTOU race condition in LoreDocs file export |
| SEC-013 | LOW | Infrastructure | NEW | SQL Optimizer missing product-level .gitignore |
| SEC-006 | LOW | Business Logic | EXISTING | CreditManager file-based race condition |
| SEC-001 | INFO | Secrets | PREVIOUSLY NOTED | Anthropic API key in local gitignored .env (single-user machine) |
| SEC-009 | INFO | Injection | EXISTING | Dynamic SQL clauses (mitigated by design) |

### New Findings (this report)

| ID | Severity | Details |
|----|----------|---------|
| SEC-012 | MEDIUM | CVE-2026-34450 + CVE-2026-34452 in anthropic==0.86.0. Fix: bump to 0.87.0 in requirements.txt |
| SEC-013 | LOW | No .gitignore in ron_skills/sql_query_optimizer/ or api/ subdirectory |

### Resolved Findings (cumulative, from prior reports)

| ID | Severity | Fix Verified | Commit |
|----|----------|-------------|--------|
| SEC-010 | HIGH | Redacted report committed | `b52d96c` |
| SEC-003 | MEDIUM | requirements-lock.txt with exact pins | `b52d96c` |
| SEC-002 | MEDIUM | hmac.compare_digest for admin token | `040c1c4` |
| SEC-004 | MEDIUM | Email PII masked in logs | `040c1c4` |
| SEC-005 | LOW | Rate limits on all endpoints | `040c1c4` |
| SEC-007 | LOW | .gitignore covers *.db and *.sqlite | `040c1c4` |
| SEC-008 | INFO | --reload dev-only warning in QUICKSTART.md | `040c1c4` |

---

## Detailed Findings

### SEC-012: CVEs in anthropic==0.86.0 (NEW)
- **Severity:** MEDIUM
- **Category:** Dependencies
- **Status:** NEW
- **Location:** `ron_skills/sql_query_optimizer/api/requirements.txt` line 3
- **CVEs:**
  - **CVE-2026-34450:** The local filesystem memory tool creates files with mode 0o666,
    making them world-readable (and world-writable in permissive umask environments like
    Docker). A local attacker on a shared host could read persisted agent state.
  - **CVE-2026-34452:** The async local filesystem memory tool has a TOCTOU vulnerability
    where a symlink can be retarget between path validation and file operation, allowing
    sandbox escape. Only the async implementation is affected.
- **Fix:** Bump `anthropic==0.86.0` to `anthropic==0.87.0` in requirements.txt.
- **Risk context:** LOW actual risk -- Debbie's Mac is single-user, the SQL Optimizer API
  is local-only, and these CVEs require a local attacker. However, the fix is a one-line
  version bump with no breaking changes expected, so it should be applied promptly.

---

### SEC-013: SQL Optimizer Missing Product-Level .gitignore (NEW)
- **Severity:** LOW
- **Category:** Infrastructure / Defense-in-Depth
- **Status:** NEW
- **Location:** `ron_skills/sql_query_optimizer/` (no .gitignore found)
- **Description:** Unlike LoreConvo and LoreDocs, which both have product-level `.gitignore`
  files covering CLAUDE.md, *.xlsx, *.env, and Python artifacts, the SQL Optimizer directory
  has no `.gitignore`. The root `.gitignore` covers `.env` and `*.db`, providing baseline
  protection, but a product-level file would match the pattern of the other products and
  add defense-in-depth against accidental commits of sensitive files.
- **Remediation:** Create `ron_skills/sql_query_optimizer/.gitignore` matching the pattern
  used by LoreConvo and LoreDocs.

---

### SEC-011: TOCTOU Race Condition in LoreDocs File Export (EXISTING)
- **Severity:** MEDIUM
- **Category:** Business Logic / Data Integrity
- **Status:** EXISTING (from 2026-03-31 report)
- **Location:** `ron_skills/loredocs/loredocs/storage.py` lines 1083-1087
- **Description:** File export checks `dest.exists()` then writes with `shutil.copy2()`.
  Between the check and write, another process could create the file.
- **Remediation:** Use atomic file creation with `os.open(dest, os.O_CREAT | os.O_EXCL)`
  or `tempfile.mkstemp()` followed by rename.
- **Risk context:** Single-user local machine -- exploitation requires concurrent local processes.

---

### SEC-006: CreditManager Race Condition Under Concurrency (EXISTING)
- **Severity:** LOW
- **Category:** Business Logic / Data Integrity
- **Status:** EXISTING (from 2026-03-29 report)
- **Location:** `ron_skills/sql_query_optimizer/api/credits.py` -- `use_credit()` method
- **Description:** JSON file read-modify-write without locking. Not urgent until API is public.
- **Remediation:** Use `filelock` library or migrate to SQLite (WAL mode).

---

### SEC-001: Anthropic API Key in Local .env (INFO -- Previously Noted)
- **Severity:** INFO
- **Category:** Secrets
- **Status:** PREVIOUSLY NOTED -- no change in risk level
- **Location:** `ron_skills/sql_query_optimizer/api/.env` (gitignored, single-user Mac)
- **Standing recommendation:** Rotate at next convenient opportunity. Not urgent.

---

### SEC-009: SQL Dynamic Clause Construction in LoreDocs (EXISTING)
- **Severity:** INFO
- **Category:** Injection (Mitigated)
- **Status:** EXISTING (informational only)
- **Location:** `ron_skills/loredocs/loredocs/storage.py` and `ron_skills/loreconvo/src/core/database.py`
- **Description:** Dynamic SQL via f-strings, but all user input goes through `?`
  parameterization. Keys from internal dicts, sort/filter fields validated against whitelists.
  No actual injection risk.

---

## Dependency Audit Results

| Product | Requirements File | pip-audit Result | Notes |
|---------|------------------|-----------------|-------|
| SQL Query Optimizer | `api/requirements.txt` | **FAIL - 2 CVEs** | anthropic 0.86.0: CVE-2026-34450, CVE-2026-34452. Fix: bump to 0.87.0 |
| LoreConvo | `requirements-lock.txt` | PASS - 0 CVEs | All exact pins, clean |
| LoreDocs | `requirements-lock.txt` | PASS - 0 CVEs | All exact pins, clean |
| All products | LiteLLM check | CLEAN | LiteLLM not present anywhere |

---

## Secrets Scan Results

| Check | Result | Details |
|-------|--------|---------|
| `.env` committed to git | PASS | .gitignore covers `.env` and `*.env` in all products |
| `.env` in git history | PASS | No `.env` files in git history |
| Partial key in git history | KNOWN | Redacted in `b52d96c`. History scrub available but not yet run. |
| Real key in `.env` on disk | INFO | SEC-001: full key in `api/.env` (local-only, gitignored, single-user) |
| Hardcoded keys in Python source | PASS | Only test stubs (sk-test-key) in test files |
| AWS credentials | PASS | No AKIA patterns found |
| Private keys / PEM files | PASS | No RSA/EC private keys found |
| Stripe live keys | PASS | Only placeholder comments |
| Recently changed files | PASS | README, COWORK_RESTORE, plugin.json, PIPELINE_AGENT_GUIDE -- no secrets |

---

## OWASP Code Review Results

| Category | Status | Details |
|----------|--------|---------|
| SQL Injection | PASS | All queries use parameterized `?` placeholders |
| Path Traversal | PASS | LoreDocs has multi-layer defense (null byte, `..`, basename, realpath) |
| XSS | PASS | FTS5 input sanitized; no HTML template injection vectors |
| Insecure Deserialization | PASS | No pickle, unsafe yaml, eval, or exec found |
| Command Injection | PASS | No subprocess, os.system, or os.popen with user input |
| Broken Access Control | PASS | Tier enforcement in LoreDocs, BSL session limit in LoreConvo, admin auth in SQL Optimizer |
| Security Misconfiguration | PASS | Security headers comprehensive, CORS env-var-driven, rate limiting on all endpoints |

---

## Infrastructure Review

| Area | Status | Notes |
|------|--------|-------|
| .gitignore coverage | GOOD (mostly) | Root and LoreConvo/LoreDocs have strong coverage. SQL Optimizer missing product-level file (SEC-013). |
| Git lock files | WATCH | HEAD.lock, index.lock, maintenance.lock present -- clean with: `find .git -name "*.lock" -delete` |
| Staged changes | NOTE | 9 files staged (CLAUDE.md, READMEs, plugin.json, PIPELINE_AGENT_GUIDE.md) -- reviewed, no secrets |
| Public repo hygiene | GOOD | Internal docs removed from tracking. Pre-push verification and scrub scripts in place. |
| Debug mode in production | CLEAN | No `DEBUG=True` or `app.debug` in application code |
| Sensitive data in logs | GOOD | Email masking implemented |
| Security headers | GOOD | Full OWASP-compliant set |
| CORS configuration | GOOD | Env-var-driven origins, localhost defaults, no wildcard |
| Rate limiting | GOOD | All endpoints rate-limited |
| Admin auth | GOOD | hmac.compare_digest timing-safe comparison |
| BSL enforcement | GOOD | LoreConvo session limit (50 free) enforced at database layer |

---

## Public Repo Hygiene Audit

| Check | Result | Details |
|-------|--------|---------|
| Sensitive files tracked in loreconvo/ | PASS | No revenue, PUBLISHING, marketplace, CLAUDE.md, or xlsx files tracked |
| Sensitive files tracked in loredocs/ | PASS | Same as above |
| Product .gitignore files | PARTIAL | LoreConvo and LoreDocs have strong .gitignore. SQL Optimizer missing (SEC-013). |
| Pre-push verification script | PRESENT | `scripts/verify_public_repo_clean.sh` |
| History scrub script | PRESENT | `scripts/scrub_public_repos.sh` (needs Debbie to run) |
| Internal docs in history | NOTE | CLAUDE.md and other internal docs still exist in git history for both products. Scrub not yet run. |

**Standing recommendation for Debbie:** Run `bash scripts/scrub_public_repos.sh` before
the next subtree push to public repos.

---

## Recommendations (Prioritized)

1. **Ron (next session -- quick fix):** Bump `anthropic==0.86.0` to `anthropic==0.87.0`
   in `ron_skills/sql_query_optimizer/api/requirements.txt` to resolve SEC-012 (2 CVEs).
   One-line change, no expected breaking changes.

2. **Ron (next session -- quick fix):** Create `ron_skills/sql_query_optimizer/.gitignore`
   matching the LoreConvo/LoreDocs pattern (SEC-013).

3. **Ron (next session):** Clean git lock files: `find .git -name "*.lock" -delete`

4. **Debbie (before next public push):** Run `bash scripts/scrub_public_repos.sh` to clean
   internal docs from public repo git history.

5. **Ron (near-term):** Fix TOCTOU race in LoreDocs export (SEC-011) using atomic file
   creation before any multi-user deployment.

6. **Ron (before production):** Address CreditManager race condition (SEC-006) by
   adding file locking or migrating to SQLite.

7. **Debbie (low priority):** Rotate Anthropic API key at next convenient opportunity
   (SEC-001). No urgency -- key is local-only and gitignored.

---

## Report Comparison vs 2026-04-01

| Metric | 2026-04-01 | 2026-04-02 | Change |
|--------|-----------|-----------|--------|
| Total active findings | 4 | 6 | +2 (SEC-012, SEC-013) |
| CRITICAL | 0 | 0 | No change |
| HIGH | 0 | 0 | No change |
| MEDIUM | 1 (SEC-011) | 2 (SEC-011, SEC-012) | +1 (SEC-012 new) |
| LOW | 1 (SEC-006) | 2 (SEC-006, SEC-013) | +1 (SEC-013 new) |
| INFO | 2 (SEC-001, SEC-009) | 2 (SEC-001, SEC-009) | No change |
| CVEs found | 0 | 2 | +2 (anthropic 0.86.0) |
| Resolved (cumulative) | 7 | 7 | No change |
| New findings | 0 | 2 | +2 |

**Trend:** Slight regression due to newly disclosed CVEs in upstream dependency. Both are
easily fixable (one-line version bump). Overall security posture remains solid with
comprehensive protections across all products.

---

*Report generated by Brock (automated security agent) - 2026-04-02*
*Next scheduled run: 2026-04-03 03:00 AM*
