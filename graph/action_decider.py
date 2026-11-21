"""
The worker decides its OWN action for a step. No verb-prefix parsing, no examples.

Input : one plain-language step + the current screen (Top-N elements from vision).
Output: {"status": "ok", "action", "element", "params", "why", "decider"}
        or {"status": "unresolved", "why"}

The model may only choose from ALLOWED, and only element ids that are really on screen.
Anything else is rejected here, so a hallucinated id can never reach the executor.
"""
import os

import llm
from vision.adapter import rerank, to_prompt, usable_for

ALLOWED = ("click", "double_click", "type", "press", "scroll", "save_file", "create_folder", "focus_window", "open_app")
NEEDS_ELEMENT = ("click", "double_click", "type", "scroll")
SCROLL_DIRECTIONS = ("up", "down", "left", "right")
MAX_SCROLL = 15
_warned = [False]

SYSTEM = """You are the hands of a Windows desktop agent. You get ONE step to carry out and the
elements currently visible on screen. Choose exactly ONE action that performs the step.

Allowed actions: click, double_click, type, press, scroll, save_file, create_folder, focus_window, open_app.
- click / type need "element_id" copied EXACTLY from the list. type also needs "text".
- double_click opens the item under an element (a file, a folder, an icon): it needs "element_id". Use it
  to open a file or folder shown in a list; a single click only selects it.
- press needs "keys": a list like ["ctrl","s"].
- scroll moves the content under an element: it needs "element_id" (an element inside the area to scroll, for
  example the file list or the text area), "direction" (up, down, left or right) and optionally "amount" (wheel
  notches, 1 to 15, default 5). Use it when the target is not in the list: the list shows only the most
  relevant elements, so look at the list, scroll, and the next look shows what appeared.
- save_file / create_folder need "path". focus_window needs nothing.
- open_app starts a program that is not open yet; it needs "app" (e.g. "Notepad"). Do not click the Start menu for this.
Use only what is on screen. If the step cannot be done from this screen, answer action "none".

Answer ONLY JSON:
{"action": "...", "element_id": null, "text": null, "keys": null, "path": null, "app": null, "direction": null, "amount": null, "why": "short"}"""


def _all(ctx: dict) -> list:
    """Every element of the observation (normalize keeps them in all_elements); the top N as a fallback."""
    return ctx.get("all_elements") or ctx.get("elements") or []


def _truncation_note(ctx: dict) -> str:
    if not ctx.get("truncated"):
        return ""
    return (f" (the screen list was truncated: the model saw {len(ctx.get('elements') or [])} of "
            f"{ctx.get('total_elements') or len(_all(ctx))} elements; grounding searched all of them)")


def _team1_element(step: str, ctx: dict):
    """(element, grounding) when Team 1 grounded THIS step's target confidently and the element is in the list."""
    g1 = ctx.get("grounding") or {}
    if g1.get("status") != "grounded" or not g1.get("element_id"):
        return None
    if str(g1.get("target") or "").strip().lower() != str(step or "").strip().lower():
        return None
    el = next((e for e in _all(ctx) if e.get("id") == g1["element_id"]), None)
    return (el, g1) if el is not None else None


def _legacy(step: str, ctx: dict) -> dict:
    """Old behaviour (first-word parsing). Only when there is no model; always labelled."""
    from vision.ground import pick
    from graph.app_subgraph_legacy import action_for, action_params
    team1 = _team1_element(step, ctx)              # F3: Team 1's GroundingResult wins when it is confident
    if team1 is not None:
        el, g1 = team1
        return {"status": "ok", "action": action_for(step), "element": el,
                "params": action_params(step, action_for(step), el),
                "why": f"team1_grounding ({g1.get('method')}, confidence {g1.get('confidence')})",
                "decider": "legacy_prefix"}
    g = pick(step, _all(ctx))                      # F2: the FULL element list, not only the top N
    if g["status"] != "grounded":
        return {"status": "unresolved", "why": f"legacy_ungrounded: {g['why']}{_truncation_note(ctx)}"}
    action = action_for(step)
    return {"status": "ok", "action": action, "element": g["element"],
            "params": action_params(step, action, g["element"]),
            "why": f"legacy prefix parser ({g['why']})", "decider": "legacy_prefix"}


def decide_action(step: str, app: str, node: str, ctx: dict, flag: str = None) -> dict:
    if os.getenv("NELLY_ACTION_DECIDER", "").lower() == "legacy" or not llm.available():
        if not _warned[0]:
            _warned[0] = True
            print("[action] no model available: using the legacy prefix parser (NOT understanding).")
        return _legacy(step, ctx)

    user = (f"App: {app}\nSub-goal: {node}\nDone when: {flag}\nStep to carry out: {step}\n\n"
            f"Screen:\n{to_prompt(ctx)}")
    try:
        out = llm.chat_json(SYSTEM, user)
    except Exception as e:                                    # noqa: BLE001
        return {"status": "unresolved", "why": f"decider_error: {type(e).__name__}: {e}"}
    return _from_model(out, ctx, target=step)


def _from_model(out, ctx: dict, target: str = None) -> dict:
    if not isinstance(out, dict):
        return {"status": "unresolved", "why": "decider_not_an_object"}
    action = (out.get("action") or "").lower()
    why = out.get("why") or ""
    if action == "none":
        return {"status": "unresolved", "why": f"model says not doable here: {why}"}
    if action not in ALLOWED:
        return {"status": "unresolved", "why": f"action {action!r} not allowed"}

    element = None
    if action in NEEDS_ELEMENT:
        by_id = {e.get("id"): e for e in _all(ctx)}          # F2: look ids up in the FULL list
        element = by_id.get(out.get("element_id"))
        if element is None:
            return {"status": "unresolved",
                    "why": f"element_id {out.get('element_id')!r} is not on screen{_truncation_note(ctx)}"}
        if not usable_for(element, target, any_text=(action == "double_click")):
            return {"status": "unresolved", "why": f"element {out.get('element_id')!r} not usable (clickable=False or not an interactive type)"}

    params = {}
    if element is not None:
        params["bbox_norm"] = element["bbox_norm"]
    if action == "type":
        if not isinstance(out.get("text"), str):
            return {"status": "unresolved", "why": "type without text"}
        params["text"] = out["text"]
    elif action == "scroll":
        direction = str(out.get("direction") or "down").lower()
        if direction not in SCROLL_DIRECTIONS:
            return {"status": "unresolved", "why": f"scroll direction {direction!r} must be one of {SCROLL_DIRECTIONS}"}
        try:
            amount = int(out.get("amount") or 5)
        except (TypeError, ValueError):
            amount = 5
        params["direction"], params["amount"] = direction, max(1, min(MAX_SCROLL, amount))
    elif action == "press":
        keys = out.get("keys")
        if not (isinstance(keys, list) and keys):
            return {"status": "unresolved", "why": "press without keys"}
        params["keys"] = [str(k).lower() for k in keys]
    elif action == "open_app":
        if not (isinstance(out.get("app"), str) and out["app"].strip()):
            return {"status": "unresolved", "why": "open_app without app"}
        params["app"] = out["app"].strip()
    elif action in ("save_file", "create_folder"):
        if not out.get("path"):
            return {"status": "unresolved", "why": f"{action} without path"}
        params["path"] = out["path"]

    return {"status": "ok", "action": action, "element": element, "params": params,
            "why": why, "decider": "llm"}


SYSTEM_LOOP = """You are the hands of a Windows desktop agent working on ONE sub-goal.
You see the live screen and what you already did. Choose the NEXT single action.

Allowed actions: click, double_click, type, press, scroll, save_file, create_folder, focus_window, open_app, finish.
- click / type need "element_id" copied EXACTLY from the list. type also needs "text".
- double_click opens the item under an element (a file, a folder, an icon): it needs "element_id". Use it
  to open a file or folder shown in a list; a single click only selects it.
- press needs "keys": a list like ["ctrl","s"].
- scroll moves the content under an element: it needs "element_id" (an element inside the area to scroll, for
  example the file list or the text area), "direction" (up, down, left or right) and optionally "amount" (wheel
  notches, 1 to 15, default 5). Use it when the target is not in the list: the list shows only the most
  relevant elements, so look at the list, scroll, and the next look shows what appeared.
- save_file / create_folder need "path". focus_window needs nothing.
- open_app starts a program that is not open yet; it needs "app" (e.g. "Notepad"). Do not click the Start menu for this.
- finish: the "done when" condition is visibly true on the CURRENT screen, or every hint is
  accomplished. Do not finish just because you are out of ideas.
- If it cannot be done from this screen, answer action "none" and say why.

The hints are suggestions written before anyone saw the screen. Follow them when they fit; when
the screen says otherwise, trust the screen. Never repeat an action that did not change anything.

Answer ONLY JSON:
{"action": "...", "element_id": null, "text": null, "keys": null, "path": null, "app": null, "direction": null, "amount": null, "why": "short"}"""


def decide_next(app: str, node: str, flag: str, hints: list, history: list, ctx: dict) -> dict:
    """One iteration of the worker loop. Same output shape as decide_action; action may be 'finish'."""
    ctx = rerank(ctx, f"{node} {flag} {' '.join(str(h) for h in hints or [])}")   # most relevant elements first
    user = (f"App: {app}\nSub-goal: {node}\nDone when: {flag}\n"
            f"Hints: {hints}\nAlready done: {history or 'nothing yet'}\n\nScreen now:\n{to_prompt(ctx)}")
    try:
        out = llm.chat_json(SYSTEM_LOOP, user)
    except Exception as e:                                    # noqa: BLE001
        return {"status": "unresolved", "why": f"decider_error: {type(e).__name__}: {e}"}
    if isinstance(out, dict) and str(out.get("action", "")).lower() == "finish":
        return {"status": "ok", "action": "finish", "element": None, "params": {},
                "why": out.get("why") or "", "decider": "llm"}
    return _from_model(out, ctx, target=node)
