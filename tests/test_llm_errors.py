import os as _o0; _o0.environ.setdefault("NELLY_DRY_RUN", "1")  # tests never move the real mouse
"""LLM provider errors become ONE clear error (LLMError) that names the kind and never contains the key; the planner
turns it into a clean failed run (no crash); NELLY_LLM_TIMEOUT (default 60 s) reaches the client. Fake client only:
no network."""
import os
import sys

sys.path.insert(0, ".")
os.environ["NELLY_PERSIST"] = "0"
SECRET = "sk-test-SECRET-do-not-print-0123456789"
os.environ.update({"NELLY_LLM_API_KEY": SECRET, "NELLY_LLM_BASE_URL": "https://llm.example.test/v1",
                   "NELLY_LLM_MODEL": "test-model"})
os.environ.pop("NELLY_LLM_TIMEOUT", None)
import httpx                                                        # noqa: E402
import openai                                                       # noqa: E402
import llm                                                          # noqa: E402

REQ = httpx.Request("POST", "https://llm.example.test/v1/chat/completions")


def status_error(cls, code):
    return cls(f"Invalid token for key {SECRET}", response=httpx.Response(code, request=REQ),
               body={"error": {"message": f"bad key {SECRET}"}})


class FakeClient:
    """Records the constructor arguments; create() raises the scripted error or answers {"ok": true}."""
    made = []
    error = None

    def __init__(self, **kw):
        FakeClient.made.append(kw)
        self.chat = self
        self.completions = self

    def create(self, **kw):
        if FakeClient.error is not None:
            raise FakeClient.error

        class M:
            content = '{"ok": true}'

        class C:
            message = M()

        class R:
            choices = [C()]
        return R()


openai.OpenAI = FakeClient                                          # llm builds its client through openai.OpenAI

# 1) every provider error becomes LLMError with the kind in the message and never the key
cases = [(status_error(openai.AuthenticationError, 401), "provider rejected the key (401)"),
         (status_error(openai.RateLimitError, 429), "rate limit (429)"),
         (openai.APITimeoutError(request=REQ), "did not answer within 60 s"),
         (openai.APIConnectionError(request=REQ), "cannot reach the provider"),
         (status_error(openai.InternalServerError, 500), "provider error (HTTP 500)")]
for err, words in cases:
    FakeClient.error = err
    try:
        llm.chat_json("s", "u")
        raise AssertionError(f"no error for {type(err).__name__}")
    except llm.LLMError as e:
        msg = str(e)
        assert words in msg, (words, msg)
        assert SECRET not in msg and SECRET not in repr(e), msg
        assert "llm.example.test" in msg, msg                        # the provider host helps; the key never
FakeClient.error = None
assert llm.chat_json("s", "u") == {"ok": True}

# 2) NELLY_LLM_TIMEOUT reaches the client (default 60 s)
FakeClient.made.clear()
llm.chat_json("s", "u")
assert FakeClient.made[-1]["timeout"] == 60.0, FakeClient.made[-1].keys()
os.environ["NELLY_LLM_TIMEOUT"] = "5"
llm.chat_json("s", "u")
assert FakeClient.made[-1]["timeout"] == 5.0
FakeClient.error = openai.APITimeoutError(request=REQ)
try:
    llm.chat_json("s", "u")
except llm.LLMError as e:
    assert "5 s" in str(e), e
os.environ.pop("NELLY_LLM_TIMEOUT")

# 3) the planner turns a 401 into a clear PlanError; the director ends the run as failed (no exception)
FakeClient.error = status_error(openai.AuthenticationError, 401)
from reasoning import QwenProvider, PlanError                       # noqa: E402
try:
    QwenProvider().plan("Open Notepad")
    raise AssertionError("planner did not fail")
except PlanError as e:
    assert "provider rejected the key (401)" in str(e) and SECRET not in str(e), e
from graph.nodes.director import director_node                      # noqa: E402
out = director_node({"goal": "Open Notepad"})
assert out["status"] == "failed" and "provider rejected the key (401)" in out["error"], out

# 4) the whole session ends with a clear message instead of crashing
from gateway.session import Session                                 # noqa: E402
res = Session(approver=None).submit("Open Notepad and type: hello Lumi")
assert res["report"]["status"] == "failed", res["report"]
assert "provider rejected the key (401)" in res["text"] and SECRET not in res["text"], res["text"]
FakeClient.error = None

print("test_llm_errors OK")
