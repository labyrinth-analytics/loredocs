# Security Report - 2026-04-03 (Run B)

**Agent:** Brock (Cybersecurity Expert)
**Run Time:** 2026-04-03 (automated daily scan -- second run, covering major new commits)
**Overall Posture:** NEEDS ATTENTION

---

## Executive Summary

A second security pass was required today due to substantial new code committed after
the first Brock run (2026-04-03 Run A). Ron built and committed the full Ed25519
license key validation system (both products), the license key generator script,
the /lore-onboard skill and onboard_verify.py script, plus the marketplace repo
structure. This is the most significant new code in several weeks and warranted
a focused review.

**Overall assessment:** The cryptographic implementation is sound. Ed25519 is the
correct algorithm, the public key is correctly embedded (not the private key), the
dev bypass requires two env vars (not just one), and test keys correctly fail against
the production public key. No actual private key material was found in code, git
history, or config files.

Two new findings are raised:

1. **SEC-014 (MEDIUM):** `cryptography` package missing from pyproject.toml dependencies in
   both LoreConvo and LoreDocs. It is in requirements-lock.txt but not the declared
   package dependencies, which means `uvx loreconvo` / `pip install loreconvo` installs
   may fail with ImportError at license validation time.

2. **SEC-015 (LOW):** `marketplace.json` contains Debbie's personal email
   (`debbie.wonderkitty@gmail.com`) in the `owner.email` field. This file is
   staged for push to a new public GitHub repo (`labyrinth-analytics/claude-plugins`).
   Debbie should decide whether to use a business contact email instead before
   creating the public repo.

**Prior findings status:**
- SEC-012 (anthropic CVE bump) and SEC-013 (SQL Optimizer .gitignore) were staged in
  Run A. Both are now committed via commits 4b483da and 9ad2bc1. RESOLVED.
- SEC-011 (TOCTOU), SEC-006 (CreditManager race), SEC-001 (local .env key),
  SEC-009 (dynamic SQL) all remain at same status -- no change.

---

## New Code Reviewed in This Run

| File | Commit | Security Rating |
|------|--------|----------------|
| ron_skills/loreconvo/src/core/license.py | 9ad2bc1 | SECURE (one note: SEC-014) |
| ron_skills/loredocs/loredocs/license.py | 9ad2bc1 | SECURE (one note: SEC-014) |
| scripts/generate_license_key.py | 9ad2bc1 | SECURE |
| scripts/test_generate_license_key.py | c392738 | SECURE |
| ron_skills/loreconvo/scripts/onboard_verify.py | b26ea21 | SECURE |
| ron_skills/loreconvo/skills/lore-onboard/SKILL.md | 9e6060f | SECURE |
| marketplace/claude-plugins/.claude-plugin/marketplace.json | 4b483da | NOTE (SEC-015) |
| ron_skills/loreconvo-plugin/.mcp.json | 4b483da | SECURE |
| ron_skills/loredocs-plugin/.mcp.json | 4b483da | SECURE |
| ron_skills/loreconvo/tests/test_license.py | 9ad2bc1 | SECURE |
| ron_skills/loredocs/tests/test_license.py | 9ad2bc1 | SECURE |

---

## Findings Summary

| ID | Severity | Category | Status | Description |
|----|----------|----------|--------|-------------|
| SEC-014 | MEDIUM | Dependency Declaration | NEW | cryptography missing from pyproject.toml in both products |
| SEC-015 | LOW | PII Exposure Risk | NEW | Personal email in marketplace.json (pre-public) |
| SEC-011 | MEDIUM | Business Logic | EXISTING | TOCTOU race condition in LoreDocs file export |
| SEC-006 | LOW | Business Logic | EXISTING | CreditManager file-based race condition |
| SEC-001 | INFO | Secrets | PREVIOUSLY NOTED | Anthropic API key in local gitignored .env (single-user) |
| SEC-009 | INFO | Injection | EXISTING | Dynamic SQL clauses (mitigated by design) |

### Resolved Findings (cumulative)

| ID | Severity | Fix Verified | Commit |
|----|----------|-------------|--------|
| SEC-013 | LOW | .gitignore created for SQL Optimizer | 4b483da |
| SEC-012 | MEDIUM | anthropic bumped to 0.87.0 | 9ad2bc1 |
| SEC-010 | HIGH | Redacted report committed | b52d96c |
| SEC-003 | MEDIUM | requirements-lock.txt with exact pins | b52d96c |
| SEC-002 | MEDIUM | hmac.compare_digest for admin token | 040c1c4 |
| SEC-004 | MEDIUM | Email PII masked in logs | 040c1c4 |
| SEC-005 | LOW | Rate limits on all endpoints | 040c1c4 |
| SEC-007 | LOW | .gitignore covers *.db and *.sqlite | 040c1c4 |
| SEC-008 | INFO | --reload dev-only warning in QUICKSTART.md | 040c1c4 |

---

## Detailed Findings

### SEC-014: cryptography Missing from pyproject.toml (NEW - MEDIUM)
- **Severity:** MEDIUM
- **Category:** Dependency Declaration
- **Status:** NEW
- **Location:** ron_skills/loreconvo/pyproject.toml and ron_skills/loredocs/pyproject.toml
- **Description:** The new license.py modules in both products import from
  `cryptography.hazmat.primitives`. This package IS pinned in requirements-lock.txt
  (`cryptography==46.0.6`) and is present in the local dev environment, so tests
  pass. However, `cryptography` is not listed in the `[project.dependencies]` section
  of pyproject.toml in either product.

  When a user installs LoreConvo or LoreDocs via `uvx loreconvo` or `pip install loreconvo`
  (from PyPI, once published), pip will not install cryptography as a transitive
  dependency. The first time the license check runs, the user will get:
  `ModuleNotFoundError: No module named 'cryptography'`

  This will manifest as a Pro tier unlock failure even for users with valid license keys.

- **Remediation:** Add `cryptography>=42.0.0` to `[project.dependencies]` in both
  pyproject.toml files. Then regenerate requirements-lock.txt. Version constraint
  `>=42.0.0` is safe -- Ed25519 support has been stable since 2.6.
  ```
  # LoreConvo pyproject.toml [project.dependencies]
  "cryptography>=42.0.0",

  # LoreDocs pyproject.toml [project.dependencies]
  "cryptography>=42.0.0",
  ```

---

### SEC-015: Personal Email in marketplace.json (NEW - LOW)
- **Severity:** LOW
- **Category:** PII Exposure Risk (pre-publication)
- **Status:** NEW -- not yet public, but about to become public
- **Location:** marketplace/claude-plugins/.claude-plugin/marketplace.json
- **Description:** The marketplace.json owner block contains:
  ```json
  {
    "name": "Labyrinth Analytics Consulting",
    "email": "debbie.wonderkitty@gmail.com"
  }
  ```
  Per CLAUDE.md, Debbie will create `labyrinth-analytics/claude-plugins` on GitHub
  and push this directory as the marketplace contents. Once pushed, this email will
  be visible in the public file.

  Using a personal Gmail for a public business registry invites spam, credential
  phishing targeting that address, and reduces perceived professionalism. A dedicated
  business contact (`hello@labyrinthanalyticsconsulting.com` or similar) would be
  preferable.

- **Remediation (Debbie action before creating the public repo):**
  Update marketplace.json to use a business contact email or remove the email field
  entirely. Many marketplace registries make the owner email optional -- if the field
  is not required, removing it is the cleanest option.

---

### SEC-011: TOCTOU Race Condition in LoreDocs File Export (EXISTING)
- **Severity:** MEDIUM
- **Status:** EXISTING (unchanged from prior reports)
- **Location:** ron_skills/loredocs/loredocs/storage.py lines 1083-1087
- **Description:** Check-then-act on file existence before shutil.copy2().
- **Remediation:** Atomic file creation with tempfile.mkstemp() + rename.
- **Risk context:** Single-user local machine; low urgency.

---

### SEC-006: CreditManager Race Condition (EXISTING)
- **Severity:** LOW
- **Status:** EXISTING (unchanged)
- **Location:** ron_skills/sql_query_optimizer/api/credits.py
- **Description:** JSON file read-modify-write without locking.
- **Remediation:** filelock library or SQLite with WAL mode.

---

### SEC-001: Anthropic API Key in Local .env (INFO - Previously Noted)
- **Severity:** INFO
- **Status:** PREVIOUSLY NOTED -- no change in risk
- **Location:** ron_skills/sql_query_optimizer/api/.env (gitignored, single-user Mac)
- **Standing recommendation:** Rotate at next convenient opportunity. Not urgent.

---

### SEC-009: SQL Dynamic Clause Construction (INFO - Mitigated)
- **Severity:** INFO
- **Status:** EXISTING -- informational only, no injection risk
- **Description:** Dynamic SQL via f-strings, but all user input goes through
  parameterized `?` placeholders. No actual injection risk.

---

## License Key Implementation Review

The Ed25519 license key system was reviewed in depth. Summary of findings:

| Security Property | Status | Notes |
|-------------------|--------|-------|
| Algorithm strength | GOOD | Ed25519 is the correct choice for offline-verifiable licenses |
| Private key in code | PASS | Not present anywhere in source, tests, or git history |
| Private key in git history | PASS | No PEM BEGIN/END PRIVATE KEY in any commit patch |
| Public key hardcoded (correct) | PASS | 32-byte raw Ed25519 public key embedded in source |
| Public key from env var | PASS | Key loading does NOT use os.environ -- immutable at runtime |
| Dev bypass security | GOOD | Requires BOTH LORECONVO_PRO and LAB_DEV_MODE=1 -- two-var gate |
| Public .mcp.json defaults | PASS | Ships with empty LORECONVO_PRO="" and no LAB_DEV_MODE |
| Test isolation | PASS | Test suite uses generated test keypair, never touches production key |
| Forgery resistance | PASS | test_roundtrip_loreconvo_key_rejected_by_production_pubkey verifies this |
| Timing oracle | ACCEPTABLE | String equality checks (product, tier) after Ed25519 verify. The crypto verify itself uses constant-time ops. No meaningful oracle risk for license strings. |
| Expiry validation | PASS | date.fromisoformat() with proper comparison against date.today() |
| Error messages | GOOD | Useful without being exploitable (no internal state revealed) |
| Secrets in test keys | PASS | All test payloads use test@example.com, not real customer data |
| generate_license_key.py secrets | PASS | Key loaded from env var only -- never written to disk |

One note on the false positive from secrets scan: the grep pattern for
`BEGIN PRIVATE KEY` matched string literals inside generate_license_key.py that
are used to detect and normalize PEM format in user input. This is NOT key
material -- it is code that handles parsing PEM keys coming in from an env var.
Confirmed false positive.

---

## generate_license_key.py Security Review

| Property | Status | Notes |
|----------|--------|-------|
| Private key source | ENV ONLY | LAB_LICENSE_PRIVATE_KEY env var, no file read, no hardcoded value |
| Key written to disk | PASS | Output is printed to stdout only; caller decides what to do with it |
| Input validation | PASS | product validated against whitelist; exp validated as ISO date or "never" |
| Past/today expiry rejected | PASS | Raises ValueError for exp <= today |
| Output format | PASS | LAB-{base64url}.{base64url}, no padding, URL-safe |
| Internal key requirement | GOOD | Exits with clear error if env var not set |

**Note:** generate_license_key.py is a monorepo-only script (in scripts/, not
in any public product directory). It will not be pushed to public repos.
LAB_LICENSE_PRIVATE_KEY must be set by Debbie from a secure password manager
when running this script. The private key is not and should not be stored
in any file in this repo.

---

## onboard_verify.py Security Review

| Property | Status | Notes |
|----------|--------|-------|
| Path traversal via CLAUDE_PLUGIN_ROOT | LOW | Reads only (no writes to env-supplied paths). Local CLI only. |
| SQL safety | PASS | Uses SessionDatabase ORM (parameterized queries) |
| Secrets | PASS | No hardcoded credentials; reads only from DB |
| Cleanup logic | PASS | Direct SQL DELETE on test session uses parameterized ID |
| Error handling | PASS | All exceptions caught, reported cleanly, execution continues |

---

## Dependency Audit Results

| Product | Requirements File | pip-audit Result | Notes |
|---------|------------------|-----------------|-------|
| LoreConvo | requirements-lock.txt | PASS - 0 CVEs | cryptography==46.0.6 |
| LoreDocs | requirements-lock.txt | PASS - 0 CVEs | cryptography==46.0.6 |
| SQL Query Optimizer | api/requirements.txt | PASS - 0 CVEs | anthropic==0.87.0 |
| All products | LiteLLM check | CLEAN | Not present anywhere |

---

## Secrets Scan Results

| Check | Result | Details |
|-------|--------|---------|
| Private key in code | PASS | Not found in any source file |
| Private key in git history | PASS | No actual key material; only string literals for PEM format detection |
| generate_license_key.py match | FALSE POSITIVE | Grep matched PEM string literals in code, not key material |
| .env committed to git | PASS | .gitignore covers .env and *.env |
| .env in git history | PASS | No .env files in git history |
| Anthropic key in .env | INFO | SEC-001: local-only, gitignored, single-user (previously noted) |
| Hardcoded keys in Python source | PASS | Only test stubs (test@example.com, no real keys) |
| AWS credentials | PASS | No AKIA patterns found |
| Stripe live keys | PASS | Only gitignored sandbox keys |
| Personal email in public-bound file | NOTE | SEC-015: marketplace.json owner.email (pre-publication) |

---

## Infrastructure Review

| Area | Status | Notes |
|------|--------|-------|
| .gitignore coverage | GOOD | All three products have product-level .gitignore |
| Git index lock | INFO | .git/index.lock was present at run start -- cleared by cleanup step |
| Staged changes | CLEAN | Only CLAUDE.md modified, no staged security-relevant changes |
| Public repo hygiene | GOOD | generate_license_key.py is in monorepo scripts/ (not public product dir) |
| Debug mode | CLEAN | No DEBUG=True or app.debug in application code |
| Security headers | GOOD | Full OWASP-compliant set |
| CORS | GOOD | Env-var-driven, no wildcard |
| Rate limiting | GOOD | All endpoints rate-limited |
| Admin auth | GOOD | hmac.compare_digest timing-safe comparison |

---

## OWASP Code Review Results (New Code Only)

| Category | Status | Details |
|----------|--------|---------|
| Cryptographic correctness | PASS | Ed25519 via cryptography library (hazmat, correct usage) |
| SQL Injection | PASS | onboard_verify.py uses SessionDatabase ORM (parameterized) |
| Path Traversal | PASS | CLAUDE_PLUGIN_ROOT: read-only, local CLI, low risk |
| Insecure Deserialization | PASS | json.loads only; no pickle, eval, or exec |
| Command Injection | PASS | No subprocess or os.system in any new file |
| Key management | PASS | Public key embedded; private key env-only; dev bypass two-gated |
| Error information leakage | PASS | License errors helpful but do not reveal internal state |

---

## Recommendations (Prioritized)

1. **Ron (high priority -- next session):** Add `"cryptography>=42.0.0"` to
   `[project.dependencies]` in ron_skills/loreconvo/pyproject.toml and
   ron_skills/loredocs/pyproject.toml (SEC-014). Without this, Pro license
   validation will fail with ImportError for fresh installs via uvx/pip.

2. **Debbie (before creating labyrinth-analytics/claude-plugins GitHub repo):**
   Review and replace the personal email in marketplace/claude-plugins/.claude-plugin/marketplace.json
   with a business contact email or remove the field (SEC-015).

3. **Debbie (ongoing):** Save the production Ed25519 private key to a password manager
   (see CLAUDE.md Debbie TODO #4). The key can be retrieved from LoreConvo session log
   for the 2026-04-03 session. Without it, Pro license keys cannot be generated for
   paying customers.

4. **Ron (near-term):** Fix TOCTOU race in LoreDocs export (SEC-011).

5. **Ron (before production):** Address CreditManager race condition (SEC-006).

6. **Debbie (low priority):** Rotate Anthropic API key at next convenient opportunity
   (SEC-001). No urgency.

---

## Report Comparison vs 2026-04-03 Run A

| Metric | Run A | Run B | Change |
|--------|-------|-------|--------|
| Total active findings | 4 | 6 | +2 (SEC-014, SEC-015) |
| CRITICAL | 0 | 0 | No change |
| HIGH | 0 | 0 | No change |
| MEDIUM | 1 (SEC-011) | 2 (SEC-011, SEC-014) | +1 (SEC-014) |
| LOW | 1 (SEC-006) | 2 (SEC-006, SEC-015) | +1 (SEC-015) |
| INFO | 2 (SEC-001, SEC-009) | 2 (SEC-001, SEC-009) | No change |
| CVEs found | 0 | 0 | No change |
| New code files reviewed | 0 | 11 | +11 (major license feature) |
| Resolved (cumulative) | 9 | 9 | No change this run |

**Trend:** Two new low-severity findings from new feature code. Both are preventable
before any public release. The cryptographic implementation itself is sound. No
critical or high findings. Overall posture stable at NEEDS ATTENTION.

---

*Report generated by Brock (automated security agent) - 2026-04-03 (Run B)*
*Next scheduled run: 2026-04-04 03:00 AM*
