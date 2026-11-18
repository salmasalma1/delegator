import os as _o0; _o0.environ.setdefault("NELLY_DRY_RUN", "1")  # tests never move the real mouse
"""F5: in a live run the worker always captures the live screen (a screenshot FILE has no window / monitor, so
Team 1's window and DPI checks cannot run); a vision call that takes longer than NELLY_VISION_TIMEOUT stops the
step (needs_review) instead of blocking it. Fakes only: no capture, no input."""
import importlib.util
import os
import sys
import time
import types

sys.path.insert(0, ".")
os.environ["NELLY_PERSIST"] = "0"
os.environ.pop("NELLY_LIVE_INPUT", None)
import graph.subgraphs.app_subgraph as A                           # noqa: E402
from vision import vision_adapter as VA                             # noqa: E402

OBS = {"schema_version": "0.3", "screenshot_id": "s1", "perception": {"detector": "yolo:x"},
       "elements": [{"id": "e1", "type": "button", "text": "Save", "bbox_norm": [.1, .1, .2, .2],
                     "confidence": .9, "clickable": True, "source": "fast"}]}
seen = []
real_observe = VA.observe
A.vision_adapter.available = lambda: True
A.vision_adapter.observe = lambda screenshot=None, target=None, allow_vlm=False: seen.append(screenshot) or OBS
A.HAS_ADAPTER = True

# 1) live: a screenshot file is ignored, the live screen is captured, and the context says so
A.desktop_adapter = types.SimpleNamespace(live_requested=lambda: True, execute=None)   # never executed here
ctx = A.perceive_screen("Notepad", "click Save", screenshot="C:/shots/after_action.png")
assert seen[-1] is None, seen
assert any("screenshot file ignored" in w for w in ctx["warnings"]), ctx["warnings"]
# 2) dry run: the file is still used (offline tests and replays need it)
A.desktop_adapter = types.SimpleNamespace(live_requested=lambda: False, execute=None)
A.perceive_screen("Notepad", "click Save", screenshot="C:/shots/after_action.png")
assert seen[-1] == "C:/shots/after_action.png", seen

# 3) the time limit
A.vision_adapter.observe = real_observe
VA._observe_once = lambda screenshot=None, target=None, allow_vlm=False, gen=None: time.sleep(2) or OBS
os.environ["NELLY_VISION_TIMEOUT"] = "0.3"
t0 = time.time()
try:
    VA.observe()
    raise AssertionError("no timeout")
except TimeoutError as e:
    assert "NELLY_VISION_TIMEOUT" in str(e) and time.time() - t0 < 1.5, (e, time.time() - t0)
ctx = A.perceive_screen("Notepad", "click Save")                    # the worker turns it into needs_review
assert ctx["needs_review"] and "TimeoutError" in (ctx.get("error") or ""), ctx
os.environ["NELLY_VISION_TIMEOUT"] = "0"                            # 0 = no limit
time.sleep(2.2)                                                      # let the timed-out calls finish first
VA._observe_once = lambda screenshot=None, target=None, allow_vlm=False, gen=None: OBS
assert VA.observe() == OBS
assert VA.vision_timeout() is None
os.environ["NELLY_VISION_TIMEOUT"] = "abc"
assert VA.vision_timeout() == 180.0                                 # unreadable -> the default
os.environ.pop("NELLY_VISION_TIMEOUT")

# 4) a call that timed out must not overwrite the observation of a later call (needs Team 1's package)
if importlib.util.find_spec("nelly_vision") and importlib.util.find_spec("contracts"):
    import importlib
    VA2 = importlib.reload(VA)

    class _Obs:
        def __init__(self, sid):
            self.sid = sid

        def model_dump(self, mode=None):
            return {**OBS, "screenshot_id": self.sid}

    class _Slow:
        def perceive_detailed(self, image, **kw):
            time.sleep(1.0)
            return types.SimpleNamespace(observation=_Obs("late"), grounding=None)
    VA2._perceiver[0] = _Slow()
    os.environ["NELLY_VISION_TIMEOUT"] = "0.2"
    try:
        VA2.observe(screenshot=object())
    except TimeoutError:
        pass
    VA2._last[0] = {"screenshot_id": "newer"}                        # a later call's result
    time.sleep(1.5)                                                  # the slow call finishes now
    assert VA2._last[0]["screenshot_id"] == "newer", VA2._last[0]
    os.environ.pop("NELLY_VISION_TIMEOUT")

print("test_vision_live_capture OK")
