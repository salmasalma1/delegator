"""Run tests/run_all.py as if Team 1's vision package (contracts, nelly_vision) were not installed.

    python tests/run_without_team1.py

It puts tests/no_team1 (a sitecustomize that blocks those imports) first on PYTHONPATH, checks that the block
works, then runs the normal suite. Tests that need the vision package should report SKIP, never FAIL.
"""
import os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
BLOCKER = os.path.join(HERE, "no_team1")

env = {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in (BLOCKER, os.environ.get("PYTHONPATH")) if p)}
probe = subprocess.run([sys.executable, "-c", "import contracts"], env=env, capture_output=True, text=True)
if probe.returncode == 0:
    print("run_without_team1: the block is not active (contracts still imports); not running the suite")
    sys.exit(2)
print("run_without_team1: Team 1's vision package is blocked (contracts, nelly_vision)", flush=True)
sys.exit(subprocess.run([sys.executable, os.path.join(HERE, "run_all.py")], env=env).returncode)
