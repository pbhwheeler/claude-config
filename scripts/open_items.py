#!/usr/bin/env python3
"""open_items.py — digest of MARKED open work across the memory repo.

WHY GENERATED, NOT HAND-MAINTAINED: a static TODO list drifts the moment any
project moves, and duplicated facts are what break correct-in-place memory
discipline. The markers already in the prose ARE the source of truth; this only
collects them.

DELIBERATELY NOT memory_lint.py — that script's contract is "facts with one
machine-checkable ground truth, and nothing else; prose is none of its business".
This reads only prose, so it is a separate tool on purpose.

⚠ THIS IS A FLOOR, NOT A CENSUS. It reports what somebody remembered to mark.
An adversarial review (2026-09-11) found ~20 open-looking lines with no marker
("not yet deployed", "NOT yet fixed", "not yet applied"), some months old.
Unmarked open work exists; /open must say so.

CANONICAL MARKING FORM (feedback_open_item_markers):
    ⏳ [YYYY-MM-DD] text     open item; bracketed date = when RAISED
    🗓️ [YYYY-MM-DD] text     item with a real DEADLINE
    ✅ [YYYY-MM-DD] text     done — replace the marker, keep the date (closes the loop)
Legacy forms still parsed: a bare ⏳, and "~YYYY-MM-DD" / "due YYYY-MM-DD" inside
the clause as a deadline. Partial "YYYY-MM" dates are accepted (1st of month).

USAGE:  open_items.py          full digest
        open_items.py --due    ON-A-CLOCK section only; prints NOTHING if empty
                               (SessionStart hook: silent when clean, like the lint)
        open_items.py --count  ONE line, always: "N marked open items — /open …"
                               (SessionStart hook: the standing reminder that the
                               digest exists, ~15 tokens; user chose this over
                               auto-loading the full ~1,400-token digest)

CONTRACT: read-only, prints only memory prose, no network, no secrets.
"""

import datetime as dt
import glob
import os
import re
import sys
import textwrap

MEM = "/home/em/.claude/projects/-home-em-development/memory"
OPEN, DUE = "⏳", "🗓️"
MARK_RE = re.compile("(" + re.escape(OPEN) + "|" + re.escape(DUE) + ")")
BRACKET_DATE = re.compile(r"^\s*\[(\d{4}-\d{2}(?:-\d{2})?)\]")
INLINE_DATE = re.compile(r"(~?)(\d{4}-\d{2}(?:-\d{2})?)(?!\d)")
DUE_CUE = re.compile(r"(due|by|around|revisit|re-?check|deadline)\s*$", re.I)
DONE_RE = re.compile(r"\b(CLOSED|RESOLVED|SUPERSEDED|RETIRED|DONE)\b", re.I)
LABEL_RE = re.compile(r"^\s*(Queued\b|QUEUED\s*\()", re.I)
SELF_RE = re.compile(r"open_items\.py|/open\b|`/open`", re.I)
CLEAN = [(re.compile(r"\[\[([^\]]+)\]\]"), r"\1"),
         (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),
         (re.compile(r"`([^`]*)`"), r"\1"),
         (re.compile(r"\*\*|\*|^[-*#]+\s*"), "")]
WIDTH = 74
MIN_LEN = 25


def parse_date(s):
    """'2026-09-15' -> (date, False); '2026-09' -> (date(1st), True); else None."""
    try:
        if len(s) == 7:
            return dt.date.fromisoformat(s + "-01"), True
        return dt.date.fromisoformat(s), False
    except ValueError:
        return None


def clean(text):
    for rx, rep in CLEAN:
        text = rx.sub(rep, text)
    return re.sub(r"\s+", " ", text).strip()


def excerpt(text, soft=110, hard=240):
    """Keep the ASK: cut at the first sentence boundary after `soft`, cap at `hard`."""
    if len(text) <= hard:
        return text
    for m in re.finditer(r"[.;]\s|\s—\s", text):
        if m.start() >= soft:
            return text[:m.start() + 1].rstrip()
    return text[:hard].rstrip() + "…"


def norm_key(text):
    return " ".join(re.sub(r"[^a-z0-9 ]", "", text.lower()).split()[:8])


def collect():
    items = []   # dicts: file, kind(open|due), when, month, text
    seen = set()
    for path in sorted(glob.glob(os.path.join(MEM, "*.md"))):
        fname = os.path.basename(path)[:-3]
        try:
            lines = open(path, encoding="utf-8").read().split("\n")
        except OSError:
            continue
        for ln in lines:
            raw = ln.strip()
            if raw.startswith(("|", ">")):            # tables / quotes
                continue
            marks = list(MARK_RE.finditer(ln))
            if not marks:
                continue
            # ★ SPLIT ON EVERY MARKER. One line often carries several items
            # ("⏳ verify X; ⏳ ~10-08 re-check Y; ⏳ deploy Z") — taking only the
            # first collapsed three tasks into one.
            for i, m in enumerate(marks):
                end = marks[i + 1].start() if i + 1 < len(marks) else len(ln)
                clause = ln[m.end():end]
                kind = "due" if m.group(1) == DUE else "open"
                if SELF_RE.search(clause):                 # the tool describing itself
                    continue
                if DONE_RE.search(clause[:60]) or LABEL_RE.match(clause):
                    continue
                when, month = None, False
                b = BRACKET_DATE.match(clause)
                if b:
                    p = parse_date(b.group(1))
                    if p:
                        when, month = p
                    clause = clause[b.end():]
                else:
                    d = INLINE_DATE.search(clause)
                    if d:
                        p = parse_date(d.group(2))
                        if p:
                            when, month = p
                            pre = clause[max(0, d.start() - 30):d.start()]
                            if d.group(1) == "~" or DUE_CUE.search(pre):
                                kind = "due"
                text = clean(clause)
                if len(text) < MIN_LEN:
                    continue
                key = norm_key(text)
                if key in seen:                            # exact restatement
                    continue
                seen.add(key)
                items.append(dict(file=fname, kind=kind, when=when, month=month,
                                  text=excerpt(text)))
    return items


def wrap(text, indent="      "):
    return textwrap.fill(text, width=WIDTH, initial_indent=indent,
                         subsequent_indent=indent)


def main():
    due_only = "--due" in sys.argv[1:]
    today = dt.date.today()
    items = collect()
    due = sorted((it for it in items if it["kind"] == "due" and it["when"]),
                 key=lambda it: it["when"])
    raised = sorted((it for it in items if it["kind"] == "open" and it["when"]),
                    key=lambda it: it["when"])
    undated = [it for it in items if not it["when"]]

    if due_only:
        if not due:
            return 0                                       # silent when clean
        print(f"⏳ ON A CLOCK ({len(due)}) — full list: /open")
        for it in due:
            n = (today - it["when"]).days
            flag = (f"OVERDUE {n}d" if n > 0 else "DUE TODAY" if n == 0 else f"in {-n}d")
            mo = " (month)" if it["month"] else ""
            print(f"  [{it['when']}] {flag:>11}{mo}  ({it['file']})")
            print(wrap(it["text"]))
        return 0

    if due:
        print("== ON A CLOCK (explicit deadline) ==")
        for it in due:
            n = (today - it["when"]).days
            flag = (f"OVERDUE {n}d" if n > 0 else "DUE TODAY" if n == 0 else f"in {-n}d")
            mo = " (month)" if it["month"] else ""
            print(f"  [{it['when']}] {flag:>11}{mo}  ({it['file']})")
            print(wrap(it["text"]))
        print()
    if raised:
        print("== RAISED — age since raised; NOT overdue, and may be correctly")
        print("   waiting on an event (a restart, a part, N clear days) ==")
        for it in raised:
            print(f"  [{it['when']}] {(today - it['when']).days:>5}d  ({it['file']})")
            print(wrap(it["text"]))
        print()
    if undated:
        print("== UNDATED (no signal on age or urgency — consider adding [YYYY-MM-DD]) ==")
        for f in sorted({it["file"] for it in undated}):
            print(f"  {f}")
            for it in undated:
                if it["file"] == f:
                    print(wrap(it["text"], indent="      - ").replace("\n      - ", "\n        "))
        print()
    files = len({it["file"] for it in items})
    print(f"{len(items)} MARKED open item(s) across {files} file(s).")
    print("⚠ Floor, not census: unmarked open work exists. /open judges; this only collects.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
