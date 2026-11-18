import os as _o0; _o0.environ.setdefault("NELLY_DRY_RUN", "1")  # tests never move the real mouse
"""F7: Team 1's executor reports a refusal code once ("stale: ...", not "stale: stale: ..."), and the bridge gives
Team 1's CoordinateManager the age limit from NELLY_MAX_OBS_AGE (its own parameter, max_age_s). Fake window and
input backends only; nothing is clicked. Needs Team 1's vision package; reports SKIP without it."""
import importlib.util
import os
import sys
import threading

if not (importlib.util.find_spec("contracts") and importlib.util.find_spec("nelly_vision")):
    print("SKIP test_team1_stale_age.py: Team 1 vision package (contracts) is not installed")
    sys.exit(0)

sys.path.insert(0, ".")
os.environ.pop("NELLY_LIVE_INPUT", None)
from contracts import ScreenObservation, ToolCall                    # noqa: E402  (Team 1)
import execution.team1.executor_desktop as D                        # noqa: E402
from execution import team1_bridge as B                             # noqa: E402


class Win:
    def foreground(self):
        return {"hwnd": 1, "process": "notepad.exe", "title": "t"}

    def windows_of(self, p):
        return [1]

    def activate(self, h):
        return True

    def launch(self, t, a=""):
        pass


class Inp:
    events = []

    def click(self, *a):
        self.events.append("click")

    def write(self, *a):
        self.events.append("write")

    def hotkey(self, *a):
        self.events.append("hotkey")

    def scroll(self, *a):
        pass

    def release_all(self):
        pass


class Rejected(Exception):                                          # shaped like Team 1's TargetRejected
    def __init__(self, code, message):
        super().__init__(f"{code}: {message}")
        self.code = code


class Coords:
    def resolve_target_point(self, obs, element_id):
        raise Rejected("stale", "observation is 20.0 s old (max 15.0 s): re-perceive")


obs = ScreenObservation(screenshot_id="s1", screen={"w": 1000, "h": 800, "dpi_scale": 1.0},
                        window={"hwnd": 1, "process": "notepad.exe", "title": "t", "bounds": (0, 0, 1000, 800)},
                        elements=[{"id": "e1", "type": "menu_item", "bbox_norm": (0.1, 0.1, 0.2, 0.2),
                                   "confidence": 0.9}]).model_dump(mode="json")
ex = D.DesktopExecutor(windows=Win(), inputs=Inp(), coords=Coords(), sleep=lambda s: None, fake_backends_live=True)
res = ex.execute(ToolCall(call_id="c1", tool="click_element", target_element_id="e1"), observation=obs,
                 stop=threading.Event(), app="Notepad")
assert res.status == "blocked", res
assert res.error == "stale: observation is 20.0 s old (max 15.0 s): re-perceive", res.error   # the code once
assert Inp.events == [], Inp.events

# the bridge passes NELLY_MAX_OBS_AGE to Team 1's CoordinateManager (max_age_s)
os.environ.pop("NELLY_MAX_OBS_AGE", None)
assert B._coords().max_age_s == 15.0                               # Team 1's own default when unset
os.environ["NELLY_MAX_OBS_AGE"] = "120"
assert B._coords().max_age_s == 120.0
seen = {}


class Recorder:
    def __init__(self, **kw):
        seen.update(kw)


real = D.DesktopExecutor
D.DesktopExecutor = Recorder
try:
    B._executors.pop("desktop", None)
    B._executor(False)                                               # the live executor is built with coords
    assert seen.get("coords") is not None and seen["coords"].max_age_s == 120.0, seen
finally:
    D.DesktopExecutor = real
    B._executors.pop("desktop", None)
    os.environ.pop("NELLY_MAX_OBS_AGE")

print("test_team1_stale_age OK")
