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


DEFAULT_RETRIES = 2


def llm_retries() -> int:
    """NELLY_LLM_RETRIES: how many times the client retries a failed call (503, timeout, connection). Default 2, max 8."""
    try:
        v = int(os.getenv("NELLY_LLM_RETRIES", DEFAULT_RETRIES))
        return min(max(v, 0), 8)
    except ValueError:
        return DEFAULT_RETRIES


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


DEFAULT_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3-vl-plus"
_NELLY_VARS = ("NELLY_LLM_API_KEY", "NELLY_LLM_BASE_URL", "NELLY_LLM_MODEL")


def provider_settings() -> dict:
    """THE provider settings, for every model call (planner, decider, plan check, VLM verifier, understand).
    NELLY_LLM_* first. The legacy DASHSCOPE_* settings are used only when NO NELLY_LLM_* variable is set, so an old
    DashScope key is never sent to a new provider. `model` is None when no model is configured."""
    if any(os.getenv(k) for k in _NELLY_VARS):
        return {"key": os.getenv("NELLY_LLM_API_KEY", ""),
                "base_url": os.getenv("NELLY_LLM_BASE_URL") or DEFAULT_BASE_URL,
                "model": os.getenv("NELLY_LLM_MODEL") or None, "source": "NELLY_LLM_*"}
    return {"key": os.getenv("DASHSCOPE_API_KEY", ""),
            "base_url": os.getenv("DASHSCOPE_BASE_URL") or DEFAULT_BASE_URL,
            "model": None, "source": "DASHSCOPE_* (legacy)"}


def _key() -> str:
    return provider_settings()["key"]


def _base_url() -> str:
    return provider_settings()["base_url"]


def startup_lines() -> list:
    """What run.py prints at start: provider host and model (never the key), and a warning when a base URL is set
    without a model (the built-in default model would be sent to that provider)."""
    st = provider_settings()
    model = st["model"] or f"{DEFAULT_MODEL} (built-in default)"
    lines = [f"[startup] LLM: provider host {_host(st['base_url'])}, model {model}, settings from {st['source']}"
             + ("" if available() else "; NO KEY (planning needs one)")]
    if os.getenv("NELLY_LLM_BASE_URL") and not os.getenv("NELLY_LLM_MODEL"):
        lines.append(f"[startup] WARNING: NELLY_LLM_BASE_URL is set but NELLY_LLM_MODEL is not: the built-in "
                     f"default model {DEFAULT_MODEL!r} would be sent to {_host(st['base_url'])}. Set NELLY_LLM_MODEL.")
    return lines


def available() -> bool:
    key = _key()
    return bool(key) and "PUT_YOUR_KEY" not in key


_KEEP_ESCAPE = re.compile(r'(\\\\|\\"|\\/|\\u[0-9a-fA-F]{4})|\\')


def loads_lenient(text: str):
    """json.loads, and if that fails ONE repair: every backslash that is not a complete JSON escape
    (a pair, \\", \\/ or \\uXXXX) is a literal backslash. Models often write a Windows path such as
    D:\\11.22.63 with single backslashes; `\\1` is not a JSON escape, so the whole answer was refused.
    Strict parsing is always tried first and a clean answer is never touched. Raises ValueError as before."""
    try:
        return json.loads(text)
    except ValueError:
        fixed = _KEEP_ESCAPE.sub(lambda m: m.group(1) or "\\\\", text)
        return json.loads(fixed)


def _json_span(text: str) -> str:
    """The outermost {...} or [...] of an answer, starting at whichever opens FIRST. A cut-off object must not be
    mistaken for the array inside it (["alt","d"]); an unclosed object is returned whole so it fails and is re-asked."""
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        return text
    i = min(starts)
    close = "}" if text[i] == "{" else "]"
    j = text.rfind(close)
    return text[i:j + 1] if j > i else text[i:]


def chat_json(system: str, user: str, model: str = "qwen3-vl-plus", temperature: float = 0.0):
    """Returns the parsed JSON object/array. Raises LLMUnavailable, LLMError or ValueError(raw text)."""
    if not available():
        raise LLMUnavailable("no API key: set DASHSCOPE_API_KEY (or NELLY_LLM_API_KEY)")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    text = chat_text(messages, model=model, temperature=temperature)
    for attempt in (1, 2):
        try:
            return loads_lenient(_json_span(text))
        except Exception as e:                               # noqa: BLE001
            if attempt == 2:
                raise ValueError(f"unparseable model answer (after one re-ask): {text[:400]}") from e
        # ONE re-ask: a cut or badly quoted answer is usually fixed by asking again for plain JSON.
        messages = messages + [
            {"role": "assistant", "content": text[:2000]},
            {"role": "user", "content": "That was not valid JSON (it may have been cut off or had quotes inside a "
                                        "string). Answer again with ONLY one complete JSON object, a very short "
                                        "\"why\" with no double quotes inside it, and Windows paths with doubled "
                                        "backslashes."}]
        text = chat_text(messages, model=model, temperature=temperature)


def chat_text(messages: list, model: str = "qwen3-vl-plus", temperature: float = 0.0) -> str:
    """One chat call -> the answer text. Raises LLMUnavailable (no key) or LLMError (provider error / timeout)."""
    if not available():
        raise LLMUnavailable("no API key: set NELLY_LLM_API_KEY (or the legacy DASHSCOPE_API_KEY)")
    import openai
    base_url = _base_url()
    client = openai.OpenAI(api_key=_key(), base_url=base_url, timeout=llm_timeout(), max_retries=llm_retries())
    model = provider_settings()["model"] or model           # NELLY_LLM_MODEL wins over the caller's default
    try:
        resp = client.chat.completions.create(model=model, temperature=temperature, messages=messages)
    except Exception as e:                                   # noqa: BLE001
        err = _as_llm_error(e, base_url)
        if err is None:
            raise
        raise err from None                                  # 'from None': the provider's text may echo the key
    return (resp.choices[0].message.content or "").strip()
