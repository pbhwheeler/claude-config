---
description: Diagnose and fix cross-machine memory autopush/autopull from THIS laptop
---
The two dev laptops share memory + config via GitHub. The "↻ Synced from ..." line
in `session_start.sh` and the `session end on mid-<id>` commits in the memory repo
are the verification mechanism (see `cross_machine_handoff.md` in the memory dir).

If you're invoked, the other laptop is not seeing pushes from this laptop. Your job
is to diagnose, propose a fix, and (with my permission) apply it.

## Required reading (already pulled into memory at session start)

- `cross_machine_handoff.md` — how the marker mechanism works
- `feedback_claude_code_hooks_shell.md` — POSIX vs bash quirk that broke the hooks
- `bootstrap_new_dev_machine.md` — what a properly bootstrapped machine looks like

## Diagnostic commands to run (read-only)

1. `readlink ~/.claude/settings.json ~/.claude/session_end.sh ~/.claude/session_start.sh ~/.claude/statusline.sh`
   — confirms all four config files are symlinks into `~/.claude-config/`. Empty
   output for any of them = not a symlink = setup-symlinks.sh didn't take effect.

2. `ls -la ~/.claude-config/ | head -20`
   — confirms config repo is present and has the recent files (`session_end.sh`,
   `setup-symlinks.sh`, `commands/`).

3. `git -C ~/.claude-config log --oneline -3`
   — should show recent commits like `b7da851 chmod +x setup-symlinks.sh`,
   `f75d977 fix: hook commands use POSIX case syntax`, etc. If only
   `30cc414 Initial: ...` appears, the repo is stale — pull it.

4. `git -C ~/.claude/projects/-home-em-development/memory remote -v`
   — confirms the memory repo's `origin` URL has auth. Should be either
   `git@github.com:pbhwheeler/claude-memory.git` (SSH) or
   `https://ghp_XXXX@github.com/pbhwheeler/claude-memory.git` (PAT inline).
   Plain `https://github.com/pbhwheeler/claude-memory.git` will silently fail
   to push because `session_end.sh` swallows stderr with `2>/dev/null`.

5. `/home/em/.claude/session_end.sh; echo "exit: $?"`
   — run the Stop hook script directly. Should print no warnings and exit 0.
   If you see `⚠ git push failed` lines, that's the smoking gun. Re-run
   without the script's `2>/dev/null` to see the actual git error:
   `git -C ~/.claude/projects/-home-em-development/memory push 2>&1`

## Common fixes (apply with my permission, in order)

- **Symlinks missing**: run `~/.claude-config/setup-symlinks.sh` (or
  `bash <(curl -sSL https://raw.githubusercontent.com/pbhwheeler/claude-config/main/setup-symlinks.sh)`).
- **Config repo stale**: `git -C ~/.claude-config pull --ff-only`.
- **Memory repo remote URL lacks auth**: ask me for my GitHub PAT, then
  `git -C ~/.claude/projects/-home-em-development/memory remote set-url origin https://ghp_<PAT>@github.com/pbhwheeler/claude-memory.git`.
  Alternatively, if SSH is set up, switch to the SSH URL.
- **machine-id collides** (unlikely — both Latitudes were tested with distinct
  `/etc/machine-id` values): suggest a friendly label in `~/.claude/machine-label`.

## Verification

After fixing, run `/home/em/.claude/session_end.sh` one more time. It should
write the marker AND push to GitHub silently. Confirm with:
`git -C ~/.claude/projects/-home-em-development/memory log origin/master..HEAD --oneline` (empty = in sync) and
`git -C ~/.claude/projects/-home-em-development/memory log --oneline -1` (shows the new commit hash).

Then tell me whether the marker pushed successfully and what the fix was — so I can
update `cross_machine_handoff.md` if there's a recurring failure mode worth
documenting.
