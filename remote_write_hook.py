#!/usr/bin/env python3
"""UserPromptSubmit hook: detect a remote-control (phone-bridged) session.

When a remote client is bridged, the link intermittently ABORTS tool calls
(Bash and the Write/Edit harness tools alike) before they finish -- the effect
does not land and the result is lost. This hook flags that state so the model
treats a hang as "unknown, re-verify" rather than "done", and detaches slow
shell writes with setsid. Prints nothing when local, so there is no noise.

Detection: find the per-session state file ~/.claude/sessions/<pid>.json whose
`sessionId` matches this session and check whether `bridgeSessionId` is set
(non-null) -- that field is populated only while a remote client is bridged.
Session id comes from the hook stdin JSON (`session_id`), falling back to the
CLAUDE_CODE_SESSION_ID env var.
"""
import glob
import json
import os
import sys


def is_remote(session_id):
    if not session_id:
        return False
    for path in glob.glob(os.path.expanduser("~/.claude/sessions/*.json")):
        try:
            with open(path) as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if data.get("sessionId") == session_id and data.get("bridgeSessionId"):
            return True
    return False


def main():
    try:
        payload = json.load(sys.stdin)
    except (OSError, ValueError):
        payload = {}
    session_id = payload.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not is_remote(session_id):
        return
    msg = (
        "REMOTE-CONTROL SESSION (phone bridged). The link can abort ANY tool call "
        "(Bash or Write/Edit) before it lands, losing the result -- treat a hang as "
        "UNKNOWN and re-verify with a separate tiny read, never assume failure. For "
        "slow shell writes to /mnt/ha Samba, detach so the abort cannot kill them: "
        "setsid sh -c '<cmd>' </dev/null >/dev/null 2>&1 &  then verify separately."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": msg,
        }
    }))


if __name__ == "__main__":
    main()
