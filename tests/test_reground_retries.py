import os as _o0; _o0.environ.setdefault("NELLY_DRY_RUN", "1")  # tests never move the real mouse
"""F4: on stale / window_moved / window_resized / window_minimized / window_gone / wrong_window the worker looks
again (a fresh capture and a fresh decision), at most NELLY_REGROUND_RETRIES times (default 2), then escalates.
Other refusals and Safety decisions are never retried. Fakes only: nothing is clicked."""
import os
import sys
import types

sys.path.insert(0, ".")
os.environ["NELLY_PERSIST"] = "0"
os.environ.pop("NELLY_LIVE_INPUT", None)
os.environ.pop("NELLY_REGROUND_RETRIES", None)
import llm                                                          # noqa: E402
import graph.subgraphs.app_subgraph as A                           # noqa: E402

SAVE = {"id": "e1", "type": "button", "text": "Save", "bbox_norm": [.1, .1, .2, .2], "confidence": .9,
        "clickable": True, "source": "fast"}
CTX = {"app": "Notepad", "elements": [SAVE], "all_elements": [SAVE], "needs_review": False, "vision_source": "t",
       "warnings": [], "quality": {"score": .9, "reasons": []}, "status": "ok", "window_title": "w"}
looks = []
A.perceive_screen = lambda app, target, screenshot=None, scenario=None: looks.append(target) or CTX


def executor(*answers):
    """Returns the scripted (status, reject_code) answers in order; the last one repeats."""
    calls = []

    def execute(req):
        status, code = answers[min(len(calls), len(answers) - 1)]
        calls.append(req)
        return {"action_id": req["action_id"], "task_id": req["task_id"], "status": status,
                "verification_status": "not_verified", "strategy_used": "fake", "duration_ms": 0,
                "output": {"reject_code": code, "dry_run": False}, "error": f"{code}: fake" if code else None,
                "screenshot_after_ref": None}
    return types.SimpleNamespace(execute=execute, live_requested=lambda: False, calls=calls)


def steps_mode(*answers):
    looks.clear()
    A.desktop_adapter, A.HAS_ADAPTER = executor(*answers), True
    llm.available = lambda: False                                    # no model: one action per step
    return A.run_app_subgraph("Notepad", "save", ["click Save"], "t", flag="saved")


def loop_mode(*answers):
    looks.clear()
    A.desktop_adapter, A.HAS_ADAPTER = executor(*answers), True
    llm.available = lambda: True
    llm.chat_json = lambda s, u, **k: {"action": "click", "element_id": "e1", "why": "save"}
    return A.run_app_subgraph("Notepad", "save", ["click Save"], "t", flag="saved", max_actions=1)


for run in (steps_mode, loop_mode):
    # always stale: 1 try + 2 re-looks (the default), then escalate
    r = run(("blocked", "stale"))
    assert len(A.desktop_adapter.calls) == 3, (run.__name__, len(A.desktop_adapter.calls))
    assert len(looks) == 3, (run.__name__, looks)                    # a NEW capture before every try
    assert r["status"] == "needs_regrounding" and "looked again 2" in r["error"], (run.__name__, r)
    assert r.get("relooks") == ["stale", "stale"], r
    # the bound is configurable and always respected
    for n, expected in (("0", 1), ("1", 2), ("5", 6)):
        os.environ["NELLY_REGROUND_RETRIES"] = n
        run(("blocked", "wrong_window"))
        assert len(A.desktop_adapter.calls) == expected, (run.__name__, n, len(A.desktop_adapter.calls))
    os.environ.pop("NELLY_REGROUND_RETRIES")
    # refused once, then it works: the step completes after one re-look
    r = run(("blocked", "window_moved"), ("success", None))
    assert len(A.desktop_adapter.calls) == 2 and r.get("relooks") == ["window_moved"], (run.__name__, r)
    assert r["status"] in ("completed", "failed"), r                 # loop mode ends on max_actions=1
    assert len(r["steps_done"]) == 1, r
    # every listed code is retried
    for code in ("stale", "window_moved", "window_resized", "window_minimized", "window_gone", "wrong_window"):
        run(("blocked", code))
        assert len(A.desktop_adapter.calls) == 3, (run.__name__, code)
    # other refusals are NOT retried
    for status, code in (("blocked", "no_application"), ("failed", "executor_error"), ("cancelled", "stale")):
        r = run((status, code))
        assert len(A.desktop_adapter.calls) == 1, (run.__name__, code, len(A.desktop_adapter.calls))

# a Safety "no" is final: never retried, never sent
os.environ["NELLY_APP_ALLOWLIST"] = "Chrome"                         # Notepad now always asks; no approver bound
r = steps_mode(("blocked", "stale"))
assert len(A.desktop_adapter.calls) == 0 and r["status"] == "needs_approval", r
os.environ.pop("NELLY_APP_ALLOWLIST")

print("test_reground_retries OK")
