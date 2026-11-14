import os as _o0; _o0.environ.setdefault("NELLY_DRY_RUN", "1")  # tests never move the real mouse
import sys, os
sys.path.insert(0, ".")
os.environ["NELLY_PERSIST"] = "0"; os.environ["NELLY_VERIFIER"] = "rule"
from graph import node_status as ns
import graph.nodes.director as dr
import graph.nodes.delegate as dl
from graph.nodes.verify import verify_step_node, finalize_node

# 1) state machine
n = {"node": "A"}
assert ns.status_of(n) == "pending"
a = ns.set_status(n, "running"); assert n.get("status") is None and a["status"] == "running"      # copy, never in place
assert ns.can_move("running", "succeeded") and not ns.can_move("succeeded", "pending")
assert not ns.can_move("dry_run", "verified")                                                      # a dry run is never promoted
assert not ns.can_move("running", "verified")                                                      # only after succeeded
bad = ns.set_status({"node": "A", "status": "pending"}, "verified", "x"); assert bad["history"][-1].get("forced")
assert ns.resume_index([{"status": "verified"}, {"status": "dry_run"}, {"status": "failed"}, {"status": "pending"}]) == 2
assert ns.resume_index([{"status": "verified"}]) is None and ns.resume_index([]) is None
assert ns.worker_to_node_status({"status": "completed", "steps_done": [{"status": "success"}]}) == "succeeded"
assert ns.worker_to_node_status({"status": "completed", "steps_done": [{"status": "dry_run"}]}) == "dry_run"
assert ns.worker_to_node_status({"status": "completed", "steps_done": [{"status": "unexecuted"}]}) == "dry_run"
assert ns.worker_to_node_status({"status": "needs_approval"}) == "awaiting_approval"
assert ns.worker_to_node_status({"status": "needs_regrounding"}) == "needs_input" and ns.worker_to_node_status({"status": "needs_review"}) == "needs_input"
assert ns.worker_to_node_status({"status": "failed"}) == "failed"

# 2) director: first plan -> pending; replan keeps verified, supersedes the rest, keeps them for the audit
plans = [[{"node": "A", "app": "X", "flag": "fa", "steps": ["s"]}, {"node": "B", "app": "X", "flag": "fb", "steps": ["s"]}],
         [{"node": "B2", "app": "X", "flag": "fb2", "steps": ["s"]}]]
calls = []
dr.plan_task = lambda *a, **k: (calls.append(k.get("replan_ctx")), plans[min(len(calls) - 1, 1)])[1]
s = {"goal": "g", "task_id": "t"}
s.update(dr.director_node(s)); assert [x["status"] for x in s["nodes"]] == ["pending", "pending"]

# 3) delegate + verify happy path: pending -> running -> succeeded -> verified
def sub(status="completed", step="success", **k): return {"app": "X", "status": status, "steps_done": [{"step": "s", "status": step, "target": {"element_id": "e"}, "execution": {"action_type": "click"}}], **k}
dl.run_app_subgraph = lambda **k: sub()
s.update(dl.delegate_node(s)); assert s["nodes"][0]["status"] == "succeeded"
assert [h["to"] for h in s["nodes"][0]["history"]] == ["running", "succeeded"] and not any(h.get("forced") for h in s["nodes"][0]["history"])
s.update(verify_step_node(s)); assert s["nodes"][0]["status"] == "verified" and s["nodes"][1]["status"] == "pending" and s["status"] == "delegating"

# 4) node B: worker succeeds but the flag is not met -> failed -> replan supersedes B, keeps A verified
dl.run_app_subgraph = lambda **k: {"app": "X", "status": "completed", "steps_done": []}      # rule verifier: no_steps_done -> not passed
s.update(dl.delegate_node(s)); assert s["nodes"][1]["status"] == "succeeded"
s.update(verify_step_node(s)); assert s["status"] == "replan" and s["nodes"][1]["status"] == "failed" and s["failed_node"]["status"] == "failed"
s.update(dr.director_node(s))
assert [(x["node"], x["status"]) for x in s["nodes"]] == [("A", "verified"), ("B2", "pending")], s["nodes"]
assert [(x["node"], x["status"]) for x in s["superseded_nodes"]] == [("B", "superseded")]
assert [h["to"] for h in s["superseded_nodes"][0]["history"]] == ["running", "succeeded", "failed", "superseded"]
assert [x["id"] for x in s["nodes"]] == ["n1", "n2"] and ns.resume_index(s["nodes"]) == 1

# 5) dry run: never verified, final status stays dry_run
dl.run_app_subgraph = lambda **k: sub(step="dry_run")
s.update(dl.delegate_node(s)); assert s["nodes"][1]["status"] == "dry_run"
s.update(verify_step_node(s)); assert s["nodes"][1]["status"] == "dry_run"
s.update(finalize_node(s)); assert s["status"] == "dry_run" and s["verification_summary"]["node_statuses"] == ["verified", "dry_run"] and s["verification_summary"]["superseded"] == 1

# 6) approval / input needed
for worker_status, expect in (("needs_approval", "awaiting_approval"), ("needs_regrounding", "needs_input")):
    t = {"goal": "g", "task_id": "t"}; t.update(dr.director_node({**t})) if False else None
    t = {"goal": "g", "task_id": "t", "nodes": ns.fresh(plans[0]), "current_node_idx": 0}
    dl.run_app_subgraph = lambda _s=worker_status, **k: {"app": "X", "status": _s, "steps_done": [], "error": "e"}
    t.update(dl.delegate_node(t)); assert t["nodes"][0]["status"] == expect
    t.update(verify_step_node(t)); assert t["status"] == "escalate" and t["nodes"][0]["status"] == expect   # stays; resume later
print("OK node status")
