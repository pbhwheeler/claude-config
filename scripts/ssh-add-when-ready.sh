#!/bin/sh
# Wait (bounded) for the GNOME-keyring SSH agent socket to exist, then load the
# passphrased key. Invoked by the ssh-add-keyring.service user unit.
#
# Why the wait: the agent socket interactive clients use ($SSH_AUTH_SOCK,
# typically $XDG_RUNTIME_DIR/keyring/ssh) is created late in graphical login by
# the keyring plumbing, AFTER the unit's After= service deps are satisfied and
# with no clean systemd unit to order against. A plain `ssh-add` therefore
# races login and dies with "Error connecting to agent: No such file or
# directory", leaving the key unloaded so the next git-over-SSH op pops an
# interactive passphrase prompt. Polling for the socket closes that race.
#
# The passphrase itself is supplied non-interactively by SSH_ASKPASS
# (ssh-askpass-keyring.sh -> secret-tool), inherited from the unit's env.
# Contains no secret. Safe for the public claude-config repo.

set -u

sock="${SSH_AUTH_SOCK:-${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/keyring/ssh}"
key="${1:-$HOME/.ssh/id_ed25519}"

n=0
while [ ! -S "$sock" ]; do
    n=$((n + 1))
    if [ "$n" -gt 75 ]; then            # ~15s at 0.2s/iter
        echo "ssh-add-when-ready: agent socket $sock never appeared" >&2
        exit 1
    fi
    sleep 0.2
done

exec ssh-add "$key"
