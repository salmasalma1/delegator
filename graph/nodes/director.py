from graph.state import AgentState
from planner import plan_task

def director_node(state: AgentState) -> dict:
    goal = state.get("goal", "")
    if not goal or not goal.strip():
        return {"status": "failed", "error": "empty task"}
    nodes = plan_task(goal, vision_ctx=state.get("last_vision_result"), memory_ctx=state.get("sub_results"))
    return {"status": "delegating", "nodes": nodes, "current_node_idx": 0, "sub_results": [], "total_steps": len(nodes)}