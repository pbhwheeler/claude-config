---
description: Digest of open items across all projects, grouped by what is actually blocking each — to pick a focus for this session
---

Run the generator, then do the part it cannot: judge what is *actionable right now*.

```
python3 ~/.claude-config/scripts/open_items.py
```

## Why a script + judgement, and not a hand-maintained list
A static list of open items drifts the moment any project moves, and duplicated facts are exactly what
breaks `feedback_memory_correct_in_place`. The `⏳` / `🗓️` markers already in the prose ARE the source
of truth — the script only collects them. **Never create a parallel hand-kept TODO file.**

⚠ This is deliberately NOT part of `memory_lint.py`, whose contract is "facts with one machine-checkable
ground truth, and deliberately nothing else — the prose in memory is hand-curated judgement and is none
of this script's business." This reads only prose, so it is a separate tool on purpose.

## How to present it

Do **not** dump the raw output. Read it, open the source memory file for anything ambiguous, and
regroup by **what is blocking**, because that is what decides whether it can be worked now:

- **READY** — nothing blocking; could be started and finished in one session.
- **NEEDS A DECISION FROM THE USER** — design forks, authorizations. Cheap to clear, and clearing one
  often unblocks several build items. Surface these first; they are the highest leverage.
- **WAITING ON HARDWARE / DELIVERY** — a part is not here yet. Not tonight, regardless of interest.
- **WAITING ON DATA, WEATHER OR TIME** — needs N clear days, a matched weather day, a 48 h window, the
  next HA restart. ⚠ Check whether the waiting condition has *already been met* — several of these
  quietly became actionable and nobody noticed.
- **ON A CLOCK** — has an explicit due/revisit date. Call out anything genuinely overdue.

Then recommend **two or three** candidate focus areas with a one-line reason each, and say plainly which
one you would pick and why. Keep it scannable — this is often read on a phone.

## Rules
- ⛔ **Do not remark on the time of day, and never suggest deferring work because of the hour**
  ([[feedback_user_works_at_night]]). Defer only for a real blocker, and name that blocker.
- ⚠ Energy-controller items carry `feedback_energy_no_build_without_auth` — they are proposals only
  until the user authorises a build.
- ★ If an item looks stale rather than open (the work was done but the marker was never cleared), say
  so and offer to correct the memory in place. The digest surfacing drift is a feature, not noise.
- The digest counts markers, not importance. A one-line `⏳` can outrank a long section.
