"""
INTERIM executor. Replaces nothing: it stands in until Team 1 delivers theirs.

    execute(request: dict) -> dict      # request = 03_ExecutionRequest, result = 04_ExecutionResult

Rules this file keeps (the worker and Safety rely on them):
  * it is LABELLED interim: strategy_used = "interim_pyautogui"
  * it never judges success: verification_status is always "not_verified" (Verify decides, from a new screenshot)
  * it NEVER computes pixels from a box. The click point comes from Team 1's coordinate manager through
    vision.vision_adapter.resolve_point(); if that is not wired or refuses (stale, window moved...), nothing is clicked
  * only click / type / press / open_app are implemented. open_app starts ONLY the programs in OPENABLE, by name. Anything else is reported as "failed: not supported", never faked
  * stop switch is checked first; the pyautogui corner failsafe is ON (mouse to a screen corner = stop everything)
  * DRY RUN IS THE DEFAULT: nothing moves unless NELLY_LIVE_INPUT=1 is set (and pyautogui exists); the result says dry_run
  * typed text is never written to the result
"""
import os
import tempfile
import time

from graph import control

STRATEGY = "interim_pyautogui"
SUPPORTED = ("click", "type", "press", "open_app")
# The model NEVER supplies a command, only an app NAME. Only these names can be started.
OPENABLE = {"notepad": "notepad.exe", "file explorer": "explorer.exe", "explorer": "explorer.exe",
            "calculator": "calc.exe"}
OPEN_WAIT_S = float(os.getenv("NELLY_OPEN_WAIT", "2.5"))     # let the new window appear and take focus
PAUSE_S = float(os.getenv("NELLY_ACTION_PAUSE", "0.4"))
SETTLE_S = float(os.getenv("NELLY_SETTLE", "0.6"))        # let the UI react before the "after" screenshot


def _load_pyautogui():
    try:
        import pyautogui                                   # noqa: PLC0415
        pyautogui.FAILSAFE = True                          # mouse to a corner = FailSafeException
        pyautogui.PAUSE = PAUSE_S
        return pyautogui
    except Exception:                                      # noqa: BLE001
        return None


def live_requested() -> bool:
    """Real mouse and keyboard only when asked for, in writing: NELLY_LIVE_INPUT=1 (and NELLY_DRY_RUN not set)."""
    on = lambda k: os.getenv(k, "").lower() in ("1", "true", "yes")          # noqa: E731
    return on("NELLY_LIVE_INPUT") and not on("NELLY_DRY_RUN")


def _dry_requested() -> bool:
    return not live_requested()


def _result(req, status, t0, error=None, **output):
    return {"action_id": req.get("action_id"), "task_id": req.get("task_id"), "status": status,
            "verification_status": "not_verified", "strategy_used": STRATEGY,
            "duration_ms": int((time.time() - t0) * 1000), "output": output, "error": error,
            "screenshot_after_ref": output.pop("_shot", None)}


def _point(req):
    """Click point from Team 1's coordinate manager. Returns ((x, y), None) or (None, (code, text))."""
    from vision import vision_adapter                      # noqa: PLC0415
    params = req.get("parameters") or {}
    try:
        return vision_adapter.resolve_point(req.get("target_element_id"), params.get("bbox_norm"),
                                            req.get("observation_id")), None
    except vision_adapter.TargetRejected as e:
        return None, (getattr(e, "code", "rejected"), str(e))
    except NotImplementedError as e:
        return None, ("resolver_not_wired", str(e))
    except Exception as e:                                 # noqa: BLE001
        return None, ("resolver_error", f"{type(e).__name__}: {e}")


def _shot(pg, req):
    try:
        d = os.path.join(os.getenv("NELLY_SHOTS_DIR") or tempfile.gettempdir(), "nelly_shots")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{req.get('action_id')}.png")
        time.sleep(SETTLE_S)
        pg.screenshot(path)
        return path
    except Exception:                                      # noqa: BLE001
        return None


def _type_text(pg, text: str):
    if text.isascii():
        pg.write(text, interval=0.02)
        return None
    try:                                                    # non-ASCII (Arabic...) goes through the clipboard
        import pyperclip                                    # noqa: PLC0415
        pyperclip.copy(text)
        pg.hotkey("ctrl", "v")
        return None
    except Exception as e:                                  # noqa: BLE001
        return f"non-ASCII text needs pyperclip ({type(e).__name__})"


def _open_app(req, params, pg, dry, t0):
    name = str(params.get("app") or "").strip().lower()
    exe = OPENABLE.get(name)
    if not exe:
        return _result(req, "failed", t0, f"app {name!r} is not in the interim executor's list {sorted(OPENABLE)}",
                       reject_code="app_not_allowed")
    if dry:
        return _result(req, "success", t0, None, dry_run=True, would_open=exe,
                       dry_run_reason="set NELLY_LIVE_INPUT=1 to act for real" if _dry_requested() else "pyautogui missing")
    try:
        import subprocess                                   # noqa: PLC0415
        subprocess.Popen([exe])                             # fixed program name from OPENABLE, no shell, no arguments
        time.sleep(OPEN_WAIT_S)
    except Exception as e:                                  # noqa: BLE001
        return _result(req, "failed", t0, f"{type(e).__name__}: {e}", reject_code="executor_error")
    return _result(req, "success", t0, None, opened=exe, _shot=_shot(pg, req))


def execute(req: dict) -> dict:
    t0 = time.time()
    action = (req.get("action_type") or "").lower()
    params = req.get("parameters") or {}

    if control.cancelled():
        return _result(req, "cancelled", t0, "stopped before acting")
    if action not in SUPPORTED:
        return _result(req, "failed", t0, f"{action!r} is not supported by the interim executor",
                       reject_code="unsupported_action")

    pg = _load_pyautogui()
    dry = _dry_requested() or pg is None

    if action == "open_app":
        return _open_app(req, params, pg, dry, t0)

    point, rejected = (None, None)
    if action in ("click", "type"):
        point, rejected = _point(req)
        if rejected and not dry:
            code, text = rejected
            return _result(req, "failed", t0, f"target rejected ({code}): {text}", reject_code=code)

    if dry:
        out = {"dry_run": True, "dry_run_reason": "set NELLY_LIVE_INPUT=1 to act for real" if _dry_requested() else "pyautogui missing"}
        if point:
            out["screen_point"] = list(point)              # what WOULD be clicked: the thing to check in a dry run
        if rejected:
            out["point_error"] = f"{rejected[0]}: {rejected[1]}"
        return _result(req, "success", t0, None, **out)

    try:
        if action == "click":
            pg.click(point[0], point[1])
        elif action == "type":
            if "text" not in params:
                return _result(req, "failed", t0, "type without text", reject_code="bad_request")
            pg.click(point[0], point[1])                   # focus the field first
            err = _type_text(pg, str(params["text"]))
            if err:
                return _result(req, "failed", t0, err, reject_code="unsupported_text")
        elif action == "press":
            keys = params.get("keys") or []
            if not keys:
                return _result(req, "failed", t0, "press without keys", reject_code="bad_request")
            pg.hotkey(*keys) if len(keys) > 1 else pg.press(keys[0])
    except pg.FailSafeException:
        control.cancel()                                   # corner failsafe = stop the whole run
        return _result(req, "cancelled", t0, "failsafe: mouse moved to a screen corner")
    except Exception as e:                                 # noqa: BLE001
        return _result(req, "failed", t0, f"{type(e).__name__}: {e}", reject_code="executor_error")

    out = {"screen_point": list(point)} if point else {}
    out["_shot"] = _shot(pg, req)
    return _result(req, "success", t0, None, **out)
