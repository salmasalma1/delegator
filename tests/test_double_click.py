import os as _o0; _o0.environ.setdefault("NELLY_DRY_RUN", "1")
"""double_click: a decider action that needs an element and may pick a plain-text file row; Safety rates it low
(and a 'Delete' label still always asks); the Team 1 bridge and the interim adapter know it. Fakes only."""
import os
import sys
sys.path.insert(0, ".")
os.environ["NELLY_PERSIST"] = "0"
os.environ.pop("NELLY_LIVE_INPUT", None)
from graph import action_decider as D                               # noqa: E402
from graph import safety_port as sp                                 # noqa: E402
from vision.adapter import usable_for                               # noqa: E402

row = {"id": "e7", "type": "text", "text": "Ai_Couple_1", "bbox_norm": [.3, .4, .4, .42], "confidence": .9, "clickable": None}
btn = {"id": "e8", "type": "text", "text": "Delete", "bbox_norm": [.1, .1, .2, .12], "confidence": .9, "clickable": False}
ctx = {"all_elements": [row, btn], "elements": [row, btn]}

assert "double_click" in D.ALLOWED and "double_click" in D.NEEDS_ELEMENT
assert "double_click" in D.SYSTEM and "double_click" in D.SYSTEM_LOOP

# a file row is plain text with clickable=None: a single click is refused (the word is not in the target), a double click accepted
assert not usable_for(row, "open a picture") and usable_for(row, "open a picture", any_text=True)
assert not usable_for(btn, "x", any_text=True)                       # clickable=False is never usable

d = D._from_model({"action": "double_click", "element_id": "e7", "why": "open it"}, ctx, target="open a random picture")
assert d["status"] == "ok" and d["action"] == "double_click" and d["element"]["id"] == "e7", d
d = D._from_model({"action": "click", "element_id": "e7", "why": "x"}, ctx, target="open a random picture")
assert d["status"] == "unresolved", d                                # a plain click on that row stays refused
d = D._from_model({"action": "double_click", "why": "x"}, ctx, target="t")
assert d["status"] == "unresolved", d                                # no element

assert sp.classify("double_click") == ("low", True)
assert sp.destructive_reason("double_click", {}, "Delete")           # a Delete label still always asks
assert sp.destructive_reason("double_click", {}, "Ai_Couple_1") == ""

from execution import desktop_adapter as A                          # noqa: E402
assert "double_click" in A.SUPPORTED

try:
    import contracts                                                # noqa: F401
    from execution import team1_bridge as B
    call, _ = B.to_tool_call({"action_id": "a1", "action_type": "double_click", "application": "File Explorer",
                              "target_element_id": "e7", "parameters": {}})
    assert call.tool == "double_click_element" and call.target_element_id == "e7"
except ImportError:
    print("(contracts not installed here: bridge part skipped)")
print("ok")
