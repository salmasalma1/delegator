"""
Boundary check for Team 1's ScreenObservation (v0.3).
Structural only: we check what WE rely on. Team 1 owns the full schema; a failure here is a
CONTRACT failure on their side of the boundary, not a bug in the orchestrator.
"""
from typing import Tuple

SUPPORTED_MAJOR_MINOR = ("0.3",)


def validate_observation(raw) -> Tuple[bool, list]:
    """Returns (ok, errors). Never raises."""
    errs = []
    if not isinstance(raw, dict):
        return False, [f"observation is {type(raw).__name__}, not a dict"]
    ver = str(raw.get("schema_version") or "")
    if not any(ver.startswith(v) for v in SUPPORTED_MAJOR_MINOR):
        errs.append(f"schema_version {ver!r} not in {SUPPORTED_MAJOR_MINOR}")
    els = raw.get("elements")
    if not isinstance(els, list):
        return False, errs + ["elements missing or not a list"]
    seen = set()
    for i, e in enumerate(els):
        if not isinstance(e, dict):
            errs.append(f"elements[{i}] not an object")
            continue
        if not e.get("id"):
            errs.append(f"elements[{i}] has no id")
        elif e["id"] in seen:
            errs.append(f"duplicate element id {e['id']}")
        seen.add(e.get("id"))
        b = e.get("bbox_norm")
        if not (isinstance(b, (list, tuple)) and len(b) == 4 and all(isinstance(v, (int, float)) for v in b)):
            errs.append(f"elements[{i}] bbox_norm is not 4 numbers")
        elif not (0 <= b[0] < b[2] <= 1 and 0 <= b[1] < b[3] <= 1):
            errs.append(f"elements[{i}] bbox_norm not [x1,y1,x2,y2] inside 0..1: {b}")
        if e.get("clickable") not in (True, False, "unknown"):
            errs.append(f"elements[{i}] clickable must be true/false/'unknown'")
    return (not errs), errs
