"""langgraph refuses a node whose name is also a state key. The offline tests use a fake graph, so check it here."""
import sys, re
sys.path.insert(0, ".")
from graph.state import AgentState
src = open("graph/builder.py", encoding="utf-8").read()
nodes = set(re.findall(r'add_node\(\s*"([^"]+)"', src))
keys = set(AgentState.__annotations__)
clash = nodes & keys
assert nodes, "no nodes found in builder"
assert not clash, f"node names that are also state keys: {sorted(clash)}"
print("node/state names OK")
