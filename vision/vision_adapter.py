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
import threading

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


DEFAULT_VISION_TIMEOUT_S = 180.0
_gen = [0]                       # call counter: a call that timed out must not overwrite a newer result
_busy = threading.Lock()         # one perception at a time (the Perceiver holds models and frame caches)


def vision_timeout():
    """F5: seconds one observe() may take (NELLY_VISION_TIMEOUT, default 180; 0 or less = no limit)."""
    raw = os.getenv("NELLY_VISION_TIMEOUT")
    if raw is None:
        return DEFAULT_VISION_TIMEOUT_S
    try:
        v = float(raw)
    except ValueError:
        return DEFAULT_VISION_TIMEOUT_S
    return v if v > 0 else None


def observe(screenshot=None, target=None, allow_vlm: bool = False) -> dict:
    """One screen -> ScreenObservation 0.3 as a JSON-able dict. Raises on any failure, and TimeoutError when it
    takes longer than NELLY_VISION_TIMEOUT (the step then stops as needs_review instead of hanging).
    `screenshot` is a path / PIL image; None captures the real screen (monitor of the foreground window)."""
    _gen[0] += 1
    gen, limit = _gen[0], vision_timeout()
    box = {}

    def run():
        if not _busy.acquire(timeout=limit if limit else -1):
            box["error"] = TimeoutError(f"a previous vision call is still running after {limit:.0f} s "
                                        "(NELLY_VISION_TIMEOUT)")
            return
        try:
            box["data"] = _observe_once(screenshot=screenshot, target=target, allow_vlm=allow_vlm, gen=gen)
        except BaseException as e:                                     # noqa: BLE001  (re-raised below)
            box["error"] = e
        finally:
            _busy.release()

    if limit is None:
        run()
    else:
        worker = threading.Thread(target=run, name="nelly-vision", daemon=True)
        worker.start()
        worker.join(limit)
        if worker.is_alive():
            _gen[0] += 1                                 # abandon this call: its late result is never stored
            raise TimeoutError(f"vision took longer than {limit:.0f} s (NELLY_VISION_TIMEOUT)")
    if "error" in box:
        raise box["error"]
    return box["data"]


def _accepts_source(perceiver) -> bool:
    """True when this Perceiver's perceive_detailed takes a `source` argument (older packages do not)."""
    import inspect                                                        # noqa: PLC0415
    try:
        params = inspect.signature(perceiver.perceive_detailed).parameters
    except (TypeError, ValueError):
        return False
    return "source" in params or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def _observe_once(screenshot=None, target=None, allow_vlm: bool = False, gen=None) -> dict:
    from vision.env_check import ensure_memory_for_ocr                   # noqa: PLC0415
    ensure_memory_for_ocr()                 # F6: below the safe level OCR is never started (it crashed the process)
    from nelly_vision import capture as _cap                              # noqa: PLC0415
    capture_screen, new_screenshot_id = _cap.capture_screen, _cap.new_screenshot_id
    p = _get()
    if screenshot is None:
        # NELLY_CAPTURE=window: only the foreground window is read (smaller picture = a much faster OCR).
        # Team 1's capture_window keeps the crop origin, so points still map back to the screen; it falls back
        # to the whole screen by itself when the window has no readable bounds.
        use_window = os.getenv("NELLY_CAPTURE", "").lower() == "window" and hasattr(_cap, "capture_window")
        image, screen, window = _cap.capture_window() if use_window else capture_screen()
    else:
        image, screen, window = screenshot, None, None
    kwargs = dict(target=target, screen=screen, window=window, screenshot_id=new_screenshot_id(),
                  allow_vlm=allow_vlm)
    if screenshot is None and _accepts_source(p):
        # Team 1's newer Perceiver marks every observation "offline_image" unless the caller says it came from a
        # live capture, and its CoordinateManager then refuses to turn any box into a click point.
        kwargs["source"] = "live_capture"
    res = p.perceive_detailed(image, **kwargs)
    obs = getattr(res, "observation", None)
    if obs is None:
        raise RuntimeError("nelly_vision returned no observation")
    data = obs.model_dump(mode="json")
    if data.get("schema_version") != "0.3":
        raise ValueError(f"expected ScreenObservation 0.3, got schema_version={data.get('schema_version')!r}")
    # what the coordinate manager needs later to turn a box into a click point
    grounding = getattr(res, "grounding", None)          # F3: Team 1's own answer for `target`, when it gives one
    if gen is not None and gen != _gen[0]:
        return data                                      # this call timed out and a newer one started: keep _last
    _last[0] = {"observation": obs, "screen": screen, "window": window, "screenshot_id": data.get("screenshot_id"),
                "grounding": grounding.model_dump(mode="json") if grounding is not None else None}
    return data


def last_grounding():
    """Team 1's GroundingResult (as a dict) for the target of the last observe() call, or None."""
    last = _last[0]
    return (last or {}).get("grounding")


def resolve_point(element_id, bbox_norm, observation_id=None):
    """
    (x, y) screen pixels for ONE element, from Team 1's CoordinateManager.resolve_target_point().
    Uses the last observation seen by observe() (kept in _last). Never computes pixels from the box itself.
    Must raise TargetRejected(code=...) when Team 1 refuses (stale, window_gone, window_resized, off_screen...).

    Team 1: CoordinateManager().resolve_target_point(obs, element_id=None, *, bbox_norm=None, anchor=None,
    now=None) -> ScreenPoint (virtual-desktop physical px). element_id wins over bbox_norm when both are given.
    Their codes: dpi_unaware, stale (default max age 15 s from obs.captured_at), unknown_element, no_target,
    invalid_bbox, frame_mismatch, window_gone, window_minimized, window_resized, off_screen, off_window.
    Ours (no Team 1 call made): no_observation, observation_mismatch.
    """
    last = _last[0]
    if last is None:
        raise TargetRejected("no observation yet: call observe() before resolving a point", code="no_observation")
    if observation_id is not None and observation_id != last["screenshot_id"]:
        raise TargetRejected(f"observation {observation_id!r} is not the last one seen "
                             f"({last['screenshot_id']!r}): re-perceive", code="observation_mismatch")
    from nelly_vision import CoordinateManager, TargetRejected as VisionRejected   # noqa: PLC0415
    try:
        # 15 s is Team 1's default. A human approval or a slow model between "look" and "click" can exceed it;
        # raise it for a test with NELLY_MAX_OBS_AGE (window moves/resizes are still checked by Team 1).
        max_age = float(os.getenv("NELLY_MAX_OBS_AGE", "15"))
        point = CoordinateManager(max_age_s=max_age).resolve_target_point(
            last["observation"], element_id, bbox_norm=bbox_norm)
    except VisionRejected as e:
        raise TargetRejected(str(e), code=e.code) from e
    return point.x, point.y
