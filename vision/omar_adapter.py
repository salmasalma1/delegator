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
    p = _get()
    obs = p.observe(screenshot=screenshot, allow_vlm=allow_vlm) if screenshot is not None \
        else p.observe(allow_vlm=allow_vlm)
    return obs.model_dump() if hasattr(obs, "model_dump") else (obs.dict() if hasattr(obs, "dict") else obs)
