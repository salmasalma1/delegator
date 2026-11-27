import os as _o0; _o0.environ.setdefault("NELLY_DRY_RUN", "1")  # tests never move the real mouse
"""Warm-up: Team 1's models are loaded once, in the background, from a blank picture. It never looks at the screen,
never stores an observation (so no click point can come from it), never breaks a task, and can be switched off.
Fakes only: no capture, no OCR, no input."""
import os
import sys
import threading
import time
import types

sys.path.insert(0, ".")
os.environ["NELLY_PERSIST"] = "0"
os.environ.pop("NELLY_VISION", None)
os.environ.pop("NELLY_WARMUP", None)

calls = []


class FakePerceiver:
    def perceive_detailed(self, image, **kw):
        calls.append((image, kw))
        time.sleep(0.2)                                     # "loading models"
        return types.SimpleNamespace(observation=None, grounding=None)


fake = types.ModuleType("nelly_vision")
fake.Perceiver = FakePerceiver
fake.capture = types.SimpleNamespace(new_screenshot_id=lambda: "warm-1",
                                     capture_screen=lambda: (_ for _ in ()).throw(AssertionError("screen read")),
                                     capture_window=lambda: (_ for _ in ()).throw(AssertionError("screen read")))
sys.modules["nelly_vision"] = fake
if "PIL" not in sys.modules:
    try:
        import PIL.Image                                    # noqa: F401
    except Exception:                                        # noqa: BLE001  (no Pillow here: a stand-in picture)
        pil = types.ModuleType("PIL")
        pil.Image = types.SimpleNamespace(new=lambda mode, size, color=None: ("blank", mode, size))
        sys.modules["PIL"] = pil
        sys.modules["PIL.Image"] = pil.Image

from vision import vision_adapter as VA                       # noqa: E402
import vision.env_check as E                                   # noqa: E402

E.ensure_memory_for_ocr = lambda: None                         # the memory gate is tested elsewhere


def fresh():
    VA._perceiver[0] = None
    VA._last[0] = None
    VA._warm.update(started=False, done=False)
    calls.clear()


# 1) warmup() uses a blank picture, no target, no screen / window, and stores no observation
fresh()
assert VA.warmup() is True
assert len(calls) == 1 and calls[0][1]["target"] is None and calls[0][1]["screen"] is None \
    and calls[0][1]["window"] is None and calls[0][1]["allow_vlm"] is False, calls
assert VA._last[0] is None, "a warm-up must never leave an observation behind"
assert VA._warm["done"] is True

# 2) async: starts one thread, once per process, and a real look waits for it instead of loading twice
fresh()
assert VA.warmup_async() is True
assert VA.warmup_async() is False                              # second call: already started
t0 = time.time()
while not VA._warm["done"] and time.time() - t0 < 3:
    time.sleep(0.02)
assert VA._warm["done"] and len(calls) == 1, calls

# 3) off switch
fresh()
os.environ["NELLY_WARMUP"] = "0"
assert VA.warmup_async() is False and not calls and VA._warm["started"] is False
os.environ.pop("NELLY_WARMUP")

# 4) vision not available (or switched off): nothing starts
fresh()
os.environ["NELLY_VISION"] = "off"
assert VA.warmup_async() is False and not calls
os.environ.pop("NELLY_VISION")

# 5) a failing warm-up is silent and returns False (the first real look reports its own error)
fresh()
FakePerceiver.perceive_detailed = lambda self, image, **kw: (_ for _ in ()).throw(RuntimeError("boom"))
assert VA.warmup() is False and VA._warm["done"] is False
assert VA._busy.acquire(blocking=False), "the vision lock must be released after a failure"
VA._busy.release()

# 6) if a real look holds the lock, warm-up steps aside instead of waiting
fresh()
VA._busy.acquire()
try:
    assert VA.warmup() is False
finally:
    VA._busy.release()

print("test_vision_warmup: OK")
