#!/usr/bin/env bash
# ~/.claude/session_end.sh — runs on Stop event (Claude exiting, /clear, /compact).
# - Stamps a marker file with this hostname + UTC time
# - Commits + pushes the marker so the OTHER dev laptop sees it on next pull
# Prints nothing on success; one "⚠ ..." line per failure.
# Bounded latency: ~1s healthy, capped near 8s worst case via timeouts.

set -u

MEMDIR=/home/em/.claude/projects/-home-em-development/memory
MARKER="$MEMDIR/.last_session"

WARN=()

# Machine identifier — must be unique per laptop. $(hostname) is unreliable
# when two laptops share the same hostname (the Latitudes do — both report
# "em-Latitude-6430U"). Priority:
#   1. ~/.claude/machine-label if present (human-friendly, user-set per machine)
#   2. /etc/machine-id truncated to 8 hex chars (always unique, persistent)
#   3. $(hostname) as last resort
if [ -s /home/em/.claude/machine-label ]; then
    HOST=$(head -1 /home/em/.claude/machine-label | tr -d '[:space:]')
elif [ -r /etc/machine-id ]; then
    HOST="mid-$(cut -c1-8 /etc/machine-id)"
else
    HOST=$(hostname)
fi
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# Atomic write so a partial marker never gets pushed if killed mid-write.
TMP=$(mktemp "$MARKER.XXXXXX")
{ echo "$HOST"; echo "$TS"; } > "$TMP" && mv "$TMP" "$MARKER" || {
    WARN+=("marker write failed")
    rm -f "$TMP"
}

# Stage + commit + push only if there's actually a diff. Skip otherwise so we
# don't churn the repo with "update" commits when nothing changed (e.g. same
# host, same second after a fast /clear).
if [ -f "$MARKER" ]; then
    if ! timeout 5 git -C "$MEMDIR" add "$(basename "$MARKER")" 2>/dev/null; then
        WARN+=("git add failed")
    elif ! git -C "$MEMDIR" diff --cached --quiet 2>/dev/null; then
        if ! timeout 5 git -C "$MEMDIR" commit -m "session end on $HOST @ $TS" --quiet 2>/dev/null; then
            WARN+=("git commit failed")
        elif ! timeout 5 git -C "$MEMDIR" push --quiet 2>/dev/null; then
            WARN+=("git push failed (marker committed locally)")
        fi
    fi
fi

if [ "${#WARN[@]}" -gt 0 ]; then
    printf '⚠ %s\n' "${WARN[@]}"
fi
