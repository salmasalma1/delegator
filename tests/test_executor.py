import sys, os, types
sys.path.insert(0, ".")
os.environ["NELLY_PERSIST"] = "0"
from graph import control
from execution import desktop_adapter as X
from vision import vision_adapter as V

def req(a="click", **p):
    return {"action_id": "a1", "task_id": "t1", "action_type": a, "target_element_id": "e1", "application": "Notepad",
            "parameters": {"bbox_norm": [.1, .1, .2, .2], **p}, "observation_id": "s1"}

class PG:                                            # fake pyautogui: records, never touches the machine
    calls = []
    class FailSafeException(Exception): pass
    FAILSAFE = True; PAUSE = 0
    def click(self, x, y): self.calls.append(("click", x, y))
    def write(self, t, interval=0): self.calls.append(("write", t))
    def hotkey(self, *k): self.calls.append(("hotkey", k))
    def press(self, k): self.calls.append(("press", k))
    def screenshot(self, path): self.calls.append(("shot", path))
pg = PG(); X._load_pyautogui = lambda: pg; X.SETTLE_S = 0
os.environ["NELLY_SHOTS_DIR"] = "/tmp"

# honesty: labelled interim, never claims verified
r = X.execute(req("save_file")); assert r["status"] == "failed" and r["output"]["reject_code"] == "unsupported_action"
assert r["strategy_used"] == "interim_pyautogui" and r["verification_status"] == "not_verified"

# no observation yet -> resolver refuses (no_observation), nothing is clicked
os.environ["NELLY_LIVE_INPUT"] = "1"; os.environ.pop("NELLY_DRY_RUN", None); pg.calls.clear()
r = X.execute(req()); assert r["status"] == "failed" and r["output"]["reject_code"] == "no_observation" and not pg.calls

# dry run is the DEFAULT: nothing moves unless live input is asked for, shows the point it WOULD click
os.environ.pop("NELLY_LIVE_INPUT"); V.resolve_point = lambda *a: (640, 360)
r = X.execute(req()); assert r["output"]["dry_run"] and r["output"]["screen_point"] == [640, 360] and not pg.calls
os.environ["NELLY_LIVE_INPUT"] = "1"; os.environ["NELLY_DRY_RUN"] = "1"
r = X.execute(req()); assert r["output"]["dry_run"] and not pg.calls        # DRY_RUN beats LIVE_INPUT
os.environ.pop("NELLY_DRY_RUN")

# real path (fake pyautogui): click, type (text never in result), press
r = X.execute(req()); assert r["status"] == "success" and ("click", 640, 360) in pg.calls and r["screenshot_after_ref"]
pg.calls.clear(); r = X.execute(req("type", text="secret hello")); assert ("write", "secret hello") in pg.calls
assert "secret" not in str(r)
pg.calls.clear(); X.execute(req("press", keys=["ctrl", "s"])); assert ("hotkey", ("ctrl", "s")) in pg.calls
assert X.execute(req("type"))["output"]["reject_code"] == "bad_request"

# Team 1 refuses the point -> nothing clicked, code kept
def refuse(*a): raise V.TargetRejected("old picture", code="stale")
V.resolve_point = refuse; pg.calls.clear()
r = X.execute(req()); assert r["status"] == "failed" and r["output"]["reject_code"] == "stale" and not pg.calls

# stop switch and corner failsafe
V.resolve_point = lambda *a: (1, 1)
control.cancel(); assert X.execute(req())["status"] == "cancelled"; control.reset()
def boom(x, y): raise PG.FailSafeException()
pg.click = boom; r = X.execute(req()); assert r["status"] == "cancelled" and control.cancelled(); control.reset()

# worker: a stale refusal becomes needs_regrounding (look again), not a failure
import graph.subgraphs.app_subgraph as A
from graph.subgraphs.app_subgraph import _perform
from graph.safety_port import get_safety, reset; reset()
A.desktop_adapter = types.SimpleNamespace(execute=lambda rq: {"action_id": rq["action_id"], "task_id": rq["task_id"], "status": "failed",
    "output": {"reject_code": "stale"}, "error": "old", "duration_ms": 1})
A.HAS_ADAPTER = True
sub = {"steps_done": [], "status": "running"}
ctx = {"quality": {"score": .9}}
dec = {"action": "click", "params": {"bbox_norm": [.1, .1, .2, .2]}, "element": {"id": "e1"}, "decider": "llm", "why": "w", "observation_id": "s1"}
ok, _ = _perform(dec, "Notepad", "t1", get_safety(), sub, ctx, "step")
assert not ok and sub["status"] == "needs_regrounding" and sub["actions"][0]["reject_code"] == "stale"
print("executor OK")

# ---- open_app: only a fixed list, by NAME; the model never supplies a command ----
import subprocess
launched = []
subprocess.Popen = lambda cmd, *a, **k: launched.append(cmd)
X.OPEN_WAIT_S = 0
os.environ["NELLY_LIVE_INPUT"] = "1"; os.environ.pop("NELLY_DRY_RUN", None)
r = X.execute({**req("open_app"), "parameters": {"app": "Notepad"}}); assert r["status"] == "success" and launched == [["notepad.exe"]], launched
launched.clear()
for bad in ("cmd.exe", "notepad; calc", "powershell", "", "C:\\x.exe"):
    r = X.execute({**req("open_app"), "parameters": {"app": bad}}); assert r["status"] == "failed" and r["output"]["reject_code"] == "app_not_allowed", bad
assert not launched
os.environ.pop("NELLY_LIVE_INPUT"); r = X.execute({**req("open_app"), "parameters": {"app": "Notepad"}})
assert r["output"]["dry_run"] and not launched
from graph.safety_port import classify
assert classify("open_app") == ("medium", True)
from graph.action_decider import _from_model
assert _from_model({"action": "open_app", "app": "Notepad", "why": "w"}, {"elements": []})["params"] == {"app": "Notepad"}
assert _from_model({"action": "open_app"}, {"elements": []})["status"] == "unresolved"
print("open_app OK")
