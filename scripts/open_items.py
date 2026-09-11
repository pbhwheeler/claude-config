#!/usr/bin/env python3
"""open_items.py — digest of OPEN work across the memory repo.

WHY THIS EXISTS (2026-09-11, user request): "it would be nice to have an easily
summarized list of open items across the project list that makes it easy to
select an area of focus for each evening's work."

WHY IT IS GENERATED, NOT HAND-MAINTAINED: a static list of open items drifts the
moment any project moves, and duplicated facts are exactly what breaks
feedback_memory_correct_in_place. The markers already in the prose ARE the
source of truth; this just collects them.

DELIBERATELY NOT memory_lint.py. That script's contract is "facts with one
machine-checkable ground truth, and deliberately nothing else — the prose in
memory is hand-curated judgement and is none of this script's business." This
one reads only prose, so it is a separate tool on purpose.

CONTRACT: read-only, prints nothing but memory prose, no network, no secrets.
"""

import glob
import os
import re
import sys
import datetime as dt

MEM = "/home/em/.claude/projects/-home-em-development/memory"

# ⏳ is the reliable open-item marker (44 hits / 16 files at time of writing).
# The word-markers are secondary and only count at the START of a bullet, so a
# passing mention of "open" mid-prose does not become a phantom task.
HOURGLASS = "⏳"
CALENDAR = "🗓️"   # also used for dated commitments
WORD_RE = re.compile(r"^[-*]\s*\**\s*(OPEN|TODO|BLOCKED|NOT STARTED|NOT DONE|PENDING)\b", re.I)
DATE_RE = re.compile(r"~?(\d{4}-\d{2}-\d{2})")
# strip markdown noise for a scannable one-liner
CLEAN = [(re.compile(r"\[\[([^\]]+)\]\]"), r"\1"),
         (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),
         (re.compile(r"`([^`]*)`"), r"\1"),
         (re.compile(r"\*\*|\*|^[-*]\s*"), "")]


def label(line: str, width: int = 132) -> str:
    s = line.strip()
    for rx, rep in CLEAN:
        s = rx.sub(rep, s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:width] + ("…" if len(s) > width else "")


def main() -> int:
    today = dt.date.today()
    files = sorted(glob.glob(os.path.join(MEM, "*.md")))
    found = {}
    for path in files:
        name = os.path.basename(path)[:-3]
        try:
            lines = open(path, encoding="utf-8").read().split("\n")
        except OSError:
            continue
        for ln in lines:
            raw = ln.strip()
            # ⚠ Skip tables/quotes, but NOT headers — real open items live in
            # headings here ("### 4. ⏳ Calendar item — re-check the 0.55
            # threshold", "## ⚠⚠ OPEN SAFETY ITEM"). Filtering headers wholesale
            # silently dropped those. Missing a real item is worse than one noisy
            # line, so only the known section-label forms are excluded below.
            if raw.startswith(("|", ">")):
                continue
            # ★ READ FROM THE MARKER FORWARD, not the whole line. A line often
            # announces finished work AND carries a trailing open clause
            # ("...DEPLOYED 2026-08-22 ... ⏳ VALIDATION = the next 19:35 stop").
            # Taking the whole line mislabels it as the deploy, and the date
            # regex then grabs the DEPLOY date and calls it overdue.
            i = ln.find(HOURGLASS)
            j = ln.find(CALENDAR)
            if i < 0 or (0 <= j < i):
                i, mk = (j, CALENDAR) if j >= 0 else (-1, "")
            else:
                mk = HOURGLASS
            if i >= 0:
                clause = ln[i + len(mk):]
            elif WORD_RE.match(raw):
                clause = raw
            else:
                continue
            # a clause that is itself an explicit completion is not open
            if re.search(r"\b(CLOSED|RESOLVED|SUPERSEDED|RETIRED)\b", clause[:60], re.I):
                continue
            # section labels, not tasks
            if re.match(r"\s*Queued\b|\s*QUEUED\s*\(", clause, re.I):
                continue
            txt = label(clause)
            if len(txt) < 25:                     # stubs / section labels
                continue
            m = DATE_RE.search(clause)            # date must be IN the open clause
            when, kind = None, None
            if m:
                try:
                    when = dt.date.fromisoformat(m.group(1))
                except ValueError:
                    when = None
                if when:
                    # ⚠ A DATE IS NOT AUTOMATICALLY A DEADLINE. Most dates in this
                    # memory are when an item was RAISED ("PENDING (user directed
                    # 2026-09-02)", "OPEN, raised 2026-09-10"). Calling those
                    # OVERDUE manufactures urgency that was never stated. Only a
                    # due-cue immediately before the date makes it a deadline.
                    # ⚠ the "~" is CONSUMED by DATE_RE, so it is not in `pre` —
                    # test the matched text itself for it, or a leading "~2026-.."
                    # (the commonest way an approximate deadline is written here)
                    # silently reads as merely "raised".
                    pre = clause[max(0, m.start() - 30):m.start()].lower()
                    tilde = m.group(0).lstrip().startswith("~")
                    kind = "due" if (tilde or re.search(
                        r"(due|by|around|revisit|re-?check|deadline)\s*$", pre)) else "raised"
            found.setdefault(name, []).append((when, kind, txt))

    if not found:
        print("No open items found.")
        return 0

    # dated items first, soonest first — these are the ones with a clock on them
    dated = sorted(((w, k, f, t) for f, items in found.items() for w, k, t in items if w),
                   key=lambda x: (x[1] != "due", x[0]))
    due = [d for d in dated if d[1] == "due"]
    aged = [d for d in dated if d[1] != "due"]
    if due:
        print("== ON A CLOCK (explicit due/revisit date) ==")
        for w, _k, f, t in due:
            n = (today - w).days
            flag = f"OVERDUE {n}d" if n > 0 else ("DUE TODAY" if n == 0 else f"in {-n}d")
            print(f"  [{w}] {flag:>12}  ({f})")
            print(f"      {t}")
        print()
    if aged:
        print("== RAISED, NO DEADLINE (oldest first — age only, NOT overdue) ==")
        for w, _k, f, t in aged:
            print(f"  [{w}] {(today - w).days:>5}d old  ({f})")
            print(f"      {t}")
        print()

    print("== BY PROJECT ==")
    for f in sorted(found, key=lambda k: (-len(found[k]), k)):
        undated = [t for w, _k, t in found[f] if not w]
        if not undated:
            continue
        print(f"  {f}  ({len(undated)})")
        for t in undated:
            print(f"      - {t}")
    total = sum(len(v) for v in found.values())
    print(f"\n{total} open item(s) across {len(found)} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
