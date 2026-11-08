from graph.state import AgentState


def escalate_node(state: AgentState) -> dict:
    """
    Terminal sink for anything the agent must NOT decide alone:
    unreadable screen, ungrounded step, flag failed after max_replans.
    Phase 1: record + ask. P3: langgraph interrupt() for real HITL resume.
    """
    reason = (state.get("escalation_reason")
              or (state.get("last_sub_result") or {}).get("error")
              or "unknown")
    return {
        "status": "escalate",
        "requires_user": bool(state.get("requires_user", True)),
        "escalation": {
            "reason": reason,
            "failed_node": (state.get("failed_node") or {}).get("node"),
            "replans": state.get("replans", 0),
            "question": f"NELLY stopped: {reason}. Should I retry, skip this step, or take over?",
        },
    }