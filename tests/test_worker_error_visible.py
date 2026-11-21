"""A stopped worker prints its reason and the rule verifier carries it in its reason. Fakes only."""
import io
import os
import sys
from contextlib import redirect_stdout
sys.path.insert(0, ".")
os.environ["NELLY_PERSIST"] = "0"
from verifier import RuleVerifier                                   # noqa: E402

v = RuleVerifier().verify({"flag": "Explorer shows Pictures"}, {"status": "failed", "steps_done": [],
                          "error": "execution blocked: unknown_app: 'Photos' is not a known application"})
assert not v["passed"] and "worker_error=execution blocked: unknown_app" in v["reason"] and "no_steps_done" in v["reason"], v
v = RuleVerifier().verify({"flag": "x y"}, {"status": "completed", "steps_done": [{"target": {"element_id": "e1"}}]})
assert v["passed"] and "worker_error" not in v["reason"], v

import graph.subgraphs.app_subgraph as A                           # noqa: E402
A._run_steps = lambda *a, **k: {"status": "failed", "error": "execution failed: boom", "steps_done": []}
import llm                                                          # noqa: E402
llm.available = lambda: False
buf = io.StringIO()
with redirect_stdout(buf):
    r = A.run_app_subgraph("File Explorer", "n", [], "t")
assert "[worker] File Explorer: stopped with status failed: execution failed: boom" in buf.getvalue(), buf.getvalue()
print("ok")
