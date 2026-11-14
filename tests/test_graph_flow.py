import sys, types, os
sys.path.insert(0, ".")
os.environ["NELLY_PERSIST"] = "0"; os.environ["NELLY_VERIFIER"] = "rule"
import llm
import graph.subgraphs.app_subgraph as app_sub      # real path now

ELS = [{"id": "e_edit", "type": "input", "text": "", "bbox_norm": [0.1,0.2,0.5,0.5], "confidence": .9,
        "clickable": True, "source": "fast"},
       {"id": "e_save", "type": "button", "text": "Save", "bbox_norm": [0.8,0.9,0.9,0.95], "confidence": .9,
        "clickable": True, "source": "fast"}]
CTX = {"app": "X", "elements": ELS, "needs_review": False, "vision_source": "t", "warnings": [],
       "quality": {"score": .9, "reasons": []}, "status": "ok", "window_title": "w"}
app_sub.perceive_screen = lambda *a, **k: CTX
llm.available = lambda: True

from graph.action_decider import decide_action
# 1) LLM picks action + element; a free-form step with NO leading verb works
llm.chat_json = lambda s, u, **k: {"action": "type", "element_id": "e_edit", "text": "hello", "why": "field"}
d = decide_action("put the greeting into the document", "X", "n", CTX)
assert d["status"] == "ok" and d["action"] == "type" and d["params"]["text"] == "hello" and d["decider"] == "llm"
# 2) hallucinated id / disallowed action / 'none' are rejected, never executed
for bad in ({"action": "click", "element_id": "e_nope"}, {"action": "format_disk"}, {"action": "none", "why": "x"},
            {"action": "type", "element_id": "e_edit"}, {"action": "press", "keys": []}):
    llm.chat_json = lambda s, u, _b=bad, **k: _b
    assert decide_action("s", "X", "n", CTX)["status"] == "unresolved", bad
# 3) press needs no element and the worker completes; safety port records mock=True
_o = iter([{"action": "press", "keys": ["Ctrl", "S"], "why": "save"}, {"action": "finish", "why": "saved"}])
llm.chat_json = lambda s, u, **k: next(_o)
r = app_sub.run_app_subgraph("Notepad", "n", ["save it"], "t", flag="saved")
assert r["status"] == "completed" and r["steps_done"][0]["target"]["element_id"] is None
assert r["steps_done"][0]["safety"]["mock"] is True and r["steps_done"][0]["status"] == "unexecuted"
# 4) always-ask action -> needs_approval with the frozen request, nothing executed
from graph.safety_port import MockSafety
r = MockSafety().check({"action_id": "a", "action_type": "delete_file", "parameters": {}})
assert r["decision"] == "needs_user_approval"
import graph.safety_port as sp
class Ask:
    def check(self, req): return {"decision": "needs_approval", "reason": "r", "action_id": req["action_id"]}
app_sub.get_safety = lambda: Ask()
llm.chat_json = lambda s, u, **k: {"action": "press", "keys": ["a"], "why": "w"}
r = app_sub.run_app_subgraph("Notepad", "n", ["save it"], "t")
assert r["status"] == "needs_approval" and r["proposed_action"]["action_type"] == "press" and not r["steps_done"]
app_sub.get_safety = sp.get_safety
# 5) no model -> legacy decider, labelled
llm.available = lambda: False
d = decide_action("click Save", "X", "n", CTX); assert d["decider"] == "legacy_prefix" and d["element"]["id"] == "e_save"
llm.available = lambda: True

# 6) plan_check
from graph.nodes.plan_check import plan_check_node
st = {"goal": "open a file, edit it and send on whatsapp", "nodes": [{"node": "a"}]}
llm.chat_json = lambda s, u, **k: {"ok": False, "missing": ["send"], "extra": [], "reason": "no send"}
o = plan_check_node(st); assert o["status"] == "replan" and o["plan_check_retries"] == 1 and "send" in o["replan_reason"]
o = plan_check_node({**st, "plan_check_retries": 1}); assert o["status"] == "escalate" and o["requires_user"]
llm.chat_json = lambda s, u, **k: {"ok": True}
assert plan_check_node(st)["status"] == "delegating"
def boom(*a, **k): raise llm.LLMUnavailable("x")
llm.chat_json = boom
o = plan_check_node(st); assert o["status"] == "delegating" and o["plan_verdict"]["method"] == "skipped"

# 7) whole graph: plan mismatch -> re-plan -> match -> execute -> final status honest (unexecuted)
import graph.nodes.director as dr
plans = [[{"node": "A", "flag": "f", "app": "Notepad", "steps": ["s"]}],
         [{"node": "A", "flag": "f", "app": "Notepad", "steps": ["s"]}, {"node": "B", "flag": "f2", "app": "Notepad", "steps": ["s2"]}]]
calls = []
def fake_plan(task, vision_ctx=None, memory_ctx=None, replan_ctx=None):
    calls.append(replan_ctx); return plans[min(len(calls) - 1, 1)]
dr.plan_task = fake_plan
verdicts = iter([{"ok": False, "missing": ["B"], "extra": [], "reason": "r"}, {"ok": True}])
def seq(s, u, **k):
    if "You review the PLAN" in s: return next(verdicts)
    return {"action": "finish", "why": "w"} if "1. press" in u else {"action": "press", "keys": ["a"], "why": "w"}
llm.chat_json = seq

# langgraph is not installed here: stub it only so builder imports, then drive the REAL nodes and
# the REAL route_* functions by hand (same topology as build_graph).
for n in ("langgraph", "langgraph.graph", "langgraph.checkpoint", "langgraph.checkpoint.memory"):
    sys.modules[n] = types.ModuleType(n)
sys.modules["langgraph.graph"].StateGraph = object; sys.modules["langgraph.graph"].END = "END"
sys.modules["langgraph.checkpoint.memory"].MemorySaver = object
import graph.builder as B
from graph.nodes.delegate import delegate_node
from graph.nodes.verify import verify_step_node, finalize_node
from graph.nodes.escalate import escalate_node
s = {"goal": "do A then B", "task_id": "t1", "max_replans": 2}
node, trace = "director", []
while True:
    trace.append(node)
    if node == "director":
        s.update(dr.director_node(s)); node = B.route_after_director(s)
        node = "plan_check" if node == "plan_check" else "END"
    elif node == "plan_check":
        s.update(plan_check_node(s)); node = B.route_after_plan_check(s)
    elif node == "delegate":
        s.update(delegate_node(s)); node = "verify_step"
    elif node == "verify_step":
        s.update(verify_step_node(s)); node = B.route_after_verify(s)
    elif node == "escalate":
        s.update(escalate_node(s)); node = "finalize"
    elif node == "finalize":
        s.update(finalize_node(s)); break
final = s
print(trace)
assert trace[:4] == ["director", "plan_check", "director", "plan_check"], trace
assert calls[0] is None and calls[1]["reason"].startswith("plan does not match"), calls
assert final["status"] == "dry_run" and final["plan_round"] == 2 and final.get("replans", 0) == 0, final["status"]
assert final["verification_summary"]["plan_check"] == "llm" and len(final["nodes"]) == 2
print("OK all")
