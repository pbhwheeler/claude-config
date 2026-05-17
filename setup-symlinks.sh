#!/usr/bin/env bash
# setup-symlinks.sh — minimal cross-machine sync setup.
#
# Use case: dev laptop already has Claude Code working but is missing the
# ~/.claude-config/ symlink infrastructure (so PostToolUse autopush, Stop
# hook, and the SessionStart marker-print stanza never run).
#
# Skips what the full bootstrap.sh does — no apt install, no fstab, no MCP
# server patching. Just clones ~/.claude-config from the public repo and
# symlinks four files into ~/.claude/.
#
# Idempotent: safe to re-run. Existing symlinks are refreshed; existing
# regular files get a one-shot .bak backup before being replaced.
#
# Run:
#   bash <(curl -sSL https://raw.githubusercontent.com/pbhwheeler/claude-config/main/setup-symlinks.sh)
# Or inside a Claude Code session:
#   !bash <(curl -sSL https://raw.githubusercontent.com/pbhwheeler/claude-config/main/setup-symlinks.sh)
# Then exit + restart Claude to load the new settings.json and trigger the
# Stop hook + marker-print stanza.

set -euo pipefail

CONFIG_DIR="$HOME/.claude-config"
CONFIG_REPO="https://github.com/pbhwheeler/claude-config.git"

echo ">>> Cloning $CONFIG_REPO to $CONFIG_DIR (if missing)"
if [ -d "$CONFIG_DIR/.git" ]; then
    echo "    already present — pulling latest"
    git -C "$CONFIG_DIR" pull --ff-only --quiet
else
    git clone --quiet "$CONFIG_REPO" "$CONFIG_DIR"
fi

echo ">>> Symlinking ~/.claude/{settings.json,statusline.sh,session_start.sh,session_end.sh}"
mkdir -p "$HOME/.claude"
for f in settings.json statusline.sh session_start.sh session_end.sh; do
    target="$HOME/.claude/$f"
    if [ -e "$target" ] && [ ! -L "$target" ]; then
        backup="$target.bak-$(date +%s)"
        echo "    backing up existing $f -> $(basename "$backup")"
        mv "$target" "$backup"
    fi
    ln -sf "$CONFIG_DIR/$f" "$target"
done

chmod +x "$CONFIG_DIR/statusline.sh" "$CONFIG_DIR/session_start.sh" "$CONFIG_DIR/session_end.sh"

echo
echo "Done. Now:"
echo "  1. Exit this Claude Code session (so settings.json gets re-read on next start)."
echo "  2. Start Claude again. session_start.sh will pull memory, write a marker on exit,"
echo "     and the FOLLOWING start will print '↻ Synced from <other-machine-id> ...'"
echo
echo "Optional: drop a friendly name into ~/.claude/machine-label (one line, e.g."
echo "'latitude-couch') so the marker shows that instead of 'mid-XXXXXXXX'."
