#!/usr/bin/env python3
"""sync_ha_todo.py — mirror the 👤 open items (waiting on the USER) into HA's
"HA Projects" to-do list (todo.ha_projects), so they can be read and ticked on a phone.

WHY: the user asked (2026-10-21) for that list to fill itself from /open. Memory stays
the ONE record — this list is a generated VIEW, never edited by hand on our side.

SOURCE: open_items.py --json, items marked  ⏳👤 «Short title» [date] text.
OWNERSHIP: an item this script made carries a `key:` line in its description. Only
those are ever changed or removed. An item the user adds by hand has no key and is
LEFT ALONE — it is reported instead, so Claude can turn it into a memory item.

  open in memory, missing from HA      -> add (due date for 🗓️ items)
  title / due changed in memory        -> update
  closed in memory (✅ or marker gone)  -> remove from HA
  TICKED in HA, still open in memory   -> left ticked, REPORTED: Claude closes it in memory
  added by hand in HA                  -> left alone, REPORTED

USAGE:  sync_ha_todo.py        sync; prints only what needs Claude (ticked / hand-added)
        sync_ha_todo.py -v     also print every add / update / remove
        DRY_RUN=1 ...          print the plan, change nothing

CONTRACT: talks only to HA (by name, never IP); token read from ~/.claude.json, never
printed. Silent and exit 0 when HA is unreachable — this runs from hooks.
"""

import hashlib
import json
import os
import subprocess
import sys
import urllib.request

HA = "http://homeassistant.local:8123"
ENTITY = "todo.ha_projects"
OPEN_ITEMS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "open_items.py")
VERBOSE = "-v" in sys.argv[1:]
DRY = os.environ.get("DRY_RUN") == "1"


def token():
    cfg = json.load(open(os.path.expanduser("~/.claude.json")))
    auth = cfg["projects"]["/home/em/development"]["mcpServers"]["home-assistant"]["headers"]["Authorization"]
    return auth.replace("Bearer ", "", 1)


def call(service, data, response=False):
    url = f"{HA}/api/services/todo/{service}" + ("?return_response" if response else "")
    req = urllib.request.Request(url, data=json.dumps(dict(data, entity_id=ENTITY)).encode(),
                                 headers={"Authorization": "Bearer " + TOKEN,
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def key_of(it):
    return hashlib.sha1(f"{it['file']}|{it['title'] or it['text'][:60]}".encode()).hexdigest()[:10]


def summary_of(it):
    if it["title"]:
        return it["title"]
    t = it["text"]
    return t if len(t) <= 90 else t[:89].rstrip() + "…"


def main():
    global TOKEN
    items = json.loads(subprocess.run([sys.executable, OPEN_ITEMS, "--json"],
                                      capture_output=True, text=True, check=True).stdout)
    want = {}
    for it in items:
        if it["user"]:
            k = key_of(it)
            want[k] = dict(summary=summary_of(it),
                           due=it["when"] if it["kind"] == "due" else None,
                           description=f"{it['text']}\n\nmemory: {it['file']}\nkey: {k}")
    try:
        TOKEN = token()
        have = call("get_items", {}, response=True)["service_response"][ENTITY]["items"]
    except Exception:
        return 0                                   # HA down / no token: hooks stay quiet
    ours, theirs = {}, []
    for h in have:
        k = next((ln[5:].strip() for ln in (h.get("description") or "").splitlines()
                  if ln.startswith("key: ")), None)
        (ours.__setitem__(k, h) if k else theirs.append(h))

    plan = []
    for k, w in want.items():
        h = ours.get(k)
        if h is None:
            d = {"item": w["summary"], "description": w["description"]}
            if w["due"]:
                d["due_date"] = w["due"]
            plan.append(("add", w["summary"], "add_item", d))
        elif (h["summary"] != w["summary"] or (h.get("due") or None) != w["due"]
              or (h.get("description") or "") != w["description"]):
            d = {"item": h["uid"], "rename": w["summary"], "description": w["description"]}
            if w["due"]:
                d["due_date"] = w["due"]
            plan.append(("update", w["summary"], "update_item", d))
    for k, h in ours.items():
        if k not in want:
            plan.append(("remove", h["summary"], "remove_item", {"item": [h["uid"]]}))

    for verb, label, service, data in plan:
        if VERBOSE or DRY:
            print(f"  {verb:6} {label}")
        if not DRY:
            call(service, data)

    ticked = [h for k, h in ours.items() if k in want and h.get("status") == "completed"]
    for h in ticked:
        print(f"☑ Ticked on the HA Projects list — close it in memory: {h['summary']}")
    for h in theirs:
        print(f"✎ Added by hand to the HA Projects list — make it a memory item: {h['summary']}"
              + (" (ticked)" if h.get("status") == "completed" else ""))
    if VERBOSE:
        print(f"{len(want)} item(s) waiting on the user; {len(plan)} change(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
