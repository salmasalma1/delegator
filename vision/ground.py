"""
Grounding matcthe store's — turns ONE plan step ("type Hello NELLY") into ONE element
from the vision module's grounding. No pixels, no clicks — just which element the step is about.

Deterministic on purpose: cheap, debuggable, and it can say "I don't know".
If it cannot find a confident element, the step is UNGROUNDED and must go back
to the Brain/VLM for re-grounding — it must never silently pick element[0].
"""
import re
from typing import Optional, Tuple

STOP = {"the", "a", "an", "in", "on", "to", "of", "and", "then", "please", "with", "into"}

# step verb -> element types it can target (ordered by preference)
AFFINITY = {
    "type": ["text_area", "text_input", "edit", "textbox", "text_field", "document"],
    "write": ["text_area", "text_input", "edit", "textbox", "text_field", "document"],
    "enter": ["text_area", "text_input", "edit", "textbox", "text_field", "search"],
    "paste": ["text_area", "text_input", "edit", "textbox", "text_field"],
    "click": ["button", "menu", "menu_item", "tab", "icon", "link", "checkbox", "toggle"],
    "press": ["button", "menu", "menu_item", "tab", "icon", "link", "key"],
    "open": ["button", "icon", "menu", "menu_item", "tab", "link", "list_item"],
    "select": ["menu_item", "list_item", "tab", "option", "checkbox", "radio"],
    "save": ["button", "menu", "menu_item", "icon", "toolbar_button"],
    "close": ["button", "icon", "menu_item"],
    "search": ["search", "text_input", "text_field", "text_area"],
    "send": ["button", "icon", "text_input", "text_field"],
}

VERBS = tuple(AFFINITY)

# Typing targets a *kind* of element; clicking targets a *named* element.
# So click-like verbs must match on-screen text, or the step is ungrounded.
TEXT_REQUIRED = {"click", "press", "open", "select", "save", "close", "send"}


def _tokens(s: Optional[str]) -> set:
    if not s:
        return set()
    return {t for t in re.split(r"[^a-z0-9]+", s.lower()) if len(t) > 1 and t not in STOP}


def _verb(step: str) -> Optional[str]:
    for t in re.split(r"[^a-z]+", step.lower()):
        if t in AFFINITY:
            return t
    return None


def score(step: str, el: dict) -> Tuple[float, list]:
    """Higthe store's = better fit. Returns (score, why)."""
    why, s = [], 0.0
    if not el.get("interactable", False):
        return -1.0, ["not interactable"]
    if el.get("confirmed") is False or el.get("ambiguous") is True:
        return -1.0, ["unconfirmed_by_t1"]   # vision says the mark is not evidence-backed

    step_tok = _tokens(step)
    el_tok = _tokens(el.get("text"))
    overlap = step_tok & el_tok
    if overlap:
        s += 3.0 * len(overlap)
        why.append(f"text:{sorted(overlap)}")

    v = _verb(step)
    etype = (el.get("type") or "").lower()
    if v in TEXT_REQUIRED and not overlap:
        return -1.0, [f"click-like verb {v!r} but no on-screen text match"]
    if v:
        prefs = AFFINITY[v]
        if etype in prefs:
            s += 2.0 + max(0.0, 1.0 - prefs.index(etype) * 0.25)
            why.append(f"type:{etype}~{v}")

    s += 0.5 * float(el.get("confidence", 0))
    return round(s, 3), why


def pick(step: str, elements: list, min_score: float = 1.0) -> dict:
    """
    -> {"status": "grounded"|"ungrounded", "element": {...}|None,
        "score": float, "why": [...], "candidates": n}
    """
    if not elements:
        return {"status": "ungrounded", "element": None, "score": 0.0,
                "why": ["no_elements"], "candidates": 0}

    ranked = []
    for el in elements:
        sc, why = score(step, el)
        if sc > 0:
            ranked.append((sc, why, el))
    if not ranked:
        return {"status": "ungrounded", "element": None, "score": 0.0,
                "why": ["no_interactable_candidate"], "candidates": 0}

    ranked.sort(key=lambda r: -r[0])
    sc, why, el = ranked[0]
    if sc < min_score:
        return {"status": "ungrounded", "element": None, "score": sc, "why": why,
                "candidates": len(ranked)}
    return {"status": "grounded", "element": el, "score": sc, "why": why,
            "candidates": len(ranked), "ambiguous": len(ranked) > 1 and ranked[1][0] > sc - 0.3}
