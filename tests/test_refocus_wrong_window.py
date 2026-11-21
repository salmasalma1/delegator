import os as _o0; _o0.environ.setdefault("NELLY_DRY_RUN", "1")  # tests never move the real mouse
"""When another window was in front at the look (target_outside_window), the worker asks for the app's window
(focus_window, through Safety), looks again, and only then clicks. If the app never comes forward it stops after
NELLY_REGROUND_RETRIES re-looks. Fakes only: nothing is clicked."""
import os
import sys
import types

sys.path.insert(0, ".")
os.environ["NELLY_PERSIST"] = "0"
os.environ.pop("NELLY_LIVE_INPUT", None)
os.environ.pop("NELLY_REGROUND_RETRIES", None)
import llm                                                          # noqa: E402
import graph.subgraphs.app_subgraph as A                           # noqa: E402

BTN = {"id": "e1", "type": "button", "text": "New", "bbox_norm": [.1, .1, .2, .2], "confidence": .9,
       "clickable": True, "source": "fast"}


def ctx(proc):
    return {"app": "File Explorer", "elements": [BTN], "all_elements": [BTN], "needs_review": False,
            "vision_source": "t", "warnings": [], "quality": {"score": .9, "reasons": []}, "status": "ok",
            "window_title": "w", "window": {"process": proc, "bounds": [0, 0, 1000, 1000]},
            "screen": {"w": 1000, "h": 1000, "left": 0, "top": 0}}


def run(procs):
    seq, calls = list(procs), []
    A.perceive_screen = lambda app, target, screenshot=None, scenario=None: ctx(seq.pop(0) if len(seq) > 1 else seq[0])

    def execute(req):
        calls.append(req["action_type"])
        return {"action_id": req["action_id"], "task_id": req["task_id"], "status": "success",
                "verification_status": "not_verified", "strategy_used": "fake", "duration_ms": 0,
                "output": {"dry_run": False}, "error": None, "screenshot_after_ref": None}
    A.desktop_adapter = types.SimpleNamespace(execute=execute, live_requested=lambda: False)
    A.HAS_ADAPTER = True
    llm.available = lambda: True
    llm.chat_json = lambda s, u, **k: {"action": "click", "element_id": "e1", "why": "new"}
    return A.run_app_subgraph("File Explorer", "new folder", ["click New"], "t", flag="x", max_actions=1), calls


# 1) first look: a WebView2 window in front; after focus_window the second look is Explorer -> click happens
r, calls = run(["msedgewebview2.exe", "explorer.exe"])
assert calls == ["focus_window", "click"], calls
assert r["steps_done"] and "target_outside_window" not in str(r.get("error")), r

# 2) never comes forward: focus_window each time, no click, stops after the bounded re-looks
r, calls = run(["msedgewebview2.exe"])
assert "click" not in calls and calls.count("focus_window") == 3, calls
assert r["status"] == "needs_regrounding" and "target_outside_window" in r["error"], r
print("ok")
