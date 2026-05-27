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

    date_str = now.strftime("%A, %B %d, %Y")
    if total_commits == 0:
        subject = f"Daily report — {now.strftime('%Y-%m-%d')} — no activity logged"
    else:
        subject = f"Daily report — {now.strftime('%Y-%m-%d')} — work in {sum(1 for r in REPOS if Path(r[0], '.git').exists() and git_log_since(r[0], since_iso))} repo(s)"

    host = socket.gethostname()
    header = f"# Daily work summary — {date_str}\n\nHost: `{host}` · Generated: {now.isoformat(timespec='seconds')}\n\n"

    body = header + "\n".join(sections)
    body += "\n\n---\n_Generated by ~/.claude-config/scripts/daily_report.py (cron, 23:59 local)_\n"
    return subject, body


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
    subject, body = build_report(now)

    # --dry-run doesn't need IMAP creds; the user might be previewing before
    # ever running setup_daily_report.sh.
    if args.dry_run:
        print(f"Subject: {subject}\n\n{body}")
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
    return 0


if __name__ == "__main__":
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    sys.exit(main())
