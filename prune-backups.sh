#!/usr/bin/env bash
# prune-backups.sh — keep the N most recent ~/.claude/backups/.claude.json.*
# entries (by mtime). Preserves .corrupted.* files unconditionally — those are
# forensic evidence of past recoveries, not regular rotating backups.
#
# Invoked from session_start.sh once per session (cheap; backups don't
# accumulate fast enough to warrant a tighter cadence). Safe to run by hand.

set -u

DIR="$HOME/.claude/backups"
KEEP=${KEEP:-10}

[ -d "$DIR" ] || exit 0

# Newest-first listing of regular backup files (NOT corrupted), then drop the
# top KEEP and delete the rest. `ls -1t` is sufficient since these names are
# unique per timestamp and the dir is small.
cd "$DIR" || exit 0
ls -1t .claude.json.* 2>/dev/null \
    | grep -v '^\.claude\.json\.corrupted\.' \
    | tail -n +$((KEEP + 1)) \
    | while IFS= read -r f; do
        rm -f -- "$f"
    done
