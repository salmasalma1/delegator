"""Offline checks: no API key, no network, no screen. Run from the repo root:

    python tests/run_all.py

Each script fakes the model (llm.chat_json) and drives the REAL nodes and routing functions.
"""
import os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.getcwd()
ok = True
for name in sorted(f for f in os.listdir(HERE) if f.startswith("test_")):
    r = subprocess.run([sys.executable, os.path.join(HERE, name)], cwd=ROOT, env={**os.environ, "NELLY_DRY_RUN": "1"}, capture_output=True, text=True)
    good = r.returncode == 0 and "OK" in r.stdout.splitlines()[-1:][0] if r.stdout.strip() else False
    print(("PASS " if good else "FAIL ") + name)
    if not good:
        ok = False
        print((r.stdout + r.stderr)[-1500:])
sys.exit(0 if ok else 1)
