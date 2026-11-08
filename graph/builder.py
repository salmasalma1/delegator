import os

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from graph.state import AgentState
from graph.nodes.director import director_node
from graph.nodes.delegate import delegate_node
from graph.nodes.verify import verify_step_node, finalize_node
from graph.nodes.escalate import escalate_node
from graph.nodes.plan_check import plan_check_node


def route_after_director(s):
    return "end" if s.get("status") == "failed" else "plan_check"


def route_after_plan_check(s):
    status = s.get("status", "")
    if status == "delegating":
        return "delegate"         # plan matches the request
    if status == "replan":
        return "director"         # mismatch, one bounded re-plan
    return "escalate"             # still wrong -> ask the user, run nothing


def route_after_delegate(s):
    return "verify_step"          # every executed node is checked, no exceptions


def route_after_verify(s):
    status = s.get("status", "")
    if status == "delegating":
        return "delegate"         # next plan node
    if status == "verified":
        return "finalize"         # all flags held
    if status == "replan":
        return "director"         # flag failed -> Brain replans (bounded)
    return "escalate"             # unreadable / exhausted / unknown


def route_after_escalate(s):
    return "finalize"             # always close out with an audit trail


def _checkpointer(kind: str = "memory"):
    """
    "memory"  (default) -> MemorySaver, nothing touches disk, tests stay clean.
    "sqlite"            -> LangGraph SqliteSaver, for crash-resume.

    NOTE (verified): LangGraph's saver owns a table literally named `checkpoints`
    with columns (thread_id, checkpoint_ns, checkpoint_id, ...). The checkpoint store
    also owns a table named `checkpoints` with different columns. Same name, different
    schema -> pointing both at one file fails with "no such column: thread_id".
    So the graph checkpointer gets its OWN file; the store's agent.db keeps the domain
    audit (persistence.audit -> save/load/list per the agreed API).
    """
    if kind == "memory":
        return MemorySaver()
    if kind == "sqlite":
        import sqlite3
        from langgraph.checkpoint.sqlite import SqliteSaver
        path = os.getenv("NELLY_GRAPH_DB", "graph_checkpoints.db")
        conn = sqlite3.connect(path, check_same_thread=False)
        saver = SqliteSaver(conn)
        saver.setup()
        return saver
    raise ValueError(f"unknown checkpointer: {kind}")


def build_graph(checkpointer: str = "memory"):
    b = StateGraph(AgentState)
    b.add_node("director", director_node)
    b.add_node("plan_check", plan_check_node)
    b.add_node("delegate", delegate_node)
    b.add_node("verify_step", verify_step_node)
    b.add_node("escalate", escalate_node)
    b.add_node("finalize", finalize_node)

    b.set_entry_point("director")
    b.add_conditional_edges("director", route_after_director, {"plan_check": "plan_check", "end": END})
    b.add_conditional_edges("plan_check", route_after_plan_check,
                            {"delegate": "delegate", "director": "director", "escalate": "escalate"})
    b.add_conditional_edges("delegate", route_after_delegate, {"verify_step": "verify_step"})
    b.add_conditional_edges("verify_step", route_after_verify,
                            {"delegate": "delegate", "director": "director",
                             "finalize": "finalize", "escalate": "escalate"})
    b.add_conditional_edges("escalate", route_after_escalate, {"finalize": "finalize"})
    b.add_edge("finalize", END)

    # Same topology for every task; complexity lives in state["nodes"].
    return b.compile(checkpointer=_checkpointer(checkpointer))