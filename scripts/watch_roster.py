#!/usr/bin/env python3
"""watch_roster.py — list the ACTIVE cron watches that must be RE-ARMED this session.

WHY THIS EXISTS (2026-09-11, user: "on new session start please include re-arming
any dropped cron watch jobs"). CronCreate jobs live only inside a Claude session;
every new session starts with NONE armed, and a shell hook cannot create them —
only the model can, via the CronCreate tool. So this script does the mechanical
half: it reads the roster's ACTIVE section and prints one ready-to-arm line per
cron expression. The model does the other half at session start (see the
instruction printed at the end).

SINGLE SOURCE OF TRUTH = reference_watch_roster.md. Nothing here is duplicated
from it; the roster's own '### N. Title — `M H * * *`' headers are parsed.

★ DESIGN: the CronCreate PROMPT is a short POINTER into the roster ("read entry
#N and execute it"), not the long inline text used on 2026-09-10. The roster
entry already holds the commands, bounds and stop condition; a pointer cannot
drift from it, and re-arming becomes deterministic.

CONTRACT: read-only, prints only roster prose, silent when there is nothing to arm.
"""

import os
import re
import sys

ROSTER = "/home/em/.claude/projects/-home-em-development/memory/reference_watch_roster.md"
HEAD = re.compile(r"^###\s+([0-9][0-9 +]*)\.\s+(.*)$")
CRON = re.compile(r"(?:\b([A-Z]{3,}|daily|dusk|hourly|nightly)\s+)?`([0-9*/,-]+ [0-9*/,-]+ [0-9*/,-]+ [0-9*/,-]+ [0-9*/,-]+)`")


def active_section(text):
    a = text.find("\n## ACTIVE")
    b = text.find("\n## RETIRED", a + 1)
    return text[a:b] if a >= 0 and b > a else ""


def main():
    try:
        text = open(ROSTER, encoding="utf-8").read()
    except OSError:
        return 0
    rows = []
    for ln in active_section(text).split("\n"):
        h = HEAD.match(ln.strip())
        if not h:
            continue
        num, rest = h.group(1).strip(), h.group(2)
        title = re.split(r"\s+—\s+", rest, 1)[0].strip("* ")
        for label, expr in CRON.findall(rest):
            rows.append((num, title, label, expr))
    if not rows:
        return 0
    print(f"⏰ RE-ARM {len(rows)} CRON WATCH(ES) — they died with the last session:")
    for num, title, label, expr in rows:
        tag = f" ({label})" if label else ""
        print(f"  #{num:<5} `{expr}`  {title}{tag}")
    print("  → CronList first (skip any already armed), then CronCreate each with prompt:")
    print("    \"WATCH #<N> '<title>' — open reference_watch_roster.md, find entry #<N> under")
    print("     ACTIVE, and execute it exactly as written (commands, PASS/FAIL, PushNotification,")
    print("     record the result in the roster). If its STOP condition is met, say so and CronDelete.\"")
    print("  → then report the armed list in one line. Recurring jobs auto-expire after 7 days.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
