import os as _o0; _o0.environ.setdefault("NELLY_DRY_RUN", "1")  # tests never move the real mouse
"""F6: one list of the environment variables (docs/ENVIRONMENT.md) that names every NELLY_* setting the code
reads; start-up warnings when the real detector is not set or free memory is low (read-only checks); and OCR is
never started when free memory is below the safe level. Fakes only."""
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, ".")
os.environ.pop("NELLY_LIVE_INPUT", None)
from vision import env_check as EC                                   # noqa: E402

# 1) memory: read-only number, warning below the safe level (default 3 GB, NELLY_MIN_FREE_MEM_GB)
EC.free_commit_gb = lambda: 1.4
os.environ.pop("NELLY_MIN_FREE_MEM_GB", None)
w = EC.memory_warning()
assert w and "1.4" in w and "3.0" in w, w
try:
    EC.ensure_memory_for_ocr()
    raise AssertionError("OCR allowed with 1.4 GB free")
except MemoryError as e:
    assert "NELLY_MIN_FREE_MEM_GB" in str(e), e
os.environ["NELLY_MIN_FREE_MEM_GB"] = "1"
assert EC.memory_warning() is None
EC.ensure_memory_for_ocr()                                          # above the (lowered) level: allowed
os.environ.pop("NELLY_MIN_FREE_MEM_GB")
EC.free_commit_gb = lambda: None                                    # unknown (not Windows): never blocks
assert EC.memory_warning() is None
EC.ensure_memory_for_ocr()

# 2) detector: not set / missing file -> warning; an existing file -> no warning
os.environ.pop("NELLY_DETECTOR_WEIGHTS", None)
assert "NELLY_DETECTOR_WEIGHTS" in EC.detector_warning()
os.environ["NELLY_DETECTOR_WEIGHTS"] = os.path.join(tempfile.gettempdir(), "no_such_weights_123.pt")
assert "not found" in EC.detector_warning()
with tempfile.NamedTemporaryFile(suffix=".pt", delete=False) as f:
    path = f.name
os.environ["NELLY_DETECTOR_WEIGHTS"] = path
assert EC.detector_warning() is None
os.remove(path)

# 3) the start-up report prints every warning, and never a secret value
EC.free_commit_gb = lambda: 1.0
os.environ.pop("NELLY_DETECTOR_WEIGHTS", None)
os.environ["NELLY_LLM_API_KEY"] = "sk-test-not-a-real-key-0000"
lines = []
EC.print_startup_warnings(out=lines.append)
assert len(lines) == 2 and all(l.startswith("[startup] WARNING") for l in lines), lines
assert not any("sk-test" in l for l in lines)
os.environ.pop("NELLY_LLM_API_KEY")

# 4) vision refuses to start OCR when memory is low (the perceiver is never called)
from vision import vision_adapter as VA                             # noqa: E402
called = []
class _P:
    def perceive_detailed(self, *a, **k):
        called.append(1)
VA._perceiver[0] = _P()
try:
    VA.observe(screenshot=object())
    raise AssertionError("observe ran with low memory")
except MemoryError:
    pass
assert called == [], called
EC.free_commit_gb = lambda: 16.0

# 5) run.py prints the start-up warnings
src = open("run.py", encoding="utf-8").read()
assert "print_startup_warnings" in src

# 6) docs/ENVIRONMENT.md lists every NELLY_* variable the (non-test) code reads
try:
    files = subprocess.run(["git", "ls-files", "*.py"], capture_output=True, text=True, check=True).stdout.split()
except Exception:                                                    # noqa: BLE001
    files = []
files = [f for f in files if not f.startswith("tests/")]
names = set()
for f in files:
    names |= set(re.findall(r'"(NELLY_[A-Z0-9_]+)"', open(f, encoding="utf-8", errors="replace").read()))
doc = open(os.path.join("docs", "ENVIRONMENT.md"), encoding="utf-8").read()
missing = sorted(n for n in names if n not in doc)
assert names and not missing, f"not documented in docs/ENVIRONMENT.md: {missing}"

print("test_env_check OK")
