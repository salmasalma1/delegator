from graph.state import AgentState
from persistence import audit
from graph import node_status as ns

NOT_EXECUTED = ns.NOT_EXECUTED      # step statuses that mean "nothing was really done on the machine"


def _mark(state, idx, new, reason=""):
    """Nodes list with nodes[idx] moved to `new` (only when it is in the status Verify expects)."""
    nodes = state.get("nodes") or []
    return ns.with_status(nodes, idx, new, reason, state.get("plan_round", 1))


def _persist(state, out):
    """
    Save the post-verdict snapshot in the shape the store expects.

    The store reads `step_number`; AgentState carries `current_node_idx` (already advanced
    by delegate, so the node that just ran is idx-1). We set the key here rather than
    asking the store to know our field names.
    """
    merged = {**state, **out}
    idx = merged.get("current_node_idx", 0)
    merged["step_number"] = max(0, int(idx) - 1)
    audit.record(merged)
    return out


def verify_step_node(state: AgentState) -> dict:
    """
    NODE-LEVEL gate, inside the loop.
    Runs right after one plan node executed: did its `flag` hold?
    Routes to: next node / replan (director) / escalate.
    """
    from verifier import get_verifier

    nodes = state.get("nodes", [])
    idx = state.get("current_node_idx", 1) - 1          # index of the node just run
    sub = state.get("last_sub_result") or {}
    if idx < 0 or idx >= len(nodes):
        return _persist(state, {"status": "escalate", "escalation_reason": "verify_step: no node in scope"})

    node = nodes[idx]

    # Worker already refused to act (unreadable grounding / ungrounded step) -> escalate.
    if sub.get("status") in ("needs_review", "needs_regrounding", "needs_approval"):
        return _persist(state, {
            "status": "escalate",
            "escalation_reason": sub.get("error") or sub.get("status"),
            "requires_user": True,
        })

    verdict = get_verifier().verify(
        node, sub, state.get("grounding"), state.get("after_screenshot")
    )
    # A step that was only a dry run (or never executed) proved nothing about the screen.
    # The verdict may still pass the wiring check, but it is recorded as NOT executed.
    executed = not any(s.get("status") in NOT_EXECUTED for s in (sub.get("steps_done") or []))
    entry = {"node": node.get("node"), "app": node.get("app"), "flag": node.get("flag"),
             "round": state.get("plan_round", 1), "executed": executed, **verdict}
    verifications = (state.get("verifications") or []) + [entry]

    # Node status: only Verify can say `verified`, and a dry run is never promoted.
    cur = ns.status_of(node)
    if cur == ns.SUCCEEDED:
        nodes = _mark(state, idx, ns.VERIFIED if verdict["passed"] else ns.FAILED,
                      "flag held" if verdict["passed"] else verdict["reason"])

    if verdict["passed"]:
        if state.get("current_node_idx", 0) < len(nodes):
            return _persist(state, {"status": "delegating", "verifications": verifications, "nodes": nodes})
        return _persist(state, {"status": "verified", "verifications": verifications, "nodes": nodes})

    # Failed -> give the Brain one more shot, bounded.
    replans = state.get("replans", 0)
    max_replans = state.get("max_replans", 2)
    if replans < max_replans:
        return _persist(state, {
            "status": "replan",
            "nodes": nodes,
            "verifications": verifications,
            "replans": replans + 1,
            "replan_reason": f"flag not met at node {idx}: {verdict['reason']}",
            "failed_node": nodes[idx],
        })
    return _persist(state, {
        "status": "escalate",
        "nodes": nodes,
        "verifications": verifications,
        "escalation_reason": f"max_replans({max_replans}) exhausted at node {idx}: {verdict['reason']}",
        "requires_user": True,
    })


def finalize_node(state: AgentState) -> dict:
    """TASK-LEVEL close-out: all flags verified? Audit trail. Never claims success blindly."""
    verifs = state.get("verifications") or []
    nodes = state.get("nodes") or []
    escalated = state.get("status") == "escalate" or state.get("requires_user")

    # Judge the FINAL plan only; earlier failures stay in the audit trail but are superseded.
    final_round = state.get("plan_round", 1)
    recent = [v for v in verifs if v.get("round", 1) == final_round] or verifs

    passed = sum(1 for v in recent if v.get("passed"))
    failed = [v for v in recent if not v.get("passed")]
    # nodes kept from an earlier round were verified there; count them if they are still in the final plan
    plan_names = {n.get("node") for n in nodes}
    covered = len({v["node"] for v in verifs if v.get("passed") and v["node"] in plan_names})

    never_ran = any(v.get("executed") is False for v in recent)

    if escalated:
        status = "escalated"
    elif nodes and covered >= len(nodes) and not failed:
        # Wiring passed, but if any step was only a dry run, do NOT claim the task is done.
        status = "dry_run" if never_ran else "completed"
    elif failed:
        status = "failed"
    else:
        status = "incomplete"

    return {
        "status": status,
        "verification_summary": {
            "final_round": final_round,
            "attempts_total": len(verifs),
            "nodes_planned": len(nodes),
            "nodes_verified": covered,
            "checks": len(verifs),
            "passed": passed,
            "failed": len(failed),
            "replans": state.get("replans", 0),
            "methods": sorted({v.get("method") for v in verifs}),
            "semantic": any(v.get("semantic") for v in verifs),
            "executed_all": not never_ran,
            "node_statuses": [ns.status_of(n) for n in nodes],
            "superseded": len(state.get("superseded_nodes") or []),
            "plan_check": (state.get("plan_check") or {}).get("method"),
        },
    }