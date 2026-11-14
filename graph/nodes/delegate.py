import time

from graph.state import AgentState
from graph import node_status as ns
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
        flag=node.get("flag"), max_actions=node.get("max_actions"),
    )
    # The verifier reads state["after_screenshot"]. Without this the VLM verifier never runs.
    # Reset it every node so a stale screenshot from the previous node is never judged.
    after = (result.get("last_execution_result") or {}).get("screenshot_after_ref")

    rnd = state.get("plan_round", 1)
    nodes = ns.with_status(nodes, idx, ns.RUNNING, "delegated", rnd)
    final = ns.worker_to_node_status(result)
    nodes = ns.with_status(nodes, idx, final, result.get("error") or result.get("finish_reason") or "", rnd)

    # action level: tag each action row with the node and plan round it belongs to
    node_id = node.get("id")
    new_actions = [{**a, "node_id": node_id, "round": rnd} for a in (result.get("actions") or [])]

    return {
        "nodes": nodes,
        "actions": (state.get("actions") or []) + new_actions,
        "after_screenshot": after,
        "status": "executed",
        "latency_ms": int((time.time() - t0) * 1000),
        "last_sub_result": result,
        "last_safety_decision": result.get("last_safety_decision"),
        "grounding": result.get("last_vision_result"),
        "sub_results": (state.get("sub_results") or []) + [result],
        "current_node_idx": idx + 1,
    }