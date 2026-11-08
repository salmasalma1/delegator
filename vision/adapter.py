"""
Vision Adapter — orchestrator side of the orchestrator <-> vision (Vision/Execution) boundary.

Two jobs only:
  1. NORMALIZE  — one shape for real Vision and for fallback (so the worker never breaks).
  2. QUALITY GATE — decide if the grounding is trustworthy enough for the Brain to act on.
     If not, the Orchestrator must re-perceive / ask / escalate — never act blind.
"""
from typing import Optional

TOP_N = 30

# --- shapes -----------------------------------------------------------------

def _bbox_norm(bbox: dict, screen: Optional[dict]) -> list:
    """
    Absolute bbox -> normalized [x, y, w, h] (window-relative, 0..1).
    Top-left origin, matching the vision module's BoundingBox {x, y, width, height}
    (02_VisionResult.schema.json). This is the ONE canonical format across all teams.
    """
    sw = (screen or {}).get("width") or 1920
    sh = (screen or {}).get("height") or 1080
    x, y, w, h = (float(bbox.get(k, 0)) for k in ("x", "y", "width", "height"))
    return [round(x / sw, 4), round(y / sh, 4), round(w / sw, 4), round(h / sh, 4)]


def _center_norm(bbox_norm: list) -> list:
    """[x,y,w,h] -> [cx,cy] for anything that needs a click point."""
    x, y, w, h = bbox_norm
    return [round(x + w / 2, 4), round(y + h / 2, 4)]


def _center_abs(bbox: dict) -> list:
    x, y, w, h = (float(bbox.get(k, 0)) for k in ("x", "y", "width", "height"))
    return [round(x + w / 2, 1), round(y + h / 2, 1)]


def _norm_element(raw: dict, idx: int, screen: Optional[dict]) -> dict:
    """Accepts the contract shape AND the legacy fallback shape. Never raises."""
    bbox = raw.get("bbox") if isinstance(raw.get("bbox"), dict) else None
    if bbox:
        bbox_norm = _bbox_norm(bbox, screen)
        center = _center_abs(bbox)
    else:  # already normalized [x,y,w,h]
        bbox_norm = list(raw.get("bbox_norm") or [0, 0, 0, 0])
        center = None
    conf = raw.get("confidence", raw.get("conf", 0.0))
    known = {"element_id", "type", "text", "bbox", "bbox_norm", "confidence", "conf",
             "interactable", "source"}
    extra = {k: v for k, v in raw.items() if k not in known}
    return {
        "element_id": raw.get("element_id") or f"el_{idx}",
        "type": raw.get("type") or raw.get("label") or "unknown",
        "text": raw.get("text"),
        "bbox_norm": bbox_norm,                  # [x, y, w, h] — canonical, all teams
        "center_norm": _center_norm(bbox_norm),  # [cx, cy] for click targets
        "center_abs": center,
        "confidence": round(float(conf), 3),
        "interactable": bool(raw.get("interactable", True)),
        "source": raw.get("source") or "unknown",
        # vision flags: a VLM mark is "grounded" only with independent evidence (see the vision module v2 report).
        "confirmed": extra.get("confirmed"),
        "ambiguous": extra.get("ambiguous"),
        "extra": extra,
    }


# --- quality gate -----------------------------------------------------------

BLUR_HINTS = ("blur", "unclear", "low contrast", "illegible", "smudge", "not clear")
UNKNOWN_APP_HINTS = ("unknown", "none", "null", "")


def assess_quality(raw: dict, elements: list) -> dict:
    """
    Deterministic (not model-based) readability check on the grounding.
    A VLM never decides 'is this clear' for us — it only supplies confidences,
    and the Orchestrator applies fixed thresholds (auditable + repeatable).
    """
    reasons, score = [], 1.0

    if raw.get("status") == "failed":
        reasons.append("perception_failed")
        score = 0.0
    elif raw.get("status") == "partial":
        reasons.append("perception_partial")
        score -= 0.3

    if not elements:
        reasons.append("no_elements")
        score = 0.0

    if elements:
        avg = sum(e["confidence"] for e in elements) / len(elements)
        low = sum(1 for e in elements if e["confidence"] < 0.5) / len(elements)
        if avg < 0.45:
            reasons.append(f"low_avg_confidence:{avg:.2f}")
            score -= 0.4
        if low > 0.7:
            reasons.append(f"mostly_low_confidence:{low:.0%}")
            score -= 0.3
        if not any(e["interactable"] for e in elements):
            reasons.append("no_interactable_elements")
            score -= 0.2

    for w in raw.get("warnings") or []:
        if any(h in str(w).lower() for h in BLUR_HINTS):
            reasons.append(f"vision_warning:{w}")
            score -= 0.3

    unconfirmed = [e for e in elements
                   if e.get("confirmed") is False or e.get("ambiguous") is True]
    if unconfirmed:
        reasons.append(f"unconfirmed_marks:{len(unconfirmed)}/{len(elements)}")
        score -= 0.35

    app = raw.get("application")
    if app is not None and str(app).strip().lower() in UNKNOWN_APP_HINTS:
        reasons.append("app_not_identified")
        score -= 0.1

    score = max(0.0, min(1.0, round(score, 2)))
    return {"clear": score >= 0.6 and not reasons.count("perception_failed"), "score": score, "reasons": reasons}


# --- main entry -------------------------------------------------------------

def normalize(raw: Optional[dict], screen: Optional[dict] = None,
              source: str = "nelly_vision") -> dict:
    """
    raw -> grounding context consumed by Director/worker.
    Never raises: a broken Vision payload becomes status=failed + needs_review=True.
    """
    if not isinstance(raw, dict):
        return {
            "app": None, "window_title": None, "status": "failed", "elements": [],
            "truncated": False, "warnings": ["empty_vision_payload"], "error": "no_vision_payload",
            "quality": {"clear": False, "score": 0.0, "reasons": ["no_vision_payload"]},
            "needs_review": True, "vision_source": source,
        }

    raw_elements = raw.get("elements") or []
    elements = [_norm_element(e, i, screen) for i, e in enumerate(raw_elements) if isinstance(e, dict)]
    elements.sort(key=lambda e: (not e["interactable"], -e["confidence"]))
    top = elements[:TOP_N]

    quality = assess_quality(raw, top)
    warnings = list(raw.get("warnings") or [])
    extra_keys = sorted({k for e in top for k in (e.get("extra") or {})})
    if extra_keys:
        warnings.append(f"element_extra_keys:{extra_keys}")

    return {
        "app": raw.get("application"),
        "window_title": raw.get("window_title"),
        "status": raw.get("status", "success"),
        "elements": top,
        "truncated": len(elements) > TOP_N,
        "warnings": warnings,
        "error": raw.get("error"),
        "quality": quality,
        "needs_review": (not quality["clear"]) or raw.get("status") == "failed",
        "vision_source": source,
    }


# --- fallback (standalone testing only, same contract shape) ----------------

def fallback_result(app: str, target: str = "button") -> dict:
    """Contract-compliant VisionResult so fallback and real Vision share ONE shape."""
    return {
        "request_id": "fallback-req",
        "task_id": "fallback-task",
        "status": "success",
        "application": app,
        "window_title": f"{app} (fallback grounding)",
        "elements": [{
            "element_id": "el_fallback_0",
            "type": "button",
            "text": target,
            "bbox": {"x": 595, "y": 486, "width": 154, "height": 43},
            "confidence": 0.82,
            "interactable": True,
            "source": "unknown",
        }],
        "warnings": ["fallback_grounding: not real perception"],
        "error": None,
    }


# --- prompt compaction (what the Brain actually sees) -----------------------

def to_prompt(ctx: Optional[dict], limit: int = TOP_N) -> str:
    """Compact grounding text for the LLM. Keeps tokens low, keeps IDs stable."""
    if not isinstance(ctx, dict):
        return "no grounding"
    lines = [
        f"app={ctx.get('app')} window={ctx.get('window_title')} "
        f"status={ctx.get('status')} quality={ctx.get('quality', {}).get('score')} "
        f"needs_review={ctx.get('needs_review')}",
    ]
    for e in (ctx.get("elements") or [])[:limit]:
        lines.append(
            f"- {e['element_id']} [{e['type']}] text={e['text']!r} "
            f"bbox_norm={e['bbox_norm']} conf={e['confidence']} "
            f"interactable={e['interactable']} src={e['source']}"
        )
    if ctx.get("warnings"):
        lines.append(f"warnings={ctx['warnings']}")
    return "\n".join(lines)
