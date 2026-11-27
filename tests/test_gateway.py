import os as _o0; _o0.environ.setdefault("NELLY_DRY_RUN", "1")  # tests never move the real mouse
import sys, os, types
sys.path.insert(0, ".")
os.environ["NELLY_PERSIST"] = "0"; os.environ["NELLY_VERIFIER"] = "rule"
from gateway.gateway import normalize_task, detect_language, transcribe
from gateway.report import final_report, render
from gateway import session as S
from graph import control, node_status as ns
import graph.nodes.delegate as dl
from graph.nodes.verify import verify_step_node, finalize_node

# 1) the request: language, whitespace, empty, voice is honestly not there
assert detect_language("افتح النوت باد واكتب ملاحظة") == "ar" and detect_language("open notepad") == "en" and detect_language("") == "en"
t = normalize_task("  open   notepad \n now ", session_id="s1"); assert t["goal"] == "open notepad now" and t["language"] == "en" and t["session_id"] == "s1" and t["task_source"] == "text"
for bad in ("", "   ", None):
    try: normalize_task(bad); raise SystemExit("empty task accepted")
    except ValueError: pass
try: transcribe("x.wav"); raise SystemExit("voice must refuse")
except NotImplementedError: pass

# 2) commands: only a message that is JUST the command
for w in ("stop", "Stop.", "وقف!", "الغي", "  cancel "): assert S.parse_command(w) == "cancel", w
assert S.parse_command("open the player and stop the music") is None and S.parse_command("وقف الاغنية بعد دقيقة") is None
assert S.parse_command("exit") == "exit" and S.parse_command("خروج") == "exit"

# 3) report: never upgrades the state
SEM = [{"node": "A", "passed": True, "semantic": True}]
r = final_report({"status": "completed", "language": "en", "nodes": [{"node": "A", "status": "verified"}], "verifications": SEM})
assert "Done" in r["headline"] and "checked on the screen" in r["headline"] and not r["needs_user"] and r["checked_on_screen"]
# honesty: the structural rule verifier never earns "checked on the screen" (problem 10 of the run report)
RULE = [{"node": "A", "passed": True, "semantic": False}]
for st in ({"status": "completed", "language": "en", "nodes": [{"node": "A"}], "verifications": RULE},
           {"status": "completed", "language": "en", "nodes": [{"node": "A"}]},            # no verification recorded
           {"status": "completed", "language": "en", "nodes": []}):
    r = final_report(st)
    assert "structural" in r["headline"] and "checked on the screen" not in r["headline"] and not r["checked_on_screen"], r
r = final_report({"status": "completed", "language": "ar", "nodes": [{"node": "A"}], "verifications": RULE})
assert "هيكلي" in r["headline"] and "اتأكدت من الشاشة" not in r["headline"].replace("ما اتأكدتش من الشاشة", "")
# one node checked on screen, the other only structurally: still not "checked on the screen"
r = final_report({"status": "completed", "language": "en", "nodes": [{"node": "A"}, {"node": "B"}],
                  "verifications": SEM + [{"node": "B", "passed": True, "semantic": False}]})
assert not r["checked_on_screen"] and "structural" in r["headline"], r
# a later passing screen check replaces an earlier structural one for the same node
r = final_report({"status": "completed", "language": "en", "nodes": [{"node": "A"}],
                  "verifications": RULE + SEM})
assert r["checked_on_screen"], r
# a failed screen check does not count
r = final_report({"status": "completed", "language": "en", "nodes": [{"node": "A"}],
                  "verifications": [{"node": "A", "passed": False, "semantic": True}]})
assert not r["checked_on_screen"], r
# other statuses are untouched
assert final_report({"status": "dry_run", "language": "en"})["checked_on_screen"] is False
r = final_report({"status": "dry_run", "language": "en"}); assert "dry run" in r["headline"] and "Done" not in r["headline"]
r = final_report({"status": "dry_run", "language": "ar"}); assert "تجريبي" in r["headline"]
r = final_report({"status": "escalated", "language": "en", "requires_user": True, "escalation_reason": "need your input: Which file?"}); assert r["needs_user"] and r["question"] == "Which file?"
r = final_report({"status": "escalated", "language": "ar", "requires_user": True, "escalation": {"reason": "flag failed"}}); assert r["needs_user"] and "flag failed" in r["question"] and "أعيد" in r["question"]
r = final_report({"status": "cancelled", "language": "en", "requires_user": False}); assert not r["needs_user"] and "Stopped" in r["headline"]
r = final_report({"status": "weird", "language": "en"}); assert "no proof" in r["headline"]
assert "A: verified" in render(final_report({"status": "completed", "language": "en", "nodes": [{"node": "A", "status": "verified"}]}))

# 4) stop switch through the real nodes
control.reset()
nodes = ns.fresh([{"id": "n1", "node": "A", "app": "Notepad", "flag": "f", "steps": ["s"]}, {"id": "n2", "node": "B", "app": "Notepad", "flag": "g", "steps": ["s"]}])
st = {"task_id": "t", "goal": "g", "nodes": nodes, "current_node_idx": 0, "language": "en"}
called = []; dl.run_app_subgraph = lambda **k: called.append(k) or {"status": "completed", "steps_done": []}
control.cancel()
st.update(dl.delegate_node(st)); assert not called and st["nodes"][0]["status"] == "cancelled" and st["last_sub_result"]["status"] == "cancelled"
st.update(verify_step_node(st)); assert st["status"] == "escalate" and st["cancelled"] and st["requires_user"] is False
st.update(finalize_node(st)); assert st["status"] == "cancelled" and st["verification_summary"]["node_statuses"][0] == "cancelled"
assert not final_report(st)["needs_user"]
import graph.subgraphs.app_subgraph as w
r = w.run_app_subgraph("Notepad", "n", ["click File"], "t"); assert r["status"] == "cancelled" and not r["steps_done"] and not r.get("actions")
control.reset(); assert not control.cancelled()

# 5) Session (fake graph): stable session id, new task id, answer to a question, stop, Ctrl+C
class Fake:
    def __init__(self, finals): self.finals, self.goals, self.cfgs, self.i = finals, [], [], -1; self.during = None
    def stream(self, init, config):
        self.i += 1; self.goals.append(init["goal"]); self.cfgs.append(config); self.cur = {**init, **self.finals[self.i]}
        if self.during: self.during()
        yield {"director": {}}
    def get_state(self, config): return types.SimpleNamespace(values=self.cur)
g = Fake([{"status": "escalated", "requires_user": True, "escalation_reason": "need your input: Which folder?"},
          {"status": "completed", "nodes": [{"node": "A", "status": "verified"}]},
          {"status": "dry_run"}, {"status": "completed"}])
events = []; s = S.Session(graph=g, approver=None, on_event=events.append)
o = s.submit("save the file"); assert o["kind"] == "report" and o["report"]["needs_user"] and s.pending["question"] == "Which folder?" and events
o = s.submit("Documents"); assert "save the file" in g.goals[1] and "Which folder?" in g.goals[1] and "Documents" in g.goals[1] and s.pending is None
assert o["report"]["status"] == "completed"
assert g.cfgs[0]["configurable"]["thread_id"] != g.cfgs[1]["configurable"]["thread_id"]          # a new task each time
assert len({h["task_id"] for h in s.history}) == 2 and s.session_id
assert s.submit("stop")["kind"] == "info"                         # nothing running: no crash, no flag left behind
assert not control.cancelled()
g.during = lambda: s.submit("stop"); o = s.submit("do something"); assert control.cancelled() and o["kind"] == "report"   # stop reaches a running task
g.during = None; s.submit("another"); assert not control.cancelled()                                  # next task starts clean
class Boom(Fake):
    def stream(self, init, config): raise KeyboardInterrupt
s2 = S.Session(graph=Boom([]), approver=None); o = s2.submit("x"); assert o["report"]["status"] == "cancelled" and not o["report"]["needs_user"] and not s2.running
control.reset()
assert s.submit("exit")["kind"] == "exit" and s.submit("   ")["kind"] == "info"
print("OK gateway")
