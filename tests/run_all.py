"""Offline checks: no API key, no network, no screen. Run from the repo root:

    python tests/run_all.py

Each script fakes the model (llm.chat_json) and drives the REAL nodes and routing functions.

A script that cannot run on this machine (for example: Team 1's vision package is not installed) prints a last
line starting with "SKIP" and exits 0. It is counted as skipped, shown in the summary, and does not fail the run.
To check a machine without the vision package, run: python tests/run_without_team1.py
"""
import os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.getcwd()


def classify(returncode: int, stdout: str) -> str:
    """pass | skip | fail, from a test script's exit code and its last line of output."""
    last = stdout.strip().splitlines()[-1] if stdout.strip() else ""
    if returncode == 0 and last.startswith("SKIP"):
        return "skip"
    if returncode == 0 and "OK" in last:
        return "pass"
    return "fail"


def main() -> int:
    counts = {"pass": 0, "skip": 0, "fail": 0}
    for name in sorted(f for f in os.listdir(HERE) if f.startswith("test_")):
        r = subprocess.run([sys.executable, os.path.join(HERE, name)], cwd=ROOT, env={**os.environ, "NELLY_DRY_RUN": "1"}, capture_output=True, text=True)
        kind = classify(r.returncode, r.stdout)
        counts[kind] += 1
        if kind == "skip":
            print(r.stdout.strip().splitlines()[-1])
        else:
            print(("PASS " if kind == "pass" else "FAIL ") + name)
        if kind == "fail":
            print((r.stdout + r.stderr)[-1500:])
    print(f"{counts['pass']} passed, {counts['skip']} skipped, {counts['fail']} failed")
    return 0 if counts["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
