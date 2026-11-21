import os as _o0; _o0.environ.setdefault("NELLY_DRY_RUN", "1")  # tests never move the real mouse
"""F2: grounding searches the FULL element list (not the top 30); the 30 shown to the model always include the
elements that match the target; a `text` element with clickable=None is usable when its text matches the target;
and when the target is not found on a truncated list the reason says so. Fakes only."""
import os
import sys

sys.path.insert(0, ".")
os.environ["NELLY_PERSIST"] = "0"
os.environ.pop("NELLY_LIVE_INPUT", None)
os.environ["NELLY_TOP_ELEMENTS"] = "30"                    # these cases are written for a list of 30
from vision.adapter import normalize, to_prompt, usable_for          # noqa: E402
from vision.ground import pick                                        # noqa: E402
from graph.action_decider import _from_model, _legacy                # noqa: E402

def el(i, typ="button", text="", conf=.95, clickable=True, y=0.0):
    return {"id": f"e{i}", "type": typ, "text": text, "bbox_norm": [0.1, 0.01 + y, 0.2, 0.02 + y],
            "confidence": conf, "clickable": clickable, "source": "fast"}

ELS = [el(i, text=f"Button {i}", y=i * 0.02) for i in range(1, 36)]              # 35 confident buttons
TARGET = el(36, typ="text", text="File Edit Format View Help", conf=.98, clickable=None, y=0.75)
ELS += [TARGET] + [el(i, typ="icon", y=0.8) for i in range(37, 41)]
OBS = {"schema_version": "0.3", "screenshot_id": "s1", "elements": ELS, "perception": {"detector": "yolo:x"},
       "window": {"process": "notepad.exe", "bounds": [0, 0, 1000, 1000]},
       "screen": {"w": 1000, "h": 1000, "left": 0, "top": 0}}

# 1) the old cut: without a target the text element is not in the 30 sent to the model
plain = normalize(OBS)
assert len(plain["elements"]) == 30 and "e36" not in [e["id"] for e in plain["elements"]]
assert plain["truncated"] is True and len(plain["all_elements"]) == 40 and plain["total_elements"] == 40

# 2) with the target, the matching element is promoted into the 30 (and into the model's prompt)
ctx = normalize(OBS, target="click File")
ids = [e["id"] for e in ctx["elements"]]
assert len(ids) == 30 and ids[0] == "e36", ids
assert "e36 text 'File Edit Format View Help'" in to_prompt(ctx)

# 3) a text element with clickable=None is usable only when its text matches the target (not by the verb alone)
assert usable_for(TARGET, "click File") and not usable_for(TARGET, "click Save")
assert not usable_for(el(99, typ="text", text="click here", clickable=None), "click Save")
assert not usable_for({**TARGET, "clickable": False}, "click File")          # clickable=False is never usable

# 4) grounding finds it on the FULL list
g = pick("click File", ctx["all_elements"])
assert g["status"] == "grounded" and g["element"]["id"] == "e36", g
d = _legacy("click File", ctx)
assert d["status"] == "ok" and d["element"]["id"] == "e36", d

# 5) the LLM path accepts the matching text element, and looks ids up in the full list
d = _from_model({"action": "click", "element_id": "e36", "why": "menu"}, ctx, target="click File")
assert d["status"] == "ok" and d["element"]["id"] == "e36", d
d = _from_model({"action": "click", "element_id": "e36", "why": "x"}, ctx, target="click Save")
assert d["status"] == "unresolved" and "not usable" in d["why"], d
d = _from_model({"action": "click", "element_id": "e40", "why": "icon"}, ctx, target="click icon")
assert d["status"] == "ok" and d["element"]["id"] == "e40", d                   # outside the 30, still found

# 6) not found on a truncated list -> the reason says so
d = _legacy("click Zorblax", ctx)
assert d["status"] == "unresolved" and "truncated" in d["why"] and "40" in d["why"], d
d = _from_model({"action": "click", "element_id": "e99", "why": "?"}, ctx, target="click Zorblax")
assert d["status"] == "unresolved" and "truncated" in d["why"], d

# 7) the worker passes the target into normalize
import graph.subgraphs.app_subgraph as A                             # noqa: E402
A.vision_adapter.available = lambda: True
A.vision_adapter.observe = lambda screenshot=None, target=None, allow_vlm=False: OBS
c = A.perceive_screen("Notepad", "click File")
assert c["elements"][0]["id"] == "e36" and len(c["all_elements"]) == 40, [e["id"] for e in c["elements"]][:3]

print("test_grounding_full_list OK")
