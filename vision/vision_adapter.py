"""
The ONE place that touches Team 1's vision package. Everything else in the repo goes through here.

Contract:
    available() -> bool
    observe(screenshot=None, target=None, allow_vlm=False) -> dict   # a ScreenObservation (v0.3)
        raises on any failure; the caller turns that into needs_review (never a silent fake screen).

Rules:
  * the vision package is INSTALLED (pip install), never imported from a folder path
  * allow_vlm defaults to False: screenshots must not leave the machine unless we say so
  * fields are returned exactly as Team 1 names them; nothing is renamed or converted here
"""
import os

_perceiver = [None]
_last = [None]                  # the last observation object (the coordinate manager needs it, not a dict)


class TargetRejected(Exception):
    """Team 1 refused a click point. `.code` is their reason: stale, window_gone, window_resized, off_screen..."""
    def __init__(self, message="rejected", code="rejected"):
        super().__init__(message)
        self.code = code


def _import_perceiver():
    """Single import point. If Team 1 renames the package/class, change only these lines."""
    from nelly_vision import Perceiver          # noqa: PLC0415
    return Perceiver


def available() -> bool:
    if os.getenv("NELLY_VISION", "").lower() in ("off", "0", "fake"):
        return False
    try:
        _import_perceiver()
        return True
    except Exception:                            # noqa: BLE001
        return False


def _get():
    if _perceiver[0] is None:
        _perceiver[0] = _import_perceiver()()
    return _perceiver[0]


def observe(screenshot=None, target=None, allow_vlm: bool = False) -> dict:
    """One screen -> ScreenObservation 0.3 as a JSON-able dict. Raises on any failure.
    `screenshot` is a path / PIL image; None captures the real screen (monitor of the foreground window)."""
    from nelly_vision.capture import capture_screen, new_screenshot_id   # noqa: PLC0415
    p = _get()
    if screenshot is None:
        image, screen, window = capture_screen()
    else:
        image, screen, window = screenshot, None, None
    res = p.perceive_detailed(image, target=target, screen=screen, window=window,
                              screenshot_id=new_screenshot_id(), allow_vlm=allow_vlm)
    obs = getattr(res, "observation", None)
    if obs is None:
        raise RuntimeError("nelly_vision returned no observation")
    data = obs.model_dump(mode="json")
    if data.get("schema_version") != "0.3":
        raise ValueError(f"expected ScreenObservation 0.3, got schema_version={data.get('schema_version')!r}")
    # what the coordinate manager needs later to turn a box into a click point
    _last[0] = {"observation": obs, "screen": screen, "window": window, "screenshot_id": data.get("screenshot_id")}
    return data


def resolve_point(element_id, bbox_norm, observation_id=None):
    """
    (x, y) screen pixels for ONE element, from Team 1's CoordinateManager.resolve_target_point().
    Uses the last observation seen by observe() (kept in _last). Never computes pixels from the box itself.
    Must raise TargetRejected(code=...) when Team 1 refuses (stale, window_gone, window_resized, off_screen...).
    NOT WIRED YET: needs the real CoordinateManager signature.
    """
    raise NotImplementedError("resolve_point is not wired to nelly_vision.CoordinateManager yet")
