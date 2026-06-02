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

# 1c) Re-run setup-symlinks.sh --quiet so any new scripts added to
# ~/.claude-config/ (after the pull above) get symlinked into ~/.claude/
# automatically. Idempotent and silent if nothing changed; only prints
# when it backs up or creates a symlink (the rare interesting case).
# This closes the gap where a new file in the repo would land on disk but
# not get its ~/.claude/ symlink without manual setup-symlinks.sh re-run.
if [ -x /home/em/.claude-config/setup-symlinks.sh ]; then
    /home/em/.claude-config/setup-symlinks.sh --quiet 2>&1 \
        | grep -v '^>>>' || true
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

# 4c) Unpushed-commit guard. The PostToolUse hook pushes memory/config to
# GitHub after every edit; if a push silently fails (e.g. the SSH key isn't
# loaded into the agent), commits pile up locally and the backup rots
# unnoticed — the exact failure that hid 13 unpushed memory commits in 2026.
# After the FF-only pulls above, any local lead over upstream means a prior
# push didn't land. Surface it loudly.
for repo in \
    /home/em/.claude/projects/-home-em-development/memory \
    /home/em/.claude-config; do
    if [ -d "$repo/.git" ]; then
        ahead=$(git -C "$repo" rev-list --count @{u}..HEAD 2>/dev/null)
        if [ -n "$ahead" ] && [ "$ahead" -gt 0 ] 2>/dev/null; then
            WARN+=("$(basename "$repo"): $ahead unpushed commit(s) — SSH push failing?")
        fi
    fi
done

if [ "${#WARN[@]}" -gt 0 ]; then
    printf '⚠ %s\n' "${WARN[@]}"
fi

# 4b) Prune ~/.claude/backups/ to keep N most recent. Fire-and-forget;
# silent on success, surfaces a warning only if the script itself crashes.
if [ -x /home/em/.claude/prune-backups.sh ]; then
    /home/em/.claude/prune-backups.sh 2>/dev/null || printf '⚠ prune-backups.sh failed\n'
fi

# 5) Cross-machine handoff confirmation. The Stop hook (session_end.sh) on the
# OTHER laptop stamps .last_session with its machine identifier + UTC time, then
# pushes. We just pulled that marker above (step 1a). If the marker is from a
# different machine than this one, announce it — positive proof memory
# round-tripped laptop → GitHub → laptop. Same-machine markers are silent.
#
# Machine identifier must match what session_end.sh writes — same fallback chain:
# ~/.claude/machine-label > mid-<8-hex of /etc/machine-id> > $(hostname). Don't
# use bare $(hostname) here — the two Latitudes both report "em-Latitude-6430U"
# and the comparison would always be silent.
if [ -s /home/em/.claude/machine-label ]; then
    THIS_HOST=$(head -1 /home/em/.claude/machine-label | tr -d '[:space:]')
elif [ -r /etc/machine-id ]; then
    THIS_HOST="mid-$(cut -c1-8 /etc/machine-id)"
else
    THIS_HOST=$(hostname)
fi
MARKER=/home/em/.claude/projects/-home-em-development/memory/.last_session
if [ -f "$MARKER" ]; then
    LAST_HOST=$(sed -n 1p "$MARKER" 2>/dev/null)
    LAST_TS=$(sed -n 2p "$MARKER" 2>/dev/null)
    if [ -n "$LAST_HOST" ] && [ "$LAST_HOST" != "$THIS_HOST" ]; then
        printf '↻ Synced from %s (last session ended %s)\n' "$LAST_HOST" "$LAST_TS"
    fi
fi
