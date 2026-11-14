import sys, os
sys.path.insert(0, ".")
from vision.adapter import normalize, is_usable, fake_observation, failed_context, to_prompt
from vision.validate import validate_observation
from vision import vision_adapter
import graph.subgraphs.app_subgraph as A

def el(i, t="button", c=True, conf=.9, box=(.1,.1,.2,.2), text="x"):
    return {"id": i, "type": t, "text": text, "bbox_norm": list(box), "confidence": conf, "clickable": c, "source": "fast"}
def obs(els, det="yolo", win=True, **k):
    return {"schema_version": "0.3", "screenshot_id": "s1", "window": {"title": "T", "process": "Notepad"} if win else None,
            "elements": els, "confidence": .8, "warnings": [], "perception": {"detector": det}, **k}

# usable rule
assert is_usable(el("a", c=True)) and not is_usable(el("a", c=False))
assert is_usable(el("a", "button", "unknown")) and not is_usable(el("a", "text", "unknown"))
assert is_usable(el("a", "button", None)) and not is_usable(el("a", "text", None))      # Team 1 sends null
assert validate_observation(obs([el("e1", c=None)]))[0] and validate_observation(obs([el("e1", c="unknown")]))[0]
assert not validate_observation(obs([el("e1", c="maybe")]))[0]

# good screen: kept as Team 1 names it, ordered usable first
ctx = normalize(obs([el("e1", "text", False), el("e2")]))
assert ctx["elements"][0]["id"] == "e2" and ctx["app"] == "Notepad" and not ctx["needs_review"]
assert ctx["elements"][0]["bbox_norm"] == [.1,.1,.2,.2]            # untouched

# quality gate
assert normalize(obs([]))["needs_review"]
assert normalize(obs([el("e1")], det="edge-proposals"))["needs_review"]       # weak detector = model did not run
assert any("no_active_window" in r for r in normalize(obs([el("e1")], win=False))["quality"]["reasons"])
assert normalize(obs([el("e1", conf=.2), el("e2", conf=.2)]))["needs_review"]
assert normalize(None)["needs_review"] and normalize("x")["error"]

# fake is labelled everywhere and never "clear" enough to be mistaken for real
f = normalize(fake_observation("Notepad", "Save"), source="fake")
assert f["detector"] == "fake" and "FAKE" in f["warnings"][0]

# validator
assert validate_observation(obs([el("e1")]))[0]
assert not validate_observation(obs([el("e1", box=(.5,.5,.2,.2))]))[0]          # [x,y,w,h]-style box rejected
assert not validate_observation(obs([el("e1"), el("e1")]))[0]
assert not validate_observation({**obs([el("e1")]), "schema_version": "0.1"})[0]
assert not validate_observation([])[0]

# perceive_screen: not installed -> FAKE ; installed but crashes -> needs_review, NOT fake
vision_adapter.available = lambda: False
A.HAS_ADAPTER = False
c = A.perceive_screen("Notepad", "Save"); assert c["vision_source"] == "fake" and c["detector"] == "fake"
A.HAS_ADAPTER = True; os.environ.pop("NELLY_DRY_RUN", None)
c = A.perceive_screen("Notepad", "Save"); assert c["needs_review"]      # live executor + fake screen = stop
vision_adapter.available = lambda: True
def boom(**k): raise RuntimeError("no gpu")
vision_adapter.observe = boom
c = A.perceive_screen("Notepad", "Save"); assert c["needs_review"] and c["error"] and c["vision_source"] != "fake" and not c["elements"]
vision_adapter.observe = lambda **k: obs([el("e1")])
c = A.perceive_screen("Notepad", "Save"); assert c["vision_source"] == "nelly_vision" and not c["needs_review"]
vision_adapter.observe = lambda **k: obs([el("e1", box=(.9,.9,.1,.1))])
c = A.perceive_screen("Notepad", "Save"); assert c["needs_review"] and any("contract_violation" in w for w in c["warnings"])

assert "e1 button" in to_prompt(normalize(obs([el("e1")])))
print("vision contract OK")
