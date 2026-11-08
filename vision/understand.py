"""
Semantic screen understanding — the part the vision module's grounding cannot give you.

vision module tells you WHAT is on screen (elements + bboxes + confidence).
The VLM tells you WHAT IT MEANS: which app, is it a person, is it a photo,
is it a dialog asking for permission, is it readable at all.

Why both: the quality gate in adapter.py is deterministic (thresholds, auditable,
free, instant). The VLM is semantic (flexible, costs a call, can hallucinate).
Use the gate first, ask the VLM only when the gate is unsure or the task needs meaning.

    python -m vision.understand shot.png
"""
import base64
import json
import mimetypes
import os
import re
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

SYSTEM = """You are the Perception Critic of NELLY, a desktop automation agent.
You receive a screenshot and optionally vision detected UI elements.
Answer ONLY with JSON:
{
  "readable": true/false,            // can a human read this screen well enough to act?
  "readability_reason": "...",
  "app_guess": "Notepad|WhatsApp|Spotify|Browser|Photos|Desktop|unknown",
  "screen_kind": "app_ui"|"photo"|"video"|"error_dialog"|"permission_prompt"|"empty"|"other",
  "contains_person": true/false,     // a human face/person is visible
  "description": "one sentence: what is on screen",
  "blocking": "nothing"|"dialog"|"login"|"captcha"|"unclear"
}
Do not invent UI elements. If the image is blurry, dark, cropped or ambiguous,
set readable=false and explain. Never guess a button you cannot see."""


def _data_url(path: str) -> str:
    mime = mimetypes.guess_type(path)[0] or "image/png"
    with open(path, "rb") as f:
        return f"data:{mime};base64," + base64.b64encode(f.read()).decode()


def understand(screenshot_path: str, grounding: Optional[dict] = None,
               model: str = "qwen3-vl-plus") -> dict:
    """Ask the VLM what the screen means. Raises if no key / no image."""
    key = os.getenv("DASHSCOPE_API_KEY", "")
    if not key or "PUT_YOUR_KEY" in key:
        raise RuntimeError("DASHSCOPE_API_KEY not set in delegator/.env")
    from openai import OpenAI
    client = OpenAI(api_key=key,
                    base_url=os.getenv("DASHSCOPE_BASE_URL",
                                       "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"))
    hint = ""
    if grounding:
        hint = (f"\nvision grounding: app={grounding.get('app')} "
                f"status={grounding.get('status')} "
                f"elements={len(grounding.get('elements') or [])} "
                f"quality={grounding.get('quality')}")
    resp = client.chat.completions.create(
        model=model,
        temperature=0.1,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": "Analyze this screen." + hint},
                {"type": "image_url", "image_url": {"url": _data_url(screenshot_path)}},
            ]},
        ],
    )
    text = (resp.choices[0].message.content or "").strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        return json.loads(m.group(0) if m else text)
    except Exception:
        return {"readable": None, "raw": text[:800], "parse_error": True}


def decide(grounding: dict, semantic: dict) -> dict:
    """
    Combine deterministic gate + VLM verdict into ONE decision the orchestrator uses.
    Rule: if the deterministic gate is clean but the VLM says unreadable/blocked,
    trust the VLM. If the gate says unreadable, never override it with the VLM.
    """
    gate_ok = bool(grounding.get("quality", {}).get("clear"))
    readable = semantic.get("readable")
    blocking = semantic.get("blocking", "nothing")
    act = gate_ok and readable is not False and blocking in ("nothing", None)
    return {
        "act": act,
        "reason": ("gate_failed" if not gate_ok else
                   "vlm_unreadable" if readable is False else
                   f"blocked:{blocking}" if blocking not in ("nothing", None) else "ok"),
        "screen_kind": semantic.get("screen_kind"),
        "contains_person": semantic.get("contains_person"),
        "app_guess": semantic.get("app_guess"),
        "gate_score": grounding.get("quality", {}).get("score"),
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: python -m vision.understand <image.png>")
        sys.exit(2)
    print(json.dumps(understand(sys.argv[1]), indent=2, ensure_ascii=False))
