import os as _o0; _o0.environ.setdefault("NELLY_DRY_RUN", "1")
"""allow: / --allow-task: medium-risk actions are not asked one by one for that task; always-ask actions still are;
the permission ends with the task. Fakes only."""
import os
import sys
sys.path.insert(0, ".")
os.environ["NELLY_PERSIST"] = "0"
os.environ["NELLY_POLICY_MODE"] = "strict"
from graph import safety_port as sp                                 # noqa: E402

sp.reset()
asked = []
g = sp.get_safety()
cm = sp.bind_approver(lambda p: asked.append(p["request"]["action_type"]) or {"granted": False})
cm.__enter__()
req = lambda a: {"action_id": "1", "task_id": "t", "action_type": a, "application": "Notepad",
                 "parameters": {}, "risk_level": "medium"}

assert g.check(req("type"))["decision"] == "rejected" and asked == ["type"]      # normal: asked (and refused here)
sp.grant_task(True)
d = g.check(req("type"))
assert d["decision"] == "approved" and d["approval_scope"] == "task" and asked == ["type"], (d, asked)
d = g.check(req("save_file"))
assert d["decision"] == "approved"
d = g.check(req("delete"))                                                         # always-ask is never covered
assert d["decision"] == "rejected" and asked[-1] == "delete", (d, asked)
d = g.check({**req("press"), "parameters": {"keys": ["delete"]}, "destructive": "press Delete"})
assert d["decision"] == "rejected", d
sp.grant_task(False)
assert g.check(req("type"))["decision"] == "rejected"

cm.__exit__(None, None, None)
print("ok")
