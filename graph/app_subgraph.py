"""
Generic App Sub-Graph — Hamlet Worker
Reusable for any app. Delegated by Main.
Calls REAL Vision (nelly_vision.perception) if available, else fallback — both normalized
through vision.adapter so the worker sees ONE shape.
"""
from typing import TypedDict, Optional
import uuid

try:
    from execution import desktop_adapter
    HAS_ADAPTER = True
except Exception:                                   # execution module not present yet
    desktop_adapter = None
    HAS_ADAPTER = False

from vision.adapter import normalize, fallback_result
from vision.validate import validate_vision_result
from vision.ground import pick as pick_element


class AppSubState(TypedDict, total=False):
    app: str
    node: str
    flag: str
    steps: list
    current_step: int
    status: str
    last_vision_result: Optional[dict]
    last_safety_decision: Optional[dict]
    error: Optional[str]


# ---- Vision Adapter (Real if available) ----
try:
    from config import ensure_vision_path
    ensure_vision_path()          # the vision module's folder can be moved/renamed; package name stays
except Exception:
    pass

try:
    from nelly_vision.perception import perceive as real_perceive  # the vision module's vision handoff
    HAS_REAL_VISION = True
except ImportError:
    HAS_REAL_VISION = False
    real_perceive = None


def _accepts(fn, kw: str) -> bool:
    import inspect
    try:
        return kw in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def perceive_screen(app: str, target: str, screenshot=None, scenario: str = None) -> dict:
    """Unified entry -> normalized grounding context (Top-30, quality gated)."""
    if HAS_REAL_VISION:
        try:
            # the vision module's real perceive(screenshot) has no scenario kwarg -> only pass it to test doubles.
            raw = real_perceive(screenshot, scenario=scenario) if _accepts(real_perceive, "scenario") \
                else real_perceive(screenshot)
            ok, errs = validate_vision_result(raw)
            if not ok:
                print(f"[Vision] contract violation from vision: {errs[:3]}")
            ctx = normalize(raw, source="nelly_vision")
            if not ok:
                ctx["warnings"].append(f"contract_violation:{errs[:2]}")
            return ctx
        except Exception as e:  # never let vision break the worker
            print(f"[Vision fallback] real failed: {e}")
    return normalize(fallback_result(app, target), source="fallback")


# Which primitive does a plain-language step correspond to?
_STEP_ACTION = (("type ", "type"), ("write ", "type"), ("click ", "click"),
                ("press ", "press"), ("open ", "click"), ("save", "save_file"),
                ("create folder", "create_folder"), ("focus", "focus_window"))


def _action_for(step: str) -> str:
    low = (step or "").strip().lower()
    for prefix, action in _STEP_ACTION:
        if low.startswith(prefix):
            return action
    return "click"          # the safest default: a click needs a grounded element


def _action_params(step: str, action: str, element: dict) -> dict:
    low = (step or "").strip()
    if action == "type":
        text = low
        for p in ("type ", "write ", "enter "):
            if low.lower().startswith(p):
                text = low[len(p):].strip().strip('"\'')
                break
        return {"text": text, "bbox_norm": element["bbox_norm"]}
    if action == "press":
        keys = low.split(" ", 1)[1] if " " in low else low
        return {"keys": [k.strip().lower() for k in keys.split("+")]}
    return {"bbox_norm": element["bbox_norm"]}


_dry_noted = [False]


def _note_dry_run():
    """Say it once, loudly: nothing is being clicked in this run."""
    if _dry_noted[0]:
        return
    _dry_noted[0] = True
    print("[execution] DRY RUN — no input backend (pyautogui missing or NELLY_DRY_RUN set).")
    print("            Steps are recorded as 'dry_run', never as 'success'.")


def _act(step: str, app: str, element: dict, task_id: str) -> dict:
    """
    Build an ExecutionRequest (schemas/vision/03_...) and run it.

    No adapter present -> return a neutral record. It is NOT "success": the step is
    reported as unexecuted so nobody downstream can mistake intention for action.
    """
    action = _action_for(step)
    req = {
        "action_id": str(uuid.uuid4()),
        "task_id": task_id,
        "action_type": action,
        "target_element_id": element.get("element_id"),
        "parameters": _action_params(step, action, element),
        "application": app,
        "strategy": "vision_fallback",
    }
    if not HAS_ADAPTER:
        return {"action_id": req["action_id"], "task_id": task_id, "status": "unexecuted",
                "verification_status": "not_verified", "strategy_used": "none",
                "duration_ms": 0, "output": {"action_type": action},
                "error": "no execution adapter installed", "screenshot_after_ref": None}
    res = desktop_adapter.execute(req)
    res.setdefault("output", {})["action_type"] = action
    return res


def mock_safety_allow(action_id: str):
    return {"decision": "approved", "action_id": action_id, "reason": "low risk"}


def run_app_subgraph(app: str, node: str, steps: list, task_id: str,
                     screenshot=None, scenario: str = None) -> dict:
    if isinstance(steps, str):   # guard: a bare string must not be iterated char-by-char
        steps = [steps]
    sub_result = {"app": app, "node": node, "status": "running", "steps_done": []}

    for step in steps:
        ctx = perceive_screen(app, step, screenshot, scenario)
        sub_result["last_vision_result"] = ctx
        sub_result["vision_source"] = ctx["vision_source"]
        sub_result["quality"] = ctx["quality"]

        # Quality gate: don't act on unreadable grounding — escalate instead of guessing.
        if ctx["needs_review"]:
            sub_result["status"] = "needs_review"
            sub_result["error"] = f"vision_not_actionable: {ctx['quality']['reasons']}"
            return sub_result

        # Ground the step to ONE element. Ungrounded => do NOT guess, send it back.
        g = pick_element(step, ctx["elements"])
        if g["status"] != "grounded":
            sub_result["status"] = "needs_regrounding"
            sub_result["error"] = f"step_not_grounded: {step!r} ({g['why']})"
            sub_result["ungrounded_step"] = step
            return sub_result
        element = g["element"]

        decision = mock_safety_allow(str(uuid.uuid4()))
        sub_result["last_safety_decision"] = decision
        if decision["decision"] != "approved":
            sub_result["status"] = "failed"
            sub_result["error"] = decision["reason"]
            return sub_result

        # ACT. Send one frozen ExecutionRequest and keep exactly what came back.
        # A dry run must not look like success — that was the persistence lesson.
        exec_result = _act(step, app, element, task_id)
        sub_result["last_execution_result"] = exec_result
        dry = bool((exec_result.get("output") or {}).get("dry_run"))
        if dry:
            _note_dry_run()
        elif exec_result.get("status") in ("failed", "blocked", "cancelled"):
            sub_result["status"] = "failed"
            sub_result["error"] = f"execution {exec_result.get('status')}: {exec_result.get('error')}"
            return sub_result

        sub_result["steps_done"].append({
            "step": step,
            # dry_run is recorded as dry_run — never as success. See _note_dry_run().
            "status": "dry_run" if dry else exec_result.get("status"),
            "execution": {"action_type": exec_result.get("output", {}).get("action_type"),
                          "duration_ms": exec_result.get("duration_ms"),
                          "action_id": exec_result.get("action_id")},
            "target": {"element_id": element["element_id"], "type": element["type"],
                       "bbox_norm": element["bbox_norm"],        # [x,y,w,h] canonical
                       "center_norm": element.get("center_norm"),
                       "center_abs": element["center_abs"],
                       "confidence": element["confidence"]},
            "grounding": {"score": g["score"], "why": g["why"], "ambiguous": g.get("ambiguous")},
            "quality": ctx["quality"]["score"],
        })

    sub_result["status"] = "completed"
    return sub_result
