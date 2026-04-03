# Security Report - 2026-04-03
**Agent:** Brock (Cybersecurity Expert)
**Run Time:** 2026-04-03 (automated daily scan)
**Overall Posture:** NEEDS ATTENTION

---

## Executive Summary

Posture remains **NEEDS ATTENTION** but trending toward improvement. Two findings from
yesterday have been resolved: SEC-012 (anthropic CVEs, bumped to 0.87.0) and SEC-013
(SQL Optimizer .gitignore added). Both fixes are staged but not yet committed -- Ron
should commit them in the next session.

Five new files were introduced since the last report: `save_to_loreconvo.py` and
`query_loredocs.py` (agent fallback scripts), plus `test_tiers_env_override.py` and
`test_credits_isolation.py` (new test files), and a Madison blog draft. All were
reviewed and found clean -- parameterized SQL throughout, proper filename validation
in LoreDocs doc-add, no secrets, no unsafe patterns.

**Changes since 2026-04-02:**

1. **RESOLVED SEC-012:** `anthropic==0.87.0` in SQL Optimizer requirements.txt (staged, pending commit).
2. **RESOLVED SEC-013:** `.gitignore` created for `ron_skills/sql_query_optimizer/` (staged, pending commit).
3. **NEW FILES REVIEWED (CLEAN):** `scripts/save_to_loreconvo.py`, `scripts/query_loredocs.py`, two test files, one blog draft. All use parameterized SQL, proper input validation, no secrets.
4. **LoreConvo and LoreDocs dependency audits remain clean** -- 0 CVEs.
5. **SQL Optimizer dependency audit now clean** -- 0 CVEs (after anthropic bump).
6. **Stale worktree detected:** `.claude/worktrees/pedantic-bardeen/` exists from a prior session. Not a security risk but should be cleaned up.

---

## Findings Summary

| ID | Severity | Category | Status | Description |
|----|----------|----------|--------|-------------|
| SEC-011 | MEDIUM | Business Logic | EXISTING | TOCTOU race condition in LoreDocs file export |
| SEC-006 | LOW | Business Logic | EXISTING | CreditManager file-based race condition |
| SEC-001 | INFO | Secrets | PREVIOUSLY NOTED | Anthropic API key in local gitignored .env (single-user machine) |
| SEC-009 | INFO | Injection | EXISTING | Dynamic SQL clauses (mitigated by design) |

### Resolved Findings (cumulative, from prior reports)

| ID | Severity | Fix Verified | Commit / Status |
|----|----------|-------------|-----------------|
| SEC-013 | LOW | .gitignore created for SQL Optimizer | Staged, pending commit |
| SEC-012 | MEDIUM | anthropic bumped to 0.87.0 | Staged, pending commit |
| SEC-010 | HIGH | Redacted report committed | `b52d96c` |
| SEC-003 | MEDIUM | requirements-lock.txt with exact pins | `b52d96c` |
| SEC-002 | MEDIUM | hmac.compare_digest for admin token | `040c1c4` |
| SEC-004 | MEDIUM | Email PII masked in logs | `040c1c4` |
| SEC-005 | LOW | Rate limits on all endpoints | `040c1c4` |
| SEC-007 | LOW | .gitignore covers *.db and *.sqlite | `040c1c4` |
| SEC-008 | INFO | --reload dev-only warning in QUICKSTART.md | `040c1c4` |

---

## New Code Review: Agent Fallback Scripts

### scripts/save_to_loreconvo.py (NEW -- CLEAN)
- **Purpose:** Direct LoreConvo session saver for when MCP tools are unavailable
- **SQL Safety:** All queries use parameterized `?` placeholders. LIKE search wraps user input with `%` but passes through parameters -- no injection risk.
- **Input Handling:** JSON list parsing has try/except fallback -- handles malformed input gracefully.
- **Secrets:** No hardcoded keys or credentials. DB path auto-discovered.
- **Rating:** SECURE

### scripts/query_loredocs.py (NEW -- CLEAN)
- **Purpose:** Direct LoreDocs query tool for when MCP tools are unavailable
- **SQL Safety:** All queries use parameterized `?` placeholders. FTS MATCH also parameterized. LIKE fallback parameterized.
- **Path Traversal:** `cmd_add_doc` validates filenames: rejects `..`, null bytes, and absolute paths (line 285). Uses `Path(db_path).parent` for root derivation -- safe.
- **File I/O:** Reads from `--file` argument and writes to vault directory. Local CLI tool with no network exposure -- attack surface limited to local user.
- **Secrets:** No hardcoded keys or credentials.
- **Rating:** SECURE

### ron_skills/loredocs/tests/test_tiers_env_override.py (NEW -- CLEAN)
- **Purpose:** Tests LOREDOCS_PRO env var override behavior
- **Secrets:** No real keys -- uses mock/patch for testing.
- **Rating:** SECURE

### ron_skills/sql_query_optimizer/api/tests/test_credits_isolation.py (NEW -- CLEAN)
- **Purpose:** Tests CreditManager file isolation (addresses MEG-036)
- **Secrets:** No real keys -- uses temp directories and patched module constants.
- **Rating:** SECURE

---

## Detailed Findings

### SEC-011: TOCTOU Race Condition in LoreDocs File Export (EXISTING)
- **Severity:** MEDIUM
- **Category:** Business Logic / Data Integrity
- **Status:** EXISTING (from 2026-03-31 report)
- **Location:** `ron_skills/loredocs/loredocs/storage.py` lines 1083-1087
- **Description:** File export checks `dest.exists()` then writes with `shutil.copy2()`. Between the check and write, another process could create the file.
- **Remediation:** Use atomic file creation with `os.open(dest, os.O_CREAT | os.O_EXCL)` or `tempfile.mkstemp()` followed by rename.
- **Risk context:** Single-user local machine -- exploitation requires concurrent local processes. Low urgency.

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
- **Description:** Dynamic SQL via f-strings, but all user input goes through `?` parameterization. Keys from internal dicts, sort/filter fields validated against whitelists. No actual injection risk.

---

## Dependency Audit Results

| Product | Requirements File | pip-audit Result | Notes |
|---------|------------------|-----------------|-------|
| LoreConvo | `requirements-lock.txt` | PASS - 0 CVEs | All exact pins, clean |
| LoreDocs | `requirements-lock.txt` | PASS - 0 CVEs | All exact pins, clean |
| SQL Query Optimizer | `api/requirements.txt` | PASS - 0 CVEs | anthropic 0.87.0 (upgraded from 0.86.0) |
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
| AWS credentials | PASS | No AKIA patterns found in project code |
| Private keys / PEM files | PASS | No RSA/EC private keys found in project code |
| Stripe live keys | PASS | Only in gitignored .env (sk_test_ prefix = sandbox) |
| Recently changed files (6 files) | PASS | Scripts, tests, blog draft -- no secrets |

---

## OWASP Code Review Results

| Category | Status | Details |
|----------|--------|---------|
| SQL Injection | PASS | All queries (including new scripts) use parameterized `?` placeholders |
| Path Traversal | PASS | LoreDocs has multi-layer defense; new query_loredocs.py validates filenames |
| XSS | PASS | FTS5 input sanitized; no HTML template injection vectors |
| Insecure Deserialization | PASS | No pickle, unsafe yaml, eval, or exec in project source code |
| Command Injection | PASS | No subprocess, os.system, or os.popen with user input |
| Broken Access Control | PASS | Tier enforcement, BSL session limit, admin auth all verified |
| Security Misconfiguration | PASS | Security headers comprehensive, CORS env-var-driven, rate limiting active |

---

## Infrastructure Review

| Area | Status | Notes |
|------|--------|-------|
| .gitignore coverage | GOOD | All three products now have product-level .gitignore (SEC-013 resolved) |
| Git lock files | WATCH | HEAD.lock and maintenance.lock present -- clean with: `find .git -name "*.lock" -delete` |
| Stale worktree | INFO | `.claude/worktrees/pedantic-bardeen/` exists -- clean with `git worktree prune` |
| Staged changes | NOTE | 3 files staged (anthropic bump, two .gitignore files) -- SEC-012/013 fixes, awaiting commit |
| Public repo hygiene | GOOD | Internal docs removed from tracking. Pre-push verification scripts in place. |
| Debug mode in production | CLEAN | No `DEBUG=True` or `app.debug` in application code |
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
| Product .gitignore files | PASS | All three products now have .gitignore files |
| Pre-push verification script | PRESENT | `scripts/verify_public_repo_clean.sh` |
| History scrub script | PRESENT | `scripts/scrub_public_repos.sh` (needs Debbie to run) |
| Internal docs in history | NOTE | CLAUDE.md and other internal docs still exist in git history for both products. Scrub not yet run. |

**Standing recommendation for Debbie:** Run `bash scripts/scrub_public_repos.sh` before the next subtree push to public repos.

---

## Recommendations (Prioritized)

1. **Ron (next session -- commit pending fixes):** Commit the staged SEC-012 and SEC-013 fixes (anthropic 0.87.0 bump + SQL Optimizer .gitignore).

2. **Ron (next session):** Clean git lock files: `find .git -name "*.lock" -delete`

3. **Ron (housekeeping):** Clean stale worktree: `git worktree prune`

4. **Debbie (before next public push):** Run `bash scripts/scrub_public_repos.sh` to clean internal docs from public repo git history.

5. **Ron (near-term):** Fix TOCTOU race in LoreDocs export (SEC-011) using atomic file creation before any multi-user deployment.

6. **Ron (before production):** Address CreditManager race condition (SEC-006) by adding file locking or migrating to SQLite.

7. **Debbie (low priority):** Rotate Anthropic API key at next convenient opportunity (SEC-001). No urgency -- key is local-only and gitignored.

---

## Report Comparison vs 2026-04-02

| Metric | 2026-04-02 | 2026-04-03 | Change |
|--------|-----------|-----------|--------|
| Total active findings | 6 | 4 | -2 (SEC-012 + SEC-013 resolved) |
| CRITICAL | 0 | 0 | No change |
| HIGH | 0 | 0 | No change |
| MEDIUM | 2 (SEC-011, SEC-012) | 1 (SEC-011) | -1 (SEC-012 resolved) |
| LOW | 2 (SEC-006, SEC-013) | 1 (SEC-006) | -1 (SEC-013 resolved) |
| INFO | 2 (SEC-001, SEC-009) | 2 (SEC-001, SEC-009) | No change |
| CVEs found | 2 | 0 | -2 (all patched) |
| Resolved (cumulative) | 7 | 9 | +2 (SEC-012, SEC-013) |
| New findings | 2 | 0 | Improvement |
| New code files reviewed | N/A | 4 (all clean) | N/A |

**Trend:** Improving. Two findings resolved, zero new findings. CVE count back to zero.
Dependency posture across all three products is fully clean. New agent fallback scripts
follow security best practices (parameterized SQL, filename validation). Only two
medium/low findings remain, both race conditions with low exploitability on the
current single-user setup.

---

*Report generated by Brock (automated security agent) - 2026-04-03*
*Next scheduled run: 2026-04-04 03:00 AM*
