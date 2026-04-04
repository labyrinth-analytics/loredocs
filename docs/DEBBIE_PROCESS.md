# Debbie's Communication Playbook

How to communicate with the agent team so decisions flow reliably and nothing gets lost.

---

## The 3 Places Agents Look for Your Input

Agents check these in order at session start. You only need to update ONE of them for your decision to propagate -- but using #1 is the most reliable since every agent reads it directly.

### 1. DEBBIE_DASHBOARD.md (primary -- agents read this every session)

This is the single source of truth. Jacqueline updates it daily with agent outputs, but **you write your decisions here too**. Every agent reads this file at session start.

**Where:** `docs/DEBBIE_DASHBOARD.md`

**What to update:**

| Section | When to update | What to write |
|---------|----------------|---------------|
| Decisions Made | When you approve, reject, or change direction | Add a dated entry: `### N. DECIDED: description (YYYY-MM-DD)` with status |
| Things Only Debbie Can Do | When you complete a Debbie TODO | Move it to a `### Completed` subsection with the date |
| Pipeline Items | When you triage Scout opportunities | Write disposition for each OPP: `OPP-XXX: APPROVED / REJECTED / DEFERRED / NEEDS INFO` |
| Reviews Waiting | When you've reviewed a Meg/Brock/Gina finding | Add: `Debbie reviewed YYYY-MM-DD: [your decision]` |

### 2. LoreConvo (secondary -- agents search for `agent:debbie`)

Use this when you want to communicate something that doesn't fit neatly into the dashboard, or when working in a Cowork session where I can save it for you.

**How:** Tell me in our Cowork session: "Log this decision to LoreConvo" and I will save it with the `agent:debbie` tag. All agents search for `agent:debbie` at session start.

**Or manually from your Mac:**
```bash
cd ~/projects/side_hustle
python scripts/save_to_loreconvo.py \
    --title "Debbie decisions YYYY-MM-DD" \
    --surface "cowork" \
    --summary "DECISIONS: ... | COMPLETED: ... | NOTES: ..." \
    --tags '["agent:debbie"]'
```

### 3. CLAUDE.md Debbie TODOs (for TODO-specific status changes)

Only update this if you want to mark a specific Debbie TODO as done or add a new one. Ron syncs from here to PipelineDB.

---

## Valid Statuses (Use These Exact Words)

Agents are trained to recognize these status keywords. Using them consistently prevents misinterpretation.

### For Pipeline Opportunities (OPP-XXX)

| Status | Meaning | What happens next |
|--------|---------|-------------------|
| `APPROVED` | Build it | Ron adds to his TODO list |
| `APPROVED-FOR-REVIEW` | Looks promising, needs Gina's architecture assessment | Gina writes a proposal |
| `NEEDS INFO` | Interesting but missing details | Scout researches further next Monday |
| `DEFERRED` | Not now, maybe later | Parked, revisited quarterly |
| `REJECTED` | Not a fit | Archived, no further work |
| `ON HOLD` | Blocked on something specific | State the blocker (e.g., "ON HOLD -- no local SQL Server") |

### For Debbie TODOs

| Status | Meaning |
|--------|---------|
| `DONE` or `COMPLETED` | Task finished. Include the date. |
| `IN PROGRESS` | You're working on it |
| `BLOCKED` | State what's blocking you |
| `DEFERRED` | Pushed to a later date |

### For Agent Findings (Meg/Brock/Gina)

| Status | Meaning |
|--------|---------|
| `ACKNOWLEDGED` | Seen it, Ron should fix in priority order |
| `FIX SCHEDULED` | Ron will fix (specify priority) |
| `WONT FIX` | Accepted risk, explain why |
| `COMPLETED` | Fix verified |

---

## Quick Decision Templates

Copy-paste these into DEBBIE_DASHBOARD.md:

**Approve a pipeline opportunity:**
```
### N. DECIDED: OPP-XXX approved (YYYY-MM-DD)
APPROVED. Priority: P[1-5]. Notes: [any constraints].
```

**Reject a pipeline opportunity:**
```
### N. DECIDED: OPP-XXX rejected (YYYY-MM-DD)
REJECTED. Reason: [why].
```

**Mark a Debbie TODO as done:**
Under "Things Only Debbie Can Do", move the item to a Completed subsection:
```
#### COMPLETED: [item description] (YYYY-MM-DD)
Done. [any notes about what you did].
```

**Respond to agent finding:**
Under "Reviews Waiting", add below the finding:
```
> Debbie reviewed YYYY-MM-DD: ACKNOWLEDGED. Ron fix in next session.
```

---

## Daily Routine (5 minutes)

1. Open `docs/internal/pm/executive_dashboard_YYYY_MM_DD.html` (Jacqueline's daily report)
2. Scan the action items -- anything urgent?
3. Open `docs/DEBBIE_DASHBOARD.md` -- update any decisions you've made
4. If you completed a Debbie TODO, mark it COMPLETED with date
5. If Scout has untriaged opportunities, write dispositions

That's it. The agents pick up your changes on their next run.

---

## When Working With Me in Cowork

Just tell me what you decided or completed. I will:
- Update DEBBIE_DASHBOARD.md for you
- Save a LoreConvo session tagged `agent:debbie`
- Update CLAUDE.md if needed

Examples of things to tell me:
- "I pushed the marketplace repo to GitHub -- mark TODO #6 as done"
- "Approve OPP-017 and OPP-019, reject the others"
- "I saved the signing key to 1Password -- mark that urgent item as done"
- "Defer the Stripe activation until we have users"
