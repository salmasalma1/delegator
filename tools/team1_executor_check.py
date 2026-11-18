"""
Team 1 executor check: drives execution/team1_bridge.execute() with OUR request shape on THIS machine.

  python tools/team1_executor_check.py                  # dry run, all scenarios: prints what WOULD happen
  python tools/team1_executor_check.py --step S2        # one scenario (S1..S7, cleanup, screenshot)
  set NELLY_LIVE_INPUT=1  (Windows)                     # real input; EVERY step asks y/n first

Scenarios
  S1 open_app Notepad                      S5 application = a terminal (protected / unknown) -> refused
  S2 type "hello Lumi" into Notepad        S6 observation older than the max age            -> stale
  S3 Explorer in front, obs says Notepad   S7 stop with Ctrl+C during typing (explained only)
     -> wrong_window, nothing typed        cleanup: read Notepad's text, close it with WM_CLOSE (never saves)
  S4 no application -> no_application      screenshot: save the whole screen to --out

Vision cannot ground Notepad's empty text area today, so S2 / S3 / S6 build a REAL observation without the model:
Team 1's window metadata (nelly_vision.capture / coordinates) and one `input` element whose box is Notepad's
edit control rectangle (Win32 GetWindowRect). CoordinateManager.resolve_target_point and the focus guard then run
for real. The script remembers the Notepad it opened (state.json in --out) and never touches other windows.
Stop any time: Ctrl+C, or move the mouse into a screen corner (pyautogui fail-safe).
"""
import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("NELLY_PERSIST", "0")
from execution import team1_bridge as B                                  # noqa: E402

TEXT = "hello Lumi"
STALE_EXTRA_S = 30          # S6: this much older than the larger of Team 1's 15 s and NELLY_MAX_OBS_AGE
WM_GETTEXT, WM_GETTEXTLENGTH, WM_CLOSE = 0x000D, 0x000E, 0x0010
live = B.live_requested()


# ------------------------------------------------------------------ windows (read-only helpers + our own windows)
def _windows(cls=None, process=None):
    import psutil
    import win32gui
    import win32process
    found = []

    def visit(h, _):
        if not win32gui.IsWindowVisible(h):
            return True
        if cls and win32gui.GetClassName(h) != cls:
            return True
        if process:
            try:
                if psutil.Process(win32process.GetWindowThreadProcessId(h)[1]).name().lower() != process:
                    return True
            except Exception:                                            # noqa: BLE001
                return True
        found.append(h)
        return True
    win32gui.EnumWindows(visit, None)
    return found


def _edit_control(hwnd):
    import win32gui
    for cls in ("Edit", "RichEditD2DPT"):                               # classic Notepad / Windows 11 Notepad
        child = win32gui.FindWindowEx(hwnd, 0, cls, None)
        if child:
            return child
    found = []
    win32gui.EnumChildWindows(hwnd, lambda c, _: found.append(c) if win32gui.GetClassName(c) in
                              ("Edit", "RichEditD2DPT") else None, None)
    return found[0] if found else None


def read_text(hwnd):
    """Notepad's text through WM_GETTEXT on its edit control (no click, no focus change)."""
    edit = _edit_control(hwnd) if hwnd else None
    if not edit:
        return None
    u = ctypes.windll.user32
    n = u.SendMessageW(edit, WM_GETTEXTLENGTH, 0, 0)
    buf = ctypes.create_unicode_buffer(n + 1)
    u.SendMessageW(edit, WM_GETTEXT, n + 1, buf)
    return buf.value


def _alive(hwnd):
    return bool(hwnd) and bool(ctypes.windll.user32.IsWindow(hwnd))


def _foreground():
    from nelly_vision.capture import foreground_window
    w = foreground_window()
    return (w.process or "?", w.title, w.hwnd) if w else ("none", "", None)


# ------------------------------------------------------------------ observation without the model
def window_info(hwnd):
    """Team 1's WindowInfo: from capture.foreground_window() when this window is in front, else the same fields."""
    import psutil
    import win32gui
    import win32process
    from contracts import WindowInfo
    from nelly_vision.capture import _monitor_dpi_scale, foreground_window   # same helpers Team 1 uses
    from nelly_vision.coordinates import get_window_bounds
    fw = foreground_window()
    if fw and fw.hwnd == hwnd:
        return fw
    state = get_window_bounds(hwnd)
    b = state.bounds if state else None
    proc = psutil.Process(win32process.GetWindowThreadProcessId(hwnd)[1]).name()
    return WindowInfo(hwnd=hwnd, title=win32gui.GetWindowText(hwnd), process=proc, bounds=b,
                      dpi_scale=_monitor_dpi_scale((b[0] + b[2]) // 2, (b[1] + b[3]) // 2) if b else None,
                      minimized=bool(state and state.minimized))


def build_observation(hwnd, age_s=0.0):
    """A real ScreenObservation (frame = Notepad's window) with one `input` element = the edit control's rect."""
    import win32gui
    from contracts import ScreenInfo, ScreenObservation, UIElement
    from contracts.perception import PerceptionMeta
    win = window_info(hwnd)
    if win.bounds is None:
        raise RuntimeError("Notepad's window bounds cannot be read")
    l, t, r, b = win.bounds
    edit = _edit_control(hwnd)
    if not edit:
        raise RuntimeError("Notepad's edit control was not found")
    el, et, er, eb = win32gui.GetWindowRect(edit)
    el, et, er, eb = max(el, l), max(et, t), min(er, r), min(eb, b)     # clip to the visible frame
    w, h = r - l, b - t
    box = ((el - l) / w, (et - t) / h, (er - l) / w, (eb - t) / h)
    obs = ScreenObservation(
        screenshot_id=f"chk_{uuid.uuid4().hex[:8]}",
        captured_at=datetime.now(timezone.utc) - timedelta(seconds=age_s),
        elements=[UIElement(id="e1", type="input", bbox_norm=box, confidence=1.0, clickable=True,
                            description="Notepad edit area (Win32 rectangle, no model)")],
        screen=ScreenInfo(w=w, h=h, left=l, top=t, frame="window", dpi_scale=win.dpi_scale or 1.0),
        window=win, perception=PerceptionMeta(detector="none (Win32 rectangle)"),
        warnings=["built by tools/team1_executor_check.py from Win32 rectangles; no vision model"])
    return obs.model_dump(mode="json")


def preview_point(obs):
    """What Team 1's CoordinateManager would do with this observation (read-only, nothing moves)."""
    from contracts import ScreenObservation
    from nelly_vision.coordinates import CoordinateManager, TargetRejected
    try:
        p = CoordinateManager().resolve_target_point(ScreenObservation.model_validate(obs), "e1")
        return f"point {p.xy}" + (f" ({'; '.join(p.notes)})" if p.notes else "")
    except TargetRejected as e:
        return f"refused: {e}"


# ------------------------------------------------------------------ requests, receipts, prompts
def request(action, app, params=None, target=None, obs=None):
    r = {"action_id": f"chk-{uuid.uuid4().hex[:8]}", "task_id": "team1-executor-check", "action_type": action,
         "application": app, "parameters": params or {}, "target_element_id": target}
    if obs is not None:                     # the bridge takes the observation from the request when it is given
        r["observation"], r["observation_id"] = obs, obs["screenshot_id"]
    return r


def show(req, res):
    ev = res.get("evidence") or {}
    print(f"   receipt: status={res['status']}  reject_code={res.get('reject_code')}  "
          f"dry_run={res['output'].get('dry_run')}  strategy={res.get('strategy_used')}")
    print(f"            action_id={res['action_id']}  same as request: {res['action_id'] == req['action_id']}")
    if res.get("error"):
        print(f"            error: {res['error']}")
    keep = {k: ev[k] for k in ("mode", "team1_status", "tool", "screen_point", "call_id_matches") if k in ev}
    print(f"            evidence: {keep}")
    return res


def run(req):
    return show(req, B.execute(req))


def ask(text):
    """Live: y/n before every step (EOF = no). Dry: nothing to ask."""
    if not live:
        return True
    try:
        return input(f"  {text} [y/N] ").strip().lower() == "y"
    except EOFError:
        return False


def verdict(expected, ok, note=""):
    print(f"   EXPECTED: {expected}  ->  {'PASS' if ok else 'FAIL'}" + (f"  ({note})" if note else ""))
    return ok


def with_one_refocus(make_req):
    """Team 1 brings the app forward, then refuses a pointer action read from another window (focus_changed).
    Like the worker's re-look, build a fresh observation once and try again (bounded: one retry)."""
    req = make_req()
    res = run(req)
    if res.get("reject_code") == "wrong_window" and "brought to the front" in (res.get("error") or ""):
        print("   Notepad was brought to the front; re-reading the window once and retrying")
        req = make_req()
        res = run(req)
    return req, res


# ------------------------------------------------------------------ scenarios
class State:
    def __init__(self, out):
        self.path = os.path.join(out, "state.json")
        self.data = json.load(open(self.path)) if os.path.exists(self.path) else {}

    def save(self):
        json.dump(self.data, open(self.path, "w"), indent=1)

    @property
    def notepad(self):
        h = self.data.get("notepad_hwnd")
        return h if _alive(h) else None


def s1(st, out):
    print("S1 open_app Notepad")
    before = set(_windows("Notepad"))
    if live and before:
        print(f"   STOP: {len(before)} Notepad window(s) already open. Close them first, so nothing of yours is used.")
        return verdict("a new test Notepad", False, "not run")
    if not ask("Open a new Notepad window now?"):
        return verdict("success", False, "skipped by the user")
    res = run(request("open_app", "Notepad", {"app": "Notepad"}))
    if live:
        new = [h for h in _windows("Notepad") if h not in before]
        st.data["notepad_hwnd"] = new[0] if new else None
        st.save()
        print(f"   test Notepad: {'hwnd ' + str(new[0]) if new else 'NOT FOUND'}; in front: {_foreground()[0]}")
        return verdict("success, a new Notepad window", res["status"] == "success" and bool(new))
    return verdict("success, dry_run", res["status"] == "success" and res["output"]["dry_run"])


def _target(st):
    """Live: the Notepad S1 opened. Dry: any Notepad already open, only for a read-only preview."""
    if live:
        return st.notepad
    found = _windows("Notepad")
    return found[0] if found else None


def s2(st, out):
    print(f"S2 type {TEXT!r} into Notepad (real observation built from Win32 rectangles)")
    hwnd = _target(st)
    if hwnd:
        obs = build_observation(hwnd)
        print(f"   target window: {obs['window']['process']} hwnd={hwnd} bounds={obs['window']['bounds']}")
        print(f"   element e1 (input) bbox_norm={[round(v, 3) for v in obs['elements'][0]['bbox_norm']]}")
        print(f"   Team 1 coordinate manager now: {preview_point(obs)}")
        if live:
            print(f"   WILL: bring that Notepad to the front, click the point, then paste {TEXT!r} (your clipboard"
                  " text is borrowed and put back; if it holds an image or files, it types key by key instead)")
    elif live:
        print("   STOP: no test Notepad (run S1 first)")
        return verdict("success", False, "not run")
    else:
        print("   no Notepad window open (S1 was a dry run): preview skipped, dry run uses a placeholder observation")
    if not ask(f"Type {TEXT!r} into that Notepad now?"):
        return verdict("success", False, "skipped by the user")
    if hwnd:
        req, res = with_one_refocus(lambda: request("type", "Notepad", {"text": TEXT}, "e1", build_observation(hwnd)))
    else:
        res = run(request("type", "Notepad", {"text": TEXT}, "e1", {"screenshot_id": "dry-placeholder"}))
    if live:
        text = read_text(hwnd)
        print(f"   read back (WM_GETTEXT): {text!r}")
        st.data["after_s2"] = text
        st.save()
        return verdict(f"success and Notepad contains {TEXT!r}", res["status"] == "success" and TEXT in (text or ""))
    return verdict("success, dry_run, same action_id", res["status"] == "success" and res["output"]["dry_run"])


def s3(st, out):
    print("S3 negative: Explorer in front, observation says Notepad -> wrong_window, nothing typed")
    hwnd = _target(st)
    if live and not hwnd:
        print("   STOP: no test Notepad (run S1 first)")
        return verdict("wrong_window", False, "not run")
    if not ask("Open a new File Explorer window (in front), then ask to type into Notepad?"):
        return verdict("wrong_window", False, "skipped by the user")
    obs = build_observation(hwnd) if hwnd else {"screenshot_id": "dry-placeholder"}
    explorer = None
    if live:
        before_text = read_text(hwnd)
        before = set(_windows("CabinetWClass"))
        subprocess.Popen(["explorer.exe"])
        for _ in range(50):
            new = [h for h in _windows("CabinetWClass") if h not in before]
            if new:
                explorer = new[0]
                break
            time.sleep(0.1)
        time.sleep(0.8)
        print(f"   test Explorer: {'hwnd ' + str(explorer) if explorer else 'NOT FOUND'}; in front: {_foreground()[0]}")
    res = run(request("type", "Notepad", {"text": TEXT}, "e1", obs))
    if live:
        after_text = read_text(hwnd)
        print(f"   Notepad text before {before_text!r}, after {after_text!r}")
        if explorer and _alive(explorer):
            ctypes.windll.user32.PostMessageW(explorer, WM_CLOSE, 0, 0)
            print("   test Explorer window closed (WM_CLOSE)")
        return verdict("blocked wrong_window, Notepad text unchanged",
                       res.get("reject_code") == "wrong_window" and after_text == before_text)
    return verdict("dry_run (the focus guard only runs live)", res["status"] == "success" and res["output"]["dry_run"])


def s4(st, out):
    print("S4 negative: no application -> no_application")
    if not ask("Send a type request with no application?"):
        return verdict("no_application", False, "skipped by the user")
    res = run(request("type", None, {"text": TEXT}))
    return verdict("blocked no_application", res.get("reject_code") == "no_application")


def s5(st, out):
    print("S5 negative: application = a terminal -> refused")
    if not ask("Send a type request for application 'Windows Terminal'?"):
        return verdict("refused", False, "skipped by the user")
    res = run(request("type", "Windows Terminal", {"text": "dir"}))
    return verdict("blocked (unknown_app: a terminal is not a known app; the protected-process list is the second"
                   " guard, covered by tests/test_team1_bridge.py)", res.get("reject_code") == "unknown_app")


def s6(st, out):
    max_age = max(15.0, float(os.getenv("NELLY_MAX_OBS_AGE", "15")))
    age = max_age + STALE_EXTRA_S
    print(f"S6 stale: observation {age:.0f} s old (Team 1's executor checks 15 s; NELLY_MAX_OBS_AGE={max_age:.0f})")
    hwnd = _target(st)
    if live and not hwnd:
        print("   STOP: no test Notepad (run S1 first)")
        return verdict("stale", False, "not run")
    if hwnd:
        print(f"   Team 1 coordinate manager now: {preview_point(build_observation(hwnd, age))}")
    if not ask("Ask to type into Notepad with that old observation?"):
        return verdict("stale", False, "skipped by the user")
    if hwnd:
        before_text = read_text(hwnd) if live else None
        req, res = with_one_refocus(lambda: request("type", "Notepad", {"text": TEXT}, "e1",
                                                    build_observation(hwnd, age)))
    else:
        res = run(request("type", "Notepad", {"text": TEXT}, "e1", {"screenshot_id": "dry-placeholder"}))
    if live:
        after_text = read_text(hwnd)
        return verdict("blocked stale, Notepad text unchanged",
                       res.get("reject_code") == "stale" and after_text == before_text)
    return verdict("dry_run (the age check only runs live)", res["status"] == "success" and res["output"]["dry_run"])


def s7(st, out):
    print("S7 stop (explained only, not run by this script)")
    print("   To test: run S2 live and press Ctrl+C in this terminal while the text is being typed (or move the mouse")
    print("   into a screen corner). Expected: the receipt says cancelled ('stopped by the user'), the rest of the text")
    print("   is not typed, and Ctrl/Shift/Alt/Win are released (key-ups). Note: with the clipboard paste the text")
    print("   arrives in one Ctrl+V, so there is almost no time to stop it; key-by-key typing is slower.")
    return verdict("explained", True)


def cleanup(st, out):
    print("cleanup: read back the test Notepad and close it with WM_CLOSE (never saves)")
    hwnd = st.notepad
    if not hwnd:
        print("   no test Notepad recorded or it is already closed")
        return verdict("nothing to close", True)
    print(f"   Notepad text now: {read_text(hwnd)!r}")
    if not ask("Close the test Notepad (WM_CLOSE, no save)?"):
        return verdict("closed", False, "skipped by the user")
    before = set(_windows("#32770", "notepad.exe"))
    ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    time.sleep(1.5)
    dialog = [h for h in _windows("#32770", "notepad.exe") if h not in before]
    if _alive(hwnd) and dialog:
        print("   Notepad asked whether to save (dialog left open, as agreed): please choose 'Don't Save'")
        return verdict("closed without saving", False, "save dialog is open")
    return verdict("closed without saving", not _alive(hwnd))


def screenshot(st, out):
    from PIL import ImageGrab
    path = os.path.join(out, f"screen_{time.strftime('%H%M%S')}.png")
    ImageGrab.grab(all_screens=True).save(path)
    print(f"screenshot saved: {path}")
    return True


STEPS = {"S1": s1, "S2": s2, "S3": s3, "S4": s4, "S5": s5, "S6": s6, "S7": s7, "cleanup": cleanup,
         "screenshot": screenshot}


def main():
    global live
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--step", default="all", help="S1..S7, cleanup, screenshot, or all (S1..S7)")
    ap.add_argument("--out", default=os.path.join(os.getenv("TEMP", "."), "team1_executor_check"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    from nelly_vision.capture import set_dpi_awareness
    set_dpi_awareness()                                     # before any window call (Team 1 rule)
    live = B.live_requested()
    print(f"MODE: {'LIVE (real input; each step asks y/n)' if live else 'DRY RUN (nothing is clicked or typed)'}"
          f"  executor: Team 1 via execution/team1_bridge.py  policy mode: {os.getenv('NELLY_POLICY_MODE', 'standard')}")
    print("Note: this script calls the bridge directly; the safety gate is not in this path, the y/n is.")
    print(f"in front now: {_foreground()[0]}\n")
    st = State(a.out)
    names = ["S1", "S2", "S3", "S4", "S5", "S6", "S7"] if a.step == "all" else [a.step]
    results = []
    for n in names:
        try:
            results.append((n, STEPS[n](st, a.out)))
        except KeyboardInterrupt:
            print("   stopped with Ctrl+C")
            results.append((n, False))
            break
        print()
    print("SUMMARY: " + "  ".join(f"{n} {'PASS' if ok else 'FAIL'}" for n, ok in results))
    return 0 if all(ok for _, ok in results) else 1


if __name__ == "__main__":
    sys.exit(main())
