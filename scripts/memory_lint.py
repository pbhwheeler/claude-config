#!/usr/bin/env python3
"""memory_lint.py — SessionStart guard against accrued memory drift.

WHY THIS EXISTS (2026-09-09). A full hand review of the memory repo found nine
stale facts. Five of them had a single machine-checkable ground truth and would
have been caught in seconds: a deploy pointer three commits behind, a rollback
file named nowhere, four device IPs two migrations out of date, and an alert
slot recorded as occupied after it was cleared. This checks exactly that class —
facts with one ground truth — and deliberately nothing else. The prose in memory
is hand-curated judgement and is none of this script's business.

CONTRACT: read-only, silent when clean, bounded by an 8 s alarm, and it must
never print a credential (it reads core.config_entries, which holds device
passwords — only title / device_name / host are ever touched).
"""

import glob
import hashlib
import json
import os
import re
import signal
import subprocess
import sys

MEM = "/home/em/.claude/projects/-home-em-development/memory"
REPO = "/home/em/development/HomeAssistant"
APPS = "/mnt/ha_addons/a0d7b954_appdaemon/apps"
STORAGE = "/mnt/ha/.storage"
CTRL = "appdaemon/apps/energy_controller.py"
IP_RE = re.compile(r"192\.168\.1\.\d{1,3}")
# Lines that are deliberately recording an OLD fact are not drift. Keeping this
# list short on purpose: a lint that cries wolf gets ignored, and a lint that
# suppresses too much stops being worth running.
HISTORICAL = ("was ", "were ", "history", "historical", "dead", "removed",
              "cleared", "superseded", "moved", "retired", "old ", "no longer")


def is_historical(line):
    low = line.lower()
    return any(k in low for k in HISTORICAL)

warn = []


def bail(*_a):
    # A hung Samba read must not eat the SessionStart budget. Say so and stop.
    print("⚑ memory lint: timed out (Samba or HA slow) — skipped")
    sys.stdout.flush()
    os._exit(0)


def sh(cmd, cwd=None, timeout=5):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


def md5(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.md5(fh.read()).hexdigest()
    except Exception:
        return None


def load_memory():
    out = {}
    for p in sorted(glob.glob(MEM + "/*.md")):
        try:
            out[os.path.basename(p)] = open(p, encoding="utf-8").read()
        except Exception:
            pass
    return out


def check_deploy_pointer(alltext):
    """The newest commit touching the controller must be named somewhere in memory,
    and what is RUNNING must match what is committed."""
    head = sh(["git", "log", "-1", "--format=%h", "--", CTRL], cwd=REPO)
    if head and head not in alltext:
        subject = sh(["git", "log", "-1", "--format=%s", "--", CTRL], cwd=REPO)[:60]
        warn.append("energy_controller %s not named in memory (%s)" % (head, subject))
    live, repo = md5(APPS + "/energy_controller.py"), md5(REPO + "/" + CTRL)
    if live and repo and live != repo:
        warn.append("live energy_controller.py differs from the repo copy — undeployed or hand-edited")


def check_rollback_files(alltext):
    """Every rollback file on the addon share should be findable in memory —
    an unnamed one is a deploy nobody wrote down."""
    orphans = []
    for p in sorted(glob.glob(APPS + "/energy_controller.py.*")):
        suffix = os.path.basename(p).split("energy_controller.py.", 1)[-1]
        if suffix and suffix not in alltext:
            orphans.append(suffix)
    if orphans:
        warn.append("rollback file(s) on the server named nowhere in memory: " + ", ".join(orphans))


def check_device_ips(mem):
    """A memory line that pairs a device's own name with an IP that is not the
    device's live IP. Catches the class where an address moves in one session and
    the device's own project file never hears about it."""
    try:
        entries = json.load(open(STORAGE + "/core.config_entries"))["data"]["entries"]
    except Exception:
        return
    live = {}
    for e in entries:
        data = e.get("data") or {}
        host = data.get("host")
        if not isinstance(host, str) or not IP_RE.fullmatch(host):
            continue
        for token in (e.get("title"), data.get("device_name")):
            if isinstance(token, str) and len(token) >= 8:
                live[token.lower()] = host
    hits = []
    for name, text in mem.items():
        for n, line in enumerate(text.splitlines(), 1):
            ips = set(IP_RE.findall(line))
            if not ips:
                continue
            if is_historical(line):
                continue
            low = line.lower()
            for token, ip in live.items():
                # Word-boundary match: bare "bt-proxy" must not match
                # "bt-proxy-dining", which is a different device.
                if not re.search(r"(?<![a-z0-9-])%s(?![a-z0-9-])" % re.escape(token), low):
                    continue
                if ip not in ips:
                    hits.append("%s:%d %s -> live %s, memory says %s"
                                % (name, n, token, ip, "/".join(sorted(ips))))
    for h in hits[:4]:
        warn.append("stale IP? " + h)
    if len(hits) > 4:
        warn.append("stale IP? ...and %d more" % (len(hits) - 4))


def check_alert_slots(mem):
    """Memory naming an entity for a reachability slot the live helper no longer holds."""
    try:
        cfg = json.load(open("/home/em/.claude.json"))
        auth = cfg["projects"]["/home/em/development"]["mcpServers"]["home-assistant"]["headers"]["Authorization"]
        token = auth.replace("Bearer ", "")
    except Exception:
        return
    out = sh(["curl", "-s", "-m", "3", "-H", "Authorization: Bearer " + token,
              "http://homeassistant.local:8123/api/states"], timeout=5)
    if not out:
        return
    try:
        states = json.loads(out)
    except Exception:
        return
    slots = {}
    for s in states:
        m = re.fullmatch(r"input_text\.ha_alert_manager_reachability_(\d+)", s.get("entity_id", ""))
        if m:
            slots[m.group(1)] = (s.get("state") or "").strip()
    ent_re = re.compile(r"\b((?:binary_)?sensor\.[a-z0-9_]+)")
    for name, text in mem.items():
        for n, line in enumerate(text.splitlines(), 1):
            m = re.search(r"[Ss]lot (\d{1,2})\b", line)
            if not m or m.group(1) not in slots or is_historical(line):
                continue
            for ent in ent_re.findall(line):
                if ent not in slots[m.group(1)]:
                    warn.append("alert slot %s: memory names %s, live slot = %s (%s:%d)"
                                % (m.group(1), ent, slots[m.group(1)] or "EMPTY", name, n))
                    break


def check_repo_state():
    """The two sync'd repos are covered by session_start.sh; this is the third one."""
    if not os.path.isdir(REPO + "/.git"):
        return
    dirty = sh(["git", "status", "--porcelain"], cwd=REPO)
    if dirty:
        warn.append("HomeAssistant repo has %d uncommitted file(s)" % len(dirty.splitlines()))
    ahead = sh(["git", "rev-list", "--count", "@{u}..HEAD"], cwd=REPO)
    if ahead.isdigit() and int(ahead) > 0:
        warn.append("HomeAssistant repo: %s unpushed commit(s)" % ahead)


def main():
    signal.signal(signal.SIGALRM, bail)
    signal.alarm(8)
    mem = load_memory()
    if not mem:
        return
    alltext = "\n".join(mem.values())
    check_deploy_pointer(alltext)
    check_rollback_files(alltext)
    check_device_ips(mem)
    check_alert_slots(mem)
    check_repo_state()
    signal.alarm(0)
    for w in warn[:8]:
        print("⚑ " + w)


if __name__ == "__main__":
    main()
