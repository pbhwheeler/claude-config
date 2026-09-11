---
description: Digest of MARKED open items across all projects, grouped by what is actually blocking each — to pick a focus for this session
---

Run the generator, then do the part it cannot: judge what is *actionable right now*.

```
python3 ~/.claude-config/scripts/open_items.py
```

## ⚠ Read this first — what the digest is and is not
- **It is a FLOOR, not a census.** It reports only lines carrying a `⏳` / `🗓️` marker. An adversarial
  review (2026-09-11) found ~20 genuinely open lines with no marker — "not yet deployed", "NOT yet
  fixed", "not yet applied" — some months old. **Say so in the summary every time**: "N marked items;
  unmarked open work exists."
- **RAISED age is not overdue.** Many items are correctly waiting on an event (next HA restart, a part,
  N clear days). Before recommending one, **open its source file and check whether the waiting
  condition has already been met** — several quietly become actionable and nobody notices.
- Generated, never hand-maintained: a static list drifts and breaks `feedback_memory_correct_in_place`.
  Never create a parallel TODO file. Marking convention → `feedback_open_item_markers`.
- Deliberately NOT `memory_lint.py` (its contract excludes prose). Separate tool on purpose.

## How to present it
Do **not** dump the raw output. Regroup by **what is blocking**, because that decides whether it can
be worked now:
- **NEEDS A DECISION FROM THE USER** — forks, authorizations. Cheap to clear; often unblocks several
  builds. Surface first.
- **READY** — nothing blocking; startable and finishable this session.
- **WAITING ON HARDWARE / DELIVERY** — not this session regardless of interest.
- **WAITING ON DATA / WEATHER / TIME** — and whether the wait is *already over*.
- **ON A CLOCK** — explicit deadlines; call out anything overdue.

Then recommend **two or three** focus candidates. ★ **Every recommendation must cite its source memory
file** (e.g. `→ hvac_project`) so the classification is checkable next session and not just this
session's opinion. Say which one you would pick and why. Keep it scannable — it is read on a phone.

## Rules
- ⛔ Never remark on the time of day or defer work because of the hour (`feedback_user_works_at_night`).
  Defer only for a real blocker, and name it.
- ⚠ Energy-controller items carry `feedback_energy_no_build_without_auth` — proposals only until the
  user authorizes a build.
- ★ If an item looks **stale** rather than open (done but the marker never became `✅`), say so and offer
  to close it in place. Surfacing drift is a feature.
- The digest counts markers, not importance; a one-line `⏳` can outrank a long section.
