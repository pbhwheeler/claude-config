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

# Quiet mode: suppress all output unless an actual change is made.
# session_start.sh calls us with --quiet on every session, idempotently;
# user-triggered runs (e.g. via `bash <(curl ...)`) get the verbose form.
QUIET=0
[ "${1:-}" = "--quiet" ] && QUIET=1
say() { [ "$QUIET" = "1" ] || echo "$@"; }
notice() { echo "$@"; }  # always prints — used for actual change events

if [ -d "$CONFIG_DIR/.git" ]; then
    say ">>> $CONFIG_DIR already present"
else
    notice ">>> Cloning $CONFIG_REPO to $CONFIG_DIR"
    git clone --quiet "$CONFIG_REPO" "$CONFIG_DIR"
fi

say ">>> Refreshing symlinks into ~/.claude/"
mkdir -p "$HOME/.claude" "$HOME/.claude/commands"

# Auto-discover everything to symlink: settings.json + every executable .sh
# at the repo root. Future scripts you add to ~/.claude-config/ get picked up
# without needing to edit this loop.
TO_LINK=(settings.json)
for sh in "$CONFIG_DIR"/*.sh; do
    [ -f "$sh" ] || continue
    case "$(basename "$sh")" in
        bootstrap.sh|setup-symlinks.sh) continue ;;  # internal — not user-facing
    esac
    TO_LINK+=("$(basename "$sh")")
done

for f in "${TO_LINK[@]}"; do
    target="$HOME/.claude/$f"
    src="$CONFIG_DIR/$f"
    # If the target is a symlink already pointing at the right place, skip silently.
    if [ -L "$target" ] && [ "$(readlink "$target")" = "$src" ]; then
        continue
    fi
    if [ -e "$target" ] && [ ! -L "$target" ]; then
        backup="$target.bak-$(date +%s)"
        notice "    backing up existing $f -> $(basename "$backup")"
        mv "$target" "$backup"
    fi
    notice "    linking $f -> $src"
    ln -sf "$src" "$target"
done

# Per-file slash command symlinks (preserves user-added commands in
# ~/.claude/commands/ that aren't part of the synced set).
if [ -d "$CONFIG_DIR/commands" ]; then
    for cmd in "$CONFIG_DIR/commands"/*.md; do
        [ -f "$cmd" ] || continue
        name=$(basename "$cmd")
        target="$HOME/.claude/commands/$name"
        if [ -L "$target" ] && [ "$(readlink "$target")" = "$cmd" ]; then
            continue
        fi
        if [ -e "$target" ] && [ ! -L "$target" ]; then
            backup="$target.bak-$(date +%s)"
            notice "    backing up existing commands/$name -> commands/$(basename "$backup")"
            mv "$target" "$backup"
        fi
        notice "    linking commands/$name"
        ln -sf "$cmd" "$target"
    done
fi

# Make all our shell scripts executable (idempotent; no output).
chmod +x "$CONFIG_DIR"/*.sh 2>/dev/null || true

echo
echo "Done. Now:"
echo "  1. Exit this Claude Code session (so settings.json gets re-read on next start)."
echo "  2. Start Claude again. session_start.sh will pull memory, write a marker on exit,"
echo "     and the FOLLOWING start will print '↻ Synced from <other-machine-id> ...'"
echo
echo "Optional: drop a friendly name into ~/.claude/machine-label (one line, e.g."
echo "'latitude-couch') so the marker shows that instead of 'mid-XXXXXXXX'."
