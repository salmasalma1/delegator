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
        # only actions that point at something on screen need a grounded element
        needs_el = ("click", "type")
        if any(not (s.get("target") or {}).get("element_id")
               and (s.get("execution") or {}).get("action_type", "click") in needs_el
               for s in steps):
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
        import llm                                   # one place for provider settings (NELLY_LLM_* first)
        st = llm.provider_settings()
        self.key, self.base_url = st["key"], st["base_url"]
        self.model = st["model"] or model

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

        import llm
        from vision.understand import _data_url
        ctx = ""
        if grounding:
            ctx = (f"\nBefore-action screen: app={grounding.get('app')} "
                   f"elements={[e.get('text') for e in (grounding.get('elements') or [])[:8]]}")
        try:
            text = llm.chat_text([
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": [
                    {"type": "text",
                     "text": f"Flag to verify: {node.get('flag')!r}\n"
                             f"Step that ran: {node.get('steps')}{ctx}"},
                    {"type": "image_url", "image_url": {"url": _data_url(after_screenshot)}},
                ]},
            ], model=self.model, temperature=0.1)
        except (llm.LLMUnavailable, llm.LLMError) as e:
            v = RuleVerifier().verify(node, sub_result, grounding)
            v["reason"] += f";vlm_error:{getattr(e, 'kind', 'no_key')}"
            return v
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
    """The VLM verifier runs only when NELLY_VERIFIER is "vlm", or unset with a key (same key as llm.py).
    "rule" or any other value -> the offline rule verifier."""
    choice = os.getenv("NELLY_VERIFIER", "").strip().lower()
    if choice == "vlm":
        return VLMVerifier()
    if choice == "":
        vlm = VLMVerifier()
        if vlm.available():
            return vlm
    return RuleVerifier()
