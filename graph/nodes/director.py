from graph.state import AgentState
from planner import plan_task


def _replan_context(state: AgentState, done: int) -> dict:
    """What the planner needs to fix ONE failed step instead of starting over."""
    nodes = state.get("nodes") or []
    return {
        "reason": state.get("replan_reason"),
        "failed_node": state.get("failed_node"),
        "completed_nodes": nodes[:done],        # already done and verified: do not redo
        "attempt": state.get("replans", 0),
    }


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

        new_nodes = plan_task(goal, vision_ctx=vision, memory_ctx=kept_results,
                              replan_ctx=_replan_context(state, done))
        nodes = kept_nodes + new_nodes
        return {
            "status": "delegating",
            "nodes": nodes,
            "current_node_idx": done,           # resume at the first NEW node
            "sub_results": kept_results,
            "total_steps": len(nodes),
            "plan_round": state.get("plan_round", 1) + 1,
        }

    # ---- FIRST PLAN ----
    nodes = plan_task(goal, vision_ctx=vision, memory_ctx=state.get("sub_results"))
    return {"status": "delegating", "nodes": nodes, "current_node_idx": 0,
            "sub_results": [], "total_steps": len(nodes), "plan_round": 1}
