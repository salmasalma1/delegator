from graph.state import AgentState
from planner import plan_task
from reasoning import PlanError


def _replan_context(state: AgentState, done: int) -> dict:
    """What the planner needs to fix ONE failed step instead of starting over."""
    nodes = state.get("nodes") or []
    return {
        "reason": state.get("replan_reason"),
        "failed_node": state.get("failed_node"),
        "completed_nodes": nodes[:done],        # already done and verified: do not redo
        "attempt": state.get("replans", 0),
    }


def _renumber(nodes: list) -> list:
    out = []
    for i, n in enumerate(nodes):
        n = dict(n)
        n["id"] = f"n{i + 1}"
        n["depends_on"] = [f"n{i}"] if i else []
        out.append(n)
    return out


def _plan_failed(e: PlanError) -> dict:
    """No plan is better than a made-up one. A question for the user goes to escalate."""
    if e.clarify:
        return {"status": "escalate", "requires_user": True,
                "escalation_reason": f"need your input: {e.clarify}"}
    return {"status": "failed", "error": str(e)}


def director_node(state: AgentState) -> dict:
    goal = state.get("goal", "")
    if not goal or not goal.strip():
        return {"status": "failed", "error": "empty task"}

    # The freshest screen we have is `grounding`; `last_vision_result` is never set by the graph.
    vision = state.get("grounding") or state.get("last_vision_result")

    # ---- REPLAN: keep what already passed, re-plan only from the failed step ----
    if state.get("status") == "replan":
        # delegate already advanced current_node_idx, so the node that failed is idx-1.
        done = max(0, int(state.get("current_node_idx", 1)) - 1)
        old_nodes = state.get("nodes") or []
        kept_nodes = old_nodes[:done]
        kept_results = (state.get("sub_results") or [])[:done]

        try:
            new_nodes = plan_task(goal, vision_ctx=vision, memory_ctx=kept_results,
                                  replan_ctx=_replan_context(state, done))
        except PlanError as e:
            return _plan_failed(e)
        nodes = _renumber(kept_nodes + new_nodes)   # new plan ids restart at n1: keep ids unique
        return {
            "status": "delegating",
            "nodes": nodes,
            "current_node_idx": done,           # resume at the first NEW node
            "sub_results": kept_results,
            "total_steps": len(nodes),
            "plan_round": state.get("plan_round", 1) + 1,
        }

    # ---- FIRST PLAN ----
    try:
        nodes = plan_task(goal, vision_ctx=vision, memory_ctx=state.get("sub_results"))
    except PlanError as e:
        return _plan_failed(e)
    return {"status": "delegating", "nodes": nodes, "current_node_idx": 0,
            "sub_results": [], "total_steps": len(nodes), "plan_round": 1}
