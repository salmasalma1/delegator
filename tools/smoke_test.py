"""
One command that answers three questions about the agent:

    python tools/smoke_test.py           offline  (Qwen stubbed, fake vision fixture)
    python tools/smoke_test.py --real    live     (real Qwen + real vision, needs DASHSCOPE_API_KEY)
    python tools/smoke_test.py --show    read the DB only, no run

    1. THINK  - did the Director produce a plan (nodes)?
    2. ACT    - did every planned node execute and get a verdict?
    3. SAVE   - are checkpoints / steps / audit_log rows on disk, and readable
                from a SEPARATE process after the first one exits (restart proof)?

Exit code 0 = all three proved. Non-zero = the failing one is printed.
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))


def find_root(start):
    """
    The project root is the folder that contains BOTH persistence/ and graph/.

    The script may sit in <root>/tools/ or directly in <root>/ — never assume which.
    """
    d = start
    for _ in range(5):
        if os.path.isdir(os.path.join(d, "persistence")) and os.path.isdir(os.path.join(d, "graph")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.dirname(start)


ROOT = find_root(HERE)
sys.path.insert(0, ROOT)

SMOKE_DIR = os.path.join(ROOT, "smoke")
DB = os.path.join(SMOKE_DIR, "agent.db")
TASK = "Type Hello NELLY in Notepad and save"

# ---------------------------------------------------------------------------
# WHERE THE CHECKPOINT STORE LIVES  -- edit this one line
#
# Point it at the folder that CONTAINS the `checkpointSaver` package.
#     F:\lib\checkpointSaver\db_helpers.py   ->  STORE_PATH = r"F:\lib"
#     F:\delegator\checkpointSaver\...       ->  STORE_PATH = r"F:\delegator"
# Leave it as None to auto-detect (next to this project) or to use NELLY_STORE_PATH.
# ---------------------------------------------------------------------------
STORE_PATH = r"F:\lib"

PASS = FAIL = 0
STORE_ROOT = None

# The delivered set, and the one line each file must contain to prove it landed correctly.
REQUIRED = [
    ("persistence/__init__.py",            None),                      # must be EMPTY
    ("persistence/audit.py",               "def record(state"),
    ("persistence/checkpoint_adapter.py",  "def _fill_missing_rows"),
    ("persistence/db_shim.py",             "def save_checkpoint"),
    ("persistence/schema.sql",             "CREATE TABLE IF NOT EXISTS checkpoints"),
    ("graph/nodes/verify.py",              "step_number"),
    ("graph/nodes/delegate.py",            "latency_ms"),
    ("graph/builder.py",                   "_checkpointer"),
    ("graph/state.py",                     "latency_ms"),
]
# easy mix-up: graph/nodes/__init__.py content pasted into persistence/__init__.py
WRONG_MARKERS = ("from .director", "from .delegate", "from .verify", "__all__")

# Files we never ship but that MUST exist, or the imports below them explode.
# graph/nodes/__init__.py imports every sibling, so a missing one breaks the whole graph.
# (graph/ and graph/nodes/ also have __init__.py files; graph/ works as a namespace
#  package even without one, so it is not required here.)
SIBLINGS = [
    "graph/nodes/__init__.py",
    "graph/nodes/director.py",
    "graph/nodes/delegate.py",
    "graph/nodes/escalate.py",
    "graph/nodes/verify.py",
    "graph/subgraphs/app_subgraph.py",
    # imported by app_subgraph / verify at import time — a missing one is a traceback,
    # not a verdict about the checkpoint store. bootstrap_missing.py writes these.
    "vision/__init__.py",
    "vision/adapter.py",
    "vision/ground.py",
    "vision/validate.py",
    "vision/understand.py",
    "verifier.py",
    "config.py",
    "schemas/vision/02_VisionResult.schema.json",
    "schemas/safety/02_SafetyDecision.schema.json",
]


def check_install(root):
    """
    Verify the copied files are the right files, in the right places.
    Catches the classic file-by-file copy mistakes before they turn into a traceback.
    """
    banner(0, "FILES  (are the delivered files in place?)")
    print(f"  root    : {root}")
    problems = []
    for rel, marker in REQUIRED:
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            print(f"  MISSING {rel}")
            problems.append(rel)
            continue
        if marker is None:                       # must be empty
            size = os.path.getsize(path)
            body = open(path, encoding="utf-8", errors="replace").read().strip()
            if body:
                bad = [m for m in WRONG_MARKERS if m in body]
                hint = ("  <- this looks like graph/nodes/__init__.py content"
                        if bad else "")
                print(f"  WRONG   {rel}  (must be EMPTY, it has {size} bytes){hint}")
                problems.append(rel)
            else:
                print(f"  ok      {rel}  (empty)")
            continue
        body = open(path, encoding="utf-8", errors="replace").read()
        if marker in body:
            print(f"  ok      {rel}")
        else:
            print(f"  WRONG   {rel}  (expected to contain: {marker!r})")
            problems.append(rel)

    missing_sibs = [rel for rel in SIBLINGS
                    if rel not in problems and not os.path.exists(os.path.join(root, rel))]
    for rel in missing_sibs:
        print(f"  MISSING {rel}   (imported by graph/, must exist)")
    problems += missing_sibs

    check("all delivered files are in place", not problems, ", ".join(problems))
    return not problems


def _reset_backend():
    """Drop a cached backend so a later import resolves against the final sys.path."""
    import sys as _s
    for name in list(_s.modules):
        if name.startswith("persistence") or name.startswith("checkpointSaver"):
            del _s.modules[name]



def ensure_store_path():
    """
    Make `import checkpointSaver` work, without the user having to set PYTHONPATH.

    Only REAL locations are auto-added. Test fixtures are never added here — if a fixture
    is on the path it can only be because the caller asked for it explicitly, and the
    banner will show the module's real file so there is no doubt whose code ran.
    """
    global STORE_ROOT
    candidates = [
        os.getenv("NELLY_STORE_PATH", ""),     # env var wins
        STORE_PATH or "",                      # the constant at the top of this file
        ROOT,                                  # <root>/checkpointSaver
        os.path.dirname(ROOT),                 # <project>/checkpointSaver beside the root
        os.getcwd(),
    ]
    print(f"  looking : {[c for c in candidates if c]}")

    found = []
    for c in candidates:
        if not c:
            continue
        pkg = os.path.join(c, "checkpointSaver")
        if os.path.isdir(pkg) and c not in found:
            found.append(c)

    if not found:
        return None

    if len(found) > 1:
        print("  NOTE: more than one checkpointSaver package was found:")
        for c in found:
            print(f"          {os.path.join(c, 'checkpointSaver')}")
        print("        Using the first one. Set NELLY_STORE_PATH to force a different one.")

    STORE_ROOT = found[0]
    if STORE_ROOT not in sys.path:
        sys.path.insert(0, STORE_ROOT)
    return STORE_ROOT


def vision_identity():
    """Whose vision is actually running: the real package, or our fallback stub."""
    try:
        from graph.subgraphs import app_subgraph as sub
        if not sub.HAS_REAL_VISION:
            return "fallback", None
        mod = sys.modules.get("nelly_vision.perception") or sys.modules.get("nelly_vision")
        f = getattr(mod, "__file__", "?")
        # the offline test fixture is NOT the vision module's code
        return ("fixture" if "fake_nelly_vision" in (f or "") else "nelly_vision"), f
    except Exception as e:                                        # noqa: BLE001
        return "error", f"{type(e).__name__}: {e}"


def _fingerprint(path):
    """size + sha1 of the store's db_helpers.py — proves WHICH copy ran."""
    import hashlib
    try:
        blob = open(path, "rb").read()
        return f"{len(blob)} bytes, sha1 {hashlib.sha1(blob).hexdigest()[:12]}"
    except OSError:
        return "?"


def store_identity():
    """(backend, module file) — the proof of WHOSE code is running."""
    from persistence import checkpoint_adapter as ad
    mod = ad._store()
    if mod is None:
        return "shim", None
    return "store", getattr(mod, "__file__", "?")


PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"   -> {detail}" if detail else ""))
    return cond


def banner(n, title):
    print()
    print("=" * 62)
    print(f"  {n}. {title}")
    print("=" * 62)


# --------------------------------------------------------------------------
# offline mode: stub only the LLM, keep every other line of real code
# --------------------------------------------------------------------------
def _stub_llm():
    sys.path.insert(0, os.path.join(ROOT, "tests", "fake_nelly_vision"))
    os.environ["NELLY_VERIFIER"] = "rule"          # deterministic, no network
    import reasoning

    class StubProvider:
        def plan(self, task, vision_ctx=None, memory_ctx=None):
            app = (vision_ctx or {}).get("app") or "Notepad"
            return [
                {"node": f"{app}: type text", "flag": "text visible in editor", "app": app,
                 "steps": ["type Hello NELLY"]},
                {"node": f"{app}: open Edit", "flag": "Edit menu is open", "app": app,
                 "steps": ["click Edit"]},
            ]

    reasoning.QwenProvider = StubProvider
    import planner
    planner.get_reasoning_provider = lambda: StubProvider()


# --------------------------------------------------------------------------
def run_agent(real: bool):
    if not real:
        _stub_llm()

    sys.path.insert(0, ROOT)
    from graph.builder import build_graph
    from gateway.gateway import normalize_task
    from persistence import audit

    from persistence import checkpoint_adapter as ad
    backend, modfile = store_identity()
    print(f"  backend : {backend}" + (f"  <- {modfile}" if modfile else ""))
    if modfile and STORE_ROOT and not os.path.abspath(modfile).startswith(
            os.path.abspath(os.path.join(STORE_ROOT, "checkpointSaver"))):
        print(f"  WARNING : a DIFFERENT checkpointSaver copy was imported than the one found.")
        print(f"            imported : {modfile}")
        print(f"            expected : {os.path.join(STORE_ROOT, 'checkpointSaver')}")
        print(f"            Fix with: $env:NELLY_STORE_PATH=\"<folder containing checkpointSaver>\"")
    print(f"  db      : {audit.db_path()}")

    from graph.subgraphs import app_subgraph as sub
    v_kind, v_file = vision_identity()
    print(f"  vision  : {v_kind}" + (f"  <- {v_file}" if v_file else ""))
    if v_kind != "nelly_vision":
        print("            (the vision package is NOT importable -> the worker uses the fallback")
        print("             stub. Nothing of the vision module's code was exercised.)")

    # The backend decides the file, not us: the store resolves BASE_DIR/agent.db itself.
    be = audit._load()
    try:
        actual_db = be.init_db()
    except TypeError:
        actual_db = be.init_db(audit.db_path())
    global DB
    DB = actual_db or DB
    print(f"  real db : {DB}")

    graph = build_graph()
    init = normalize_task(TASK, source="text",
                          task_id=str(uuid.uuid4()), session_id=str(uuid.uuid4()))
    if not real:
        init["vision_scenario"] = "ok"
    cfg = {"configurable": {"thread_id": init["session_id"]}}
    for _ in graph.stream(init, config=cfg):
        pass
    final = graph.get_state(cfg).values
    return final


def report_think(final):
    banner(1, "DID IT THINK?  (Director -> plan)")
    nodes = final.get("nodes") or []
    print(f"  goal    : {final.get('goal')}")
    print(f"  plan    : {len(nodes)} node(s)")
    for i, n in enumerate(nodes, 1):
        print(f"            {i}. {n.get('node')}  [flag: {n.get('flag')}]")
    check("a plan was produced", len(nodes) > 0, "nodes is empty")
    check("every node has a checkable flag", all(n.get("flag") for n in nodes))


def report_act(final):
    banner(2, "DID IT MOVE?  (delegate -> execute -> verify each node)")
    subs = final.get("sub_results") or []
    verifs = final.get("verifications") or []
    print(f"  executed : {len(subs)} node(s)")
    for i, s in enumerate(subs, 1):
        steps = s.get("steps_done") or []
        print(f"            {i}. status={s.get('status'):<12} app={s.get('app')} "
              f"vision={s.get('vision_source')} steps={len(steps)}")
    print(f"  verdicts : {len(verifs)}")
    for v in verifs:
        print(f"            - {v.get('node')}: passed={v.get('passed')} "
              f"via={v.get('method')} ({v.get('reason')})")
    check("nodes actually executed", len(subs) > 0, "sub_results is empty")
    check("every executed node was verified", len(verifs) >= len(subs) - 0,
          f"{len(subs)} executed vs {len(verifs)} verdicts")
    check("graph reached a terminal status",
          final.get("status") in ("completed", "failed", "escalated", "incomplete"),
          str(final.get("status")))
    print(f"  final    : {final.get('status')}   summary={final.get('verification_summary')}")


def report_save(final):
    banner(3, "DID IT SAVE?  (rows on disk)")
    print(f"  looking in: {DB}")
    if not os.path.exists(DB):
        check("database file exists", False, DB)
        return
    conn = sqlite3.connect(DB)
    counts = {}
    for t in ("checkpoints", "steps", "audit_log"):
        try:
            counts[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except sqlite3.Error as e:
            counts[t] = f"ERR {e}"
    print(f"  file     : {DB}")
    print(f"  rows     : {counts}")
    check("checkpoints rows written", isinstance(counts["checkpoints"], int) and counts["checkpoints"] > 0)
    check("steps rows written", isinstance(counts["steps"], int) and counts["steps"] > 0)
    check("audit_log rows written", isinstance(counts["audit_log"], int) and counts["audit_log"] > 0)

    row = conn.execute(
        "SELECT checkpoint_id, session_id, step_number, created_at FROM checkpoints "
        "ORDER BY created_at DESC, rowid DESC LIMIT 1").fetchone()
    if row:
        print(f"  latest   : id={row[0][:8]}... session={row[1][:8]}... "
              f"step_number={row[2]} at={row[3]}")
    for r in conn.execute("SELECT step_id, description, app, status, bbox_norm, confidence, source "
                          "FROM steps ORDER BY id LIMIT 5"):
        print(f"    step   : {r}")
    for r in conn.execute("SELECT safety_decision, latency_ms FROM audit_log ORDER BY id LIMIT 5"):
        print(f"    audit  : {r}")
    conn.close()


def report_restart(session_id):
    banner(4, "RESTART PROOF  (a fresh process reads it back)")
    # Path order matters when two copies of checkpointSaver exist: ROOT first, then the
    # store root on top, so the child imports exactly what this process imported.
    path_setup = "import sys;sys.path.insert(0,%r);" % ROOT
    if STORE_ROOT:
        path_setup += "sys.path.insert(0,%r);" % STORE_ROOT
    code = (
        "import os,json;" + path_setup +
        "from persistence import audit;"
        "s=audit.resume(%r);"
        "print(json.dumps({'found': s is not None,"
        "'status': (s or {}).get('status'),"
        "'nodes': len((s or {}).get('nodes') or []),"
        "'db': audit.db_path()}, default=str))"
    ) % (session_id,)
    env = dict(os.environ, NELLY_PERSIST="1", NELLY_DB=DB)
    if STORE_ROOT:
        env["NELLY_STORE_PATH"] = STORE_ROOT      # the child must resolve the same store
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    print("  " + (out.stdout.strip() or out.stderr.strip()[:400]))
    ok = False
    try:
        got = json.loads(out.stdout.strip().splitlines()[-1])
        ok = got["found"] and got["nodes"] > 0
        print(f"  resumed  : status={got['status']} nodes={got['nodes']} db={got['db']}")
    except Exception:
        pass
    check("a new process can resume the run from the DB", ok)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", action="store_true", help="real Qwen + real vision")
    ap.add_argument("--show", action="store_true", help="read the DB only")
    ap.add_argument("--fresh", action="store_true", help="delete smoke/agent.db first (default)")
    ap.add_argument("--require-store", action="store_true",
                    help="abort unless the checkpoint store's own code is what runs")
    ap.add_argument("--require-vision", action="store_true",
                    help="abort unless the REAL vision package is what runs")
    a = ap.parse_args()

    os.makedirs(SMOKE_DIR, exist_ok=True)
    os.environ["NELLY_PERSIST"] = "1"
    os.environ["NELLY_DB"] = DB

    _reset_backend()
    os.environ.setdefault("NELLY_VERIFIER", "rule")   # deterministic unless overridden
    if not check_install(ROOT):
        print()
        print("  ABORT: fix the files above first (see the ok / WRONG / MISSING lines).")
        print("         Nothing was run — a traceback here would tell you nothing about the agent.")
        return 3

    ensure_store_path()

    from persistence import checkpoint_adapter as _ad
    _backend, _file = store_identity()
    _ad._warned.discard("x")
    print(f"  store   : {_backend.upper()}" + (f"  <- {_file}" if _file else ""))
    if _file:
        print(f"            {_fingerprint(_file)}")

    if _backend == "shim":
        print("            (the store package is NOT on the path — nothing of the store's code")
        print("             was exercised. Point NELLY_STORE_PATH at the folder that CONTAINS")
        print("             checkpointSaver, and run again.)")
    if a.require_vision:
        v_kind, v_file = vision_identity()
        print(f"  vision  : {v_kind}" + (f"  <- {v_file}" if v_file else ""))
        if v_kind != "nelly_vision":
            print()
            print("  ABORT: --require-vision was given, but the real vision package did not load.")
            print("         Set NELLY_VISION_PATH to the folder that CONTAINS nelly_vision,")
            print("         or drop nelly_vision\\ next to the project, then run again.")
            return 2

    if a.require_store and _backend != "store":
        print()
        print("  ABORT: --require-store was given but the store was not importable.")
        print("         This run would have proved nothing about the store's database.")
        return 2

    if a.show:
        report_save({})
        return 0 if FAIL == 0 else 1

    if os.path.exists(DB):
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(DB + suffix)
            except OSError:
                pass

    print(f"  mode    : {'LIVE (real Qwen + vision)' if a.real else 'offline (LLM stubbed, vision fixture)'}")
    print(f"  task    : {TASK}")

    final = run_agent(a.real)
    report_think(final)
    report_act(final)
    report_save(final)
    report_restart(final.get("session_id"))

    print()
    print("=" * 62)
    print(f"  {PASS} passed, {FAIL} failed")
    print("=" * 62)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
