import os as _o0; _o0.environ.setdefault("NELLY_DRY_RUN", "1")  # tests never move the real mouse
import sys, types, os
sys.path.insert(0, ".")
os.environ["NELLY_PERSIST"] = "0"
import llm
import graph.subgraphs.app_subgraph as A
ELS = [{"id": "e_edit", "type": "input", "text": "", "bbox_norm": [0.1,0.2,0.5,0.5], "confidence": .9,
        "clickable": True, "source": "fast"},
       {"id": "e_menu", "type": "menu_item", "text": "File", "bbox_norm": [0,0,.1,.05], "confidence": .9,
        "clickable": True, "source": "fast"}]
CTX = {"app": "X", "elements": ELS, "needs_review": False, "vision_source": "t", "warnings": [],
       "quality": {"score": .9, "reasons": []}, "status": "ok", "window_title": "w"}
shots = []
def perceive(app, target, screenshot=None, scenario=None):
    shots.append(screenshot); return CTX
A.perceive_screen = perceive
llm.available = lambda: True
def script(*outs):
    it = iter(outs)
    def f(system, user, **k): return next(it)
    return f
run = lambda **k: A.run_app_subgraph("Notepad", "write a note", ["open File menu", "type the note"], "t", flag="note visible", **k)

# 1) two DIFFERENT actions then finish -> completed, 2 steps, loop mode, history reaches the model
seen = []
outs = iter([{"action": "click", "element_id": "e_menu", "why": "open menu"},
             {"action": "type", "element_id": "e_edit", "text": "hello", "why": "write"},
             {"action": "finish", "why": "note is visible"}])
def f(system, user, **k): seen.append(user); return next(outs)
llm.chat_json = f
r = run()
assert r["status"] == "completed" and r["mode"] == "loop" and len(r["steps_done"]) == 2 and r["finish_reason"] == "note is visible"
assert "1. click e_menu open menu" in seen[2] and "Hints: ['open File menu', 'type the note']" in seen[0]
assert r["steps_done"][1]["step"].startswith("type:")                 # redaction masks type steps by this
# 2) finish with nothing done is allowed but visible (no steps)
llm.chat_json = script({"action": "finish", "why": "already true"}); r = run()
assert r["status"] == "completed" and r["steps_done"] == []
# 3) hallucinated id / none -> needs_regrounding
llm.chat_json = script({"action": "click", "element_id": "nope", "why": "x"}); assert run()["status"] == "needs_regrounding"
llm.chat_json = script({"action": "none", "why": "cannot"}); assert run()["status"] == "needs_regrounding"
# 4) stuck: same action 3x -> failed, not an endless loop
llm.chat_json = lambda *a, **k: {"action": "click", "element_id": "e_menu", "why": "again"}
r = run(); assert r["status"] == "failed" and r["error"].startswith("stuck") and len(r["steps_done"]) == 2
# 5) leash: always different actions never finishing -> max_actions_exhausted
n = [0]
def endless(*a, **k):
    n[0] += 1; return {"action": "type", "element_id": "e_edit", "text": str(n[0]), "why": "w"}
llm.chat_json = endless
r = run(max_actions=4); assert r["status"] == "failed" and r["error"].startswith("max_actions_exhausted") and len(r["steps_done"]) == 4
# 6) approval needed mid-loop stops with the frozen request, earlier steps kept
class Ask:
    c = 0
    def check(self, req):
        Ask.c += 1
        return {"decision": "approved" if Ask.c == 1 else "needs_approval", "action_id": req["action_id"], "reason": "r"}
A.get_safety = lambda: Ask()
llm.chat_json = script({"action": "click", "element_id": "e_menu", "why": "a"}, {"action": "type", "element_id": "e_edit", "text": "t", "why": "b"})
r = run(); assert r["status"] == "needs_approval" and len(r["steps_done"]) == 1 and r["proposed_action"]["action_type"] == "type"
import graph.safety_port as sp; A.get_safety = sp.get_safety
# 7) next observation uses the screenshot the executor left
A.desktop_adapter = types.SimpleNamespace(execute=lambda req: {"status": "success", "output": {}, "screenshot_after_ref": "/tmp/after.png", "action_id": req["action_id"], "duration_ms": 1})
A.HAS_ADAPTER = True; shots.clear()
llm.chat_json = script({"action": "click", "element_id": "e_menu", "why": "a"}, {"action": "finish", "why": "ok"})
r = run(screenshot="/tmp/before.png"); assert shots == ["/tmp/before.png", "/tmp/after.png"], shots
A.HAS_ADAPTER = False
# 8) no model -> old one-action-per-step path, labelled
llm.available = lambda: False
r = A.run_app_subgraph("Notepad", "n", ["click File"], "t"); assert r["mode"] == "steps" and r["status"] == "completed"
print("OK loop")
