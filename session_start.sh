#!/usr/bin/env bash
# ~/.claude/session_start.sh — runs at every Claude Code session start.
# - Pulls latest memory from GitHub (cross-machine sync).
# - Probes the HA-side connections we rely on.
# - Prints nothing on success; one "⚠ <reason>" line per failure.
# Bounded latency: ~1s healthy, capped near 8s worst case via timeouts.

set -u

HA=http://192.168.1.41:8123
TOKEN=$(jq -r '.projects."/home/em/development".mcpServers."home-assistant".headers.Authorization' \
        /home/em/.claude.json 2>/dev/null | sed 's/^Bearer //')

WARN=()

# 1a) Memory git pull (cross-machine sync). PostToolUse pushes; this pulls.
if ! timeout 5 git -C /home/em/.claude/projects/-home-em-development/memory \
       pull --ff-only --quiet 2>/dev/null; then
    WARN+=("memory pull failed")
fi

# 1b) Config repo pull (~/.claude-config) — picks up settings.json/script edits
# from other machines. Same FF-only/timeout discipline as memory.
if [ -d /home/em/.claude-config/.git ]; then
    if ! timeout 5 git -C /home/em/.claude-config \
           pull --ff-only --quiet 2>/dev/null; then
        WARN+=("config pull failed")
    fi
fi

# 2) HA REST API + bearer-token validity. /api/ returns 200 with valid token.
if [ -z "$TOKEN" ]; then
    WARN+=("HA token missing from .claude.json")
else
    HA_REST=$(curl -s -m 2 -o /dev/null -w '%{http_code}' \
               -H "Authorization: Bearer $TOKEN" "$HA/api/" 2>/dev/null)
    [ "$HA_REST" = "200" ] || WARN+=("HA REST $HA_REST")
fi

# 3) AppDaemon admin port — returns 302 redirect to login.
AD=$(curl -s -m 2 -o /dev/null -w '%{http_code}' \
     "http://192.168.1.41:5050/" 2>/dev/null)
case "$AD" in
    200|302|303) ;;
    *) WARN+=("AppDaemon :5050 $AD") ;;
esac

# 4) Samba mounts — both mounted AND readable (handles "stale mount" case).
for mp in /mnt/ha /mnt/ha_addons /mnt/ha_media; do
    if ! mountpoint -q "$mp" 2>/dev/null; then
        WARN+=("$mp not mounted")
    elif ! timeout 2 ls "$mp" >/dev/null 2>&1; then
        WARN+=("$mp stale (mounted, unreadable)")
    fi
done

if [ "${#WARN[@]}" -gt 0 ]; then
    printf '⚠ %s\n' "${WARN[@]}"
fi
