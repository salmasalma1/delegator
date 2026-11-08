"""
Reasoning — VLM 
Understands any task alone via qwen3-vl-plus.
"""
import os, json
try:
    from dotenv import load_dotenv; load_dotenv()
except: pass
from typing import List

class StrategyProvider:
    def plan(self, task: str, vision_ctx=None, memory_ctx=None) -> List[dict]:
        raise NotImplementedError

class QwenProvider(StrategyProvider):
    """calls vlm Understands task."""
    def __init__(self, model="qwen3-vl-plus"):
        self.model = model
        self.base_url = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
        self.api_key = os.getenv("DASHSCOPE_API_KEY")

    def plan(self, task: str, vision_ctx=None, memory_ctx=None) -> List[dict]:
        if not self.api_key:
            raise RuntimeError("DASHSCOPE_API_KEY not set — cannot use real reasoning. Set NELLY_BRAIN=qwen and API key.")
        from openai import OpenAI
        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        system = """You are a Director for NELLY agent.
Decompose ANY task into Nodes.
Each Node: {"node": "App: action", "flag": "completion condition", "app": "AppName", "steps": ["step1", "step2"]}
Rules: Top-30 elements, window-relative coordinates, one app per Node, 1-3 steps per Node.
Return JSON list only."""
        user = f"Task: {task}\nVision: {str(vision_ctx)[:500]}\nMemory: {str(memory_ctx)[:300]}"
        resp = client.chat.completions.create(
            model=self.model,
            messages=[{"role":"system","content":system},{"role":"user","content":user}],
            temperature=0.2,
        )
        text = resp.choices[0].message.content.strip()
        # Try parse JSON
        try:
            # Extract JSON array if wrapped in markdown
            import re
            m = re.search(r'\[.*\]', text, re.DOTALL)
            if m:
                text = m.group(0)
            nodes = json.loads(text)
            # Validate
            if isinstance(nodes, list) and all("node" in n and "app" in n for n in nodes):
                return nodes
        except Exception as e:
            print(f"[Qwen parse failed] {e}, raw: {text[:500]}")
        # Fallback to single generic node
        return [{"node": f"Generic: {task[:40]}", "flag": "task completed", "app": "Notepad", "steps": ["perceive", "act", "verify"]}]

def get_reasoning_provider() -> StrategyProvider:
    """return vlm provider"""
    return QwenProvider()
