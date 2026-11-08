"""
Redaction BEFORE anything is written to the store. The store keeps whatever it is given.

Policy (small on purpose, easy to audit):
  1. keys that look secret (password, token, api_key, authorization, cookie, secret) -> masked
  2. secret-looking strings (sk-..., Bearer ...) are masked anywhere
  3. typed text is masked: parameters.text, and the step text of a `type` action
  4. screen text (OCR) is dropped from grounding; element ids, types and boxes stay
  5. anything not JSON-serialisable (bytes, objects) becomes a short string, so the store's
     json.dumps can never raise TypeError

The input is never modified: a deep, redacted copy is returned.
"""
import re

MASK = "[REDACTED]"
_SECRET_KEY = re.compile(r"pass(word|wd)?|secret|token|api[_-]?key|authorization|cookie|credential", re.I)
_SECRET_VAL = re.compile(r"(sk-[A-Za-z0-9_\-]{16,}|Bearer\s+[A-Za-z0-9._\-]{8,})")
_KEEP_ELEMENT = ("element_id", "type", "bbox", "bbox_norm", "center_abs", "center_norm",
                 "confidence", "interactable", "source", "confirmed", "ambiguous")
_MAX_DEPTH = 12


def _elements(els):
    return [{k: e.get(k) for k in _KEEP_ELEMENT if k in e} | ({"text": MASK} if e.get("text") else {})
            for e in els if isinstance(e, dict)]


def _walk(o, depth=0, key=None):
    if depth > _MAX_DEPTH:
        return "[too deep]"
    if key is not None and isinstance(key, str) and _SECRET_KEY.search(key):
        return MASK
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            if k == "elements" and isinstance(v, list):            # screen text goes
                out[k] = _elements(v)
            elif k == "parameters" and isinstance(v, dict):         # typed text is never stored
                out[k] = {pk: (MASK if pk == "text" else _walk(pv, depth + 2, pk)) for pk, pv in v.items()}
            else:
                out[k] = _walk(v, depth + 1, k)
        # a typed step: keep that it happened, not what was typed
        if (o.get("execution") or {}).get("action_type") == "type" and isinstance(o.get("step"), str):
            out["step"] = f"type [{len(o['step'])} chars redacted]"
        return out
    if isinstance(o, (list, tuple)):
        return [_walk(v, depth + 1) for v in o]
    if isinstance(o, str):
        return _SECRET_VAL.sub(MASK, o)
    if o is None or isinstance(o, (bool, int, float)):
        return o
    if isinstance(o, (bytes, bytearray)):
        return f"<{len(o)} bytes>"
    return _SECRET_VAL.sub(MASK, str(o))


def redact(state: dict) -> dict:
    return _walk(state)
