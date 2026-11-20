"""
Run trace: one JSON file that shows what the brain and the vision did in a run.

    python run.py --trace "your task"      -> runs/run_<task_id>.json  and  runs/run_<task_id>.html
    python tools/run_viewer.py runs/run_X.json                         -> the same page from a saved file
    runs/latest.html = the newest run, runs/index.html = every run (rebuilt after each run)

It only RESTATES the final state. It never upgrades a status: `dry_run` stays `dry_run`, `succeeded`
stays "the worker's claim", and only Verify's `verified` is shown as verified.

Privacy: a screen contains private text. By default the trace holds NO window title and NO element text
(only types, boxes, confidences and counts). Set NELLY_TRACE_FULL=1 on your own machine to keep them;
such a file must be cropped or cleaned before it is shown to anyone. No key or header is ever written.
"""
import json
import os

TOP_LOOK_ELEMENTS = 30


def _full() -> bool:
    return os.getenv("NELLY_TRACE_FULL", "") == "1"


def _text(value, full: bool):
    if value in (None, ""):
        return value
    return value if full else f"[{len(str(value))} chars hidden]"


def look_summary(ctx: dict) -> dict:
    """One vision look, reduced to what a person needs. Raw text is kept here and removed on export."""
    q = ctx.get("quality") or {}
    g = ctx.get("grounding") or {}
    els = []
    for e in (ctx.get("elements") or [])[:TOP_LOOK_ELEMENTS]:
        els.append({"id": e.get("id"), "type": e.get("type"), "text": e.get("text"),
                    "bbox_norm": e.get("bbox_norm"), "confidence": e.get("confidence"),
                    "clickable": e.get("clickable")})
    return {
        "source": ctx.get("vision_source"),
        "detector": ctx.get("detector"),
        "app": ctx.get("app"),
        "window_title": ctx.get("window_title"),
        "total_elements": ctx.get("total_elements"),
        "quality": {"score": q.get("score"), "clear": q.get("clear"), "reasons": q.get("reasons")},
        "needs_review": ctx.get("needs_review"),
        "seconds": ctx.get("look_seconds"),
        "warnings": list(ctx.get("warnings") or []),
        "error": ctx.get("error"),
        "grounding": {k: g.get(k) for k in ("target", "element_id", "status", "confidence")} if g else None,
        "elements": els,
    }


def _clean_look(look: dict, full: bool) -> dict:
    out = dict(look)
    out["window_title"] = _text(look.get("window_title"), full)
    out["elements"] = [{**e, "text": _text(e.get("text"), full)} for e in look.get("elements") or []]
    g = out.get("grounding")
    if g:
        out["grounding"] = {**g, "target": _text(g.get("target"), full)}
    return out


def build_trace(state: dict, report: dict = None, full: bool = None, timeline: list = None) -> dict:
    full = _full() if full is None else full
    report = report or {}
    sub_results = state.get("sub_results") or []
    actions = state.get("actions") or []
    verifs = state.get("verifications") or []

    cur = state.get("plan_round", 1)

    def in_round(r: dict, current: bool) -> bool:
        rr = r.get("round")
        return rr is None or (rr >= cur if current else rr < cur)

    def node_view(n: dict, current: bool = True) -> dict:
        nid = n.get("id")
        looks = []
        for r in sub_results:
            if r.get("node_id") == nid and r.get("node") == n.get("node") and in_round(r, current):
                looks += [_clean_look(l, full) for l in (r.get("looks") or [])]
        acts = [{k: a.get(k) for k in ("action_type", "element_id", "decision", "reason", "risk_level",
                                       "policy_mode", "approval_scope", "mock", "result_status", "reject_code",
                                       "latency_ms")}
                for a in actions if a.get("node_id") == nid and in_round(a, current)]
        ver = [v for v in verifs if v.get("node") == n.get("node")]
        return {
            "id": nid, "title": n.get("node"), "app": n.get("app"), "worker": n.get("worker"),
            "resource": n.get("resource"), "depends_on": n.get("depends_on"),
            "flag": n.get("flag"), "steps": n.get("steps"), "status": n.get("status"),
            "history": n.get("history"),
            "verification": [{k: v.get(k) for k in ("passed", "reason", "confidence", "method", "executed", "round")}
                             for v in ver],
            "actions": acts, "looks": looks,
        }

    esc = state.get("escalation") or {}
    return {
        "schema": "nelly.run_trace.v1",
        "task": state.get("goal") or state.get("task") or report.get("task"),
        "task_id": state.get("task_id"),
        "language": state.get("language"),
        "execution_mode": "dry_run" if _is_dry(state) else "live_or_unknown",
        "executor": os.getenv("NELLY_EXECUTOR") or "default",
        "replans": state.get("replans", 0),
        "plan_warnings": (state.get("plan_verdict") or {}).get("warnings"),
        "plan_check": state.get("plan_verdict"),
        "nodes": [node_view(n) for n in state.get("nodes") or []],
        "superseded": [node_view(n, False) for n in state.get("superseded_nodes") or []],
        "final_status": state.get("status") or report.get("status"),
        "final": report.get("headline"),
        "question": report.get("question"),
        "escalation": esc or None,
        "timeline": timeline or [],
        "redacted": not full,
    }


def _is_dry(state: dict) -> bool:
    return any(n.get("status") == "dry_run" for n in state.get("nodes") or []) \
        or (state.get("status") == "dry_run")


def write_trace(state: dict, report: dict = None, out_dir: str = None, html: bool = True,
                timeline: list = None) -> dict:
    """Writes runs/run_<task_id>.json (+ .html). Returns the paths. Never raises into a run."""
    out_dir = out_dir or os.getenv("NELLY_TRACE_DIR") or "runs"
    try:
        os.makedirs(out_dir, exist_ok=True)
        trace = build_trace(state, report, timeline=timeline)
        base = os.path.join(out_dir, f"run_{trace.get('task_id') or 'x'}")
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump(trace, f, ensure_ascii=False, indent=2, default=str)
        paths = {"json": base + ".json"}
        if html:
            from tools.run_viewer import make_html, make_index
            page = make_html(trace)
            with open(base + ".html", "w", encoding="utf-8") as f:
                f.write(page)
            with open(os.path.join(out_dir, "latest.html"), "w", encoding="utf-8") as f:
                f.write(page)
            with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
                f.write(make_index(out_dir))
            paths["html"] = base + ".html"
            paths["index"] = os.path.join(out_dir, "index.html")
        return paths
    except Exception as e:                                   # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
