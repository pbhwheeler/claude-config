#!/bin/sh
# Non-interactive SSH askpass helper.
# Returns the passphrase for ~/.ssh/id_ed25519 from the GNOME login keyring
# (stored once via `secret-tool store ssh-key id_ed25519`).
#
# Used by the ssh-add-keyring.service user unit so the passphrased key loads
# into the agent automatically at login — keeping the non-interactive memory
# /config auto-push + session-start pull hooks working without a prompt.
#
# Contains NO secret: it only looks one up. Safe to live in the public
# claude-config repo. If the keyring is locked or the entry is missing,
# secret-tool exits non-zero and ssh-add fails cleanly (no garbage fed in).
exec secret-tool lookup ssh-key id_ed25519
