#!/usr/bin/env bash
# ~/.claude/statusline.sh — fast Claude Code status line.
# Outputs: optional "📌N " (count of pending reminders due today or earlier)
# followed by "ha:🟢|🔴 addons:🟢|🔴" (samba mount health).
# Must be cheap — runs on every prompt. No network calls.

set -u

MEM=/home/em/.claude/projects/-home-em-development/memory/MEMORY.md
TODAY=$(date +%F)

DUE=0
if [ -r "$MEM" ]; then
  DUE=$(awk -v d="$TODAY" '
    /^## ⏰ Pending reminders/ { in_section=1; next }
    in_section && /^## /        { in_section=0 }
    in_section && /^- \*\*After / {
      if (match($0, /[0-9]{4}-[0-9]{2}-[0-9]{2}/)) {
        date = substr($0, RSTART, RLENGTH)
        if (date <= d) c++
      }
    }
    END { print c+0 }
  ' "$MEM")
fi

ha="🟢";     mountpoint -q /mnt/ha        2>/dev/null || ha="🔴"
addons="🟢"; mountpoint -q /mnt/ha_addons 2>/dev/null || addons="🔴"

prefix=""
[ "$DUE" -gt 0 ] && prefix="📌${DUE} "

echo "${prefix}ha:${ha} addons:${addons}"
