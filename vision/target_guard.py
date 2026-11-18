"""
Target guard: a pointer target must lie inside the window of the application the step names.

    check_target(element, observation, app, live) -> (ok, reason)

`observation` is a ScreenObservation dict or the worker's context: it needs `window` (process, bounds) and
`screen` (w, h, left, top), exactly as Team 1 names them. A refusal reason always starts with
"target_outside_window". Used by the worker (before Safety and the executor) and by the Team 1 bridge.

Why: grounding can pick an element of ANOTHER window on the screen (the capture is the whole monitor), and Team 1's
CoordinateManager accepts points outside the observed window, so the click would land in a different app.
"""
from typing import Optional, Tuple

REASON = "target_outside_window"

# Application name (as the planner / schema writes it) -> process names of its windows, without ".exe".
APP_PROCESSES = {
    "notepad": {"notepad"},
    "file explorer": {"explorer"},
    "explorer": {"explorer"},
    "calculator": {"calculatorapp", "calculator"},
    "chrome": {"chrome"},
    "google chrome": {"chrome"},
    "edge": {"msedge"},
    "microsoft edge": {"msedge"},
}


def _norm_proc(name) -> str:
    n = str(name or "").strip().lower()
    return n[:-4] if n.endswith(".exe") else n


def app_processes(app) -> set:
    """Process names (no .exe) of a known application; empty when the application is unknown."""
    return APP_PROCESSES.get(str(app or "").strip().lower(), set())


def _centre_px(element: dict, screen: dict) -> Optional[Tuple[float, float]]:
    box = element.get("bbox_norm")
    if not box or not screen or not screen.get("w") or not screen.get("h"):
        return None
    x1, y1, x2, y2 = box
    return (screen.get("left", 0) + (x1 + x2) / 2 * screen["w"],
            screen.get("top", 0) + (y1 + y2) / 2 * screen["h"])


def check_target(element: Optional[dict], observation: Optional[dict], app: Optional[str],
                 live: bool) -> Tuple[bool, Optional[str]]:
    """(True, None) when the target may be used; (False, "target_outside_window: ...") when it may not.
    Live runs must PROVE the target is inside the app's window; a dry run on a fake / file screen without
    window bounds is allowed (nothing can be clicked)."""
    if not element:
        return True, None
    obs = observation or {}
    window = obs.get("window") or {}
    eid = element.get("id") or element.get("element_id")

    procs = app_processes(app)
    seen = _norm_proc(window.get("process"))
    if procs and seen and seen not in procs:
        return False, (f"{REASON}: the screen was read from {window.get('process')!r}, not {app!r}; "
                       f"element {eid} belongs to another window")

    bounds = window.get("bounds")
    centre = _centre_px(element, obs.get("screen") or {})
    if not bounds or centre is None:
        if live:
            return False, (f"{REASON}: window bounds unknown, cannot prove that element {eid} is inside "
                           f"{app or 'the target app'}")
        return True, None
    left, top, right, bottom = bounds
    cx, cy = centre
    if not (left <= cx <= right and top <= cy <= bottom):
        return False, (f"{REASON}: element {eid} centre ({cx:.0f}, {cy:.0f}) is outside the "
                       f"{window.get('process') or 'target'} window {list(bounds)}")
    return True, None
