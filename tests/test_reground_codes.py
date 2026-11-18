import os as _o0; _o0.environ.setdefault("NELLY_DRY_RUN", "1")  # tests never move the real mouse
"""wrong_window (Team 1's focus guard) is a regrounding refusal, like stale: the worker reports needs_regrounding,
not failed. Fakes only: fake screen, fake model, fake executor; nothing is clicked or typed."""
import os
import sys
import types

sys.path.insert(0, ".")
os.environ["NELLY_PERSIST"] = "0"
os.environ.pop("NELLY_LIVE_INPUT", None)
import llm                                                          # noqa: E402
import graph.subgraphs.app_subgraph as A                           # noqa: E402

ELS = [{"id": "e1", "type": "input", "text": "", "bbox_norm": [0.1, 0.2, 0.5, 0.5], "confidence": .9,
        "clickable": True, "source": "fast"}]
CTX = {"app": "Notepad", "elements": ELS, "needs_review": False, "vision_source": "t", "warnings": [],
       "quality": {"score": .9, "reasons": []}, "status": "ok", "window_title": "w"}
A.perceive_screen = lambda app, target, screenshot=None, scenario=None: CTX
llm.available = lambda: True


def fake_executor(status, code):
    calls = []

    def execute(req):
        calls.append(req)
        return {"action_id": req["action_id"], "task_id": req["task_id"], "status": status,
                "verification_status": "not_verified", "strategy_used": "fake", "duration_ms": 0,
                "output": {"reject_code": code, "dry_run": False}, "error": f"{code}: fake refusal",
                "screenshot_after_ref": None}
    return types.SimpleNamespace(execute=execute, live_requested=lambda: False, calls=calls)


def run_with(status, code):
    A.desktop_adapter, A.HAS_ADAPTER = fake_executor(status, code), True
    llm.chat_json = lambda s, u, **k: {"action": "type", "element_id": "e1", "text": "hello", "why": "write"}
    return A.run_app_subgraph("Notepad", "write hello", ["type hello"], "t", flag="hello visible")


assert "wrong_window" in A.REGROUND_CODES and "stale" in A.REGROUND_CODES

r = run_with("blocked", "wrong_window")
assert r["status"] == "needs_regrounding" and "wrong_window" in r["error"], r
# F4: the worker looks again (fresh capture + decision) up to NELLY_REGROUND_RETRIES times, then escalates
assert len(A.desktop_adapter.calls) == 1 + A.reground_retries(), len(A.desktop_adapter.calls)
assert r["steps_done"] == [], r                                     # a refused action is never a done step

r = run_with("blocked", "stale")                                    # unchanged: stale is still a regrounding code
assert r["status"] == "needs_regrounding", r

r = run_with("blocked", "no_application")                           # unchanged: other refusals still fail
assert r["status"] == "failed", r

r = run_with("cancelled", "wrong_window")                           # unchanged: a user stop stays cancelled
assert r["status"] == "cancelled", r

print("test_reground_codes OK")
