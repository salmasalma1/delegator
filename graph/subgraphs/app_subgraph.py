"""
Generic App Sub-Graph — Hamlet Worker
Reusable for any app. Delegated by Main.
Calls Team 1 vision through vision.vision_adapter when it is installed; otherwise a loudly labelled
FAKE screen. Both go through vision.adapter so the worker sees ONE shape (Team 1's ScreenObservation 0.3).
"""
from typing import TypedDict, Optional
import uuid

try:
    from execution import desktop_adapter
    HAS_ADAPTER = True
except Exception:                                   # execution module not present yet
    desktop_adapter = None
    HAS_ADAPTER = False

from vision.adapter import normalize, fake_observation, failed_context
from vision.validate import validate_observation
from vision import vision_adapter
import os
import llm
from graph import control
from graph.action_decider import decide_action, decide_next
from graph.safety_port import (get_safety, classify, proposal_hash, normalize_decision,
                               APPROVED, NEEDS_USER_APPROVAL)

# Opt-in: NELLY_EXECUTOR=team1 runs Team 1's executor through execution/team1_bridge.py (same execute() and
# live_requested() as desktop_adapter). Default: our interim executor, execution/desktop_adapter.py.
if HAS_ADAPTER and os.getenv("NELLY_EXECUTOR", "").strip().lower() == "team1":
    from execution import team1_bridge as desktop_adapter


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


# ---- Vision (Team 1) ----
def perceive_screen(app: str, target: str, screenshot=None, scenario: str = None) -> dict:
    """
    Unified entry -> normalized screen context (quality gated).
    * vision installed  -> real observation; a crash becomes needs_review (never a silent fake screen)
    * not installed     -> FAKE screen, labelled fake in detector + warnings (dry runs / tests only)
    """
    if not vision_adapter.available():
        ctx = normalize(fake_observation(app, target), source="fake")
        # A fake screen may only feed a DRY run. With a real input backend it must stop, never click fake coordinates.
        live = HAS_ADAPTER and desktop_adapter.live_requested() \
            and os.getenv("NELLY_ALLOW_FAKE_VISION", "") != "1"
        ctx["needs_review"] = live
        if live:
            ctx["warnings"].append("fake vision with a live executor: refusing to act (unset NELLY_LIVE_INPUT)")
        return ctx
    try:
        raw = vision_adapter.observe(screenshot=screenshot, target=target)
    except Exception as e:                                   # noqa: BLE001
        print(f"[Vision] failed: {type(e).__name__}: {e}")
        return failed_context(f"vision_error:{type(e).__name__}: {e}")
    ok, errs = validate_observation(raw)
    ctx = normalize(raw, source="nelly_vision")
    if not ok:
        print(f"[Vision] contract violation: {errs[:3]}")
        ctx["warnings"].append(f"contract_violation:{errs[:2]}")
        ctx["needs_review"] = True
    return ctx


_dry_noted = [False]


def _note_dry_run():
    """Say it once, loudly: nothing is being clicked in this run."""
    if _dry_noted[0]:
        return
    _dry_noted[0] = True
    print("[execution] DRY RUN — nothing is clicked or typed (set NELLY_LIVE_INPUT=1 to act for real).")
    print("            Steps are recorded as 'dry_run', never as 'success'.")


def _build_request(decision: dict, app: str, task_id: str) -> dict:
    """The ONE frozen ExecutionRequest. Safety sees exactly this; the executor runs exactly this."""
    element = decision.get("element") or {}
    risk, reversible = classify(decision["action"])      # static table; the real Safety may override
    return {
        "action_id": str(uuid.uuid4()),
        "task_id": task_id,
        "risk_level": risk,
        "reversible": reversible,
        "action_type": decision["action"],
        "target_element_id": element.get("id"),
        "parameters": decision["params"],
        "application": app,
        "strategy": "vision_fallback",
        "observation_id": decision.get("observation_id"),
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


REGROUND_CODES = ("stale", "window_resized", "window_gone", "window_minimized", "off_window", "stale_target")
MAX_ACTIONS = int(os.getenv("NELLY_MAX_ACTIONS", "8"))     # the worker's leash per sub-goal
STUCK_AFTER = 3                                             # same action this many times in a row = stuck


def _record_action(sub_result: dict, req: dict, verdict: dict, element: dict,
                   exec_result: dict = None, ran: bool = False):
    """One row per proposed action (the action level; the node level is the plan node itself)."""
    sub_result.setdefault("actions", []).append({
        "action_id": req["action_id"], "task_id": req["task_id"],
        "action_type": req["action_type"], "element_id": element.get("id"),
        "risk_level": verdict.get("risk_level") or req.get("risk_level"),
        "decision": verdict.get("decision"), "reason": verdict.get("reason"),
        "policy_id": verdict.get("policy_id"), "policy_mode": verdict.get("policy_mode"),
        "approval_id": verdict.get("approval_id"), "approval_scope": verdict.get("approval_scope"),
        "proposal_hash": verdict.get("proposal_hash"), "mock": verdict.get("mock"),
        "result_status": (exec_result or {}).get("status") if ran else "not_run",
        "screenshot_ref": (exec_result or {}).get("screenshot_after_ref") if ran else None,
        "latency_ms": (exec_result or {}).get("duration_ms") if ran else None,
        "reject_code": ((exec_result or {}).get("output") or {}).get("reject_code") if ran else None,
    })


def _perform(decision: dict, app: str, task_id: str, safety, sub_result: dict, ctx: dict, label: str):
    """
    SAFETY then ACT for one decided action, and record it.
    Returns (ok, exec_result). ok=False means the worker must stop: sub_result already says why.
    """
    element = decision.get("element") or {}
    req = _build_request(decision, app, task_id)

    verdict = normalize_decision(safety.check(req))      # whatever it returns, only the frozen words count
    sub_result["last_safety_decision"] = verdict
    if verdict["decision"] == NEEDS_USER_APPROVAL:
        _record_action(sub_result, req, verdict, element)
        sub_result["status"] = "needs_approval"
        sub_result["error"] = f"approval needed: {verdict.get('reason')}"
        sub_result["proposed_action"] = req              # frozen: what the user would approve
        return False, None
    if verdict["decision"] != APPROVED:
        _record_action(sub_result, req, verdict, element)
        sub_result["status"] = "failed"
        sub_result["error"] = f"safety {verdict['decision']}: {verdict.get('reason')}"
        return False, None

    # what runs must be exactly what was approved
    approved_hash = verdict.get("proposal_hash")
    if approved_hash and approved_hash != proposal_hash(req):
        _record_action(sub_result, req, verdict, element)
        sub_result["status"] = "failed"
        sub_result["error"] = "request changed after it was approved; not executed"
        return False, None

    exec_result = _act(req)
    sub_result["last_execution_result"] = exec_result
    _record_action(sub_result, req, verdict, element, exec_result, ran=True)
    dry = bool((exec_result.get("output") or {}).get("dry_run"))
    if dry:
        _note_dry_run()
    elif exec_result.get("status") in ("failed", "blocked", "cancelled"):
        code = (exec_result.get("output") or {}).get("reject_code")
        # Team 1 refused the click because the picture is out of date: look again, do not call it a failure
        sub_result["status"] = ("cancelled" if exec_result.get("status") == "cancelled"
                                else "needs_regrounding" if code in REGROUND_CODES else "failed")
        sub_result["error"] = f"execution {exec_result.get('status')}: {exec_result.get('error')}"
        return False, exec_result

    sub_result["steps_done"].append({
        "step": label,
        "status": "dry_run" if dry else exec_result.get("status"),
        "execution": {"action_type": req["action_type"],
                      "duration_ms": exec_result.get("duration_ms"),
                      "action_id": exec_result.get("action_id")},
        "target": {"element_id": element.get("id"), "type": element.get("type"),
                   "bbox_norm": element.get("bbox_norm"),            # Team 1: [x1, y1, x2, y2], 0..1
                   "clickable": element.get("clickable"),
                   "confidence": element.get("confidence")},
        "decision": {"decider": decision["decider"], "why": decision["why"]},
        "safety": {"decision": verdict["decision"], "mock": verdict.get("mock"),
                   "approval_scope": verdict.get("approval_scope")},
        "quality": ctx["quality"]["score"],
    })
    return True, exec_result


def _observe(sub_result: dict, ctx: dict) -> bool:
    """Record what we see. False = the screen is not readable enough to act on."""
    sub_result["last_vision_result"] = ctx
    sub_result["vision_source"] = ctx["vision_source"]
    sub_result["quality"] = ctx["quality"]
    if ctx["needs_review"]:      # don't act on unreadable grounding — escalate instead of guessing
        sub_result["status"] = "needs_review"
        sub_result["error"] = f"vision_not_actionable: {ctx['quality']['reasons']}"
        return False
    return True


def _sig(decision: dict) -> tuple:
    p = decision["params"]
    return (decision["action"], (decision.get("element") or {}).get("id"),
            p.get("text"), tuple(p.get("keys") or ()), p.get("path"))


def _run_loop(app, node, hints, task_id, screenshot, scenario, flag, max_actions) -> dict:
    """
    The worker as a mini-agent: look -> decide ONE action -> safety -> act -> look again,
    until the model says `finish`, the leash runs out, or it gets stuck.
    It never judges success: `finish` only means "I think I am done"; Verify decides.
    """
    sub_result = {"app": app, "node": node, "status": "running", "steps_done": [], "mode": "loop"}
    safety = get_safety()
    history, sigs, shot = [], [], screenshot

    for _ in range(max_actions):
        if control.cancelled():
            sub_result["status"] = "cancelled"
            sub_result["error"] = "cancelled by the user"
            return sub_result
        ctx = perceive_screen(app, node, shot, scenario)
        if not _observe(sub_result, ctx):
            return sub_result

        decision = decide_next(app, node, flag, hints, history, ctx)
        decision["observation_id"] = ctx.get("screenshot_id")
        if decision["status"] != "ok":
            sub_result["status"] = "needs_regrounding"
            sub_result["error"] = f"step_not_resolved: {node!r} ({decision['why']})"
            sub_result["ungrounded_step"] = node
            return sub_result
        if decision["action"] == "finish":
            sub_result["status"] = "completed"
            sub_result["finish_reason"] = decision["why"]
            return sub_result

        sigs.append(_sig(decision))
        if len(sigs) >= STUCK_AFTER and len(set(sigs[-STUCK_AFTER:])) == 1:
            sub_result["status"] = "failed"
            sub_result["error"] = f"stuck: repeated {decision['action']} {STUCK_AFTER} times with no progress"
            return sub_result

        ok, exec_result = _perform(decision, app, task_id, safety, sub_result, ctx,
                                   f"{decision['action']}: {decision['why']}")
        if not ok:
            return sub_result
        history.append(f"{len(history) + 1}. {decision['action']} "
                       f"{(decision.get('element') or {}).get('id') or ''} {decision['why']}".strip())
        # look at the screen the executor just left, when it gives one
        shot = (exec_result or {}).get("screenshot_after_ref") or screenshot

    sub_result["status"] = "failed"
    sub_result["error"] = f"max_actions_exhausted: {max_actions} actions and the sub-goal is not finished"
    return sub_result


def _run_steps(app, node, steps, task_id, screenshot, scenario, flag) -> dict:
    """No model: one action per step (the old behaviour, legacy prefix parser)."""
    sub_result = {"app": app, "node": node, "status": "running", "steps_done": [], "mode": "steps"}
    safety = get_safety()
    for step in steps:
        if control.cancelled():
            sub_result["status"] = "cancelled"
            sub_result["error"] = "cancelled by the user"
            return sub_result
        ctx = perceive_screen(app, step, screenshot, scenario)
        if not _observe(sub_result, ctx):
            return sub_result
        decision = decide_action(step, app, node, ctx, flag=flag)
        decision["observation_id"] = ctx.get("screenshot_id")
        if decision["status"] != "ok":
            sub_result["status"] = "needs_regrounding"
            sub_result["error"] = f"step_not_resolved: {step!r} ({decision['why']})"
            sub_result["ungrounded_step"] = step
            return sub_result
        ok, _ = _perform(decision, app, task_id, safety, sub_result, ctx, step)
        if not ok:
            return sub_result
    sub_result["status"] = "completed"
    return sub_result


def run_app_subgraph(app: str, node: str, steps: list, task_id: str,
                     screenshot=None, scenario: str = None, flag: str = None,
                     max_actions: int = None) -> dict:
    """`steps` are HINTS written by the planner. With a model the worker loops on the live screen;
    without one it falls back to one action per step."""
    if isinstance(steps, str):   # guard: a bare string must not be iterated char-by-char
        steps = [steps]
    use_loop = llm.available() and os.getenv("NELLY_ACTION_DECIDER", "").lower() != "legacy"
    if use_loop:
        return _run_loop(app, node, steps, task_id, screenshot, scenario, flag, max_actions or MAX_ACTIONS)
    return _run_steps(app, node, steps, task_id, screenshot, scenario, flag)
