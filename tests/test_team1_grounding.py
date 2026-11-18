import os as _o0; _o0.environ.setdefault("NELLY_DRY_RUN", "1")  # tests never move the real mouse
"""F3: when Team 1's vision returns a GroundingResult for the target, the worker uses it instead of our own word
matching (and shows it to the model). Fakes only."""
import importlib.util
import os
import sys
import types

sys.path.insert(0, ".")
os.environ["NELLY_PERSIST"] = "0"
os.environ.pop("NELLY_LIVE_INPUT", None)
from vision import vision_adapter as VA                              # noqa: E402
from vision.adapter import to_prompt                                 # noqa: E402
from graph.action_decider import _legacy                             # noqa: E402

E1 = {"id": "e1", "type": "button", "text": "Save", "bbox_norm": [.5, .5, .6, .6], "confidence": .9,
      "clickable": True, "source": "fast"}
E2 = {"id": "e2", "type": "menu_item", "text": "", "bbox_norm": [.1, .1, .15, .13], "confidence": .8,
      "clickable": True, "source": "fast"}                           # File box with no text (as Team 1 returns it)
CTX = {"elements": [E1, E2], "all_elements": [E1, E2], "truncated": False, "app": "notepad.exe"}
G = {"target": "click File", "status": "grounded", "element_id": "e2", "confidence": 0.82, "method": "fuzzy"}

# 1) our own matching cannot find File (the box has no text) ...
assert _legacy("click File", CTX)["status"] == "unresolved"
# ... Team 1's grounding can: use it
d = _legacy("click File", {**CTX, "grounding": G})
assert d["status"] == "ok" and d["element"]["id"] == "e2" and "team1_grounding" in d["why"], d
# 2) only a confident answer is used: ambiguous / not_found / unknown id fall back to our matching
for g in ({**G, "status": "ambiguous"}, {**G, "status": "not_found", "element_id": None}, {**G, "element_id": "e9"}):
    assert _legacy("click Save", {**CTX, "grounding": g})["element"]["id"] == "e1", g
# 3) grounding for a DIFFERENT target is ignored
assert _legacy("click Save", {**CTX, "grounding": {**G, "target": "click File"}})["element"]["id"] == "e1"
# 4) the model sees it too
assert "vision grounding for 'click File': e2 (grounded" in to_prompt({**CTX, "grounding": G})

# 5) the worker puts the vision package's grounding into the context
import graph.subgraphs.app_subgraph as A                             # noqa: E402
OBS = {"schema_version": "0.3", "screenshot_id": "s1", "elements": [E1, E2], "perception": {"detector": "yolo:x"}}
A.vision_adapter.available = lambda: True
A.vision_adapter.observe = lambda screenshot=None, target=None, allow_vlm=False: OBS
A.vision_adapter.last_grounding = lambda: G
assert A.perceive_screen("Notepad", "click File")["grounding"] == G

# 6) vision_adapter.observe keeps the GroundingResult that perceive_detailed returned (needs Team 1's package)
if importlib.util.find_spec("nelly_vision") and importlib.util.find_spec("contracts"):
    import importlib
    VA2 = importlib.reload(VA)
    class _Obs:
        def model_dump(self, mode=None):
            return dict(OBS)
    class _G:
        def model_dump(self, mode=None):
            return dict(G)
    class _Perceiver:
        def perceive_detailed(self, image, **kw):
            assert kw.get("target") == "click File"
            return types.SimpleNamespace(observation=_Obs(), grounding=_G())
    VA2._perceiver[0] = _Perceiver()
    VA2.observe(screenshot=object(), target="click File")
    assert VA2.last_grounding() == G, VA2.last_grounding()

print("test_team1_grounding OK")
