"""NELLY_CAPTURE=window reads the foreground window (capture_window); default is the whole screen. Fakes only."""
import os
import sys
import types
sys.path.insert(0, ".")

calls = []
sources = []


class Obs:
    def model_dump(self, mode=None):
        return {"schema_version": "0.3", "screenshot_id": "s1", "elements": []}


class Res:
    observation = Obs()
    grounding = None


class Perceiver:
    def perceive_detailed(self, image, target=None, screen=None, window=None, screenshot_id=None, allow_vlm=False,
                          source="offline_image"):
        calls.append(("perceive", image, screen))
        sources.append(source)
        return Res()


cap = types.ModuleType("nelly_vision.capture")
cap.capture_screen = lambda: (calls.append(("screen",)) or ("IMG_SCREEN", "SCREEN_INFO", "W"))
cap.capture_window = lambda window=None: (calls.append(("window",)) or ("IMG_WINDOW", "WINDOW_INFO", "W"))
cap.new_screenshot_id = lambda: "s1"
pkg = types.ModuleType("nelly_vision")
pkg.Perceiver = Perceiver
pkg.capture = cap
sys.modules["nelly_vision"], sys.modules["nelly_vision.capture"] = pkg, cap

import vision.env_check as ec                                       # noqa: E402
ec.ensure_memory_for_ocr = lambda: None
from vision import vision_adapter as va                             # noqa: E402

os.environ.pop("NELLY_CAPTURE", None)
va._observe_once()
assert calls[0] == ("screen",) and calls[1][1] == "IMG_SCREEN", calls

calls.clear()
os.environ["NELLY_CAPTURE"] = "window"
va._observe_once()
assert calls[0] == ("window",) and calls[1][1] == "IMG_WINDOW" and calls[1][2] == "WINDOW_INFO", calls

calls.clear()                                           # an older vision package without capture_window: whole screen
del cap.capture_window
va._observe_once()
assert calls[0] == ("screen",), calls
assert sources == ["live_capture", "live_capture", "live_capture"], sources     # live looks say so

sources.clear()                                         # a screenshot FILE stays offline
va._observe_once(screenshot="shot.png")
assert sources == ["offline_image"], sources

# an older Perceiver without a `source` argument still works
class OldPerceiver:
    def perceive_detailed(self, image, target=None, screen=None, window=None, screenshot_id=None, allow_vlm=False):
        return Res()
va._perceiver[0] = OldPerceiver()
va._observe_once()
print("ok")

# the target guard works with a window crop: bbox_norm is relative to the crop, left/top is its origin
from vision.target_guard import check_target                        # noqa: E402
obs = {"window": {"process": "explorer.exe", "bounds": [500, 200, 1300, 800]},
       "screen": {"w": 800, "h": 600, "left": 500, "top": 200}}
assert check_target({"id": "e1", "bbox_norm": [0.4, 0.4, 0.5, 0.5]}, obs, "File Explorer", live=True)[0]
obs_bad = {**obs, "screen": {"w": 800, "h": 600, "left": 0, "top": 0}}   # origin lost: centre would be off
print("ok guard")
