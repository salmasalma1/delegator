"""
Vision adapter — the orchestrator side of the Team 1 vision boundary.

The contract is Team 1's ScreenObservation (v0.3). We do NOT rename its fields or convert its boxes:
elements keep their own names (`id`, `type`, `text`, `bbox_norm` = [x1, y1, x2, y2] as 0..1 fractions
of the screenshot, `confidence`, `clickable` = True | False | None (None = not sure), `source`, `provenance`...).

What this module adds is only ours:
  1. a deterministic QUALITY GATE: is this screen trustworthy enough to act on? If not, the worker
     must re-look / ask / escalate, never act blind.
  2. `is_usable(el)`: ONE place that says whether an element may be acted on.
  3. `to_prompt(ctx)`: a compact table of the screen for the LLM.
  4. `fake_observation(app)`: a screen that is NOT real, always labelled as fake.

Click POINTS are never computed from a box here. They come from Team 1's
CoordinateManager.resolve_target_point() on the executor side.
"""
from typing import Optional

TOP_N = 30

# Element types Team 1's contract allows (v0.3).
ELEMENT_TYPES = ("text", "icon", "button", "input", "checkbox", "link", "menu_item", "tab", "image", "other")
# `clickable` can be None (Team 1: not sure; the string "unknown" is treated the same). We may TRY these types anyway, because
# controls of these kinds are meant to be pressed; Verify checks the screen afterwards.
INTERACTIVE_TYPES = ("button", "link", "input", "checkbox", "menu_item", "tab")

# The detector paths that mean "the learned model did not run".
WEAK_DETECTORS = ("edge-proposals", "none", "fake")

BLUR_HINTS = ("blur", "unclear", "low contrast", "illegible", "smudge", "not clear")


def is_usable(el: dict) -> bool:
    """
    May the worker act on this element?
      clickable True      -> yes
      clickable False     -> no
      clickable None      -> only for interactive types (we try, then Verify looks at the screen)
    """
    c = el.get("clickable")
    if c is True:
        return True
    if c is False:
        return False
    # None or "unknown": no evidence either way
    return (el.get("type") or "") in INTERACTIVE_TYPES


# --- quality gate -----------------------------------------------------------

def assess_quality(obs: dict, elements: list) -> dict:
    """
    Deterministic (not model-based) readability check on one ScreenObservation.
    Fixed thresholds: auditable and repeatable. A VLM never decides "is this clear" for us.
    """
    reasons, score = [], 1.0
    perception = obs.get("perception") or {}

    if not elements:
        reasons.append("no_elements")
        score = 0.0
    else:
        confs = [float(e.get("confidence") or 0.0) for e in elements]
        avg = sum(confs) / len(confs)
        low = sum(1 for c in confs if c < 0.5) / len(confs)
        if avg < 0.45:
            reasons.append(f"low_avg_confidence:{avg:.2f}")
            score -= 0.4
        if low > 0.7:
            reasons.append(f"mostly_low_confidence:{low:.0%}")
            score -= 0.3
        if not any(is_usable(e) for e in elements):
            reasons.append("nothing_usable_on_screen")
            score -= 0.3

    overall = obs.get("confidence")
    if isinstance(overall, (int, float)) and overall < 0.4:
        reasons.append(f"low_overall_confidence:{overall:.2f}")
        score -= 0.3

    detector = perception.get("detector")
    if detector in WEAK_DETECTORS:
        reasons.append(f"weak_detector:{detector}")           # the trained model did NOT run
        score = min(score - 0.4, 0.5)                          # never "clear" on its own

    if not obs.get("window"):
        reasons.append("no_active_window")                    # vision silently captured the whole screen
        score -= 0.2

    if perception.get("vlm_error"):
        reasons.append("vlm_error")

    for w in obs.get("warnings") or []:
        if any(h in str(w).lower() for h in BLUR_HINTS):
            reasons.append(f"vision_warning:{w}")
            score -= 0.3

    score = max(0.0, min(1.0, round(score, 2)))
    return {"clear": score >= 0.6, "score": score, "reasons": reasons}


# --- main entry -------------------------------------------------------------

def normalize(obs: Optional[dict], source: str = "nelly_vision") -> dict:
    """
    ScreenObservation (as a plain dict) -> the context the worker and the decider read.
    Elements are Team 1's own dicts, untouched, only ordered and cut to the top N.
    Never raises: anything that is not an observation becomes needs_review.
    """
    if not isinstance(obs, dict):
        return failed_context("no_vision_payload", source)

    elements = [e for e in (obs.get("elements") or []) if isinstance(e, dict)]
    # usable first, then the most confident; ties keep Team 1's reading order
    ranked = sorted(enumerate(elements), key=lambda p: (not is_usable(p[1]),
                                                       -(p[1].get("confidence") or 0.0), p[0]))
    top = [e for _, e in ranked[:TOP_N]]

    quality = assess_quality(obs, top)
    window = obs.get("window") or {}
    perception = obs.get("perception") or {}
    return {
        "screenshot_id": obs.get("screenshot_id"),
        "schema_version": obs.get("schema_version"),
        "app": window.get("process"),
        "window_title": window.get("title"),
        "elements": top,
        "truncated": len(elements) > TOP_N,
        "confidence": obs.get("confidence"),
        "detector": perception.get("detector"),
        "vlm_used": obs.get("vlm_used"),
        "warnings": list(obs.get("warnings") or []),
        "error": None,
        "quality": quality,
        "needs_review": not quality["clear"],
        "vision_source": source,
        "window": obs.get("window"),        # process + bounds: the target guard checks clicks against them
        "screen": obs.get("screen"),        # screenshot frame on the desktop (bbox_norm -> pixels)
    }


def failed_context(reason: str, source: str = "nelly_vision") -> dict:
    """A screen we could not read. The worker must stop and ask; it must never act on this."""
    return {
        "screenshot_id": None, "schema_version": None, "app": None, "window_title": None,
        "elements": [], "truncated": False, "confidence": 0.0, "detector": None, "vlm_used": False,
        "warnings": [reason], "error": reason,
        "quality": {"clear": False, "score": 0.0, "reasons": [reason]},
        "needs_review": True, "vision_source": source,
    }


# --- fake screen (no vision installed; dry runs and offline tests only) -----

def fake_observation(app: str, target: str = "button") -> dict:
    """
    A ScreenObservation-shaped screen that is NOT real. It exists so the rest of the system can be
    exercised without Team 1's vision, and it says so everywhere: the detector is "fake" and a
    warning is attached. Never mistake it for a real screen.
    """
    return {
        "schema_version": "0.3",
        "screenshot_id": "fake-screenshot",
        "window": {"title": f"{app} (FAKE SCREEN)", "process": app},
        "elements": [{
            "id": "e1", "type": "button", "text": target,
            "bbox_norm": [0.31, 0.45, 0.39, 0.50],
            "confidence": 0.82, "clickable": True, "source": "fast",
        }],
        "confidence": 0.82,
        "warnings": ["FAKE SCREEN: not real perception (Team 1 vision is not installed)"],
        "perception": {"detector": "fake"},
        "vlm_used": False,
    }


# --- prompt compaction (what the Brain actually sees) -----------------------

def to_prompt(ctx: Optional[dict], limit: int = TOP_N) -> str:
    """Compact screen text for the LLM: one line per element, ids exactly as Team 1 numbered them."""
    if not isinstance(ctx, dict):
        return "no screen"
    lines = [
        f"app={ctx.get('app')} window={ctx.get('window_title')} detector={ctx.get('detector')} "
        f"quality={ctx.get('quality', {}).get('score')} needs_review={ctx.get('needs_review')}",
    ]
    for e in (ctx.get("elements") or [])[:limit]:
        box = [round(v, 2) for v in (e.get("bbox_norm") or [])]
        lines.append(f"{e.get('id')} {e.get('type')} {e.get('text')!r} {box} "
                     f"conf={e.get('confidence')} clickable={e.get('clickable')}")
    if ctx.get("warnings"):
        lines.append(f"warnings={ctx['warnings']}")
    return "\n".join(lines)
