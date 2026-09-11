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
            if HOURGLASS not in ln and not WORD_RE.match(ln.strip()):
                continue
            if ln.lstrip().startswith(("|", ">")):      # table rows / quotes
                continue
            txt = label(ln)
            if len(txt) < 25:                            # headers, stubs
                continue
            m = DATE_RE.search(ln)
            when = None
            if m:
                try:
                    when = dt.date.fromisoformat(m.group(1))
                except ValueError:
                    when = None
            found.setdefault(name, []).append((when, txt))

    if not found:
        print("No open items found.")
        return 0

    # dated items first, soonest first — these are the ones with a clock on them
    dated = sorted(((w, f, t) for f, items in found.items() for w, t in items if w),
                   key=lambda x: x[0])
    if dated:
        print("== DATED ==")
        for w, f, t in dated:
            age = (today - w).days
            flag = "OVERDUE" if age > 0 else ("TODAY" if age == 0 else f"in {-age}d")
            print(f"  [{w}] {flag:>9}  ({f})")
            print(f"      {t}")
        print()

    print("== BY PROJECT ==")
    for f in sorted(found, key=lambda k: (-len(found[k]), k)):
        undated = [t for w, t in found[f] if not w]
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
