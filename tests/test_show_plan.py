import os as _o0; _o0.environ.setdefault("NELLY_DRY_RUN", "1")
import sys, io, contextlib
sys.path.insert(0, ".")
import run
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    run._progress({"director": {"nodes": [{"id": "n1", "app": "Notepad", "node": "open Notepad", "flag": "Notepad window visible", "steps": ["open it"]}]}})
    run._progress({"plan_check": {"plan_verdict": {"ok": True, "method": "llm"}}})
    run._progress({"delegate": None})
out = buf.getvalue()
assert "PLAN:" in out and "done when: Notepad window visible" in out and "plan check: ok=True" in out and "-> delegate" in out, out
print("show plan OK")
