"""
PLAN CHECK — runs once after the director, BEFORE anything touches the machine.
Question: does this plan do what the user asked — all of it, and nothing more?

Same honesty rule as the verifier: with no model it does not pretend. It lets the plan through
marked method="skipped" so the audit shows the plan was never really checked.
"""
import json

import llm
from graph.state import AgentState

MAX_PLAN_RETRIES = 1          # one re-plan costs one more LLM call; more is a loop, not a fix

SYSTEM = """You review the PLAN of a desktop automation agent BEFORE it runs.
You get the user's request and the plan (an ordered list of nodes: app, steps, completion flag).
Judge only these:
1. COVERAGE: every part of the request is done by some node. List anything missing.
2. NO EXTRAS: no node does something the user did not ask for (especially sending, deleting,
   paying, installing). List anything extra.
3. ORDER: a node never needs a result that a LATER node produces.
4. CHECKABLE: each completion flag is something visible on screen, not "done".
If you are unsure, ok=false and say why. Answer ONLY JSON:
{"ok": true/false, "missing": [], "extra": [], "reason": "short"}"""


def check_plan(goal: str, nodes: list) -> dict:
    try:
        out = llm.chat_json(SYSTEM, f"User request: {goal}\n\nPlan:\n{json.dumps(nodes, ensure_ascii=False, indent=1)}")
    except llm.LLMUnavailable:
        return {"ok": True, "method": "skipped", "reason": "no_model_plan_not_checked",
                "missing": [], "extra": []}
    except Exception as e:                                    # noqa: BLE001
        return {"ok": True, "method": "skipped", "reason": f"plan_check_error:{type(e).__name__}",
                "missing": [], "extra": []}
    if not isinstance(out, dict) or "ok" not in out:
        return {"ok": True, "method": "skipped", "reason": "plan_check_unparseable",
                "missing": [], "extra": []}
    return {"ok": bool(out["ok"]), "method": "llm", "reason": out.get("reason") or "",
            "missing": out.get("missing") or [], "extra": out.get("extra") or []}


def plan_check_node(state: AgentState) -> dict:
    verdict = check_plan(state.get("goal", ""), state.get("nodes") or [])
    if verdict["ok"]:
        return {"status": "delegating", "plan_check": verdict}

    why = f"plan does not match the request. missing={verdict['missing']} extra={verdict['extra']} ({verdict['reason']})"
    retries = state.get("plan_check_retries", 0)
    if retries < MAX_PLAN_RETRIES:
        # Nothing has run yet, so the director re-plans the WHOLE plan (its replan branch with
        # current_node_idx=0 keeps nothing). This does not spend the execution `replans` budget.
        return {"status": "replan", "plan_check": verdict, "plan_check_retries": retries + 1,
                "replan_reason": why, "failed_node": None}
    return {"status": "escalate", "plan_check": verdict, "requires_user": True,
            "escalation_reason": why}
