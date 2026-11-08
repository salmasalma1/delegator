"""
Verifier .

Given ONE executed plan node and its worker result, decide:
    did this node's `flag` actually hold?

Two backends, same interface:
  RuleVerifier  — structural, free, offline. Proves wiring, not semantics.
  VLMVerifier   — looks at the post-action screenshot and answers the flag.
Default: VLM if a key is configured, else Rule (with a clear reason string).
"""
import json
import os
import re
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


class Verifier:
    name = "base"

    def verify(self, node: dict, sub_result: dict, grounding: Optional[dict] = None,
               after_screenshot: Optional[str] = None) -> dict:
        raise NotImplementedError


class RuleVerifier(Verifier):
    """Structural only: did the worker finish every step with a grounded target?"""
    name = "rule"

    def verify(self, node, sub_result, grounding=None, after_screenshot=None):
        flag = (node.get("flag") or "").strip()
        status = sub_result.get("status")
        steps = sub_result.get("steps_done") or []

        problems = []
        if status != "completed":
            problems.append(f"worker_status={status}")
        if not steps:
            problems.append("no_steps_done")
        if any(not (s.get("target") or {}).get("element_id") for s in steps):
            problems.append("step_without_grounded_target")
        if not flag or flag.lower() in ("done", "ok", "success", "completed"):
            problems.append("flag_not_checkable")

        passed = not problems
        return {
            "passed": passed,
            "confidence": 0.6 if passed else 0.0,   # structural ≠ semantic, cap it
            "method": self.name,
            "reason": "structural_ok" if passed else ";".join(problems),
            "evidence": {"flag": flag, "steps": len(steps)},
            "semantic": False,   # honest: this did not look at the screen
        }


SYSTEM = """You verify ONE step of a desktop automation agent.
You get: the completion flag (what must be TRUE now), and a screenshot taken AFTER the action.
Decide if the flag holds. Answer ONLY JSON:
{"passed": true/false, "confidence": 0.0-1.0, "reason": "short", "evidence": "what you see"}
Be strict: if the screenshot does not clearly show it, passed=false.
Never assume an action worked because it was attempted."""


class VLMVerifier(Verifier):
    """Takes the AFTER screenshot and answers the flag. Real semantic check."""
    name = "vlm"

    def __init__(self, model: str = "qwen3-vl-plus"):
        self.model = model
        self.key = os.getenv("DASHSCOPE_API_KEY", "")
        self.base_url = os.getenv("DASHSCOPE_BASE_URL",
                                  "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")

    def available(self) -> bool:
        return bool(self.key) and "PUT_YOUR_KEY" not in self.key

    def verify(self, node, sub_result, grounding=None, after_screenshot=None):
        if not after_screenshot or not os.path.exists(after_screenshot):
            v = RuleVerifier().verify(node, sub_result, grounding)
            v["reason"] += ";no_after_screenshot"
            return v
        if not self.available():
            v = RuleVerifier().verify(node, sub_result, grounding)
            v["reason"] += ";no_api_key"
            return v

        from vision.understand import _data_url
        from openai import OpenAI
        client = OpenAI(api_key=self.key, base_url=self.base_url)
        ctx = ""
        if grounding:
            ctx = (f"\nBefore-action screen: app={grounding.get('app')} "
                   f"elements={[e.get('text') for e in (grounding.get('elements') or [])[:8]]}")
        resp = client.chat.completions.create(
            model=self.model, temperature=0.1,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": [
                    {"type": "text",
                     "text": f"Flag to verify: {node.get('flag')!r}\n"
                             f"Step that ran: {node.get('steps')}{ctx}"},
                    {"type": "image_url", "image_url": {"url": _data_url(after_screenshot)}},
                ]},
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        m = re.search(r"\{.*\}", text, re.DOTALL)
        try:
            out = json.loads(m.group(0) if m else text)
        except Exception:
            return {"passed": False, "confidence": 0.0, "method": self.name,
                    "reason": f"unparseable_vlm_answer:{text[:120]}", "evidence": None,
                    "semantic": True}
        return {
            "passed": bool(out.get("passed")),
            "confidence": float(out.get("confidence") or 0.0),
            "method": self.name,
            "reason": out.get("reason") or ("ok" if out.get("passed") else "flag_not_met"),
            "evidence": out.get("evidence"),
            "semantic": True,
        }


def get_verifier() -> Verifier:
    """NELLY_VERIFIER=rule forces offline; default is VLM when a key exists."""
    choice = os.getenv("NELLY_VERIFIER", "").lower()
    if choice == "rule":
        return RuleVerifier()
    vlm = VLMVerifier()
    if choice == "vlm" or vlm.available():
        return vlm
    return RuleVerifier()
