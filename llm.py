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


class LLMError(RuntimeError):
    """The provider answered with an error or could not be reached. The message names the kind and the provider host;
    it never contains the key (the provider's own text, which may echo it, is not used)."""
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


DEFAULT_TIMEOUT_S = 60.0


def llm_timeout() -> float:
    """NELLY_LLM_TIMEOUT: seconds the client waits for the provider (default 60)."""
    try:
        v = float(os.getenv("NELLY_LLM_TIMEOUT", DEFAULT_TIMEOUT_S))
        return v if v > 0 else DEFAULT_TIMEOUT_S
    except ValueError:
        return DEFAULT_TIMEOUT_S


def _host(url: str) -> str:
    from urllib.parse import urlparse
    return urlparse(url or "").netloc or "unknown host"


def _as_llm_error(exc: Exception, base_url: str):
    """openai errors -> LLMError (None for anything else). Order matters: timeout is a kind of connection error."""
    import openai
    host = _host(base_url)
    status = getattr(exc, "status_code", None)
    if isinstance(exc, openai.AuthenticationError):
        return LLMError("auth", f"LLM: provider rejected the key ({status or 401}) at {host}")
    if isinstance(exc, openai.RateLimitError):
        return LLMError("rate_limit", f"LLM: provider rate limit ({status or 429}) at {host}; try again later")
    if isinstance(exc, openai.APITimeoutError):
        return LLMError("timeout", f"LLM: {host} did not answer within {llm_timeout():.0f} s (NELLY_LLM_TIMEOUT)")
    if isinstance(exc, openai.APIConnectionError):
        return LLMError("connection", f"LLM: cannot reach the provider {host} (connection error)")
    if isinstance(exc, openai.APIStatusError):
        return LLMError("status", f"LLM: provider error (HTTP {status}) at {host}")
    return None


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
    """Returns the parsed JSON object/array. Raises LLMUnavailable, LLMError or ValueError(raw text)."""
    if not available():
        raise LLMUnavailable("no API key: set DASHSCOPE_API_KEY (or NELLY_LLM_API_KEY)")
    text = chat_text([{"role": "system", "content": system}, {"role": "user", "content": user}],
                     model=model, temperature=temperature)
    m = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    try:
        return json.loads(m.group(1) if m else text)
    except Exception as e:                                   # noqa: BLE001
        raise ValueError(f"unparseable model answer: {text[:200]}") from e


def chat_text(messages: list, model: str = "qwen3-vl-plus", temperature: float = 0.0) -> str:
    """One chat call -> the answer text. Raises LLMUnavailable (no key) or LLMError (provider error / timeout)."""
    if not available():
        raise LLMUnavailable("no API key: set NELLY_LLM_API_KEY (or the legacy DASHSCOPE_API_KEY)")
    import openai
    base_url = _base_url()
    client = openai.OpenAI(api_key=_key(), base_url=base_url, timeout=llm_timeout())
    model = os.getenv("NELLY_LLM_MODEL") or model          # one switch to try another provider's model
    try:
        resp = client.chat.completions.create(model=model, temperature=temperature, messages=messages)
    except Exception as e:                                   # noqa: BLE001
        err = _as_llm_error(e, base_url)
        if err is None:
            raise
        raise err from None                                  # 'from None': the provider's text may echo the key
    return (resp.choices[0].message.content or "").strip()
