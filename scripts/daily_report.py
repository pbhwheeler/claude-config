#!/usr/bin/env python3
"""Daily work-summary report.

Walks the user's three tracked git repositories (HomeAssistant, claude-config,
claude-memory), assembles a markdown summary of commits + new memory files
since midnight local time, and APPENDs the message to the user's StartMail
INBOX and Sent folders via IMAP. No SMTP involved — the message simply
materializes in the server-side mailbox; Thunderbird and any other IMAP
client see it on next sync.

Usage:
    daily_report.py            # normal run; assumes cron context
    daily_report.py --test     # build report, print to stdout AND send via IMAP
    daily_report.py --dry-run  # build report, print to stdout, DO NOT send

Config: ~/.config/daily-report/imap.cfg (key=value, mode 600).
Required keys: imap_server, imap_port, username, password, to_address,
from_address. Optional: sent_folder (auto-discovered on first send if absent).
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.message
import email.utils
import imaplib
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

CONFIG_PATH = Path("~/.config/daily-report/imap.cfg").expanduser()
LOG_PATH = Path("~/.local/share/daily-report.log").expanduser()

# Ad-hoc notes — drop a markdown file into NOTES_PENDING and tonight's report
# includes its contents verbatim under a "Notes" section. After a successful
# send, consumed files move to NOTES_SENT (date-stamped subdir) so the same
# note doesn't reappear in tomorrow's report.
NOTES_PENDING = Path("~/.local/share/daily-report/notes/pending").expanduser()
NOTES_SENT    = Path("~/.local/share/daily-report/notes/sent").expanduser()

# Repos to inspect. (path, friendly-name, kind)
# kind="memory" gets special treatment (lists new files, not just commit msgs).
REPOS = [
    ("/home/em/development/HomeAssistant", "HomeAssistant", "code"),
    ("/home/em/.claude-config", "claude-config", "code"),
    ("/home/em/.claude/projects/-home-em-development/memory", "claude-memory", "memory"),
]

# Sent-folder candidates to try if not configured. Server-specific naming is
# the main gotcha — StartMail historically uses "Sent" but other accounts may
# differ. The first one that exists wins; the discovered name is written back
# to the config for future runs.
SENT_FOLDER_CANDIDATES = ["Sent", "Sent Messages", "Sent Items", "INBOX.Sent"]

# Security-hardening project tracker. The report includes a live progress block
# parsed from the checklist between these markers in the memory file, and drops
# it automatically once every item is checked (the "until complete" stop).
SECURITY_STATUS_FILE = Path(
    "/home/em/.claude/projects/-home-em-development/memory/project_security_hardening.md"
)
SEC_START = "<!-- SEC-STATUS:START -->"
SEC_END = "<!-- SEC-STATUS:END -->"

# ── Temporary diagnostic (2026-05-28): overnight HVAC relay-board Wi-Fi event ──
# The board drops its link in a recurring ~04:00-04:45 network blip. It now
# exposes an `uptime` sensor, so a reboot (uptime resets ~0) is distinguishable
# from a pure Wi-Fi drop (uptime stays continuous). This reads that morning's
# recorder window and reports the verdict in the nightly email. Fully defensive:
# any failure returns "" so the email is never affected. REMOVE once the ~4am
# blip's cause (power vs network/AP) is confirmed.
HA_BASE = "http://192.168.1.41:8123"


def _ha_token() -> str:
    """Pull the HA long-lived token out of the local (gitignored) .claude.json.
    Returns "" if unavailable. No secret is stored in this repo."""
    import json, re
    try:
        data = json.loads(Path("~/.claude.json").expanduser().read_text())
    except Exception:
        return ""
    found = []
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, str) and "eyJ" in v:
                    found.append(v)
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)
    walk(data)
    for h in found:
        m = re.search(r"(eyJ[A-Za-z0-9_.\-]+)", h)
        if m:
            return m.group(1)
    return ""


def hvac_overnight_wifi_check(now: dt.datetime) -> str:
    """Did the HVAC relay board drop its link overnight (03:30-05:30), and if so
    did it reboot (uptime reset) or just lose Wi-Fi (uptime continuous)? Reads
    the HA recorder. Fully defensive — returns "" on any problem. Temporary."""
    try:
        import json, urllib.request, urllib.parse
        tok = _ha_token()
        if not tok:
            return ""
        local = now.astimezone()
        start = local.replace(hour=3, minute=30, second=0, microsecond=0)
        end = local.replace(hour=5, minute=30, second=0, microsecond=0)
        if local < end:
            return ""  # this morning's window hasn't fully elapsed yet
        q = urllib.parse.urlencode({
            "end_time": end.isoformat(),
            "filter_entity_id": "input_text.hvac_waveshare_last_disconnect,sensor.hvac_relay_board_uptime",
            "minimal_response": "",
        })
        url = f"{HA_BASE}/api/history/period/{urllib.parse.quote(start.isoformat())}?{q}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.load(resp)
        disc_times, uptimes = [], []
        for series in data:
            if not series:
                continue
            eid = series[0].get("entity_id", "")
            for s in series:
                raw = s.get("last_changed") or s.get("last_updated")
                try:
                    ts = dt.datetime.fromisoformat(raw)
                except Exception:
                    continue
                if not (start <= ts <= end):
                    continue
                if eid.endswith("last_disconnect"):
                    disc_times.append(ts)
                elif eid.endswith("uptime"):
                    try:
                        uptimes.append(float(s["state"]))
                    except (ValueError, TypeError, KeyError):
                        pass
        if not disc_times:
            return "## HVAC board overnight Wi-Fi check\n\n_No link drop 03:30-05:30._\n\n"
        if not uptimes:
            verdict = "uptime telemetry not available for this window yet (sensor added 2026-05-28); conclusive from the next event onward"
        elif any(uptimes[i] < uptimes[i - 1] - 60 for i in range(1, len(uptimes))):
            verdict = "**REBOOTED** — uptime reset, so likely a power event"
        else:
            verdict = "**Wi-Fi drop only** — uptime stayed continuous, so the board kept power (network/AP event)"
        times = ", ".join(t.astimezone(local.tzinfo).strftime("%H:%M:%S") for t in disc_times)
        return ("## HVAC board overnight Wi-Fi check\n\n"
                f"- Link drop(s) 03:30-05:30: {len(disc_times)} ({times})\n"
                f"- Verdict: {verdict}\n\n")
    except Exception:
        return ""


def security_hardening_section() -> str:
    """Progress block for the active security-hardening project. Parses the
    checklist between the SEC-STATUS markers, tallies done/total per phase
    (a phase is an "### " heading), and renders a compact summary plus the
    next few open items. Returns "" if the file/markers are missing or every
    item is complete, so the report silently stops carrying it once done."""
    try:
        text = SECURITY_STATUS_FILE.read_text(encoding="utf-8")
    except OSError:
        return ""
    if SEC_START not in text or SEC_END not in text:
        return ""
    block = text.split(SEC_START, 1)[1].split(SEC_END, 1)[0]

    phases: list[list] = []  # [title, done, total]
    for line in block.splitlines():
        s = line.strip()
        if s.startswith("### "):
            phases.append([s[4:].strip(), 0, 0])
        elif s.startswith("- [") and phases:
            phases[-1][2] += 1
            if s[:5].lower() == "- [x]":
                phases[-1][1] += 1

    total = sum(p[2] for p in phases)
    done = sum(p[1] for p in phases)
    if total == 0 or done >= total:
        return ""

    pct = round(100 * done / total)
    out = ["## Security hardening progress\n",
           f"\n**{done}/{total} complete ({pct}%)** — full plan in "
           "`project_security_hardening.md`\n\n"]
    for title, d, t in phases:
        mark = "[x]" if t and d >= t else ("[~]" if d else "[ ]")
        out.append(f"- {mark} {title}: {d}/{t}\n")

    nxt = []
    for line in block.splitlines():
        s = line.strip()
        if s.startswith("- [ ]"):
            label = s[5:].strip()
            if "**" in label:
                parts = label.split("**")
                if len(parts) >= 3:
                    label = parts[1]
            nxt.append(label)
        if len(nxt) >= 3:
            break
    if nxt:
        out.append("\n**Next up:**\n")
        out.extend(f"- {n}\n" for n in nxt)

    return "".join(out) + "\n"


def parse_config(path: Path) -> dict[str, str]:
    """Read key=value file. Lines starting with # are comments. Values may be
    quoted to preserve trailing whitespace, but normally aren't."""
    if not path.exists():
        die(f"config file not found: {path}\nRun setup_daily_report.sh first.")
    cfg = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        cfg[k.strip()] = v.strip().strip('"').strip("'")
    required = ["imap_server", "imap_port", "username", "password", "to_address", "from_address"]
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        die(f"config missing required keys: {', '.join(missing)}")
    return cfg


def write_config(path: Path, cfg: dict[str, str]) -> None:
    """Rewrite the config file preserving mode 0600."""
    lines = []
    for k, v in cfg.items():
        lines.append(f"{k} = {v}")
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n")
    tmp.chmod(0o600)
    os.replace(tmp, path)


def run(cmd: list[str], cwd: str | None = None) -> str:
    """Run a command, return stdout. Silent on non-zero exit; caller checks."""
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=30)
        return r.stdout
    except (subprocess.SubprocessError, OSError) as e:
        return f"[error running {' '.join(cmd)}: {e}]"


def git_log_since(repo: str, since_iso: str) -> str:
    """Commits in this repo since the given ISO timestamp. One block per
    commit: short hash, author, summary, then body indented. Empty string if
    no commits."""
    fmt = "%h  %ai  %s%n%n    %an: %B"
    out = run(["git", "-C", repo, "log",
               f"--since={since_iso}",
               f"--pretty=format:{fmt}",
               "--no-merges"])
    return out.rstrip()


def gather_notes() -> list[tuple[Path, str]]:
    """Find ad-hoc notes queued for inclusion. Returns [(path, content), ...]
    sorted by filename so a deterministic ordering can be enforced by naming
    (e.g. "01-foo.md" before "02-bar.md"). Skips files starting with a dot."""
    if not NOTES_PENDING.exists():
        return []
    out = []
    for p in sorted(NOTES_PENDING.iterdir()):
        if not p.is_file() or p.name.startswith("."):
            continue
        if p.suffix.lower() not in (".md", ".markdown", ".txt"):
            continue
        try:
            out.append((p, p.read_text(encoding="utf-8")))
        except OSError as e:
            out.append((p, f"_(error reading {p.name}: {e})_"))
    return out


def archive_notes(consumed: list[Path], now: dt.datetime) -> None:
    """Move successfully-included note files into NOTES_SENT/<YYYY-MM-DD>/."""
    if not consumed:
        return
    dest = NOTES_SENT / now.strftime("%Y-%m-%d")
    dest.mkdir(parents=True, exist_ok=True)
    for p in consumed:
        try:
            os.replace(p, dest / p.name)
        except OSError as e:
            print(f"  warning: could not archive {p}: {e}", file=sys.stderr)


def new_memory_files(repo: str, since_iso: str) -> list[str]:
    """List paths of memory .md files first-introduced since the cutoff.
    For the claude-memory repo only — uses --diff-filter=A to find adds."""
    out = run(["git", "-C", repo, "log",
               f"--since={since_iso}",
               "--name-status",
               "--pretty=format:",
               "--no-merges"])
    added = []
    for line in out.splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2 and parts[0].strip() == "A":
            f = parts[1].strip()
            if f.endswith(".md"):
                added.append(f)
    return sorted(set(added))


def build_report(now: dt.datetime) -> tuple[str, str, list[Path]]:
    """Returns (subject, body, consumed_note_paths). The note paths are the
    pending notes whose content went into `body` — caller moves them to
    NOTES_SENT only after a successful send so a failed run can be retried
    without losing the note."""
    # "Since midnight local" — the cron fires at 23:59 local so this captures
    # everything since this morning.
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    since_iso = midnight.isoformat(sep=" ")

    sections = []
    total_commits = 0

    for repo_path, name, kind in REPOS:
        if not Path(repo_path, ".git").exists():
            sections.append(f"## {name}\n\n_(repo not present at {repo_path} — skipped)_\n")
            continue

        log = git_log_since(repo_path, since_iso)
        commit_count = log.count("\n\n") if log else 0  # rough
        total_commits += (log.count("\n\n") + 1) if log else 0

        section = f"## {name}\n\n"
        if not log:
            section += "_(no commits today)_\n"
        else:
            section += "```\n" + log + "\n```\n"

        if kind == "memory" and log:
            adds = new_memory_files(repo_path, since_iso)
            if adds:
                section += "\n**New memory files written today:**\n"
                for a in adds:
                    section += f"- `{a}`\n"

        sections.append(section)

    # Ad-hoc notes go into a single section at the top of the body — they're
    # the most "hand-curated" content and likely the reason the report was
    # being read attentively. Repo activity follows below.
    notes = gather_notes()
    notes_section = ""
    consumed_paths: list[Path] = []
    if notes:
        parts = ["## Notes\n"]
        for p, content in notes:
            parts.append(f"\n### {p.stem}\n\n{content.rstrip()}\n")
            consumed_paths.append(p)
        notes_section = "".join(parts) + "\n"

    date_str = now.strftime("%A, %B %d, %Y")
    note_tag = f", {len(notes)} note(s)" if notes else ""
    if total_commits == 0:
        subject = f"Daily report — {now.strftime('%Y-%m-%d')} — no activity logged{note_tag}"
    else:
        subject = f"Daily report — {now.strftime('%Y-%m-%d')} — work in {sum(1 for r in REPOS if Path(r[0], '.git').exists() and git_log_since(r[0], since_iso))} repo(s){note_tag}"

    host = socket.gethostname()
    header = f"# Daily work summary — {date_str}\n\nHost: `{host}` · Generated: {now.isoformat(timespec='seconds')}\n\n"

    body = header + security_hardening_section() + notes_section + "\n".join(sections)
    body += "\n\n---\n_Generated by ~/.claude-config/scripts/daily_report.py (cron, 23:59 local)_\n"
    return subject, body, consumed_paths


def build_message(cfg: dict[str, str], subject: str, body: str, now: dt.datetime) -> bytes:
    """Construct an RFC 5322 message as bytes ready for IMAP APPEND."""
    msg = email.message.EmailMessage()
    msg["From"] = cfg["from_address"]
    msg["To"] = cfg["to_address"]
    msg["Subject"] = subject
    msg["Date"] = email.utils.format_datetime(now.astimezone())
    msg["Message-ID"] = email.utils.make_msgid(domain="daily-report.local")
    msg["X-Daily-Report"] = "1"  # makes it easy to filter/find later
    msg.set_content(body)
    return msg.as_bytes()


def discover_sent_folder(M: imaplib.IMAP4_SSL) -> str | None:
    """List all mailboxes, find the most likely Sent folder."""
    typ, data = M.list()
    if typ != "OK":
        return None
    available = []
    for raw in data:
        if not raw:
            continue
        s = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
        # The LIST response format is: (\flags) "delim" "name"
        # Pick the part after the last quote-pair.
        last_q = s.rfind('"')
        if last_q == -1:
            continue
        first_q = s.rfind('"', 0, last_q)
        if first_q == -1:
            continue
        name = s[first_q + 1:last_q]
        available.append(name)

    # Try candidates in order. Also try SPECIAL-USE \Sent flag in the raw list.
    for cand in SENT_FOLDER_CANDIDATES:
        if cand in available:
            return cand
    # Fallback: any folder whose name has "Sent" in it.
    for n in available:
        if "Sent" in n:
            return n
    return None


def append_to_folder(M: imaplib.IMAP4_SSL, folder: str, raw_msg: bytes, seen: bool) -> None:
    """APPEND the message to the given folder with appropriate flags."""
    flags = r"(\Seen)" if seen else r"()"  # unread in INBOX, read in Sent
    # APPEND uses INTERNALDATE = now if not specified
    typ, data = M.append(folder, flags, imaplib.Time2Internaldate(time.time()), raw_msg)
    if typ != "OK":
        raise RuntimeError(f"APPEND to {folder!r} failed: {typ} {data!r}")


def send_report(cfg: dict[str, str], raw_msg: bytes) -> dict[str, str]:
    """Append to INBOX (unread) and Sent (read). Returns a dict mapping
    folder name to status text. Mutates cfg to cache the discovered sent
    folder if absent."""
    port = int(cfg["imap_port"])
    with imaplib.IMAP4_SSL(cfg["imap_server"], port) as M:
        M.login(cfg["username"], cfg["password"])

        results = {}
        # Inbox
        append_to_folder(M, "INBOX", raw_msg, seen=False)
        results["INBOX"] = "appended (unread)"

        # Sent — discover if not configured
        sent = cfg.get("sent_folder")
        if not sent:
            sent = discover_sent_folder(M)
            if sent:
                cfg["sent_folder"] = sent
                # Persist for next run so we don't re-discover every time
                write_config(CONFIG_PATH, cfg)
        if sent:
            try:
                append_to_folder(M, sent, raw_msg, seen=True)
                results[sent] = "appended (read)"
            except Exception as e:
                results[sent] = f"FAILED: {e}"
        else:
            results["(no sent folder found)"] = "skipped"

        M.logout()
    return results


def die(msg: str) -> None:
    print(f"daily_report: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--test", action="store_true",
                    help="print report to stdout AND send via IMAP")
    ap.add_argument("--dry-run", action="store_true",
                    help="print report to stdout, do not send")
    args = ap.parse_args()

    now = dt.datetime.now()
    subject, body, consumed_notes = build_report(now)

    # --dry-run doesn't need IMAP creds; the user might be previewing before
    # ever running setup_daily_report.sh. Notes are NOT archived on dry-run —
    # they stay pending so the next real send still picks them up.
    if args.dry_run:
        print(f"Subject: {subject}\n\n{body}")
        if consumed_notes:
            print(f"\n(dry-run: {len(consumed_notes)} note(s) WOULD be archived after a real send)")
        print("\n---\ndry-run: not sending")
        return 0

    cfg = parse_config(CONFIG_PATH)

    if args.test:
        print(f"Subject: {subject}\n\n{body}")
        print("\n---")

    raw = build_message(cfg, subject, body, now)
    try:
        results = send_report(cfg, raw)
    except Exception as e:
        die(f"send failed: {type(e).__name__}: {e}")

    for folder, status in results.items():
        print(f"  {folder}: {status}")

    # Only archive notes after the send succeeded — a failure should leave
    # them pending so the next attempt picks them up rather than silently
    # dropping content.
    archive_notes(consumed_notes, now)
    if consumed_notes:
        print(f"  archived {len(consumed_notes)} note(s) → {NOTES_SENT / now.strftime('%Y-%m-%d')}")

    return 0


if __name__ == "__main__":
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    sys.exit(main())
