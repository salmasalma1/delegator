"""A model answer with a Windows path written with single backslashes must still parse (it stopped a live run)."""
import sys
sys.path.insert(0, ".")
import importlib
import types

# llm.py imports nothing heavy at module level; no key or network is touched here.
import llm

# 1) the exact answer that stopped the live run
raw = ('{"action": "press", "element_id": null, "text": null, "keys": ["alt", "d"], "path": null, "app": null, '
       '"why": "Focus File Explorer\'s address bar so I can navigate to D:\\11.22.63"}')
out = llm.loads_lenient(raw)
assert out["action"] == "press" and out["keys"] == ["alt", "d"] and out["why"].endswith("D:\\11.22.63")

# 2) a clean answer is untouched, including real escapes
clean = '{"a": "line1\\nline2", "p": "D:\\\\x\\\\y", "u": "\\u0627", "q": "say \\"hi\\""}'
c = llm.loads_lenient(clean)
assert c["a"] == "line1\nline2" and c["p"] == "D:\\x\\y" and c["u"] == "\u0627" and c["q"] == 'say "hi"'

# 3) repair keeps valid pairs and unicode escapes next to a bad backslash
mixed = '{"p": "D:\\11\\\\22", "u": "\\u0627"}'
m = llm.loads_lenient(mixed)
assert m["p"] == "D:\\11\\22" and m["u"] == "\u0627"

# 4) still an error for text that is not JSON at all
try:
    llm.loads_lenient("not json \\1")
    assert 0
except ValueError:
    pass
print("OK json backslash")
