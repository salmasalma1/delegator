import os as _o0; _o0.environ.setdefault("NELLY_DRY_RUN", "1")
import sys, os
sys.path.insert(0, ".")
sys.path.insert(0, "tools")
from vision import vision_adapter as V
import vision_check as C

raw = {"schema_version": "0.3", "screenshot_id": "s1", "window": {"title": "T", "process": "Notepad"}, "confidence": .9, "warnings": [],
       "perception": {"detector": "yolo:best.pt"},
       "elements": [{"id": "e1", "type": "button", "text": "Save", "bbox_norm": [.1, .1, .2, .2], "confidence": .9, "clickable": True}]}
V.available = lambda: True
V.observe = lambda **k: raw
V.resolve_point = lambda *a: (100, 200)
assert C.main(["--target", "Save", "--countdown", "0"]) == 0
V.resolve_point = lambda *a: (_ for _ in ()).throw(V.TargetRejected("old", code="stale"))
assert C.main(["--target", "Save", "--countdown", "0"]) == 0
assert C.main(["--target", "Nope", "--countdown", "0"]) == 0
V.observe = lambda **k: (_ for _ in ()).throw(RuntimeError("no memory"))
assert C.main(["--target", "Save", "--countdown", "0"]) == 1
print("vision check OK")
