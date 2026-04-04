Run a competitive intelligence scan for the Lore product family: LoreConvo (persistent conversational memory across AI sessions, SQLite-backed) and LoreDocs (document reference management for AI sessions, SQLite-backed). Both are Claude Code/Cowork plugins.

## TURN BUDGET: 20 TOOL CALLS MAXIMUM
- At 15 tool calls: Begin wrap-up (write report, commit, save LoreConvo).
- At 20 tool calls: STOP IMMEDIATELY, save session, exit.
- NEVER exceed 50 tool calls in a single session.

## GIT: USE safe_git.py ONLY
```
python scripts/safe_git.py commit -m "message" --agent "competitive-intel" file1 file2
python scripts/safe_git.py push
```
Do NOT use raw git commands. Do NOT fight lock files. 1 call for commit, 1 for push, max.

## SESSION STARTUP
1. `python scripts/safe_git.py status`
2. `python scripts/save_to_loreconvo.py --read --limit 10` -- read ALL agents. Search `agent:debbie` for product direction decisions.
3. Read `CLAUDE.md` for current product status and features
4. Read previous competitive intel reports for trend comparison

## INPUTS
- Web research: Claude ecosystem, GitHub, AI plugin marketplaces
- Previous competitive intel reports
- Current product feature lists from `ron_skills/<product>/CLAUDE.md`
- LoreConvo sessions (especially `agent:debbie` for product direction)

## OUTPUTS
- Competitive analysis report (HTML or markdown)
- LoreConvo session (surface: `pipeline`, tags: `["agent:competitive-intel"]`)

## RESEARCH SCOPE
Search for the top 5 tools/products most similar to each Lore product across:
- Claude plugin ecosystem (official and community)
- GitHub repositories
- AI agent infrastructure tools
- Knowledge management tools for LLMs

## COMPARISON CRITERIA
For each competitor: name, pricing, key differentiators, weaknesses relative to Lore, feature overlap percentage, threat level (LOW/MEDIUM/HIGH).

## RULES
- Use Lore branding consistently (LoreConvo, LoreDocs)
- Focus on actionable competitive intelligence, not just feature lists

## SESSION SAVE (MANDATORY)
```
python scripts/save_to_loreconvo.py \
    --title "Competitive intel scan YYYY-MM-DD" \
    --surface "pipeline" \
    --summary "COMPLETED: ... | BLOCKED: ... | PENDING_GIT: ... | HANDOFFS: ..." \
    --tags '["agent:competitive-intel"]' \
    --artifacts '["path/to/report"]'
```
