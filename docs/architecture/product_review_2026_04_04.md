# Product Architecture Review - 2026-04-04

**Agent:** Gina (Enterprise Architect)
**Run type:** Scheduled (Wed/Sat)
**Products reviewed:** LoreConvo v0.3.0, LoreDocs v0.1.0
**Git range:** Last 4 days (2026-03-31 through 2026-04-04)

---

## Executive Summary

Two major features shipped this period: (1) the Ed25519 license key validation system
for both products, and (2) the /lore-onboard first-time setup wizard skill for LoreConvo.
The cryptographic implementation is sound (Brock confirmed in security_report_2026_04_03_b.md).

Two architectural concerns are raised:

1. **LoreDocs vault_set_tier bypasses license validation** (MEDIUM) -- a user can call
   `vault_set_tier('pro')` via MCP to unlock Pro without a license key, because the
   config.json fallback in get_tier() is read before the license check returns False
   for an empty LOREDOCS_PRO env var.

2. **lore-onboard skill not included in the .plugin bundle** (MEDIUM) -- the skill was
   built and committed to the product source tree but not packaged into the .plugin file.
   Users installing from the marketplace will not get the /lore-onboard command.

One SEC-014 tracking item (cryptography not in pyproject.toml) is confirmed -- this is
a Brock finding, noted here for cross-reference.

---

## Changes Reviewed

| Commit | Date | Description |
|--------|------|-------------|
| 9e6060f | 2026-04-03 | ron: build /lore-onboard skill (LoreConvo) |
| 9ad2bc1 | 2026-04-03 | ron: Ed25519 license key validation (both products) |
| 4b483da | 2026-04-03 | Build marketplace repo, fix plugin .mcp.json defaults |
| 79bf5c4 | 2026-04-03 | meg: 7 sync tests (QA) |
| c0a2c46 | 2026-04-02 | Fallback scripts for agents |

---

## LoreConvo (v0.3.0)

### Code Architecture

**Rating: SOLID**

The license.py module (ron_skills/loreconvo/src/core/license.py) is well-structured:
- Clean separation: validate_license_key() handles parsing + verification; is_pro_licensed()
  handles the env var read; get_license_status() handles diagnostics.
- The dev bypass correctly requires two env vars (LAB_DEV_MODE=1 AND a non-LAB- value),
  preventing accidental activation in public deployments.
- The `_load_public_key()` pattern (importing `cryptography` lazily inside the function)
  means the import error surfaces at validation time rather than at startup, which is the
  right behavior for a dependency that may be missing (see SEC-014 below).
- Config.is_pro property correctly delegates to is_pro_licensed() without caching,
  ensuring every tier check reads the current env state.

The onboard_verify.py script (ron_skills/loreconvo/scripts/onboard_verify.py) is
well-designed as a standalone diagnostic tool with clean dataclass-based reporting.
The --json output flag is a good pattern for automated health checks.

### CONCERN 1 (MEDIUM): lore-onboard skill not in plugin bundle

**File:** ron_skills/loreconvo/skills/lore-onboard/SKILL.md (source)
**Plugin bundle contents:** skills/recall/SKILL.md, skills/save/SKILL.md ONLY

The /lore-onboard skill was built in the product source tree but NOT included in the
loreconvo-v0.3.0.plugin file. The plugin zip contains only the recall and save skills.

This means:
- Users installing `loreconvo@labyrinth-analytics-claude-plugins` will NOT get /lore-onboard
- The skill only exists for developers running from source
- The product's own README mentions the onboarding wizard; it will not appear for marketplace users

**Recommendation for Ron:**
Rebuild the .plugin bundle to include the lore-onboard skill:
1. Add ron_skills/loreconvo/skills/lore-onboard/ to the plugin skills directory
2. Verify plugin.json references (or update if plugin format auto-discovers skills/)
3. Repackage: cd ron_skills/loreconvo-plugin && zip -r ../loreconvo-v0.3.0.plugin .

### CONCERN 2 (LOW): onboard_verify.py path discovery in uvx context

**File:** ron_skills/loreconvo/scripts/onboard_verify.py, function _find_src_path() (line ~17)

_find_src_path() tries to locate the src directory relative to the script's location.
When running via `uvx loreconvo`, scripts are not in a predictable path relative to src.
The CLAUDE_PLUGIN_ROOT fallback may not be set in all install contexts.

The hooks check (check_hooks, line ~178) has the same issue: it looks for
hooks/scripts/ relative to script_dir.parent or CLAUDE_PLUGIN_ROOT.

This is LOW severity because onboard_verify.py is currently more of a developer/agent
diagnostic tool than a user-facing command. But if it's promoted in docs as a
user-runnable diagnostic, the path resolution failure will confuse users.

**Recommendation for Ron:**
Add a third path resolution fallback for installed package context:
```python
# Try installed package location via importlib.resources
try:
    import importlib.resources as pkg_resources
    import loreconvo
    pkg_dir = Path(loreconvo.__file__).parent
    candidate = pkg_dir.parent / "src"
    if candidate.exists():
        return str(candidate)
except Exception:
    pass
```

Or: document that onboard_verify.py is intended for development use only, and that
the /lore-onboard SKILL.md is the user-facing onboarding experience.

### CONCERN 3 (LOW, cross-reference SEC-014): cryptography not in pyproject.toml

**File:** ron_skills/loreconvo/pyproject.toml

pyproject.toml declares `dependencies = ["mcp[cli]>=1.0.0", "click>=8.0.0"]` only.
The `cryptography` package is missing. A fresh `uvx loreconvo` install that hits a
LORECONVO_PRO key will raise ImportError at the lazy import in _load_public_key().

This is a Brock finding (SEC-014, MEDIUM). Confirmed architecturally: the dependency
must be declared. Ron should add `cryptography>=41.0.0` to pyproject.toml dependencies.

### Security Architecture

**Rating: STRONG (with noted exceptions)**

The dual-env-var dev bypass design (LAB_DEV_MODE + LORECONVO_PRO) is architecturally
correct. The public .mcp.json files do not include LAB_DEV_MODE. The trust boundary
between public distribution and internal agent use is correctly enforced at the
configuration level, not the code level.

---

## LoreDocs (v0.1.0)

### Code Architecture

**Rating: SOLID WITH ONE GAP**

The tiers.py module (ron_skills/loredocs/loredocs/tiers.py) correctly integrates
with license.py: get_tier() calls is_pro_licensed() FIRST, and only falls back to
config.json if no license key is present. The license check is the primary gate.

However, there is an architectural gap in the vault_set_tier MCP tool.

### CONCERN 4 (MEDIUM): vault_set_tier allows Pro activation without a license key

**File:** ron_skills/loredocs/loredocs/server.py, function vault_set_tier() (line ~1390)

The vault_set_tier MCP tool writes the chosen tier directly to config.json without
validating a license key. The tool's own docstring acknowledges this:
> "Note: In a future release this will verify a license key. For now it trusts
> the caller (suitable for single-user local installs)."

The bypass path:
1. User calls vault_set_tier(tier='pro') via MCP (no LOREDOCS_PRO env var needed)
2. tiers.py writes "pro" to ~/.loredocs/config.json
3. Next call to get_tier() calls is_pro_licensed(), which returns False (no env var)
4. Falls through to config.json -- reads "pro" -- returns TIER_PRO
5. TierEnforcer.limits() returns PRO_LIMITS (no vault/doc/storage limits)
6. User has Pro tier without a license key

This is a MEDIUM severity architectural gap. The license.py system was just built
to enforce paid access, but vault_set_tier allows bypassing it entirely.

**Recommendation for Ron:**
Validate the license key before writing Pro to config in vault_set_tier:
```python
async def vault_set_tier(params: VaultSetTierInput, ctx: Context) -> str:
    if params.tier == TIER_PRO:
        # Must have a valid Pro license key in LOREDOCS_PRO
        pro_env = os.environ.get("LOREDOCS_PRO", "").strip()
        if not pro_env:
            return (
                "Error: LOREDOCS_PRO environment variable must be set to a valid "
                "Labyrinth Analytics license key to activate Pro tier. "
                "Get a license key at labyrinthanalyticsconsulting.com."
            )
        from .license import is_pro_licensed, LicenseError
        if not is_pro_licensed(pro_env):
            return "Error: The provided license key is invalid or expired."
    # Proceed with set_tier...
    storage = _get_storage(ctx)
    set_tier(storage.root, params.tier)
    ...
```

Note: The config.json fallback in get_tier() can remain for legitimate cases where
LOREDOCS_PRO is set in the environment -- this allows Pro tier to be confirmed
without re-validating the key on every API call. The fix is specifically to prevent
vault_set_tier from writing "pro" without a key.

### CONCERN 5 (LOW, cross-reference SEC-014): cryptography not in pyproject.toml

Same finding as LoreConvo. Ron should add `cryptography>=41.0.0` to
ron_skills/loredocs/pyproject.toml dependencies.

### Security Architecture

**Rating: STRONG (with vault_set_tier gap noted above)**

The TierEnforcer pattern is well-designed. All write operations route through
TierEnforcer.check_*() methods before executing. The license integration in
get_tier() is correct for runtime enforcement. The remaining gap is
specifically the config.json persistence path via vault_set_tier.

---

## Cross-Product Consistency

**Rating: GOOD**

Both products now share the same license.py pattern (copy-adapted for product name),
the same dev bypass design, and the same pyproject.toml structure. The tier enforcement
patterns are appropriately different (LoreConvo uses session count limits, LoreDocs uses
vault/doc/storage count limits) given their different data models.

One minor divergence: LoreConvo's tier is checked via `Config.is_pro` property on every
database operation; LoreDocs checks via `get_tier(root)` called at the start of each
operation. Both are correct. The LoreConvo property approach is slightly more testable.
Consider standardizing in a future refactor, but not a blocking issue.

---

## Summary Table

| Concern | Severity | Product | File | Status |
|---------|----------|---------|------|--------|
| lore-onboard not in .plugin bundle | MEDIUM | LoreConvo | loreconvo-v0.3.0.plugin | Open |
| vault_set_tier bypasses license validation | MEDIUM | LoreDocs | server.py:1390 | Open |
| cryptography missing from pyproject.toml | MEDIUM | Both | pyproject.toml | Open (Brock SEC-014) |
| onboard_verify.py path discovery fragility | LOW | LoreConvo | onboard_verify.py:17 | Open |

---

## Recommended Actions for Ron (priority order)

1. Add `cryptography>=41.0.0` to pyproject.toml in both LoreConvo and LoreDocs
   (also fixes Brock SEC-014)
2. Fix vault_set_tier in LoreDocs server.py to validate license key before writing "pro"
3. Rebuild loreconvo-v0.3.0.plugin to include the lore-onboard skill
4. Document or fix onboard_verify.py path discovery for non-development installs
