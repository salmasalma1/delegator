import os as _o0; _o0.environ.setdefault("NELLY_DRY_RUN", "1")  # tests never move the real mouse
"""One place for provider settings: llm.py, the VLM verifier and vision/understand.py use the same key, base URL
and model (NELLY_LLM_* first; the legacy DASHSCOPE_* only when no NELLY_LLM_* is set). The VLM verifier runs only
when NELLY_VERIFIER is "vlm", or unset with a key. One start-up line names the provider host and model (never the
key); a warning when NELLY_LLM_BASE_URL is set without NELLY_LLM_MODEL. Fake client only: no network."""
import os
import sys
import tempfile

sys.path.insert(0, ".")
os.environ["NELLY_PERSIST"] = "0"
LEGACY, NEW = "legacy-SECRET-0000000000", "new-SECRET-1111111111"
for k in ("NELLY_LLM_API_KEY", "NELLY_LLM_BASE_URL", "NELLY_LLM_MODEL", "DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL",
          "NELLY_VERIFIER"):
    os.environ.pop(k, None)
import types                                                        # noqa: E402
_no_dotenv = types.ModuleType("dotenv")                             # the real .env must never be read by this test
_no_dotenv.load_dotenv = lambda *a, **k: False
sys.modules["dotenv"] = _no_dotenv
import openai                                                       # noqa: E402
import llm                                                          # noqa: E402
import verifier as V                                                # noqa: E402


class FakeClient:
    made = []
    error = None

    def __init__(self, **kw):
        FakeClient.made.append(kw)
        self.chat = self
        self.completions = self

    def create(self, **kw):
        FakeClient.made[-1]["model"] = kw.get("model")
        if FakeClient.error is not None:
            raise FakeClient.error

        class M:
            content = '{"passed": true, "confidence": 0.9, "reason": "ok", "readable": true}'

        class C:
            message = M()

        class R:
            choices = [C()]
        return R()


openai.OpenAI = FakeClient
shot = os.path.join(tempfile.gettempdir(), "nelly_test_shot.png")
open(shot, "wb").write(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
NODE = {"node": "n", "flag": "text visible", "steps": ["type"]}

# 1) legacy key present, but NELLY_LLM_* is set: the legacy key is NOT used (no key at all here)
os.environ.update({"DASHSCOPE_API_KEY": LEGACY, "NELLY_LLM_BASE_URL": "https://new.example.test/v1",
                   "NELLY_LLM_MODEL": "new-model"})
s = llm.provider_settings()
assert s["key"] == "" and s["base_url"] == "https://new.example.test/v1" and s["model"] == "new-model",     (s["source"], bool(s["key"]))
assert not llm.available()
assert V.VLMVerifier().key == "" and not V.VLMVerifier().available()
assert isinstance(V.get_verifier(), V.RuleVerifier)                 # unset + no key -> rule, never the old key

# 2) NELLY_LLM_API_KEY set: llm, verifier and understand all use the new key, URL and model
os.environ["NELLY_LLM_API_KEY"] = NEW
vlm = V.get_verifier()
assert isinstance(vlm, V.VLMVerifier) and vlm.key == NEW and vlm.base_url == "https://new.example.test/v1"
FakeClient.made.clear()
out = vlm.verify(NODE, {"status": "completed"}, after_screenshot=shot)
assert out["method"] == "vlm" and out["passed"], out
assert FakeClient.made[-1]["api_key"] == NEW and FakeClient.made[-1]["base_url"] == "https://new.example.test/v1"
assert FakeClient.made[-1]["model"] == "new-model", FakeClient.made[-1].get("model")
from vision.understand import understand                            # noqa: E402
FakeClient.made.clear()
understand(shot)
assert FakeClient.made[-1]["api_key"] == NEW and FakeClient.made[-1]["model"] == "new-model",     FakeClient.made[-1].get("model")
llm.chat_json("s", "u")
assert FakeClient.made[-1]["api_key"] == NEW

# 3) no NELLY_LLM_* at all: the legacy DASHSCOPE_* settings are used
for k in ("NELLY_LLM_API_KEY", "NELLY_LLM_BASE_URL", "NELLY_LLM_MODEL"):
    os.environ.pop(k)
s = llm.provider_settings()
assert s["key"] == LEGACY and "dashscope" in s["base_url"] and "legacy" in s["source"], s["source"]
os.environ["NELLY_LLM_API_KEY"] = NEW

# 4) NELLY_VERIFIER: the VLM verifier runs only when "vlm", or unset with a key
for value, cls in (("rule", V.RuleVerifier), ("vlm", V.VLMVerifier), ("", V.VLMVerifier),
                   ("something-else", V.RuleVerifier)):
    os.environ["NELLY_VERIFIER"] = value
    assert isinstance(V.get_verifier(), cls), (value, type(V.get_verifier()))
os.environ.pop("NELLY_VERIFIER")

# 5) a provider error in the VLM verifier falls back to the rule verifier, with the kind and without the key
import httpx                                                        # noqa: E402
req = httpx.Request("POST", "https://new.example.test/v1/chat/completions")
FakeClient.error = openai.AuthenticationError(f"bad {NEW}", response=httpx.Response(401, request=req), body=None)
out = V.VLMVerifier().verify(NODE, {"status": "completed", "steps_done": [{"status": "success"}]},
                             after_screenshot=shot)
assert out["method"] != "vlm" and "vlm_error:auth" in out["reason"] and NEW not in str(out), out.get("method")
FakeClient.error = None

# 6) start-up lines: provider host and model, never the key; warning for a base URL without a model
os.environ.update({"NELLY_LLM_BASE_URL": "https://new.example.test/v1", "NELLY_LLM_MODEL": "new-model"})
lines = llm.startup_lines()
assert any("new.example.test" in l and "new-model" in l for l in lines), lines
assert not any("WARNING" in l for l in lines) and not any(NEW in l or LEGACY in l for l in lines), lines
os.environ.pop("NELLY_LLM_MODEL")
lines = llm.startup_lines()
assert any("WARNING" in l and "NELLY_LLM_MODEL" in l for l in lines), lines
assert "startup_lines" in open("run.py", encoding="utf-8").read()
os.remove(shot)

print("test_llm_provider_settings OK")
