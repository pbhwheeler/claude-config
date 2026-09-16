#!/usr/bin/env bash
# bootstrap.sh — set up Claude Code on a new dev machine.
# Idempotent. Run with:
#   bash <(curl -sSL https://raw.githubusercontent.com/pbhwheeler/claude-config/main/bootstrap.sh)
# Or, if already cloned:
#   ~/.claude-config/bootstrap.sh

set -euo pipefail

CONFIG_DIR="$HOME/.claude-config"
MEMORY_DIR="$HOME/.claude/projects/-home-em-development/memory"
HA_HOST="homeassistant.local"   # by NAME, never the IP: the server moved .41 -> .2 on
                                # 2026-09-02 and this line was still .41 (dry-run 2026-09-16)

# Git remotes use SSH (durable; matches MEMORY.md auth doc). PATs in URLs have
# previously gone silently dead (the 2026-06-01 incident: PAT revoked, push
# failed, hook kept committing locally — invisible until a manual push). SSH
# keys don't expire and the failure mode is loud.
repo_url() { local repo="$1"; echo "git@github.com:pbhwheeler/${repo}.git"; }

cat <<'INTRO'
=== Claude Code dev machine bootstrap ===
This will:
  1. apt install git jq curl cifs-utils npm libsecret-tools nmap avahi-daemon
     python3-venv
  2. Verify SSH access to GitHub (needed before private-repo clones)
  3. Clone ~/.claude-config, the memory repo AND the HomeAssistant repo
     (/home/em/development/HomeAssistant — haq.py, lovelace_ws.py, the apps)
  4. Symlink config files into ~/.claude/
  5. Install + enable the ssh-add-keyring user service (auto-loads the
     passphrased SSH key into the agent at login)
  6. Patch ~/.claude.json with the home-assistant MCP server entry
  7. Add Samba mount entries to /etc/fstab and mount them
  8. Create the ~/.ha-tools python venv (PEP 668 blocks plain pip on Ubuntu)
  9. (optional) Wire up the daily activity report — IMAP-driven daily
     email summary of this laptop's git/memory activity to StartMail

NOT covered (manual, see memory bootstrap_new_dev_machine.md): Claude Code
itself (native installer), node via nvm, the esphome venv + its secrets.yaml.

Prereqs: an SSH key registered on github.com/settings/keys. If you don't have
one yet: ssh-keygen -t ed25519, then paste ~/.ssh/id_ed25519.pub into GitHub.

You'll be prompted for: the HA long-lived token (SHARED across laptops —
paste the existing one from the password manager), the Samba password, and
optionally a StartMail app password for the daily report. No GitHub PAT:
git is SSH-only and there is no GitHub MCP server (2026-09-16).

INTRO
read -rp "Proceed? [y/N] " ans
[[ "$ans" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }

# 1. apt packages
echo ">>> Installing apt packages..."
# A broken THIRD-PARTY source (a PPA with no build for this release) makes
# `apt update` exit non-zero even though every Ubuntu repo refreshed fine;
# with set -e that killed the whole bootstrap at step 1 (dry-run 2026-09-16:
# doctormo/wacom-plus had no noble Release file). Warn and continue instead.
sudo apt update -qq || echo "    WARN: apt update reported errors — usually a third-party PPA with no" \
                            "release for this Ubuntu; continuing (disable the source to silence it)"
sudo apt install -y git jq curl cifs-utils smbclient npm libsecret-tools \
    nmap avahi-daemon python3-venv
# nmap: netinv_client.py is useless without it. avahi-daemon: homeassistant.local
# is mDNS-only and the fstab lines wait on avahi-daemon.service. python3-venv:
# step 8 (PEP 668 blocks pip outside a venv on Ubuntu).

# 2. SSH precheck — git operations on the private memory repo and durable
# pushes both require an SSH key registered with GitHub. Bail loudly if not.
echo ">>> Verifying SSH access to GitHub..."
# ⚠ GitHub's `ssh -T` ALWAYS exits 1 ("does not provide shell access"), so under
# `set -o pipefail` a `ssh … | grep -q` pipeline reports FAILURE even when the
# key is accepted (dry-run 2026-09-16: every run died here with a valid key).
# Capture the output first; judge only the text.
GH_CHECK="$(ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -T git@github.com 2>&1 || true)"
if grep -q "successfully authenticated" <<< "$GH_CHECK"; then
    echo "    OK: SSH auth as pbhwheeler works."
else
    echo "    FAIL: ssh -T git@github.com did not return 'successfully authenticated'."
    echo "    Add this machine's SSH key to https://github.com/settings/keys first."
    echo "    Quick path: ssh-keygen -t ed25519, then add the .pub to GitHub, then re-run."
    exit 1
fi

# 3. Tokens — prompt up front so the rest can run unattended.
#    No GitHub PAT (dropped 2026-09-16): git is SSH-only and the GitHub MCP
#    entry this script used to write never existed on the working laptop.
#    Re-runs on an already-bootstrapped machine must not force a re-paste
#    (dry-run finding 2026-09-16): reuse the token already in ~/.claude.json
#    when Enter is pressed, and skip the Samba prompt if /etc/cifs.creds exists.
# (|| true: on a FRESH machine ~/.claude.json does not exist yet, jq exits 2,
#  and under set -e that would abort the run right here.)
EXISTING_HA=$( { jq -r '.projects."/home/em/development".mcpServers."home-assistant".headers.Authorization // empty' \
                 "$HOME/.claude.json" 2>/dev/null || true; } | sed 's/^Bearer //')
if [ -n "$EXISTING_HA" ]; then
    read -rp "Home Assistant long-lived access token [Enter = keep the one already configured]: " HA_TOKEN
    HA_TOKEN="${HA_TOKEN:-$EXISTING_HA}"
else
    read -rp "Home Assistant long-lived access token (shared across laptops): " HA_TOKEN
fi
if [ -f /etc/cifs.creds ]; then
    echo "    Samba credentials already present at /etc/cifs.creds — not prompting"
    SAMBA_PASS=""
else
    read -rsp "Samba password for HA share: " SAMBA_PASS; echo
fi

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

# 5b. Clone or update the HomeAssistant repo — supplies haq.py, lovelace_ws.py,
#     netinv_client.py, the deploy_*_lovelace.py scripts and every deployed app.
#     Gap #6 of the parity list until 2026-09-16.
HA_REPO_DIR="/home/em/development/HomeAssistant"
if [ -d "$HA_REPO_DIR/.git" ]; then
    echo ">>> Updating HomeAssistant repo..."
    git -C "$HA_REPO_DIR" pull --ff-only || echo "    (pull failed — resolve by hand)"
else
    echo ">>> Cloning HomeAssistant repo to $HA_REPO_DIR..."
    mkdir -p "$(dirname "$HA_REPO_DIR")"
    git clone "$(repo_url HomeAssistant)" "$HA_REPO_DIR"
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

# 7b. Dashboards daily snapshot timer — nightly (23:45) runs sync_dashboards.py in
# the HomeAssistant repo and pushes any dashboard changes. Wrapper skips cleanly if
# /home/em/development/HomeAssistant or /mnt/ha aren't present, so safe to enable
# even on a machine that doesn't have them yet.
echo ">>> Installing dashboards-sync user timer..."
cp "$CONFIG_DIR/systemd/dashboards-sync.service" "$HOME/.config/systemd/user/dashboards-sync.service"
cp "$CONFIG_DIR/systemd/dashboards-sync.timer"   "$HOME/.config/systemd/user/dashboards-sync.timer"
if systemctl --user daemon-reload 2>/dev/null; then
    if systemctl --user enable --now dashboards-sync.timer 2>/dev/null; then
        echo "    enabled — nightly Lovelace dashboard snapshot to the HomeAssistant repo"
    else
        echo "    WARN: enable failed — run in a desktop session: systemctl --user enable --now dashboards-sync.timer"
    fi
else
    echo "    WARN: no user systemd session here. After your first graphical login, run:"
    echo "          systemctl --user daemon-reload && systemctl --user enable --now dashboards-sync.timer"
fi

# 8. Patch ~/.claude.json with MCP servers under the /home/em/development project
CLAUDE_JSON="$HOME/.claude.json"
[ -f "$CLAUDE_JSON" ] || echo "{}" > "$CLAUDE_JSON"
echo ">>> Writing MCP server entries to $CLAUDE_JSON..."
jq --arg ha "$HA_TOKEN" --arg host "$HA_HOST" '
  .projects = (.projects // {})
  | .projects["/home/em/development"] = (.projects["/home/em/development"] // {})
  | .projects["/home/em/development"].mcpServers = {
      "home-assistant": {
        type: "http",
        url: ("http://" + $host + ":8123/api/mcp"),
        headers: { Authorization: ("Bearer " + $ha) }
      }
    }
' "$CLAUDE_JSON" > "$CLAUDE_JSON.tmp" && mv "$CLAUDE_JSON.tmp" "$CLAUDE_JSON"

# 9. Samba mounts
echo ">>> Configuring Samba mounts..."
sudo mkdir -p /mnt/ha /mnt/ha_addons /mnt/ha_media
# Credentials go in a root-only file, never inline in the world-readable fstab
# (dry-run 2026-09-16: the script had password=... in fstab while the working
# laptop used credentials=/etc/cifs.creds). The password reaches root via a
# pipe, so it never appears on a command line.
CREDS=/etc/cifs.creds
if [ -n "$SAMBA_PASS" ]; then
    printf 'username=homeassistant\npassword=%s\n' "$SAMBA_PASS" | sudo tee "$CREDS" > /dev/null
    sudo chown root:root "$CREDS" && sudo chmod 600 "$CREDS"
    echo "    wrote $CREDS (root, mode 600)"
elif sudo test -f "$CREDS"; then
    echo "    using existing $CREDS"
else
    echo "    ERROR: no Samba password given and no $CREDS — the mounts below will fail"
fi
UID_GID="uid=$(id -u),gid=$(id -g),vers=3.0"
# _netdev + x-systemd.after=avahi-daemon.service are REQUIRED: the share is
# addressed by mDNS name and a boot-time mount races the responder without them.
OPTS="credentials=${CREDS},${UID_GID},_netdev,x-systemd.after=avahi-daemon.service"
add_fstab() {
    local share="$1" mp="$2"
    if grep -q "^//${HA_HOST}/${share} " /etc/fstab; then
        echo "    fstab already has $share -> $mp"
        return
    fi
    echo "    adding fstab: //$HA_HOST/$share -> $mp"
    echo "//${HA_HOST}/${share} $mp cifs ${OPTS} 0 0" \
        | sudo tee -a /etc/fstab > /dev/null
}
# Retire legacy lines from bootstraps before 2026-09-02: they point at the
# server's OLD address and carry the Samba password inline (dry-run 2026-09-16
# found all three on the second Latitude, making `mount -a` error while the
# new lines mounted fine). Deleted, not commented — a commented line would
# still hold the plaintext password.
if grep -qE '^//192\.168\.1\.41/(config|addon_configs|media) ' /etc/fstab; then
    echo "    removing legacy //192.168.1.41/ HA share lines (old address, inline password)"
    sudo sed -i -E '\|^//192\.168\.1\.41/(config\|addon_configs\|media) |d' /etc/fstab
fi
add_fstab config       /mnt/ha
add_fstab addon_configs /mnt/ha_addons
add_fstab media        /mnt/ha_media
sudo systemctl daemon-reload
sudo mount -a || echo "    (some mounts failed — check 'mount -a' manually)"

# 10. Normalize both repo remotes to SSH (idempotent — repairs prior installs
# that may have inherited HTTPS+PAT URLs from older bootstrap revisions).
git -C "$MEMORY_DIR" remote set-url origin "$(repo_url claude-memory)" || true
git -C "$CONFIG_DIR" remote set-url origin "$(repo_url claude-config)" || true

# 10b. ~/.ha-tools venv — the ONLY place python deps can be installed on Ubuntu
#      (PEP 668 blocks pip outside a venv). Pinned list lives in this repo.
HA_TOOLS="$HOME/.ha-tools"
REQ="$CONFIG_DIR/scripts/ha-tools-requirements.txt"
if [ -x "$HA_TOOLS/bin/pip" ]; then
    echo ">>> ~/.ha-tools venv already exists — leaving it alone"
elif [ -f "$REQ" ]; then
    echo ">>> Creating ~/.ha-tools venv..."
    python3 -m venv "$HA_TOOLS" && "$HA_TOOLS/bin/pip" install -q -r "$REQ" \
        && echo "    installed $("$HA_TOOLS/bin/pip" list 2>/dev/null | wc -l) packages" \
        || echo "    WARN: venv install failed — run: python3 -m venv ~/.ha-tools && ~/.ha-tools/bin/pip install -r $REQ"
else
    echo "    (no $REQ — skipping venv)"
fi

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
Verify (parity smoke test — each line exercises a different capability):
  /home/em/.claude/statusline.sh    # should print "ha:🟢 addons:🟢"
  getent hosts homeassistant.local && ls /mnt/ha      # mDNS + Samba
  jq -r '.projects."/home/em/development".mcpServers | keys' ~/.claude.json   # ["home-assistant"]
  cd /home/em/development/HomeAssistant && python3 haq.py states sun.sun     # HA token + repo
  ~/.ha-tools/bin/pip list | wc -l  # ~36
  command -v nmap && ssh -T git@github.com
Still manual: claude --version (native installer), node -v (nvm), esphome venv.

SSH key auto-unlock — the ssh-add-keyring service is installed + enabled, but it
can only load the key once THIS machine's GNOME keyring holds the passphrase.
One-time per machine, in a desktop session (so the login keyring is unlocked):
  1. Passphrase the key if it isn't already:  ssh-keygen -p -f ~/.ssh/id_ed25519
  2. Store that passphrase in the keyring (attributes must match the askpass helper):
       secret-tool store --label='ssh id_ed25519 passphrase' ssh-key id_ed25519
  3. Test:  systemctl --user start ssh-add-keyring.service && ssh-add -l
Until that's done, git-over-SSH will prompt for the passphrase interactively.

Run 'claude' in any project dir to start working.

If the SessionStart hook doesn't fire on your first session, run /hooks
once or restart the session — Claude Code's settings watcher picks up
changes for new sessions only.
EOF
