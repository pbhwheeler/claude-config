#!/usr/bin/env bash
# bootstrap.sh — set up Claude Code on a new dev machine.
# Idempotent. Run with:
#   bash <(curl -sSL https://raw.githubusercontent.com/pbhwheeler/claude-config/main/bootstrap.sh)
# Or, if already cloned:
#   ~/.claude-config/bootstrap.sh

set -euo pipefail

CONFIG_DIR="$HOME/.claude-config"
MEMORY_DIR="$HOME/.claude/projects/-home-em-development/memory"
HA_HOST="192.168.1.41"

# Git remotes use SSH (durable; matches MEMORY.md auth doc). PATs in URLs have
# previously gone silently dead (the 2026-06-01 incident: PAT revoked, push
# failed, hook kept committing locally — invisible until a manual push). SSH
# keys don't expire and the failure mode is loud.
repo_url() { local repo="$1"; echo "git@github.com:pbhwheeler/${repo}.git"; }

cat <<'INTRO'
=== Claude Code dev machine bootstrap ===
This will:
  1. apt install git jq curl cifs-utils npm libsecret-tools
  2. Verify SSH access to GitHub (needed before private-repo clones)
  3. Clone ~/.claude-config and the memory repo via SSH
  4. Symlink config files into ~/.claude/
  5. Patch ~/.claude.json with MCP server entries (HA, GitHub)
  6. Add Samba mount entries to /etc/fstab and mount them
  7. (optional) Wire up the daily activity report — IMAP-driven daily
     email summary of this laptop's git/memory activity to StartMail

Prereqs: an SSH key registered on github.com/settings/keys. If you don't have
one yet: ssh-keygen -t ed25519, then paste ~/.ssh/id_ed25519.pub into GitHub.

You'll be prompted for: GitHub PAT (for the GitHub MCP server only; git uses
SSH), HA long-lived token (unique per laptop), Samba password, and optionally
a StartMail app password for the daily report.

INTRO
read -rp "Proceed? [y/N] " ans
[[ "$ans" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }

# 1. apt packages
echo ">>> Installing apt packages..."
sudo apt update -qq
sudo apt install -y git jq curl cifs-utils samba-client npm libsecret-tools

# 2. SSH precheck — git operations on the private memory repo and durable
# pushes both require an SSH key registered with GitHub. Bail loudly if not.
echo ">>> Verifying SSH access to GitHub..."
if ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -T git@github.com 2>&1 | grep -q "successfully authenticated"; then
    echo "    OK: SSH auth as pbhwheeler works."
else
    echo "    FAIL: ssh -T git@github.com did not return 'successfully authenticated'."
    echo "    Add this machine's SSH key to https://github.com/settings/keys first."
    echo "    Quick path: ssh-keygen -t ed25519, then add the .pub to GitHub, then re-run."
    exit 1
fi

# 3. Tokens — prompt up front so the rest can run unattended
read -rp "GitHub PAT (repo scope, for MCP server only — NOT for git): " GH_TOKEN
read -rp "Home Assistant long-lived access token: " HA_TOKEN
read -rsp "Samba password for HA share: " SAMBA_PASS; echo

# 4. Clone or update config repo (this script's home)
if [ ! -d "$CONFIG_DIR/.git" ]; then
    echo ">>> Cloning config repo via SSH..."
    git clone "$(repo_url claude-config)" "$CONFIG_DIR"
fi

# 5. Clone or update memory repo
if [ ! -d "$MEMORY_DIR/.git" ]; then
    echo ">>> Cloning memory repo via SSH..."
    mkdir -p "$(dirname "$MEMORY_DIR")"
    git clone "$(repo_url claude-memory)" "$MEMORY_DIR"
fi

# 6. Symlink config files into ~/.claude/
echo ">>> Symlinking config files into ~/.claude/..."
mkdir -p "$HOME/.claude" "$HOME/.claude/commands"
for f in settings.json statusline.sh session_start.sh session_end.sh prune-backups.sh; do
    target="$HOME/.claude/$f"
    if [ -e "$target" ] && [ ! -L "$target" ]; then
        echo "    backing up existing $f -> $f.pre-bootstrap"
        mv "$target" "$target.pre-bootstrap"
    fi
    ln -sf "$CONFIG_DIR/$f" "$target"
done
# Per-file slash command symlinks (preserves user-added commands)
if [ -d "$CONFIG_DIR/commands" ]; then
    for cmd in "$CONFIG_DIR/commands"/*.md; do
        [ -f "$cmd" ] || continue
        name=$(basename "$cmd")
        target="$HOME/.claude/commands/$name"
        if [ -e "$target" ] && [ ! -L "$target" ]; then
            echo "    backing up existing commands/$name -> commands/$name.pre-bootstrap"
            mv "$target" "$target.pre-bootstrap"
        fi
        ln -sf "$cmd" "$target"
    done
fi
chmod +x "$CONFIG_DIR/statusline.sh" "$CONFIG_DIR/session_start.sh" "$CONFIG_DIR/session_end.sh" "$CONFIG_DIR/prune-backups.sh"

# 7. SSH-key auto-load user service. The passphrased id_ed25519 must load into
# the agent non-interactively at login, or the memory/config auto-push and
# session-start pull hooks pop a GUI passphrase prompt (the 2026-06-03 incident).
# The unit runs scripts/ssh-add-when-ready.sh (waits for the keyring agent
# socket — it's created late in graphical login — then ssh-add), which pulls the
# passphrase from the GNOME login keyring via scripts/ssh-askpass-keyring.sh.
# We deploy + enable the unit here; the per-machine SECRET (the passphrase in
# the keyring) is a manual step, printed in the final summary — it can't live in
# this public repo.
echo ">>> Installing ssh-add-keyring user service..."
mkdir -p "$HOME/.config/systemd/user"
cp "$CONFIG_DIR/systemd/ssh-add-keyring.service" "$HOME/.config/systemd/user/ssh-add-keyring.service"
if systemctl --user daemon-reload 2>/dev/null; then
    if systemctl --user enable ssh-add-keyring.service 2>/dev/null; then
        echo "    enabled — loads ~/.ssh/id_ed25519 into the agent at each login"
    else
        echo "    WARN: enable failed — run in a desktop session: systemctl --user enable ssh-add-keyring.service"
    fi
else
    echo "    WARN: no user systemd session here. After your first graphical login, run:"
    echo "          systemctl --user daemon-reload && systemctl --user enable ssh-add-keyring.service"
fi

# 8. Patch ~/.claude.json with MCP servers under the /home/em/development project
CLAUDE_JSON="$HOME/.claude.json"
[ -f "$CLAUDE_JSON" ] || echo "{}" > "$CLAUDE_JSON"
echo ">>> Writing MCP server entries to $CLAUDE_JSON..."
jq --arg ha "$HA_TOKEN" --arg gh "$GH_TOKEN" --arg host "$HA_HOST" '
  .projects = (.projects // {})
  | .projects["/home/em/development"] = (.projects["/home/em/development"] // {})
  | .projects["/home/em/development"].mcpServers = {
      "home-assistant": {
        type: "http",
        url: ("http://" + $host + ":8123/api/mcp"),
        headers: { Authorization: ("Bearer " + $ha) }
      },
      "github": {
        type: "http",
        url: "https://api.githubcopilot.com/mcp",
        headers: { Authorization: ("Bearer " + $gh) }
      }
    }
' "$CLAUDE_JSON" > "$CLAUDE_JSON.tmp" && mv "$CLAUDE_JSON.tmp" "$CLAUDE_JSON"

# 9. Samba mounts
echo ">>> Configuring Samba mounts..."
sudo mkdir -p /mnt/ha /mnt/ha_addons /mnt/ha_media
UID_GID="uid=$(id -u),gid=$(id -g),vers=3.0"
add_fstab() {
    local share="$1" mp="$2"
    if grep -q "^//${HA_HOST}/${share} " /etc/fstab; then
        echo "    fstab already has $share -> $mp"
        return
    fi
    echo "    adding fstab: //$HA_HOST/$share -> $mp"
    echo "//${HA_HOST}/${share} $mp cifs username=homeassistant,password=${SAMBA_PASS},${UID_GID} 0 0" \
        | sudo tee -a /etc/fstab > /dev/null
}
add_fstab config       /mnt/ha
add_fstab addon_configs /mnt/ha_addons
add_fstab media        /mnt/ha_media
sudo systemctl daemon-reload
sudo mount -a || echo "    (some mounts failed — check 'mount -a' manually)"

# 10. Normalize both repo remotes to SSH (idempotent — repairs prior installs
# that may have inherited HTTPS+PAT URLs from older bootstrap revisions).
git -C "$MEMORY_DIR" remote set-url origin "$(repo_url claude-memory)" || true
git -C "$CONFIG_DIR" remote set-url origin "$(repo_url claude-config)" || true

# 11. Optional: daily activity report (see reference_daily_report.md).
#    The setup script is interactive — prompts for the StartMail app password
#    silently and writes ~/.config/daily-report/imap.cfg mode 600, then
#    installs the 23:59 crontab line. Each laptop reports independently
#    (the report's "Host:" header distinguishes them). Skip on temporary
#    or shared machines.
DAILY_REPORT_SETUP="$CONFIG_DIR/scripts/setup_daily_report.sh"
if [ -x "$DAILY_REPORT_SETUP" ]; then
    echo
    read -rp "Set up daily activity reports (StartMail IMAP)? [y/N] " ans_dr
    if [[ "$ans_dr" =~ ^[Yy]$ ]]; then
        "$DAILY_REPORT_SETUP"
    else
        echo "    Skipped. To enable later, run:  $DAILY_REPORT_SETUP"
    fi
else
    echo "    (daily report scripts not found at $DAILY_REPORT_SETUP — skipping)"
fi

cat <<EOF

=== Bootstrap complete ===
Verify:
  /home/em/.claude/statusline.sh    # should print "ha:🟢 addons:🟢"
  ls /mnt/ha                        # should list HA config
  jq -r '.projects."/home/em/development".mcpServers | keys' ~/.claude.json
Run 'claude' in any project dir to start working.

If the SessionStart hook doesn't fire on your first session, run /hooks
once or restart the session — Claude Code's settings watcher picks up
changes for new sessions only.
EOF
