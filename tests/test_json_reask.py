"""chat_json re-asks ONCE when the first answer is not valid JSON (cut off / bad quotes); fakes only."""
import os
import sys
sys.path.insert(0, ".")
os.environ["NELLY_LLM_API_KEY"] = "test-not-a-real-key"
import llm                                                          # noqa: E402

def fake(answers):
    calls = []
    def chat_text(messages, model=None, temperature=0.0):
        calls.append(len(messages))
        return answers[min(len(calls) - 1, len(answers) - 1)]
    llm.chat_text = chat_text
    return calls

calls = fake(['{"action": "press", "keys": ["alt","d"], "why": "The D: drive is not listed, so I', '{"action": "press", "why": "ok"}'])
assert llm.chat_json("s", "u") == {"action": "press", "why": "ok"} and len(calls) == 2, calls
calls = fake(['{"a": 1}'])
assert llm.chat_json("s", "u") == {"a": 1} and len(calls) == 1
calls = fake(['{"bad'])
try:
    llm.chat_json("s", "u"); raise SystemExit("should fail")
except ValueError as e:
    assert "after one re-ask" in str(e) and len(calls) == 2
print("ok")
