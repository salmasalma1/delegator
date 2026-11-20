"""NELLY_LLM_RETRIES is read safely; an unclear approval answer is never a yes."""
import builtins
import os
import sys

sys.path.insert(0, ".")
import llm
from graph import safety_port as sp

for raw, want in (("5", 5), ("0", 0), ("99", 8), ("-3", 0), ("abc", 2)):
    os.environ["NELLY_LLM_RETRIES"] = raw
    assert llm.llm_retries() == want, (raw, llm.llm_retries())
del os.environ["NELLY_LLM_RETRIES"]
assert llm.llm_retries() == 2

PROPOSAL = {"request": {"action_type": "type", "application": "Notepad", "target_element_id": "e1", "parameters": {}},
            "reason": "r", "risk_level": "medium", "hash": "0" * 12, "scopes": ["once", "session"]}


def answers(*a):
    it = iter(a)
    builtins.input = lambda prompt="": next(it)


real_input = builtins.input
try:
    answers("\u063a", "y")                   # the Arabic layout letter first, then a real y
    assert sp.console_approver(PROPOSAL)["granted"] is True
    answers("\u063a", "\u063a", "\u063a")      # three unclear answers: no
    assert sp.console_approver(PROPOSAL)["granted"] is False
    answers("n")
    assert sp.console_approver(PROPOSAL)["granted"] is False
    answers("s")
    assert sp.console_approver(PROPOSAL) == {"granted": True, "scope": "session"}
finally:
    builtins.input = real_input
print("OK llm retries and approval answers")
