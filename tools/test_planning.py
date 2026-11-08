"""
test_planning — does the BRAIN actually understand and decompose?

This tests the planner alone: no graph, no worker, no database, no vision.
One question only: when a task arrives, does the model produce a plan that the
rest of the system can actually execute?

    python tools/test_planning.py               # all tasks below, real Qwen
    python tools/test_planning.py --task "..."  # one task of your own
    python tools/test_planning.py --offline     # no API key: check the checker itself

For every task it prints the plan, then audits it against the rules the Director's
own prompt promises (one app per node, 1-3 steps per node) plus the things that
break the loop downstream:

  * valid JSON list, every node has node/flag/app/steps
  * the flag is CHECKABLE (not "done", "ok", "success" — the rule verifier rejects those)
  * one app per node, 1-3 steps per node
  * no duplicate consecutive nodes
  * the apps the task names actually appear in the plan
  * order matches the task (a send must not be planned before its search)

Exit code 0 = every task produced an executable plan.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

PASS = FAIL = 0
UNCHECKABLE = {"done", "ok", "success", "completed", "finished", "task completed",
               "task done", "n/a", "none"}

TASKS = [
    ("single app, single step",
     "Open Notepad and type Hi NELLY"),
    ("multi-app, dependent",
     "Open Spotify, search for the song Imagine, copy its share link, then send it on WhatsApp"),
    ("explorer + notepad",
     "Create a folder called NELLY in File Explorer, then open Notepad and save a file named notes.txt inside it"),
    ("ambiguous / missing parameter",
     "Send the file to the team"),
    ("unknown app",
     "Open Blender and render the current scene at 1080p"),
]


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"   -> {detail}" if detail else ""))
    return cond


# --------------------------------------------------------------------------
# the audit
# --------------------------------------------------------------------------
def audit(task, nodes):
    """Return a list of problems with the plan. Empty list = the loop can run it."""
    problems = []

    if not isinstance(nodes, list) or not nodes:
        return ["plan is empty or not a list"]

    for i, n in enumerate(nodes, 1):
        if not isinstance(n, dict):
            problems.append(f"node {i} is not an object")
            continue
        for key in ("node", "flag", "app", "steps"):
            if not n.get(key):
                problems.append(f"node {i} missing '{key}'")
        steps = n.get("steps")
        if isinstance(steps, str):
            problems.append(f"node {i}: steps is a bare string (would iterate char by char)")
        elif isinstance(steps, list) and not (1 <= len(steps) <= 3):
            problems.append(f"node {i}: {len(steps)} steps (prompt promises 1-3)")

        flag = str(n.get("flag") or "").strip().lower()
        if flag in UNCHECKABLE:
            problems.append(f"node {i}: flag {flag!r} is not checkable — verify would reject it")
        elif len(flag) < 6:
            problems.append(f"node {i}: flag {flag!r} is too vague to check")

    apps = [str(n.get("app") or "").strip().lower() for n in nodes if isinstance(n, dict)]

    # duplicate consecutive identical nodes
    seen = [str(n.get("node")) for n in nodes if isinstance(n, dict)]
    for a, b in zip(seen, seen[1:]):
        if a == b:
            problems.append(f"duplicate consecutive node: {a!r}")

    # the task's own words must show up somewhere
    low = task.lower()
    named = [w for w in ("spotify", "whatsapp", "notepad", "explorer", "blender")
             if w in low]
    for w in named:
        if not any(w in a for a in apps) and not any(w in str(n.get("node", "")).lower()
                                                     for n in nodes if isinstance(n, dict)):
            problems.append(f"task names {w!r} but no node mentions it")

    # ordering: a send/copy must not be planned before its search/open
    def first_index(*words):
        for i, s in enumerate(seen):
            sl = str(s).lower()
            if any(w in sl for w in words):
                return i
        return None

    search_i = first_index("search", "find", "open", "play")
    send_i = first_index("send", "share", "type")
    if search_i is not None and send_i is not None and send_i < search_i:
        problems.append("a send/share node is planned before the search/open node")

    return problems


def show(nodes):
    if not isinstance(nodes, list):
        print(f"    (not a list: {type(nodes).__name__})")
        return
    for i, n in enumerate(nodes, 1):
        if not isinstance(n, dict):
            print(f"    {i}. <not an object>")
            continue
        print(f"    {i}. [{n.get('app')}] {n.get('node')}")
        print(f"       flag : {n.get('flag')}")
        for s in (n.get("steps") or []):
            print(f"       - {s}")


# --------------------------------------------------------------------------
# offline: prove the auditor itself works, using two canned plans
# --------------------------------------------------------------------------
GOOD = [
    {"node": "Spotify: search Imagine", "flag": "Imagine appears in the results list",
     "app": "Spotify", "steps": ["click search", "type Imagine", "press Enter"]},
    {"node": "WhatsApp: send the link", "flag": "the message appears in the chat with the contact",
     "app": "WhatsApp", "steps": ["paste the link", "press Enter"]},
]
BAD = [
    {"node": "do the task", "flag": "done", "app": "Spotify", "steps": "click"},
    {"node": "do the task", "flag": "done", "app": "Spotify", "steps": []},
]


def run_offline():
    print("  offline mode: no model call. Proving the auditor accepts a good plan")
    print("  and rejects a bad one.\n")
    task = "Open Spotify, search Imagine, then send it on WhatsApp"

    good = audit(task, GOOD)
    print("  candidate plan A:")
    show(GOOD)
    check("the auditor accepts a well-formed plan", not good, str(good))
    print()

    bad = audit(task, BAD)
    print("  candidate plan B:")
    show(BAD)
    check("the auditor rejects a bad plan", bool(bad), "it accepted an empty plan")
    for p in bad:
        print(f"       caught: {p}")


def run_real(task, label):
    print("=" * 68)
    print(f"  {label}")
    print(f"  task: {task}")
    print("=" * 68)

    import reasoning
    provider = reasoning.get_reasoning_provider()
    print(f"  model: {getattr(provider, 'model', '?')}")

    try:
        nodes = provider.plan(task)
    except Exception as e:                                        # noqa: BLE001
        check("the brain answered", False, f"{type(e).__name__}: {e}")
        return

    show(nodes)
    problems = audit(task, nodes)
    print()
    check(f"{len(nodes) if isinstance(nodes, list) else 0} node(s) produced", bool(nodes))
    check("the plan is executable by the loop", not problems,
          "; ".join(problems[:4]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", action="append", default=None,
                    help="a task of your own (repeatable)")
    ap.add_argument("--offline", action="store_true",
                    help="no API key: check the auditor itself")
    ap.add_argument("--json", action="store_true", help="dump raw plans as JSON")
    a = ap.parse_args()

    print("=" * 68)
    print("  BRAIN TEST — planning only (no graph, no worker, no database)")
    print("=" * 68)

    if a.offline:
        run_offline()
    else:
        key = os.getenv("DASHSCOPE_API_KEY", "")
        if not key or "PUT_YOUR_KEY" in key or len(key) < 30:
            print()
            print("  The API key is missing or still the placeholder.")
            print("  Put a real key in delegator/.env :  DASHSCOPE_API_KEY=sk-...")
            print("  Then run this again. To check the tool itself: --offline")
            return 2

        for label, task in (TASKS if not a.task else
                            [(f"custom {i}", t) for i, t in enumerate(a.task, 1)]):
            run_real(task, label)
            print()

    print("=" * 68)
    print(f"  {PASS} passed, {FAIL} failed")
    print("=" * 68)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
