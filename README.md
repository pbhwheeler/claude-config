# claude-config

Claude Code config that's portable across dev machines (paired with the
`claude-memory` private repo).

Contents:
- `settings.json` — `~/.claude/settings.json` (hooks, statusLine, etc.)
- `statusline.sh` — fast status line script
- `session_start.sh` — health-check probe + cross-machine handoff banner at session start
- `session_end.sh` — stamps `.last_session` marker + pushes memory at Stop
- `prune-backups.sh` — periodic cleanup of `.claude.json` timestamped backups
- `setup-symlinks.sh` — extracted from `bootstrap.sh`; relinks `~/.claude/*` after a config-file addition
- `bootstrap.sh` — one-shot setup for a fresh machine
- `commands/` — per-file slash command definitions, symlinked into `~/.claude/commands/`

## Bootstrap a new dev machine

One-liner (after `git` and `curl` are available):

```sh
bash <(curl -sSL https://raw.githubusercontent.com/pbhwheeler/claude-config/main/bootstrap.sh)
```

The script will:
1. `apt install` git, jq, curl, cifs-utils, samba-client, npm
2. Clone this repo to `~/.claude-config`
3. Clone `claude-memory` to `~/.claude/projects/-home-em-development/memory`
4. Symlink `settings.json`, `statusline.sh`, `session_start.sh`, `session_end.sh`, `prune-backups.sh`, and `commands/*.md` into `~/.claude/`
5. Patch `~/.claude.json` with the HA + GitHub MCP server entries (sqlite retired 2026-05-17 — REST `/api/history/period/` is used instead)
6. Add Samba mount entries to `/etc/fstab` and run `mount -a`
7. Reset both repo remotes to the inline-PAT URL so PostToolUse autopush works

It will prompt for: GitHub PAT, HA long-lived access token, Samba password.
Save these in your password manager so this is fast.

Idempotent — safe to re-run on an already-bootstrapped machine.

## Architecture

The active files in `~/.claude/` are symlinks back to this repo, so editing
`~/.claude/settings.json` actually edits `~/.claude-config/settings.json`.
A PostToolUse hook auto-commits and pushes config changes; SessionStart on
other machines pulls them. Same pattern as `claude-memory`.

## Manually managed (not in this repo)

- `~/.claude.json` — contains tokens; manual edit (or re-run bootstrap)
- `/etc/fstab` — system file; manual edit (or re-run bootstrap)
- The shares' password is stored in fstab in plaintext. The `claude-memory` repo
  is the source of truth for what the password is; bootstrap prompts for it.

## Notes

- This repo is private. Tokens are NOT stored here — only in `~/.claude.json`
  and `/etc/fstab` on each machine.
- The bootstrap one-liner uses `bash <(...)` not `... | bash` so prompts work.
