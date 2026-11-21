import os as _o0; _o0.environ.setdefault("NELLY_DRY_RUN", "1")
"""When the model names no usable element, the worker looks again (bounded by NELLY_FIND_RETRIES) and feeds the
failure back; it stops with the old error after the bound. Fakes only."""
import os
import sys
import types
sys.path.insert(0, ".")
os.environ["NELLY_PERSIST"] = "0"
os.environ.pop("NELLY_LIVE_INPUT", None)
os.environ.pop("NELLY_FIND_RETRIES", None)
import llm                                                          # noqa: E402
import graph.subgraphs.app_subgraph as A                           # noqa: E402

BTN = {"id": "e1", "type": "button", "text": "New folder", "bbox_norm": [.1, .1, .2, .2], "confidence": .9,
       "clickable": True, "source": "fast"}
CTX = {"app": "Notepad", "elements": [BTN], "all_elements": [BTN], "needs_review": False, "vision_source": "t",
       "warnings": [], "quality": {"score": .9, "reasons": []}, "status": "ok", "window_title": "w"}
looks = []
A.perceive_screen = lambda app, target, screenshot=None, scenario=None: looks.append(1) or CTX
A.desktop_adapter = types.SimpleNamespace(
    execute=lambda req: {"action_id": req["action_id"], "task_id": req["task_id"], "status": "success",
                         "verification_status": "not_verified", "strategy_used": "fake", "duration_ms": 0,
                         "output": {"dry_run": False}, "error": None, "screenshot_after_ref": None},
    live_requested=lambda: False)
A.HAS_ADAPTER = True
llm.available = lambda: True


def run(answers):
    looks.clear()
    seq = list(answers)
    llm.chat_json = lambda s, u, **k: seq.pop(0) if len(seq) > 1 else seq[0]
    return A.run_app_subgraph("Notepad", "make a folder", ["click New folder"], "t", flag="x", max_actions=1)


bad = {"action": "click", "element_id": None, "why": "cannot see it"}
good = {"action": "click", "element_id": "e1", "why": "found"}

r = run([bad, bad, good])                                           # found on the third look
assert len(looks) == 3 and r["steps_done"] and r.get("find_attempts") and len(r["find_attempts"]) == 2, (looks, r)

r = run([bad])                                                      # never found: 1 + 3 looks, then the old error
assert len(looks) == 4 and r["status"] == "needs_regrounding" and "not on screen" in r["error"] \
    and "searched 3 more" in r["error"], (looks, r)

os.environ["NELLY_FIND_RETRIES"] = "0"
r = run([bad])
assert len(looks) == 1 and "searched" not in r["error"], r
os.environ["NELLY_FIND_RETRIES"] = "99"
assert A.find_retries() == 10
print("ok")
