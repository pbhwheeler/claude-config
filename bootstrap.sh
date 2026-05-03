#!/usr/bin/env bash
# bootstrap.sh — set up Claude Code on a new dev machine.
# Idempotent. Run with:
#   bash <(curl -sSL https://raw.githubusercontent.com/pbhwheeler/claude-config/main/bootstrap.sh)
# Or, if already cloned:
#   ~/.claude-config/bootstrap.sh

set -euo pipefail

CONFIG_REPO_URL="https://github.com/pbhwheeler/claude-config.git"
MEMORY_REPO_URL="https://github.com/pbhwheeler/claude-memory.git"
CONFIG_DIR="$HOME/.claude-config"
MEMORY_DIR="$HOME/.claude/projects/-home-em-development/memory"
HA_HOST="192.168.1.41"

# Resolve git URLs with token interpolation (used after we have GH_TOKEN).
gh_url() { local repo="$1"; echo "https://${GH_TOKEN}@github.com/pbhwheeler/${repo}.git"; }

cat <<'INTRO'
=== Claude Code dev machine bootstrap ===
This will:
  1. apt install git jq curl cifs-utils npm
  2. Clone ~/.claude-config and the memory repo
  3. Symlink config files into ~/.claude/
  4. Patch ~/.claude.json with MCP server entries (HA, GitHub, sqlite)
  5. Add Samba mount entries to /etc/fstab and mount them
You'll be prompted for: GitHub PAT, HA long-lived token, Samba password.

INTRO
read -rp "Proceed? [y/N] " ans
[[ "$ans" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }

# 1. apt packages
echo ">>> Installing apt packages..."
sudo apt update -qq
sudo apt install -y git jq curl cifs-utils samba-client npm

# 2. Tokens — prompt up front so the rest can run unattended
read -rp "GitHub PAT (repo scope, for MCP + repo clones): " GH_TOKEN
read -rp "Home Assistant long-lived access token: " HA_TOKEN
read -rsp "Samba password for HA share: " SAMBA_PASS; echo

# 3. Clone or update config repo (this script's home)
if [ ! -d "$CONFIG_DIR/.git" ]; then
    echo ">>> Cloning config repo..."
    git clone "$(gh_url claude-config)" "$CONFIG_DIR"
fi

# 4. Clone or update memory repo
if [ ! -d "$MEMORY_DIR/.git" ]; then
    echo ">>> Cloning memory repo..."
    mkdir -p "$(dirname "$MEMORY_DIR")"
    git clone "$(gh_url claude-memory)" "$MEMORY_DIR"
fi

# 5. Symlink config files into ~/.claude/
echo ">>> Symlinking config files into ~/.claude/..."
mkdir -p "$HOME/.claude"
for f in settings.json statusline.sh session_start.sh; do
    target="$HOME/.claude/$f"
    if [ -e "$target" ] && [ ! -L "$target" ]; then
        echo "    backing up existing $f -> $f.pre-bootstrap"
        mv "$target" "$target.pre-bootstrap"
    fi
    ln -sf "$CONFIG_DIR/$f" "$target"
done
chmod +x "$CONFIG_DIR/statusline.sh" "$CONFIG_DIR/session_start.sh"

# 6. Patch ~/.claude.json with MCP servers under the /home/em/development project
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
      },
      "sqlite": {
        type: "stdio",
        command: "npx",
        args: ["-y", "mcp-sqlite", "/mnt/ha/home-assistant_v2.db"]
      }
    }
' "$CLAUDE_JSON" > "$CLAUDE_JSON.tmp" && mv "$CLAUDE_JSON.tmp" "$CLAUDE_JSON"

# 7. Samba mounts
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

# 8. Set memory repo's remote to use the GH_TOKEN (so PostToolUse push works)
git -C "$MEMORY_DIR" remote set-url origin "$(gh_url claude-memory)" || true
git -C "$CONFIG_DIR" remote set-url origin "$(gh_url claude-config)" || true

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
