"""Planner split rule is in the prompt; NELLY_PLAN_MODEL is passed on (and forced) only when set;
plan_check says loudly when it was skipped. Fakes only."""
import os
import sys
sys.path.insert(0, ".")
os.environ["NELLY_LLM_API_KEY"] = "test-not-a-real-key"
import llm                                                          # noqa: E402
import reasoning                                                    # noqa: E402
from graph.nodes import plan_check                                  # noqa: E402

assert "getting to the right place" in reasoning.SYSTEM
assert "EXACTLY as written" in reasoning.SYSTEM

seen = []
def fake(system, user, model=None, temperature=0.0, **kw):
    seen.append((model, kw))
    return [{"node": "Notepad: open it", "app": "Notepad", "worker": "native",
             "flag": "an empty Notepad window is in front", "steps": ["open Notepad"]}]
llm.chat_json = fake
os.environ.pop("NELLY_PLAN_MODEL", None)
prov = reasoning.QwenProvider()
prov.plan("open notepad")
assert seen[-1][1] == {}, seen                                       # nothing forced by default
os.environ["NELLY_PLAN_MODEL"] = "big-model"
prov.plan("open notepad")
assert seen[-1] == ("big-model", {"force_model": True}), seen

def boom(*a, **k):
    raise ValueError("unparseable model answer (after one re-ask): {cut")
llm.chat_json = boom
v = plan_check.check_plan("x", [])
assert v["method"] == "skipped" and "ValueError" in v["reason"] and "cut" in v["reason"], v
print("ok")

os.environ["NELLY_PLAN_CHECK"] = "off"
llm.chat_json = lambda *a, **k: (_ for _ in ()).throw(AssertionError("the model must not be called"))
v = plan_check.check_plan("x", [])
assert v["ok"] and v["method"] == "skipped" and v["reason"] == "disabled_by_NELLY_PLAN_CHECK", v
os.environ.pop("NELLY_PLAN_CHECK")
print("ok off")
