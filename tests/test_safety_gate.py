import sys, os, types
sys.path.insert(0, ".")
os.environ["NELLY_PERSIST"] = "0"
from graph import safety_port as sp

def req(action="click", app="Notepad", **k):
    return {"action_id": "a1", "task_id": "t", "action_type": action, "application": app,
            "risk_level": sp.classify(action)[0], "reversible": True, "parameters": {}, **k}

# 1) vocabulary = Team 3's frozen schema; legacy spellings are mapped and flagged; unknown fails closed
assert sp.normalize_decision({"decision": "denied"})["decision"] == "rejected"
d = sp.normalize_decision({"decision": "needs_approval"}); assert d["decision"] == "needs_user_approval" and d["normalized_from"] == "needs_approval"
assert sp.normalize_decision({"decision": "allow"})["decision"] == "approved"
assert sp.normalize_decision({"decision": "banana"})["decision"] == "blocked"
assert sp.normalize_decision(None)["decision"] == "blocked"
assert sp.normalize_decision({})["decision"] == "blocked"

# 2) mock policy: low risk approved; always-ask asks; outside allowlist asks; strict asks above low
sp.reset(); g = sp.get_safety()
r = g.check(req("click")); assert r["decision"] == "approved" and r["mock"] and r["policy_mode"] == "standard" and r["proposal_hash"]
assert g.check(req("delete_file"))["decision"] == "needs_user_approval"
assert g.check(req("click", app="Calculator"))["decision"] == "needs_user_approval"
os.environ["NELLY_APP_ALLOWLIST"] = "Calculator"; assert sp.get_safety().check(req("click", app="Calculator"))["decision"] == "approved"; del os.environ["NELLY_APP_ALLOWLIST"]
os.environ["NELLY_POLICY_MODE"] = "strict"; sp.reset()
assert sp.get_safety().check(req("type"))["decision"] == "needs_user_approval"
assert sp.get_safety().check(req("click"))["decision"] == "approved"
del os.environ["NELLY_POLICY_MODE"]

# 3) no approver bound -> pauses, and the reason says so (never a silent yes)
sp.reset(); g = sp.get_safety(); r = g.check(req("send_message"))
assert r["decision"] == "needs_user_approval" and r["approver"] == "none" and "no approver bound" in r["reason"]

# 4) bound approver: once, deny, session scope; always-ask collapses scope to once and never gets a session grant
asked = []
def approver(answer):
    def f(p): asked.append(p); return answer
    return f
os.environ["NELLY_POLICY_MODE"] = "strict"; sp.reset(); g = sp.get_safety()
with sp.bind_approver(approver({"granted": True, "scope": "session"})):
    r = g.check(req("type"))
    assert r["decision"] == "approved" and r["approval_scope"] == "session" and r["approval_id"] and asked[-1]["scopes"] == ["once", "session"]
    n = len(asked); r2 = g.check(req("type"))                                # same action+app later: no new question
    assert r2["decision"] == "approved" and r2["approval_scope"] == "session" and len(asked) == n
    r3 = g.check(req("delete_file")); assert asked[-1]["scopes"] == ["once"]    # no session option is offered
    assert r3["approval_scope"] == "once"
    r4 = g.check(req("click", app="Calculator")); assert asked[-1]["scopes"] == ["once"]   # outside the allowlist: always asks
    n = len(asked); g.check(req("delete_file")); assert len(asked) == n + 1       # always-ask asks again every time
del os.environ["NELLY_POLICY_MODE"]
with sp.bind_approver(approver({"granted": False})):
    sp.reset(); r = sp.get_safety().check(req("send_message")); assert r["decision"] == "rejected" and r["approval_id"]
assert sp._approver[0] is None                                                    # unbound after the run

# 5) the proposal hash follows the request: a changed request has a different hash
a = req("click"); h = sp.proposal_hash(a); a["parameters"] = {"text": "x"}; assert sp.proposal_hash(a) != h

# 6) Team 3's module: used, normalized, and a crash fails closed
mod = types.ModuleType("fake_safety"); mod.check = lambda r: {"decision": "allow", "policy_id": "p1"}; sys.modules["fake_safety"] = mod
os.environ["NELLY_SAFETY_MODULE"] = "fake_safety"; sp.reset(); r = sp.get_safety().check(req("click"))
assert r["decision"] == "approved" and r["mock"] is False and r["normalized_from"] == "allow" and r["policy_id"] == "p1"
mod.check = lambda r: 1 / 0; sp.reset(); r = sp.get_safety().check(req("click"))
assert r["decision"] == "blocked" and "ZeroDivisionError" in r["reason"]
del os.environ["NELLY_SAFETY_MODULE"]; sp.reset()

# 7) worker: action rows carry the decision/approval; a changed request is not executed
import graph.subgraphs.app_subgraph as w
w._act = lambda r: {"action_id": r["action_id"], "task_id": r["task_id"], "status": "success", "duration_ms": 5, "screenshot_after_ref": "s.png", "output": {}}
dec = {"action": "type", "params": {"text": "hi"}, "element": {"element_id": "e1"}, "decider": "llm", "why": "w"}
ctx = {"quality": {"score": 1}}
sub = {"steps_done": []}; sp.reset()
ok, _ = w._perform(dec, "Notepad", "t", sp.get_safety(), sub, ctx, "type hi")
row = sub["actions"][0]
assert ok and row["decision"] == "approved" and row["result_status"] == "success" and row["proposal_hash"] and row["risk_level"] == "medium" and row["policy_mode"] == "standard"
# paused: not run
sub = {"steps_done": []}; dec2 = {**dec, "action": "send_message"}
ok, _ = w._perform(dec2, "Notepad", "t", sp.get_safety(), sub, ctx, "send")
assert not ok and sub["status"] == "needs_approval" and sub["actions"][0]["result_status"] == "not_run" and sub["proposed_action"]["action_type"] == "send_message"
# rejected by the user: failed, not executed
sub = {"steps_done": []}; sp.reset()
with sp.bind_approver(approver({"granted": False})):
    ok, _ = w._perform(dec2, "Notepad", "t", sp.get_safety(), sub, ctx, "send")
assert not ok and sub["status"] == "failed" and "rejected" in sub["error"] and sub["actions"][0]["result_status"] == "not_run"
# tampering between approval and action
class Tamper:
    def check(self, r): d = sp.get_safety().backend.check(r); d["proposal_hash"] = "0" * 64; return d
sub = {"steps_done": []}; ok, _ = w._perform(dec, "Notepad", "t", Tamper(), sub, ctx, "x")
assert not ok and "changed after it was approved" in sub["error"] and sub["actions"][0]["result_status"] == "not_run"

# 8) delegate carries action rows into state with node id and round
import graph.nodes.delegate as dl
from graph import node_status as ns
dl.run_app_subgraph = lambda **k: {"app": "X", "status": "completed", "steps_done": [], "actions": [{"action_id": "z"}]}
s = {"task_id": "t", "nodes": ns.fresh([{"id": "n1", "node": "A", "app": "X", "flag": "f", "steps": []}]), "current_node_idx": 0, "plan_round": 2}
out = dl.delegate_node(s); assert out["actions"] == [{"action_id": "z", "node_id": "n1", "round": 2}]
print("OK safety gate")
