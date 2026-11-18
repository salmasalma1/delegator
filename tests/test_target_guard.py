import os as _o0; _o0.environ.setdefault("NELLY_DRY_RUN", "1")  # tests never move the real mouse
"""F1: a target must lie inside the window of the application the node names. Outside it (or on another app's
window) the request is never sent: grounding error `target_outside_window`. Fakes only; nothing is clicked."""
import importlib.util
import os
import sys
import types

sys.path.insert(0, ".")
os.environ["NELLY_PERSIST"] = "0"
os.environ.pop("NELLY_LIVE_INPUT", None)
from vision.target_guard import check_target                        # noqa: E402
from vision.adapter import normalize                                # noqa: E402

WIN = {"process": "notepad.exe", "title": "Untitled - Notepad", "bounds": [100, 100, 500, 400], "hwnd": 7}
SCREEN = {"w": 1000, "h": 1000, "left": 0, "top": 0, "dpi_scale": 1.0}
INSIDE = {"id": "e1", "type": "input", "text": "", "bbox_norm": [0.2, 0.2, 0.3, 0.3], "confidence": .9,
          "clickable": True, "source": "fast"}                      # centre (250, 250): inside the window
OUTSIDE = {"id": "e2", "type": "button", "text": "Save", "bbox_norm": [0.7, 0.7, 0.8, 0.8], "confidence": .9,
           "clickable": True, "source": "fast"}                     # centre (750, 750): another window
OBS = {"window": WIN, "screen": SCREEN}

# 1) the guard itself
assert check_target(INSIDE, OBS, "Notepad", live=True) == (True, None)
ok, why = check_target(OUTSIDE, OBS, "Notepad", live=True)
assert not ok and why.startswith("target_outside_window") and "e2" in why, why
ok, why = check_target(INSIDE, {"window": {**WIN, "process": "claude.exe"}, "screen": SCREEN}, "Notepad", live=True)
assert not ok and why.startswith("target_outside_window") and "claude.exe" in why, why      # another app's window
ok, why = check_target(INSIDE, {"window": {"process": "notepad.exe"}, "screen": SCREEN}, "Notepad", live=True)
assert not ok and why.startswith("target_outside_window") and "unknown" in why, why        # live: must be provable
assert check_target(INSIDE, {"window": {"process": "Notepad"}}, "Notepad", live=False)[0]   # dry / fake screen: allowed
assert check_target(None, OBS, "Notepad", live=True) == (True, None)                         # no pointer target
assert check_target(INSIDE, OBS, "Basic System Dialog", live=True)[0]                        # unknown app: bounds only

# 2) the worker's context carries the window and the screen (needed by the guard)
ctx = normalize({"schema_version": "0.3", "screenshot_id": "s1", "window": WIN, "screen": SCREEN,
                 "elements": [INSIDE, OUTSIDE], "perception": {"detector": "yolo:x"}})
assert ctx["window"]["bounds"] == [100, 100, 500, 400] and ctx["screen"]["w"] == 1000, ctx

# 3) the worker never sends a request for a target outside the window
import llm                                                          # noqa: E402
import graph.subgraphs.app_subgraph as A                           # noqa: E402
CTX = {"app": "notepad.exe", "elements": [INSIDE, OUTSIDE], "all_elements": [INSIDE, OUTSIDE], "needs_review": False,
       "vision_source": "t", "warnings": [], "quality": {"score": .9, "reasons": []}, "status": "ok",
       "window_title": "w", "window": WIN, "screen": SCREEN}
A.perceive_screen = lambda app, target, screenshot=None, scenario=None: CTX
llm.available = lambda: True
calls = []
A.desktop_adapter = types.SimpleNamespace(execute=lambda req: calls.append(req) or {}, live_requested=lambda: False)
A.HAS_ADAPTER = True
llm.chat_json = lambda s, u, **k: {"action": "click", "element_id": "e2", "why": "save"}
r = A.run_app_subgraph("Notepad", "save", ["click Save"], "t", flag="saved")
assert calls == [], f"a request was sent for a target outside the window: {calls}"
assert r["status"] == "needs_regrounding" and "target_outside_window" in r["error"], r
llm.chat_json = lambda s, u, **k: {"action": "click", "element_id": "e1", "why": "field"}   # inside: still allowed
A.desktop_adapter = types.SimpleNamespace(
    execute=lambda req: calls.append(req) or {"action_id": req["action_id"], "status": "success",
                                              "output": {"dry_run": True}}, live_requested=lambda: False)
A.run_app_subgraph("Notepad", "click field", ["click the field"], "t", flag="x", max_actions=1)
assert len(calls) == 1 and calls[0]["target_element_id"] == "e1", calls

# 4) the Team 1 bridge refuses it too (product code, not only the worker), when Team 1's contracts exist
if importlib.util.find_spec("contracts") and importlib.util.find_spec("nelly_vision"):
    from execution import team1_bridge as B
    obs = {"screenshot_id": "s1", "window": WIN, "screen": SCREEN, "elements": [INSIDE, OUTSIDE]}
    out = B.execute({"action_id": "a1", "task_id": "t", "action_type": "click", "application": "Notepad",
                     "parameters": {}, "target_element_id": "e2", "observation": obs})
    assert out["status"] == "blocked" and out["reject_code"] == "target_outside_window", out
    assert out["action_id"] == "a1" and out["output"]["reject_code"] == "target_outside_window", out
    ok_in = B.execute({"action_id": "a2", "task_id": "t", "action_type": "click", "application": "Notepad",
                       "parameters": {}, "target_element_id": "e1", "observation": obs})
    assert ok_in["status"] == "success" and ok_in["output"]["dry_run"] is True, ok_in

print("test_target_guard OK")
