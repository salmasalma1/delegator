"""Team 1 executor bridge. Never moves the mouse or types: dry run, or FAKE window / input backends that only
record what they were asked to do. NELLY_LIVE_INPUT is removed from the environment first.
Needs Team 1's vision package; without it the script reports SKIP (counted by tests/run_all.py), not FAIL."""
import importlib.util
import os
import subprocess
import sys
import types


def _missing_team1():
    """The first of Team 1's packages that cannot be imported here, or None. Looks only, imports nothing."""
    for name in ("contracts", "nelly_vision"):
        try:
            if importlib.util.find_spec(name) is None:
                return name
        except (ImportError, ValueError):
            return name
    return None


if _missing_team1():
    print(f"SKIP test_team1_bridge.py: Team 1 vision package ({_missing_team1()}) is not installed")
    sys.exit(0)

os.environ.pop("NELLY_LIVE_INPUT", None)
os.environ["NELLY_DRY_RUN"] = "1"
os.environ.pop("NELLY_EXECUTOR", None)
sys.path.insert(0, ".")

# 1) importing the executor does not import pyautogui (it stays lazy)
import execution.team1.executor_desktop as D                      # noqa: E402
import execution.team1.apps as apps                                # noqa: E402
assert "pyautogui" not in sys.modules, "executor_desktop imported pyautogui at import time"


class FakePyAutoGui(types.ModuleType):                             # safety net: any pyautogui use only records
    class FailSafeException(Exception):
        pass

    def __init__(self):
        super().__init__("pyautogui")
        self.events, self.trip = [], False

    def failSafeCheck(self):
        if self.trip:
            raise FakePyAutoGui.FailSafeException("mouse in a corner")

    def __getattr__(self, name):                                   # click, mouseUp, scroll... -> recorded
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: self.events.append((name, a, k))


pg = FakePyAutoGui()
sys.modules["pyautogui"] = pg

from contracts import ActionResult, ToolCall                       # noqa: E402  (Team 1)
from execution import team1_bridge as B                            # noqa: E402
from graph import control                                          # noqa: E402


class FakeWindows:
    def __init__(self, fg_process, can_activate=False):
        self.fg = {"hwnd": 1, "process": fg_process, "title": "t"}
        self.can_activate, self.activated, self.launched = can_activate, [], []

    def foreground(self):
        return self.fg

    def windows_of(self, processes):
        return [2] if self.can_activate else []

    def activate(self, hwnd):
        self.activated.append(hwnd)
        return self.can_activate

    def launch(self, target, args=""):
        self.launched.append(target)


class FakeInput:
    def __init__(self):
        self.events = []

    def click(self, point, kind):
        self.events.append(("click", kind))
        return (0, 0)

    def write(self, text):
        self.events.append(("write", len(text)))

    def hotkey(self, keys):
        self.events.append(("hotkey", tuple(keys)))

    def scroll(self, direction, amount, point):
        self.events.append(("scroll", direction))

    def release_all(self):
        self.events.append(("release_all",))

    def release_modifiers(self):
        self.events.append(("release_modifiers",))


class FakeKeys:                                                     # stands in for SendInputKeyboard
    def __init__(self, fail=False):
        self.fail, self.chords, self.released = fail, [], 0

    def chord(self, keys):
        if self.fail:
            raise OSError("SendInput was blocked (fake)")
        self.chords.append(tuple(keys))

    def release_modifiers(self):
        self.released += 1


def executor(windows, inputs, live=True):
    return D.DesktopExecutor(windows=windows, inputs=inputs, sleep=lambda s: None, focus_settle_s=0,
                             fake_backends_live=live)


def run(ex, tool, app, args=None, target=None, observation=None):
    call = ToolCall(call_id="a1", tool=tool, args=args or {}, target_element_id=target)
    return ex.execute(call, observation=observation, stop=__import__("threading").Event(), app=app)


def req(action="click", app="Notepad", **extra):
    r = {"action_id": "act-123", "task_id": "t1", "action_type": action, "application": app,
         "target_element_id": "e3", "parameters": {}, "observation": {"screenshot_id": "s1"}}
    r.update(extra)
    return r


# 2) the bridge stays in dry run: same action_id back, recorded as dry_run (never as a real success)
assert not B.live_requested()
r = B.execute(req())
assert r["action_id"] == "act-123" and r["status"] == "success", r
assert r["output"]["dry_run"] is True and r["strategy_used"] == "team1_dryrun", r
assert r["evidence"]["team1_status"] == "ok" and r["evidence"]["call_id_matches"] is True, r
t = B.execute(req("type", parameters={"text": "very private words"}, target_element_id=None))
assert t["status"] == "success" and t["action_id"] == "act-123" and "very private" not in repr(t), t

# 3) no application -> refused (dry run and desktop executor), nothing is sent
r = B.execute(req("type", app=None, parameters={"text": "x"}))
assert r["status"] == "blocked" and r["reject_code"] == "no_application", r
assert r["output"]["reject_code"] == "no_application" and r["output"]["dry_run"] is False, r
assert r["action_id"] == "act-123", r
assert B.execute(req(app="Chrome"))["reject_code"] == "unknown_app"
W, I = FakeWindows("notepad.exe"), FakeInput()
res = run(executor(W, I), "press_keys", None, {"keys": ["ctrl", "s"]})
assert res.status == "blocked" and res.error.startswith("no_application"), res
res = run(executor(W, I), "type_text", "Chrome", {"text": "x"})
assert res.status == "blocked" and res.error.startswith("unknown_app"), res
assert I.events == [] and W.activated == [], (I.events, W.activated)

# 4) the desktop executor is dry by default: without NELLY_LIVE_INPUT it refuses before touching anything
res = run(executor(W, I, live=False), "press_keys", "Notepad", {"keys": ["ctrl", "s"]})
assert res.status == "blocked" and res.error.startswith("dry_run"), res
real_windows = D.Win32Windows
D.Win32Windows = lambda: FakeWindows("notepad.exe")                # the opt-in needs BOTH backends to be fakes
try:
    one_fake = D.DesktopExecutor(inputs=I, sleep=lambda s: None, fake_backends_live=True)
    assert run(one_fake, "press_keys", "Notepad", {"keys": ["ctrl", "s"]}).error.startswith("dry_run")
finally:
    D.Win32Windows = real_windows
assert I.events == [], I.events

# 5) wrong_window: focus_guard / focus_changed are reported as wrong_window, original code kept in the detail
W = FakeWindows("chrome.exe", can_activate=False)
res = run(executor(W, I), "press_keys", "Notepad", {"keys": ["ctrl", "s"]})
assert res.status == "blocked" and res.error.startswith("wrong_window: focus_guard:"), res
W = FakeWindows("notepad.exe")
res = run(executor(W, I), "click_element", "Notepad", target="e3",
          observation={"screenshot_id": "s1", "window": {"process": "chrome.exe"}})
assert res.status == "blocked" and res.error.startswith("wrong_window: focus_changed:"), res
mapped = B.from_action_result(req(), res, 0, dry=False)
assert mapped["status"] == "blocked" and mapped["reject_code"] == "wrong_window", mapped
assert "focus_changed" in mapped["error"] and mapped["action_id"] == "act-123", mapped
assert I.events == [], I.events

# 6) an exception during input releases Ctrl/Shift/Alt/Win (fake pyautogui + fake keyboard, no mouse events)
inp = object.__new__(D.PyAutoGuiInput)
inp.gui, inp.keys = pg, FakeKeys(fail=True)
res = run(executor(FakeWindows("notepad.exe"), inp), "press_keys", "Notepad", {"keys": ["ctrl", "s"]})
assert res.status == "error" and "OSError" in res.error, res
assert inp.keys.released == 1 and not any(e[0] == "mouseUp" for e in pg.events), (inp.keys.released, pg.events)
inp.keys, pg.trip = FakeKeys(), True                                 # pyautogui corner fail-safe = user stop
res = run(executor(FakeWindows("notepad.exe"), inp), "press_keys", "Notepad", {"keys": ["ctrl", "s"]})
assert res.status == "skipped" and "corner" in res.error and inp.keys.released == 1, res
pg.trip, inp.keys = False, FakeKeys()                                # finished normally: nothing to release
res = run(executor(FakeWindows("notepad.exe"), inp), "press_keys", "Notepad", {"keys": ["ctrl", "s"]})
assert res.status == "ok" and inp.keys.chords == [("ctrl", "s")] and inp.keys.released == 0, res

# 7) status mapping table (Team 1 -> ours), action_id always the request's
table = [("ok", None, "success", None), ("blocked", "stale: observation too old", "blocked", "stale"),
         ("blocked", "wrong_window: focus_guard: x", "blocked", "wrong_window"),
         ("skipped", "stopped by the user", "cancelled", None), ("error", "OSError: x", "failed", "executor_error")]
for team1, err, ours, code in table:
    out = B.from_action_result(req(), ActionResult(call_id="other-id", status=team1, error=err), 0, dry=False)
    assert (out["status"], out["reject_code"], out["action_id"]) == (ours, code, "act-123"), (team1, out)
    assert out["evidence"]["team1_status"] == team1 and out["evidence"]["call_id_matches"] is False
    assert out["output"]["reject_code"] == code

# 8) a protected process is refused, even if someone maps an application to it
assert {"windowsterminal.exe", "powershell.exe", "pwsh.exe", "cmd.exe", "conhost.exe", "code.exe", "claude.exe",
        "keepass.exe", "keepassxc.exe", "1password.exe", "bitwarden.exe", "lastpass.exe"} <= apps.PROTECTED_PROCESSES
apps.PROCESSES["terminal"] = frozenset({"windowsterminal.exe"}); apps._ALIASES["terminal"] = "terminal"
try:
    res = run(executor(FakeWindows("windowsterminal.exe"), I), "type_text", "terminal", {"text": "dir"})
    assert res.status == "blocked" and "protected" in res.error and res.error.startswith("wrong_window"), res
finally:
    del apps.PROCESSES["terminal"], apps._ALIASES["terminal"]
assert B.execute(req("type", app="cmd", parameters={"text": "dir"}))["reject_code"] == "unknown_app"
assert I.events == [], I.events

# 9) the Alt key-tap is gone from activate(), and other bridge refusals
import inspect                                                       # noqa: E402
assert "keybd_event(" not in inspect.getsource(D.Win32Windows.activate)       # no Alt key is sent
assert B.execute(req("save_file"))["reject_code"] == "unsupported_action"
assert B.execute(req("press"))["reject_code"] == "bad_request"
control.cancel()
try:
    c = B.execute(req())
    assert c["status"] == "cancelled" and c["action_id"] == "act-123", c
finally:
    control.reset()

# 10) the switch: default is our interim executor, NELLY_EXECUTOR=team1 picks the bridge
probe = "import graph.subgraphs.app_subgraph as a; print(a.desktop_adapter.__name__)"
env = {k: v for k, v in os.environ.items() if k not in ("NELLY_LIVE_INPUT", "NELLY_EXECUTOR")}
default = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True, text=True)
team1 = subprocess.run([sys.executable, "-c", probe], env={**env, "NELLY_EXECUTOR": "team1"},
                       capture_output=True, text=True)
assert default.stdout.strip().splitlines()[-1] == "execution.desktop_adapter", default.stdout + default.stderr
assert team1.stdout.strip().splitlines()[-1] == "execution.team1_bridge", team1.stdout + team1.stderr

assert not any(e[0] in ("click", "write", "press", "hotkey", "typewrite") for e in pg.events), pg.events
print("test_team1_bridge OK")
