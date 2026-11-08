import time

from graph.state import AgentState
from graph.subgraphs.app_subgraph import run_app_subgraph


def delegate_node(state: AgentState) -> dict:
    """Main: execute exactly ONE plan node, hand it to verify. Makes no pass/fail call."""
    nodes = state.get("nodes", [])
    idx = state.get("current_node_idx", 0)
    if idx >= len(nodes):
        return {"status": "nodes_exhausted"}

    node = nodes[idx]
    t0 = time.time()
    result = run_app_subgraph(
        app=node.get("app", "Notepad"), node=node.get("node", ""),
        steps=node.get("steps", []), task_id=state.get("task_id", ""),
        screenshot=state.get("screenshot"), scenario=state.get("vision_scenario"),
    )
    return {
        "status": "executed",
        "latency_ms": int((time.time() - t0) * 1000),
        "last_sub_result": result,
        "last_safety_decision": result.get("last_safety_decision"),
        "grounding": result.get("last_vision_result"),
        "sub_results": (state.get("sub_results") or []) + [result],
        "current_node_idx": idx + 1,
    }