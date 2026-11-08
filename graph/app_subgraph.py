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
from graph.action_decider import decide_action
from graph.safety_port import get_safety


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


_dry_noted = [False]


def _note_dry_run():
    """Say it once, loudly: nothing is being clicked in this run."""
    if _dry_noted[0]:
        return
    _dry_noted[0] = True
    print("[execution] DRY RUN — no input backend (pyautogui missing or NELLY_DRY_RUN set).")
    print("            Steps are recorded as 'dry_run', never as 'success'.")


def _build_request(decision: dict, app: str, task_id: str) -> dict:
    """The ONE frozen ExecutionRequest. Safety sees exactly this; the executor runs exactly this."""
    element = decision.get("element") or {}
    return {
        "action_id": str(uuid.uuid4()),
        "task_id": task_id,
        "action_type": decision["action"],
        "target_element_id": element.get("element_id"),
        "parameters": decision["params"],
        "application": app,
        "strategy": "vision_fallback",
    }


def _act(req: dict) -> dict:
    """
    Run an already-approved ExecutionRequest.

    No adapter present -> return a neutral record. It is NOT "success": the step is
    reported as unexecuted so nobody downstream can mistake intention for action.
    """
    if not HAS_ADAPTER:
        return {"action_id": req["action_id"], "task_id": req["task_id"], "status": "unexecuted",
                "verification_status": "not_verified", "strategy_used": "none",
                "duration_ms": 0, "output": {"action_type": req["action_type"]},
                "error": "no execution adapter installed", "screenshot_after_ref": None}
    res = desktop_adapter.execute(req)
    res.setdefault("output", {})["action_type"] = req["action_type"]
    return res


def run_app_subgraph(app: str, node: str, steps: list, task_id: str,
                     screenshot=None, scenario: str = None, flag: str = None) -> dict:
    if isinstance(steps, str):   # guard: a bare string must not be iterated char-by-char
        steps = [steps]
    sub_result = {"app": app, "node": node, "status": "running", "steps_done": []}
    safety = get_safety()

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

        # DECIDE: the worker picks its own action from what is on screen. Unresolved => send it
        # back, never guess.
        decision = decide_action(step, app, node, ctx, flag=flag)
        if decision["status"] != "ok":
            sub_result["status"] = "needs_regrounding"
            sub_result["error"] = f"step_not_resolved: {step!r} ({decision['why']})"
            sub_result["ungrounded_step"] = step
            return sub_result
        element = decision.get("element") or {}
        req = _build_request(decision, app, task_id)

        # SAFETY: the only door to the machine. Approved => act. Anything else => stop.
        verdict = safety.check(req)
        sub_result["last_safety_decision"] = verdict
        if verdict["decision"] == "needs_approval":
            sub_result["status"] = "needs_approval"
            sub_result["error"] = f"approval needed: {verdict.get('reason')}"
            sub_result["proposed_action"] = req          # frozen: what the user would approve
            return sub_result
        if verdict["decision"] != "approved":
            sub_result["status"] = "failed"
            sub_result["error"] = f"safety {verdict['decision']}: {verdict.get('reason')}"
            return sub_result

        # ACT. Send the frozen ExecutionRequest and keep exactly what came back.
        # A dry run must not look like success — that was the persistence lesson.
        exec_result = _act(req)
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
            "execution": {"action_type": req["action_type"],
                          "duration_ms": exec_result.get("duration_ms"),
                          "action_id": exec_result.get("action_id")},
            "target": {"element_id": element.get("element_id"), "type": element.get("type"),
                       "bbox_norm": element.get("bbox_norm"),        # [x,y,w,h] canonical
                       "center_norm": element.get("center_norm"),
                       "center_abs": element.get("center_abs"),
                       "confidence": element.get("confidence")},
            "decision": {"decider": decision["decider"], "why": decision["why"]},
            "safety": {"decision": verdict["decision"], "mock": verdict.get("mock")},
            "quality": ctx["quality"]["score"],
        })

    sub_result["status"] = "completed"
    return sub_result
