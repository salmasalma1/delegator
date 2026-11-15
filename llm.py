"""
One tiny place that talks to the model for JSON answers.
Used by the action decider and the plan check (reasoning.py keeps its own call for now).
"""
import json
import os
import re

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


class LLMUnavailable(RuntimeError):
    """No key / no client: the caller decides what an honest fallback is."""


def _key() -> str:
    """NELLY_LLM_API_KEY wins (any OpenAI-compatible provider); DASHSCOPE_API_KEY is the default."""
    return os.getenv("NELLY_LLM_API_KEY") or os.getenv("DASHSCOPE_API_KEY", "")


def _base_url() -> str:
    return (os.getenv("NELLY_LLM_BASE_URL") or os.getenv("DASHSCOPE_BASE_URL")
            or "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")


def available() -> bool:
    key = _key()
    return bool(key) and "PUT_YOUR_KEY" not in key


def chat_json(system: str, user: str, model: str = "qwen3-vl-plus", temperature: float = 0.0):
    """Returns the parsed JSON object/array. Raises LLMUnavailable or ValueError(raw text)."""
    if not available():
        raise LLMUnavailable("no API key: set DASHSCOPE_API_KEY (or NELLY_LLM_API_KEY)")
    from openai import OpenAI
    client = OpenAI(api_key=_key(), base_url=_base_url())
    model = os.getenv("NELLY_LLM_MODEL") or model          # one switch to try another provider's model
    resp = client.chat.completions.create(
        model=model, temperature=temperature,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    text = (resp.choices[0].message.content or "").strip()
    m = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    try:
        return json.loads(m.group(1) if m else text)
    except Exception as e:                                   # noqa: BLE001
        raise ValueError(f"unparseable model answer: {text[:200]}") from e
