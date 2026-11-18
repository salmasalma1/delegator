"""
Bridge to Team 1's executor (execution/team1/). Translation only: no executor logic lives here.

    execute(request: dict) -> dict      # request = our 03_ExecutionRequest, result = our 04_ExecutionResult
    live_requested() -> bool            # same switch as execution/desktop_adapter.py

Our request  -> Team 1's ToolCall:
    action_id          -> call_id (the result's action_id is ALWAYS the request's action_id)
    action_type        -> tool     (click -> click_element, type -> type_text, press -> press_keys, open_app -> open_app)
    parameters         -> args     (text / clear_first, keys, app -> name)
    target_element_id  -> target_element_id
    application        -> app      (Team 1 refuses click / type / press without one: no_application)

Team 1's ActionResult -> our result (status words from our 04 schema, so the worker treats refusals as failures):
    ok -> success, blocked -> blocked (+ reject_code), skipped -> cancelled, error -> failed (executor_error)
    reject_code is the code before the first ':' in Team 1's error, e.g. "wrong_window: focus_guard: ...".
    It is returned at the top level and in output.reject_code (where the worker reads it); Team 1's own
    status and fields go into `evidence`. Typed text is never written to the result.

DRY RUN IS THE DEFAULT: Team 1's DryRunExecutor runs unless NELLY_LIVE_INPUT=1 (and NELLY_DRY_RUN is not set).
Only then is Team 1's DesktopExecutor used, and it checks NELLY_LIVE_INPUT again itself.
"""
import os
import threading
import time

from graph import control

TOOLS = {"click": "click_element", "type": "type_text", "press": "press_keys", "open_app": "open_app"}
STATUS = {"ok": "success", "blocked": "blocked", "skipped": "cancelled", "error": "failed"}
STRATEGY = {True: "team1_dryrun", False: "team1_desktop"}

_executors = {}                 # one instance of each, created on first use (the desktop one remembers launches)


def live_requested() -> bool:
    """Real mouse and keyboard only when asked for, in writing: NELLY_LIVE_INPUT=1 (and NELLY_DRY_RUN not set)."""
    on = lambda k: os.getenv(k, "").strip().lower() in ("1", "true", "yes")          # noqa: E731
    return on("NELLY_LIVE_INPUT") and not on("NELLY_DRY_RUN")


class _ControlStop(threading.Event):
    """Team 1 checks stop.is_set() before every input event; our stop switch is graph.control. One flag for both."""
    def is_set(self):
        return super().is_set() or control.cancelled()


def _executor(dry: bool):
    key = "dry" if dry else "desktop"
    if key not in _executors:
        if dry:
            from execution.team1.executor_dryrun import DryRunExecutor        # noqa: PLC0415
            _executors[key] = DryRunExecutor()
        else:
            from execution.team1.executor_desktop import DesktopExecutor      # noqa: PLC0415
            _executors[key] = DesktopExecutor()
    return _executors[key]


def _result(req, status, t0, dry, *, reject_code=None, error=None, evidence=None):
    output = {"dry_run": bool(dry and status == "success"), "reject_code": reject_code}
    ev = {"executor": "team1", "mode": "dry_run" if dry else "live"}
    ev.update(evidence or {})
    if ev.get("screen_point") is not None:
        output["screen_point"] = list(ev["screen_point"])
    return {"action_id": req.get("action_id"), "task_id": req.get("task_id"), "status": status,
            "reject_code": reject_code, "evidence": ev, "verification_status": "not_verified",
            "strategy_used": STRATEGY[bool(dry)], "duration_ms": int((time.time() - t0) * 1000),
            "output": output, "error": error, "screenshot_after_ref": None}


def to_tool_call(req: dict):
    """Our request -> (Team 1 ToolCall, app). Raises ValueError(code, text) when it cannot be translated."""
    from contracts import ToolCall                                            # noqa: PLC0415  (Team 1)
    action = (req.get("action_type") or "").lower()
    tool = TOOLS.get(action)
    if tool is None:
        raise ValueError("unsupported_action", f"{action!r} has no Team 1 tool ({sorted(TOOLS)})")
    if not req.get("action_id"):
        raise ValueError("bad_request", "the request has no action_id")
    params = req.get("parameters") or {}
    app = req.get("application")
    if tool == "type_text":
        if "text" not in params:
            raise ValueError("bad_request", "type without text")
        args = {"text": str(params["text"])}
        if params.get("clear_first"):
            args["clear_first"] = True
    elif tool == "press_keys":
        keys = [str(k).lower() for k in (params.get("keys") or [])]
        if not keys:
            raise ValueError("bad_request", "press without keys")
        args = {"keys": keys}
    elif tool == "open_app":
        app = params.get("app") or app
        args = {"name": str(app or "")}
    else:
        args = {}
    try:
        call = ToolCall(call_id=str(req["action_id"]), tool=tool, args=args,
                        target_element_id=req.get("target_element_id"))
    except Exception as e:                                                    # noqa: BLE001  (pydantic)
        raise ValueError("bad_request", f"not a valid Team 1 ToolCall: {type(e).__name__}") from None
    return call, app


def _observation(req: dict):
    """The observation Team 1 needs (it checks the window the elements came from). A dict passed in the request
    wins; otherwise the last one vision.vision_adapter saw, which must be the request's observation_id."""
    if isinstance(req.get("observation"), dict):
        return req["observation"], None
    from vision import vision_adapter                                         # noqa: PLC0415
    last = getattr(vision_adapter, "_last", [None])[0]
    if last is None:
        return None, None
    oid = req.get("observation_id")
    if oid is not None and oid != last.get("screenshot_id"):
        return None, ("observation_mismatch", f"observation {oid!r} is not the last one seen: re-perceive")
    obs = last.get("observation")
    return (obs.model_dump(mode="json") if hasattr(obs, "model_dump") else obs), None


def from_action_result(req: dict, res, t0: float, dry: bool) -> dict:
    """Team 1 ActionResult -> our result. The action_id is the request's, whatever the executor returned."""
    team1 = getattr(res, "status", None)
    status = STATUS.get(team1, "failed")
    error = getattr(res, "error", None)
    code = None
    if team1 == "blocked":
        code = (error or "").split(":", 1)[0].strip() or "blocked"
    elif team1 == "error" or team1 not in STATUS:
        code = "executor_error"
    point = getattr(res, "screen_point", None)
    evidence = {"team1_status": team1, "call_id": getattr(res, "call_id", None), "tool": getattr(res, "tool", None),
                "before_id": getattr(res, "before_id", None), "after_id": getattr(res, "after_id", None),
                "target_element_id": getattr(res, "target_element_id", None),
                "screen_point": list(point) if point else None,
                "call_id_matches": getattr(res, "call_id", None) == str(req.get("action_id"))}
    return _result(req, status, t0, dry, reject_code=code, error=error, evidence=evidence)


def execute(req: dict) -> dict:
    t0 = time.time()
    dry = not live_requested()
    if control.cancelled():
        return _result(req, "cancelled", t0, dry, error="stopped before acting")
    try:
        call, app = to_tool_call(req)
    except ValueError as e:
        code, text = (e.args + ("",))[:2]
        return _result(req, "failed", t0, dry, reject_code=code, error=text)
    observation, rejected = _observation(req)
    if rejected:
        return _result(req, "failed", t0, dry, reject_code=rejected[0], error=rejected[1])
    try:
        res = _executor(dry).execute(call, observation=observation, stop=_ControlStop(), app=app)
    except Exception as e:                                                    # noqa: BLE001
        return _result(req, "failed", t0, dry, reject_code="executor_error", error=f"{type(e).__name__}: {e}")
    return from_action_result(req, res, t0, dry)
