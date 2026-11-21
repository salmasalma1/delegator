import os as _o0; _o0.environ.setdefault("NELLY_DRY_RUN", "1")
"""scroll is a decider action (element + direction + amount); elements are ranked by relevance to the goal and the
list size comes from NELLY_TOP_ELEMENTS; Safety knows scroll; the bridge and the interim adapter translate it."""
import os
import sys
sys.path.insert(0, ".")
os.environ["NELLY_PERSIST"] = "0"
os.environ.pop("NELLY_LIVE_INPUT", None)
os.environ.pop("NELLY_TOP_ELEMENTS", None)

from vision import adapter                                          # noqa: E402
from graph import action_decider as D                               # noqa: E402
from graph import safety_port as sp                                 # noqa: E402

# --- list size
assert adapter._top_n() == 60 and adapter.TOP_N == 60
os.environ["NELLY_TOP_ELEMENTS"] = "5";   assert adapter._top_n() == 10
os.environ["NELLY_TOP_ELEMENTS"] = "999"; assert adapter._top_n() == 200
os.environ["NELLY_TOP_ELEMENTS"] = "x";   assert adapter._top_n() == 60
os.environ.pop("NELLY_TOP_ELEMENTS")

# --- ranking by relevance to the goal (not only confidence)
els = [{"id": f"e{i}", "type": "text", "text": t, "confidence": c, "bbox_norm": [0, 0, .1, .1], "clickable": True}
       for i, (t, c) in enumerate([("Home", .99), ("Gallery", .98), ("New folder", .50), ("Address bar", .40),
                                   ("Documents", .97)])]
ctx = {"all_elements": els, "elements": els[:2], "total_elements": 5, "truncated": True, "quality": {}}
r = adapter.rerank(ctx, "File Explorer: create a new folder named reviews", limit=3)
assert r["elements"][0]["id"] == "e2" and len(r["elements"]) == 3 and r["truncated"] is True, r["elements"]
assert ctx["elements"] == els[:2]                                    # the original context is not touched
assert "showing the 3 most relevant of 5" in adapter.to_prompt(r, limit=3)

# --- decider: scroll
ctx2 = {"all_elements": els, "elements": els}
ok = D._from_model({"action": "scroll", "element_id": "e4", "direction": "DOWN", "amount": 99, "why": "list"}, ctx2)
assert ok["status"] == "ok" and ok["params"]["direction"] == "down" and ok["params"]["amount"] == 15 and ok["element"]["id"] == "e4", ok
d = D._from_model({"action": "scroll", "element_id": "e4", "why": "x"}, ctx2)
assert d["params"] == {"bbox_norm": [0, 0, .1, .1], "direction": "down", "amount": 5}, d
assert D._from_model({"action": "scroll", "element_id": "e4", "direction": "sideways"}, ctx2)["status"] == "unresolved"
assert D._from_model({"action": "scroll", "element_id": "nope", "direction": "down"}, ctx2)["status"] == "unresolved"
assert "scroll" in D.SYSTEM and "scroll" in D.SYSTEM_LOOP

# --- safety
assert sp.classify("scroll") == ("low", True)

# --- interim adapter dry run
from execution import desktop_adapter as A                          # noqa: E402
assert "scroll" in A.SUPPORTED

# --- Team 1 bridge translation (needs Team 1's contracts package)
try:
    import contracts                                                # noqa: F401
    from execution import team1_bridge as B
    call, app = B.to_tool_call({"action_id": "a1", "action_type": "scroll", "application": "File Explorer",
                                "target_element_id": "e4", "parameters": {"direction": "up", "amount": 99}})
    assert call.tool == "scroll" and call.args == {"direction": "up", "amount": 15}
    for bad in ({"direction": "x"}, {}):
        try:
            B.to_tool_call({"action_id": "a1", "action_type": "scroll", "target_element_id": "e4", "parameters": bad})
            raise SystemExit("should refuse")
        except ValueError:
            pass
    try:
        B.to_tool_call({"action_id": "a1", "action_type": "scroll", "parameters": {"direction": "up"}})
        raise SystemExit("scroll without an element must be refused")
    except ValueError:
        pass
except ImportError:
    print("(contracts not installed here: bridge part skipped)")
print("ok")
