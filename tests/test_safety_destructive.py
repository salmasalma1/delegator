"""A press on Delete or a click on a 'Delete' control always asks, in every mode, even though press/click are low risk."""
import os
import sys
sys.path.insert(0, ".")
from graph import safety_port as sp

# the detector
assert sp.destructive_reason("press", {"keys": ["Delete"]})
assert sp.destructive_reason("press", {"keys": ["shift", "delete"]})
assert sp.destructive_reason("press", {"keys": ["ctrl", "s"]}) == ""
assert sp.destructive_reason("press", {"keys": ["enter"]}) == ""
assert sp.destructive_reason("click", {}, "Delete") and sp.destructive_reason("click", {}, "Move to Recycle Bin")
assert sp.destructive_reason("click", {}, "Save") == ""
assert sp.destructive_reason("type", {"text": "delete me"}, "") == ""      # typing the word is not deleting

# the mock backend: standard mode, low-risk press, but flagged -> asks, and never offers a session scope
os.environ["NELLY_POLICY_MODE"] = "standard"; sp.reset()
safe = {"action_id": "a1", "task_id": "t", "action_type": "press", "application": "File Explorer",
        "parameters": {"keys": ["ctrl", "s"]}}
assert sp.MockSafety().check(safe)["decision"] == "approved"
flagged = {**safe, "parameters": {"keys": ["delete"]}, "destructive": "presses the Delete key"}
d = sp.MockSafety().check(flagged)
assert d["decision"] == "needs_user_approval" and d["always_ask"] is True and "Delete" in d["reason"]

# a request without the flag behaves exactly as before
assert sp.MockSafety().check({**safe, "parameters": {"keys": ["delete"]}})["decision"] == "approved"

# the request builder sets the flag (only when the app subgraph can be imported here)
try:
    from graph.subgraphs.app_subgraph import _build_request
except Exception as e:                                                     # noqa: BLE001
    print("skipped _build_request check:", type(e).__name__)
else:
    r = _build_request({"action": "press", "params": {"keys": ["delete"]}, "element": {}}, "File Explorer", "t")
    assert r["destructive"] == "presses the Delete key"
    r2 = _build_request({"action": "click", "params": {}, "element": {"id": "e1", "text": "Delete"}}, "File Explorer", "t")
    assert "delete" in r2["destructive"]
    r3 = _build_request({"action": "press", "params": {"keys": ["enter"]}, "element": {}}, "File Explorer", "t")
    assert "destructive" not in r3
print("OK safety destructive")
