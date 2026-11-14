"""
Node lifecycle. One small state machine so every part of the system talks about a node the same way.

    pending -> running -> succeeded -> verified
                  |            |
                  |            +-> failed
                  +-> awaiting_approval -> running (after approval) | failed | cancelled
                  +-> needs_input       -> running (after the user answered) | cancelled
                  +-> dry_run           (ran, but nothing really happened on the machine)
                  +-> failed
    any non-final node -> cancelled      (user / kill-switch)
    pending / failed / needs_input / dry_run -> superseded   (a replan replaced it)

`succeeded` is only the worker's claim ("I think I am done"). Only Verify can make a node `verified`.
`dry_run` is never promoted to `verified`: it proves nothing about the screen.

Every change is appended to node["history"], so the audit shows the whole path. An illegal change does
not crash a run; it is applied but marked forced=True, which tests assert never happens on normal flows.
"""
from typing import List, Optional

PENDING, RUNNING, AWAITING_APPROVAL = "pending", "running", "awaiting_approval"
SUCCEEDED, VERIFIED, FAILED = "succeeded", "verified", "failed"
NEEDS_INPUT, CANCELLED = "needs_input", "cancelled"
DRY_RUN, SUPERSEDED = "dry_run", "superseded"

ALL = (PENDING, RUNNING, AWAITING_APPROVAL, SUCCEEDED, VERIFIED, FAILED,
       NEEDS_INPUT, CANCELLED, DRY_RUN, SUPERSEDED)

# step statuses that mean "nothing was really done on the machine"
NOT_EXECUTED = ("dry_run", "unexecuted")

_ALLOWED = {
    PENDING: {RUNNING, CANCELLED, SUPERSEDED},
    RUNNING: {AWAITING_APPROVAL, SUCCEEDED, DRY_RUN, FAILED, NEEDS_INPUT, CANCELLED},
    AWAITING_APPROVAL: {RUNNING, FAILED, CANCELLED},
    NEEDS_INPUT: {RUNNING, CANCELLED, SUPERSEDED},
    SUCCEEDED: {VERIFIED, FAILED, CANCELLED},
    FAILED: {SUPERSEDED, RUNNING, CANCELLED},      # RUNNING = a retry of the same node
    DRY_RUN: {SUPERSEDED, CANCELLED},
    VERIFIED: {CANCELLED},
    CANCELLED: set(),
    SUPERSEDED: set(),
}

# a resumed run skips these: they are done (or can never run again)
DONE = (VERIFIED, DRY_RUN, SUPERSEDED, CANCELLED)


def status_of(node: dict) -> str:
    return (node or {}).get("status") or PENDING          # nodes from older code have no status


def can_move(old: str, new: str) -> bool:
    return new in _ALLOWED.get(old, set())


def set_status(node: dict, new: str, reason: str = "", round_: int = 1) -> dict:
    """Return a COPY of the node in the new status (state is never mutated in place)."""
    assert new in ALL, f"unknown node status {new!r}"
    old = status_of(node)
    out = dict(node)
    entry = {"from": old, "to": new, "reason": reason, "round": round_}
    if old != new and not can_move(old, new):
        entry["forced"] = True
        print(f"[node-status] unexpected move {old} -> {new} on {node.get('node')!r} ({reason})")
    out["status"] = new
    out["history"] = list(node.get("history") or []) + [entry]
    return out


def with_status(nodes: List[dict], idx: int, new: str, reason: str = "", round_: int = 1) -> List[dict]:
    """New list where only nodes[idx] changed."""
    out = list(nodes)
    out[idx] = set_status(nodes[idx], new, reason, round_)
    return out


def fresh(nodes: List[dict]) -> List[dict]:
    """Nodes straight from the planner: every one is pending."""
    return [dict(n, status=PENDING, history=[]) for n in nodes]


def resume_index(nodes: List[dict]) -> Optional[int]:
    """Where a restored run continues: the first node that is not done. None = nothing left."""
    for i, n in enumerate(nodes or []):
        if status_of(n) not in DONE:
            return i
    return None


def worker_to_node_status(sub: dict) -> str:
    """Map the worker's result to the node's status. Never `verified`: that is Verify's call."""
    s = sub.get("status")
    if s == "completed":
        ran_nothing = any(st.get("status") in NOT_EXECUTED for st in (sub.get("steps_done") or []))
        return DRY_RUN if ran_nothing else SUCCEEDED
    if s == "needs_approval":
        return AWAITING_APPROVAL
    if s in ("needs_review", "needs_regrounding"):
        return NEEDS_INPUT
    return FAILED
