# NotebookLM Skill — Setup & Onboarding

**Date:** 2026-04-08
**Skill:** RoboNuggets NotebookLM skill for Claude
**Repo:** https://github.com/robonuggets/notebooklm-skill
**Built on:** [notebooklm-py](https://github.com/teng-lin/notebooklm-py) by Teng Lin

## What it does

Connects Claude (Code or Cowork) to Google NotebookLM so an agent can:

- List, create, and describe notebooks
- Add sources programmatically (URLs, PDFs, files, raw text) — no manual copy/paste
- Query notebooks (RAG-style answers grounded in your sources)
- Generate branded presenter slide decks from inside NotebookLM
- Keep Google auth alive via an optional headless cookie refresh

The skill ships as a SKILL.md plus two Python scripts (`scripts/nlm.py` is the CLI wrapper; `scripts/refresh_auth.py` is the optional headless refresher). All notebook operations go through `python scripts/nlm.py <command>`.

## Files staged in this repo

A clean copy (no `.git`) is checked in at:

```
external_skills/notebooklm-skill/
├── SKILL.md
├── README.md
├── INSTALL_PROMPT.md
└── scripts/
    ├── nlm.py
    └── refresh_auth.py
```

This is the working copy. The skill itself needs to live in `~/.claude/skills/notebooklm/` on Debbie's Mac to be discoverable by Claude Code (see manual install steps below — Cowork cannot write to `~/.claude` from the VM, so this is a Debbie task).

## Manual install steps Debbie needs to do

The Cowork VM cannot write to `~/.claude/` (read-only mount), so installation has to happen on the Mac. Run these from a Mac terminal:

```bash
# 1. Copy the skill into Claude's skills directory
mkdir -p ~/.claude/skills/notebooklm
cp -R ~/projects/side_hustle/external_skills/notebooklm-skill/* ~/.claude/skills/notebooklm/

# 2. Install the underlying Python library (pin recommended — see below)
pip install "notebooklm-py[browser]"
playwright install chromium

# 3. One-time Google auth (opens a real browser window)
python ~/.claude/skills/notebooklm/scripts/nlm.py login
# -> Sign into Google, wait until the NotebookLM homepage loads, then press ENTER
# -> Cookies are written to ~/.notebooklm/storage_state.json

# 4. Verify
python ~/.claude/skills/notebooklm/scripts/nlm.py list
# -> Should print your existing notebooks
```

After step 4, restart Claude Code (or `/skills reload`) and confirm `notebooklm` shows up in the skill list.

### Pinning note (project rule)

Project Ron's standing rule is to pin every Python dependency. After confirming the install works, lock the version:

```bash
pip show notebooklm-py | grep Version
# then add to a requirements file:
notebooklm-py[browser]==<that_version>
```

Run `pip-audit` after install and flag any advisories before relying on the skill in scheduled agent tasks.

## Auth — the likely blocker

The only step that cannot be automated is the one-time Google sign-in. Google session cookies last 7–30 days. Two options:

- **Manual refresh:** When `nlm.py list` starts failing with an auth error, re-run `python ~/.claude/skills/notebooklm/scripts/nlm.py login`. ~30 seconds.
- **Headless auto-refresh:** `scripts/refresh_auth.py` can be scheduled (cron / launchd / Cowork scheduled task) to refresh cookies without opening a window. See the "Keeping Auth Alive" section in `SKILL.md` for the exact setup. Requires that the saved storage_state.json still be valid the first time it runs.

If 2FA / advanced protection is on the Google account, the browser-based login is the only path that works — there is no service-account or API-key flow.

## Which agents should use this

- **Madison (marketing)** — drop competitor blogs, industry reports, and conference talks into a "Marketing Research" notebook. Query it for grounded copy ideas instead of free-form web research. Lower hallucination risk for blog drafts.
- **Competitive Intel agent** — primary user. Maintain a "Competitors" notebook per tracked vendor (Cipher, Lossless Claw, etc.). Add new pages as sources, then query for diff-style findings. Source-grounded answers are exactly the agent's output format.
- **Gina (enterprise architect)** — keep an "Architecture Reference" notebook of papers, vendor docs, and ADRs she cites. When reviewing pipeline opportunities, query it for prior art and trade-off precedents instead of re-deriving from memory.

Other agents (Ron, Meg, Brock, Jacqueline, Scout, John) do not need this in v1. Revisit if Scout's research feeds get noisy and we want a curated source layer.

## Gotchas

- **Cowork cannot install this.** `~/.claude/` is read-only inside the Cowork VM. The skill must live on the Mac. Cowork sessions can still *use* it once it's installed in Claude Code, but only Code sessions reading `~/.claude/skills/` will discover it through the normal SKILL.md mechanism.
- **Single-machine auth.** `~/.notebooklm/storage_state.json` is tied to one Mac and one Google session. Don't try to sync it between machines.
- **Browser window on first login.** Expected. Only happens once per refresh cycle.
- **Do not install `notebooklm-py` from `main`.** The README explicitly says pin to a release tag. Use `pip install "notebooklm-py[browser]"` (PyPI) or a specific `git+...@<tag>` ref.
- **Slide generation prompts the user for brand colors.** When agents call the slide flow, they should pass Labyrinth Analytics' palette automatically rather than asking Debbie every time. (TODO for whichever agent adopts it first.)
- **Public-repo hygiene still applies.** Do not commit notebook IDs, source URLs containing internal data, or anything from a notebook into `ron_skills/loreconvo/` or `ron_skills/loredocs/` — those repos are public.

## Status checklist

- [x] Skill repo cloned and staged at `external_skills/notebooklm-skill/`
- [x] README and SKILL.md reviewed
- [x] Onboarding doc written (this file)
- [ ] **Debbie:** Copy to `~/.claude/skills/notebooklm/` on the Mac
- [ ] **Debbie:** `pip install "notebooklm-py[browser]" && playwright install chromium`
- [ ] **Debbie:** Run `nlm.py login` to authorize Google
- [ ] **Debbie:** Verify with `nlm.py list`
- [ ] **Debbie:** Pin notebooklm-py version in a requirements file
- [ ] **Debbie:** Decide whether to enable headless cookie refresh
- [ ] **Ron (after Debbie confirms):** Update Madison / competitive-intel / Gina agent prompts to mention the skill is available
