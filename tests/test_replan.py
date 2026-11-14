import os as _o0; _o0.environ.setdefault("NELLY_DRY_RUN", "1")  # tests never move the real mouse
import sys; sys.path.insert(0, "."); 
import planner
calls = []
def fake(task, vision_ctx=None, memory_ctx=None, replan_ctx=None):
    calls.append(replan_ctx)
    return [{"node": "N-new", "flag": "f", "app": "X", "steps": ["s"]}] if replan_ctx else \
           [{"node": "A", "flag": "fa", "app": "X", "steps": ["s"]}, {"node": "B", "flag": "fb", "app": "X", "steps": ["s"]}]
planner.plan_task = fake
import graph.nodes.director as d
d.plan_task = fake

s = {"goal": "g"}
s.update(d.director_node(s)); assert s["plan_round"] == 1 and len(s["nodes"]) == 2
# node A ran and passed, node B ran and failed -> idx advanced to 2, status replan
s.update({"current_node_idx": 2, "sub_results": ["rA", "rB"], "status": "replan",
          "replan_reason": "flag not met", "failed_node": s["nodes"][1], "replans": 1})
out = d.director_node(s)
assert [n["node"] for n in out["nodes"]] == ["A", "N-new"], out["nodes"]
assert out["current_node_idx"] == 1 and out["sub_results"] == ["rA"], out
assert out["plan_round"] == 2 and out["status"] == "delegating"
r = calls[-1]; assert r["reason"] == "flag not met" and [n["node"] for n in r["completed_nodes"]] == ["A"]
# failure at the very first node -> resumes from 0
s2 = {"goal": "g", "nodes": [{"node": "A"}], "current_node_idx": 1, "sub_results": ["rA"], "status": "replan"}
o2 = d.director_node(s2); assert o2["current_node_idx"] == 0 and o2["sub_results"] == []
print("OK")
