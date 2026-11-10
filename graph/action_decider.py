"""
The worker decides its OWN action for a step. No verb-prefix parsing, no examples.

Input : one plain-language step + the current screen (Top-N elements from vision).
Output: {"status": "ok", "action", "element", "params", "why", "decider"}
        or {"status": "unresolved", "why"}

The model may only choose from ALLOWED, and only element_ids that are really on screen.
Anything else is rejected here, so a hallucinated id can never reach the executor.
"""
import os

import llm
from vision.adapter import to_prompt

ALLOWED = ("click", "type", "press", "save_file", "create_folder", "focus_window")
NEEDS_ELEMENT = ("click", "type")
_warned = [False]

SYSTEM = """You are the hands of a Windows desktop agent. You get ONE step to carry out and the
elements currently visible on screen. Choose exactly ONE action that performs the step.

Allowed actions: click, type, press, save_file, create_folder, focus_window.
- click / type need "element_id" copied EXACTLY from the list. type also needs "text".
- press needs "keys": a list like ["ctrl","s"].
- save_file / create_folder need "path". focus_window needs nothing.
Use only what is on screen. If the step cannot be done from this screen, answer action "none".

Answer ONLY JSON:
{"action": "...", "element_id": null, "text": null, "keys": null, "path": null, "why": "short"}"""


def _usable(el: dict) -> bool:
    return (el.get("interactable", False) and el.get("confirmed") is not False
            and el.get("ambiguous") is not True)


def _legacy(step: str, ctx: dict) -> dict:
    """Old behaviour (first-word parsing). Only when there is no model; always labelled."""
    from vision.ground import pick
    from graph.app_subgraph_legacy import action_for, action_params
    g = pick(step, ctx.get("elements") or [])
    if g["status"] != "grounded":
        return {"status": "unresolved", "why": f"legacy_ungrounded: {g['why']}"}
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
    return _from_model(out, ctx)


def _from_model(out, ctx: dict) -> dict:
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
        by_id = {e.get("element_id"): e for e in (ctx.get("elements") or [])}
        element = by_id.get(out.get("element_id"))
        if element is None:
            return {"status": "unresolved", "why": f"element_id {out.get('element_id')!r} is not on screen"}
        if not _usable(element):
            return {"status": "unresolved", "why": f"element {out.get('element_id')!r} not usable (not interactable/confirmed)"}

    params = {}
    if element is not None:
        params["bbox_norm"] = element["bbox_norm"]
    if action == "type":
        if not isinstance(out.get("text"), str):
            return {"status": "unresolved", "why": "type without text"}
        params["text"] = out["text"]
    elif action == "press":
        keys = out.get("keys")
        if not (isinstance(keys, list) and keys):
            return {"status": "unresolved", "why": "press without keys"}
        params["keys"] = [str(k).lower() for k in keys]
    elif action in ("save_file", "create_folder"):
        if not out.get("path"):
            return {"status": "unresolved", "why": f"{action} without path"}
        params["path"] = out["path"]

    return {"status": "ok", "action": action, "element": element, "params": params,
            "why": why, "decider": "llm"}


SYSTEM_LOOP = """You are the hands of a Windows desktop agent working on ONE sub-goal.
You see the live screen and what you already did. Choose the NEXT single action.

Allowed actions: click, type, press, save_file, create_folder, focus_window, finish.
- click / type need "element_id" copied EXACTLY from the list. type also needs "text".
- press needs "keys": a list like ["ctrl","s"].
- save_file / create_folder need "path". focus_window needs nothing.
- finish: the "done when" condition is visibly true on the CURRENT screen, or every hint is
  accomplished. Do not finish just because you are out of ideas.
- If it cannot be done from this screen, answer action "none" and say why.

The hints are suggestions written before anyone saw the screen. Follow them when they fit; when
the screen says otherwise, trust the screen. Never repeat an action that did not change anything.

Answer ONLY JSON:
{"action": "...", "element_id": null, "text": null, "keys": null, "path": null, "why": "short"}"""


def decide_next(app: str, node: str, flag: str, hints: list, history: list, ctx: dict) -> dict:
    """One iteration of the worker loop. Same output shape as decide_action; action may be 'finish'."""
    user = (f"App: {app}\nSub-goal: {node}\nDone when: {flag}\n"
            f"Hints: {hints}\nAlready done: {history or 'nothing yet'}\n\nScreen now:\n{to_prompt(ctx)}")
    try:
        out = llm.chat_json(SYSTEM_LOOP, user)
    except Exception as e:                                    # noqa: BLE001
        return {"status": "unresolved", "why": f"decider_error: {type(e).__name__}: {e}"}
    if isinstance(out, dict) and str(out.get("action", "")).lower() == "finish":
        return {"status": "ok", "action": "finish", "element": None, "params": {},
                "why": out.get("why") or "", "decider": "llm"}
    return _from_model(out, ctx)
