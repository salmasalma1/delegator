import os as _o0; _o0.environ.setdefault("NELLY_DRY_RUN", "1")  # tests never move the real mouse
import sys, types, os
sys.path.insert(0, ".")
m = types.ModuleType("graph.subgraphs"); a = types.ModuleType("graph.subgraphs.app_subgraph"); a.run_app_subgraph = lambda **k: {}
sys.modules["graph.subgraphs"] = m; sys.modules["graph.subgraphs.app_subgraph"] = a
import llm, reasoning
from reasoning import QwenProvider, PlanError, validate_plan
good = [{"node": "Notepad: write note", "app": "Notepad", "flag": "Notepad shows the text 'hi'", "steps": ["write hi in the document"]},
        {"node": "Chrome: search", "app": "Chrome", "worker": "browser", "flag": "Search results page for 'x' is visible", "steps": ["search for x"]}]
calls = []
def seq(*outs):
    it = iter(outs)
    def f(system, user, **k):
        calls.append(user); o = next(it)
        if isinstance(o, Exception): raise o
        return o
    return f
P = QwenProvider()
# 1) valid plan is normalised (ids, depends_on, resource)
llm.chat_json = seq(good); n = P.plan("t")
assert [x["id"] for x in n] == ["n1", "n2"] and n[1]["depends_on"] == ["n1"] and n[0]["resource"] == "desktop" and n[1]["resource"] == "browser:default"
# 2) bad flag -> ONE retry with the reason fed back -> accepted
bad = [{"node": "A: x", "app": "A", "flag": "done", "steps": ["s"]}]
calls.clear(); llm.chat_json = seq(bad, good); n = P.plan("t")
assert len(calls) == 2 and "cannot be checked on screen" in calls[1] and len(n) == 2
# 3) two bad answers -> PlanError, NOT a Notepad plan
llm.chat_json = seq(bad, bad)
try: P.plan("t"); assert 0
except PlanError as e: assert "no valid plan" in str(e) and e.clarify is None
llm.chat_json = seq(ValueError("unparseable model answer: blah"), ValueError("x"))
try: P.plan("t"); assert 0
except PlanError: pass
# 4) clarify, no model, too many nodes, bad worker, empty steps
llm.chat_json = seq({"clarify": "Who should I send it to?"})
try: P.plan("t"); assert 0
except PlanError as e: assert e.clarify == "Who should I send it to?"
llm.chat_json = seq(llm.LLMUnavailable("no key"))
try: P.plan("t"); assert 0
except PlanError as e: assert "no model" in str(e)
assert validate_plan(good * 5)[1] and validate_plan([{**good[0], "worker": "x"}])[1] and validate_plan([{**good[0], "steps": []}])[1] and validate_plan([])[1]
# 5) replan context reaches the model
calls.clear(); llm.chat_json = seq(good)
P.plan("t", replan_ctx={"failed_node": {"node": "B"}, "reason": "flag not met", "completed_nodes": [{"node": "A"}], "attempt": 1})
assert "REPLAN" in calls[0] and "flag not met" in calls[0] and "['A']" in calls[0]
# 6) director: failure -> failed; clarify -> escalate; replan renumbers ids
import graph.nodes.director as dr, planner
def boom(*a, **k): raise PlanError("x")
dr.plan_task = boom
assert dr.director_node({"goal": "g"})["status"] == "failed"
def ask(*a, **k): raise PlanError("x", clarify="which file?")
dr.plan_task = ask
o = dr.director_node({"goal": "g"}); assert o["status"] == "escalate" and "which file?" in o["escalation_reason"] and o["requires_user"]
dr.plan_task = lambda *a, **k: n
s = {"goal": "g", "nodes": n, "current_node_idx": 2, "sub_results": ["r1", "r2"], "status": "replan"}
o = dr.director_node(s); assert [x["id"] for x in o["nodes"]] == ["n1", "n2", "n3"] and o["nodes"][2]["depends_on"] == ["n2"]
# 7) builder routes
for n_ in ("langgraph", "langgraph.graph", "langgraph.checkpoint", "langgraph.checkpoint.memory"): sys.modules[n_] = types.ModuleType(n_)
sys.modules["langgraph.graph"].StateGraph = object; sys.modules["langgraph.graph"].END = "END"; sys.modules["langgraph.checkpoint.memory"].MemorySaver = object
import graph.builder as B
assert B.route_after_director({"status": "escalate"}) == "escalate" and B.route_after_director({"status": "failed"}) == "end" and B.route_after_director({"status": "delegating"}) == "plan_check"
# 8) "Windows Shell" is not an application: refused once, then the corrected plan is accepted
shell = [{"node": "Windows Shell: Open Notepad", "app": "Windows Shell", "flag": "A Notepad window is open", "steps": ["open notepad"]}]
calls.clear(); llm.chat_json = seq(shell, good); n = P.plan("t")
assert len(calls) == 2 and "is not an application" in calls[1] and n[0]["app"] == "Notepad"
assert "Windows Shell" in reasoning.SYSTEM and "never" in reasoning.SYSTEM     # the prompt names the rule
print("OK brain")
