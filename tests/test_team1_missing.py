"""Delegator WITHOUT Team 1's vision package (contracts, nelly_vision). Needs no vision package itself.

- the default executor (execution/desktop_adapter.py) works and never imports execution.team1 or the bridge;
- the bridge returns a clear failure, and NELLY_EXECUTOR=team1 stops with a clear message (no traceback);
- tests/test_team1_bridge.py reports SKIP, and tests/run_all.py counts SKIP apart from PASS and FAIL.
Dry run only: NELLY_LIVE_INPUT is removed, pyautogui is never loaded, nothing is clicked or typed.
"""
import importlib.util
import os
import subprocess
import sys

os.environ.pop("NELLY_LIVE_INPUT", None)
os.environ["NELLY_DRY_RUN"] = "1"
os.environ.pop("NELLY_EXECUTOR", None)
sys.path.insert(0, ".")
sys.modules["contracts"] = None          # any import of these now raises ImportError, as if not installed
sys.modules["nelly_vision"] = None

HERE = os.path.dirname(os.path.abspath(__file__))
BLOCKER = os.path.join(HERE, "no_team1")
MSG = "NELLY_EXECUTOR=team1 needs Team 1's vision package (contracts, nelly_vision) installed"
team1_loaded = lambda: sorted(m for m in sys.modules if m.startswith("execution.team1"))   # noqa: E731

# 1) default path: the worker imports and runs our interim executor, and execution.team1* is never imported
import graph.subgraphs.app_subgraph as A                           # noqa: E402
from execution import desktop_adapter as X                         # noqa: E402
X._load_pyautogui = lambda: None                                   # belt and braces: no pyautogui at all
assert A.desktop_adapter is X, A.desktop_adapter
req = {"action_id": "a1", "task_id": "t1", "action_type": "press", "parameters": {"keys": ["ctrl", "s"]},
       "application": "Notepad", "target_element_id": None}
r = A._act(req)
assert r["status"] == "success" and r["output"]["dry_run"] is True and r["action_id"] == "a1", r
assert team1_loaded() == [], team1_loaded()

# 2) the bridge (if someone calls it anyway): clear failure, no traceback, still nothing from execution.team1
from execution import team1_bridge as B                            # noqa: E402
assert B.available() is False
r = B.execute({**req, "action_id": "a2"})
assert r["status"] == "failed" and r["reject_code"] == "team1_unavailable" and r["error"] == MSG, r
assert r["action_id"] == "a2" and r["output"]["reject_code"] == "team1_unavailable", r
try:
    B.require()
    raise AssertionError("require() did not stop")
except B.Team1Unavailable as e:
    assert str(e) == MSG, e
assert team1_loaded() == ["execution.team1_bridge"], team1_loaded()   # the bridge only, never execution.team1.*

# 3) in a fresh process with Team 1 blocked (tests/no_team1): the switch stops with the message, the default works
env = {k: v for k, v in os.environ.items() if k not in ("NELLY_LIVE_INPUT", "NELLY_EXECUTOR")}
env["PYTHONPATH"] = os.pathsep.join(p for p in (BLOCKER, env.get("PYTHONPATH")) if p)
py = lambda code, **extra: subprocess.run([sys.executable, "-c", code], env={**env, **extra},   # noqa: E731
                                          capture_output=True, text=True)
p = py("import contracts")
assert p.returncode != 0 and "blocked by tests/no_team1" in p.stderr, p.stderr
p = py("import graph.subgraphs.app_subgraph", NELLY_EXECUTOR="team1")
assert p.returncode == 1 and p.stderr.strip() == MSG, (p.returncode, p.stderr)
assert "Traceback" not in p.stderr, p.stderr
p = py("import sys, graph.subgraphs.app_subgraph as a; "
       "print(a.desktop_adapter.__name__, [m for m in sys.modules if m.startswith('execution.team1')])")
assert p.returncode == 0 and p.stdout.strip() == "execution.desktop_adapter []", p.stdout + p.stderr

# 4) the bridge test reports SKIP (exit 0) when Team 1 is not installed
p = subprocess.run([sys.executable, os.path.join(HERE, "test_team1_bridge.py")], env=env, capture_output=True, text=True)
last = p.stdout.strip().splitlines()[-1] if p.stdout.strip() else ""
assert p.returncode == 0 and last == "SKIP test_team1_bridge.py: Team 1 vision package (contracts) is not installed", \
    (p.returncode, p.stdout, p.stderr)

# 5) run_all counts SKIP as its own outcome
spec = importlib.util.spec_from_file_location("run_all", os.path.join(HERE, "run_all.py"))
RA = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RA)                                         # main() runs only as a script
assert RA.classify(0, "x\nSKIP test_x.py: reason\n") == "skip"
assert RA.classify(0, "test_x OK") == "pass"
assert RA.classify(1, "SKIP test_x.py: reason") == "fail"           # a SKIP line with a non-zero exit is a failure
assert RA.classify(0, "") == "fail" and RA.classify(0, "done") == "fail"

print("test_team1_missing OK")
