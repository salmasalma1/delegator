"""
Executor check WITHOUT vision: does our interim executor really move the mouse / type / open an app on THIS machine?

It replaces Team 1's point resolver with a fixed pixel, so a failure here is NOT a vision problem.
  python tools/executor_check.py                 # dry run: prints what it WOULD do
  set NELLY_LIVE_INPUT=1  (Windows)              # real input; each step asks y/n first
  python tools/executor_check.py --x 800 --y 500 # where the test click goes (default: screen centre)

Steps: 1 open Notepad  2 click inside it + type "hello Lumi"  3 click at (x, y) and read the real mouse position back.
Stop any time: Ctrl+C, or throw the mouse into a screen corner (pyautogui failsafe).
"""
import argparse, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("NELLY_PERSIST", "0")
from execution import desktop_adapter as X
from vision import vision_adapter as V


def _req(action, **params):
    return {"action_id": f"chk-{action}", "task_id": "executor-check", "action_type": action,
            "target_element_id": "e1", "application": "Notepad", "parameters": params, "observation_id": "chk"}


def _window_centre(class_name="Notepad"):
    """Windows only: centre of the first window of this class (so the click lands INSIDE it). None if not found."""
    try:
        import ctypes                                       # noqa: PLC0415
        from ctypes import wintypes                         # noqa: PLC0415
        u = ctypes.windll.user32
        hwnd = u.FindWindowW(class_name, None)
        if not hwnd:
            return None
        r = wintypes.RECT()
        u.GetWindowRect(hwnd, ctypes.byref(r))
        return (r.left + r.right) // 2, (r.top + r.bottom) // 2
    except Exception:                                       # noqa: BLE001
        return None


def _ask(text):
    return input(f"  {text} [y/N] ").strip().lower() == "y"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--x", type=int)
    ap.add_argument("--y", type=int)
    a = ap.parse_args()
    live = X.live_requested()
    print("LIVE (real mouse + keyboard)" if live else "DRY RUN (nothing moves). Set NELLY_LIVE_INPUT=1 for real input.")

    pg = X._load_pyautogui()
    if pg is None and live:
        print("pyautogui is not installed -> executor cannot act for real."); return 1
    w, h = pg.size() if pg else (1920, 1080)
    x, y = (a.x if a.x is not None else w // 2), (a.y if a.y is not None else h // 2)
    point = [x, y]
    V.resolve_point = lambda *args, **kw: tuple(point)      # fixed pixel: vision is NOT involved in this check
    print(f"screen {w}x{h}, test click point ({x},{y})")

    results = []

    def step(name, req, ask, verify=None):
        if live and not _ask(ask):
            results.append((name, "skipped by you")); return
        r = X.execute(req)
        out = r.get("output") or {}
        line = f"{r.get('status')}" + (f" reject={out.get('reject_code')}" if out.get("reject_code") else "")
        if out.get("dry_run"):
            line += " (dry run)"
        if r.get("error"):
            line += f" error={r['error']}"
        if verify and live and r.get("status") == "success":
            line += " | " + verify()
        results.append((name, line)); print(f"  -> {name}: {line}")
        if r.get("status") == "cancelled":
            raise SystemExit("cancelled (Ctrl+C / corner)")

    step("open_app Notepad", _req("open_app", app="Notepad"), "Open Notepad now?")
    if live:
        time.sleep(1.0)
    # The executor clicks the point first (to focus the field) and then types. So the point must be INSIDE Notepad.
    if a.x is None and a.y is None:
        c = _window_centre()
        if c:
            x, y = c
            point[:] = [x, y]
            print(f"found the Notepad window, using its centre ({x},{y}) for the type + click steps")
        else:
            print("WARNING: no Notepad window found; the click may land on another window (use --x/--y)")
    step("type text", _req("type", text="hello Lumi"), f"Click ({x},{y}) to focus, then type 'hello Lumi'?")
    step("click", _req("click", bbox_norm=[0.1, 0.1, 0.2, 0.2]), f"Click at ({x},{y})?",
         verify=lambda: f"mouse is now at {tuple(pg.position())} (asked {x},{y})")

    print("\nSUMMARY")
    for n, l in results:
        print(f" - {n}: {l}")
    print("\nLook at the screen: is Notepad open and does it say 'hello Lumi'? That is the real proof (the result"
          " is always 'not_verified').")
    return 0


if __name__ == "__main__":
    sys.exit(main())
