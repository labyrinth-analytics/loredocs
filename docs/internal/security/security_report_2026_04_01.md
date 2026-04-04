# Security Report - 2026-04-01
**Agent:** Brock (Cybersecurity Expert)
**Run Time:** 2026-04-01 (automated daily scan)
**Overall Posture:** NEEDS ATTENTION

---

## Executive Summary

Overall posture remains **NEEDS ATTENTION**, driven by SEC-011 (TOCTOU race in LoreDocs
export, MEDIUM) and SEC-006 (CreditManager race condition, LOW). Both are low-risk in the
current single-user local environment but should be addressed before any multi-user deployment.

**Positive developments since 2026-03-31:**

1. **SEC-010 RESOLVED:** The redacted security report (2026-03-29) was committed in `b52d96c`.
   The partial API key prefix still exists in git history at commit `34d6f43`, but Debbie has
   the `scrub_public_repos.sh` script ready to clean public repo history when she runs it.
2. **Public repo hygiene significantly improved:** Internal docs (revenue projections, PRDs,
   PUBLISHING.md, marketplace listings, CLAUDE.md) were removed from git tracking in both
   product directories (commits `535a537`, `01dc048`). Product `.gitignore` files updated.
   Pre-push verification script (`verify_public_repo_clean.sh`) and history scrub script
   (`scrub_public_repos.sh`) added as safety nets.
3. **BSL 1.1 session limit enforcement** added to LoreConvo (`config.py` max_free_sessions=50,
   `database.py` raises SessionLimitError). Code review shows clean implementation.
4. **All dependency audits pass:** pip-audit returns 0 CVEs for all three products.
   LiteLLM remains absent from all dependency chains.

**No new findings this report.** All existing findings are carried forward with updated status.

---

## Findings Summary

| ID | Severity | Category | Status | Description |
|----|----------|----------|--------|-------------|
| SEC-011 | MEDIUM | Business Logic | EXISTING | TOCTOU race condition in LoreDocs file export |
| SEC-006 | LOW | Business Logic | EXISTING | CreditManager file-based race condition |
| SEC-001 | INFO | Secrets | PREVIOUSLY NOTED | Anthropic API key in local gitignored .env (single-user machine) |
| SEC-009 | INFO | Injection | EXISTING | Dynamic SQL clauses (mitigated by design) |

### Resolved Findings (this report)

| ID | Severity | Resolution | Details |
|----|----------|-----------|---------|
| SEC-010 | HIGH | RESOLVED | Redacted report committed in `b52d96c`. Partial key in history at `34d6f43` -- scrub script available for public repo cleanup. |

### Resolved Findings (from prior reports)

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

### SEC-011: TOCTOU Race Condition in LoreDocs File Export (EXISTING)
- **Severity:** MEDIUM
- **Category:** Business Logic / Data Integrity
- **Status:** EXISTING (from 2026-03-31 report)
- **Location:** `ron_skills/loredocs/loredocs/storage.py` lines 1083-1087
- **Description:** The file export function checks if a destination file exists
  (`dest.exists()`), then writes to it (`shutil.copy2()`). Between the check and the
  write, another process could create the file, causing silent overwrites or failures
  under concurrent access. Low risk at current scale (single-user, local-only).
- **Remediation:** Use atomic file creation with `os.open(dest, os.O_CREAT | os.O_EXCL)`
  or `tempfile.mkstemp()` followed by rename.
- **Risk context:** Single-user local machine -- exploitation requires concurrent local processes.

---

### SEC-006: CreditManager Race Condition Under Concurrency (EXISTING)
- **Severity:** LOW
- **Category:** Business Logic / Data Integrity
- **Status:** EXISTING (from 2026-03-29 report)
- **Location:** `ron_skills/sql_query_optimizer/api/credits.py` -- `use_credit()` method
- **Description:** JSON file read-modify-write without locking. Under concurrent requests,
  credits can be double-spent. A test file (`test_credits_concurrency.py`) exists,
  suggesting awareness and future work planned.
- **Remediation:** Use `filelock` library or migrate CreditManager to SQLite (WAL mode).
  Not urgent until the API is deployed publicly.

---

### SEC-001: Anthropic API Key in Local .env (INFO -- Previously Noted)
- **Severity:** INFO
- **Category:** Secrets
- **Status:** PREVIOUSLY NOTED -- no change in risk level
- **Location:** `ron_skills/sql_query_optimizer/api/.env` (line 5)
- **Description:** Anthropic API key exists in a gitignored `.env` file on Debbie's
  single-user Mac. Not in git history, no remote access, no evidence of compromise.
  Per classification guidelines, this is INFO-level.
- **Standing recommendation:** Rotate the key at next convenient opportunity
  (console.anthropic.com). Not urgent.

---

### SEC-009: SQL Dynamic Clause Construction in LoreDocs (EXISTING)
- **Severity:** INFO
- **Category:** Injection (Mitigated)
- **Status:** EXISTING (informational only)
- **Location:** `ron_skills/loredocs/loredocs/storage.py` lines 641-644, 754-764
- **Description:** Dynamic SQL via f-strings, but all user input goes through `?`
  parameterization. Keys come from internal dicts, sort/filter fields validated against
  whitelists. No actual injection risk. LoreConvo database.py uses the same safe pattern.
- **Remediation:** No fix required. Informational note carried forward.

---

## Dependency Audit Results

| Product | Requirements File | pip-audit Result | Notes |
|---------|------------------|-----------------|-------|
| SQL Query Optimizer | `api/requirements.txt` | PASS - 0 CVEs | All exact pins |
| LoreConvo | `requirements-lock.txt` | PASS - 0 CVEs | Exact pins in lock file |
| LoreDocs | `requirements-lock.txt` | PASS - 0 CVEs | Exact pins in lock file |
| All products | LiteLLM check | CLEAN | LiteLLM not present anywhere |

---

## Secrets Scan Results

| Check | Result | Details |
|-------|--------|---------|
| `.env` committed to git | PASS | .gitignore covers `.env` and `*.env` in all products |
| `.env` in git history | PASS | No `.env` files in git history |
| Partial key in git history | PASS (disk) | SEC-010 resolved: redacted report committed in `b52d96c`. History scrub available. |
| Real key in `.env` on disk | INFO | SEC-001: full key in `api/.env` (local-only, gitignored, single-user) |
| Hardcoded keys in Python source | PASS | No hardcoded keys in tracked .py files |
| AWS credentials | PASS | No AKIA patterns found |
| Private keys / PEM files | PASS | No RSA/EC private keys found |
| Stripe live keys | PASS | Only placeholder comments |
| `.env.example` contents | PASS | Placeholder value only |

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
| .gitignore coverage | GOOD | Root and product .gitignore files cover .env, *.db, *.sqlite, *.log, internal docs |
| Git lock files | WATCH | `HEAD.lock` and `maintenance.lock` present -- clean with `find .git -name "*.lock" -delete` |
| Uncommitted changes | NOTE | Root `.gitignore` has uncommitted revenue pattern exclusions (good change, needs commit) |
| Public repo hygiene | IMPROVED | Internal docs removed from tracking. Pre-push verification and scrub scripts added. |
| Debug mode in production | CLEAN | No `DEBUG=True` or `app.debug` in application code |
| Sensitive data in logs | GOOD | Email masking implemented |
| Security headers | GOOD | Full OWASP-compliant set |
| CORS configuration | GOOD | Env-var-driven origins, localhost defaults, no wildcard |
| Rate limiting | GOOD | All endpoints rate-limited |
| Admin auth | GOOD | hmac.compare_digest timing-safe comparison |
| BSL enforcement | NEW - GOOD | LoreConvo session limit (50 free) enforced at database layer |
| Untracked test files | OK | test_null_id_migration.py, test_credits_concurrency.py -- not a security concern |

---

## Public Repo Hygiene Audit (New Section)

This is the first report since the internal doc relocation (commits `535a537`, `01dc048`).

| Check | Result | Details |
|-------|--------|---------|
| Sensitive files tracked in loreconvo/ | PASS | No revenue, PUBLISHING, marketplace, CLAUDE.md, or xlsx files tracked |
| Sensitive files tracked in loredocs/ | PASS | No revenue, PUBLISHING, marketplace, CLAUDE.md, or xlsx files tracked |
| Product .gitignore files | PASS | Both products have .gitignore covering CLAUDE.md, *.xlsx, *.env |
| Pre-push verification script | PRESENT | `scripts/verify_public_repo_clean.sh` |
| History scrub script | PRESENT | `scripts/scrub_public_repos.sh` (needs Debbie to run) |
| Internal docs in history | NOTE | CLAUDE.md and other internal docs still exist in git history for both products. History scrub not yet run. |

**Recommendation for Debbie:** Run `bash scripts/scrub_public_repos.sh` before the next
subtree push to public repos. This will remove all historical traces of internal docs.
This is especially important because the product CLAUDE.md files contained revenue targets,
agent instructions, and pricing strategy.

---

## Recommendations (Prioritized)

1. **Debbie (before next public push):** Run `bash scripts/scrub_public_repos.sh` to clean
   internal docs from public repo git history. The files are no longer tracked, but history
   still contains them.

2. **Ron (next session):** Commit the uncommitted `.gitignore` changes (revenue pattern
   exclusions). These are good safety-net rules.

3. **Ron (next session):** Clean git lock files: `find .git -name "*.lock" -delete`

4. **Ron (near-term):** Fix TOCTOU race in LoreDocs export (SEC-011) using atomic file
   creation before any multi-user deployment.

5. **Ron (before production):** Address CreditManager race condition (SEC-006) by
   adding file locking or migrating to SQLite.

6. **Debbie (low priority):** Rotate Anthropic API key at next convenient opportunity
   (SEC-001). No urgency -- key is local-only and gitignored.

---

## Report Comparison vs 2026-03-31

| Metric | 2026-03-31 | 2026-04-01 | Change |
|--------|-----------|-----------|--------|
| Total active findings | 5 | 4 | -1 (SEC-010 resolved) |
| CRITICAL | 0 | 0 | No change |
| HIGH | 1 (SEC-010) | 0 | -1 (SEC-010 resolved) |
| MEDIUM | 1 (SEC-011) | 1 (SEC-011) | No change |
| LOW | 1 (SEC-006) | 1 (SEC-006) | No change |
| INFO | 2 (SEC-001, SEC-009) | 2 (SEC-001, SEC-009) | No change |
| CVEs found | 0 | 0 | No change |
| Resolved (cumulative) | 6 | 7 | +1 (SEC-010) |
| New findings | 0 | 0 | No change |

**Trend:** Positive. One HIGH finding resolved, no new findings. Public repo hygiene
significantly improved with automated verification tooling.

---

*Report generated by Brock (automated security agent) - 2026-04-01*
*Next scheduled run: 2026-04-02 03:00 AM*
