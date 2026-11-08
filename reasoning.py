"""
Reasoning — the planner's brain (qwen3-vl-plus).

The model UNDERSTANDS the request and writes the plan. This file only:
  - tells it the rules of the game (system prompt: principles, no memorised examples),
  - checks that what came back is a usable plan (shape, checkable flags, sane size),
  - gives it ONE chance to fix its own mistake, then fails loudly.
There is no silent fallback plan: a wrong plan is worse than no plan.
"""
import json
from typing import List, Optional

import llm

MAX_NODES = 8
MAX_STEPS = 6
UNCHECKABLE = {"done", "ok", "success", "completed", "finished", "task completed",
               "task done", "n/a", "none", ""}


class PlanError(Exception):
    """No usable plan. `clarify` is set when the model needs an answer from the user."""
    def __init__(self, msg: str, clarify: Optional[str] = None):
        super().__init__(msg)
        self.clarify = clarify


SYSTEM = """You are the planner of NELLY, an agent that operates a Windows PC through its screen.
Turn the user's request into an ordered plan of sub-goals. You only plan: separate workers will
look at the live screen and perform each sub-goal, one worker per sub-goal.

Return ONLY a JSON array. Each item is a sub-goal:
{"node": "<App>: <what this sub-goal achieves>",
 "app": "<the ONE app it happens in>",
 "worker": "native" | "browser",
 "flag": "<what must be visibly true on screen when it is finished>",
 "steps": ["<intention>", ...]}

Principles:
- Cover everything the user asked and NOTHING more. Never add sending, deleting, paying,
  installing or submitting unless the user explicitly asked for that.
- One app per sub-goal. Start a new sub-goal when the app changes, or when a result must be
  confirmed before the next part can rely on it.
- Order by dependency. If a sub-goal needs something an earlier one produced (a link, text, a
  file path), say in its steps where it comes from, and make the earlier flag state that the
  thing now exists.
- "flag" is a condition someone could confirm by looking at the screen afterwards. Be specific
  about window, name or content. Never "done", "completed" or "success".
- "steps" are 1 to 4 plain-language intentions: what to achieve, not how. No coordinates, no
  element ids, no required wording. The worker decides the exact action from the live screen.
- worker = "browser" when the work happens inside a web page or web app, otherwise "native".
- If the request is ambiguous, impossible, or lacks something only the user knows (a recipient,
  a file name, a choice), do not guess. Return {"clarify": "<one short question>"} instead.
- On a REPLAN: return only the REMAINING sub-goals. Do not repeat completed ones, and change
  the approach that failed instead of repeating it."""


def _problems(item, i: int) -> List[str]:
    p = []
    if not isinstance(item, dict):
        return [f"item {i} is not an object"]
    for k in ("node", "app", "flag"):
        if not (isinstance(item.get(k), str) and item[k].strip()):
            p.append(f"item {i}: '{k}' missing or empty")
    if isinstance(item.get("flag"), str) and item["flag"].strip().lower().rstrip(".") in UNCHECKABLE:
        p.append(f"item {i}: flag {item['flag']!r} cannot be checked on screen; describe what is visible")
    st = item.get("steps")
    if not (isinstance(st, list) and 1 <= len(st) <= MAX_STEPS and all(isinstance(s, str) and s.strip() for s in st)):
        p.append(f"item {i}: 'steps' must be 1-{MAX_STEPS} non-empty strings")
    if item.get("worker", "native") not in ("native", "browser"):
        p.append(f"item {i}: worker must be 'native' or 'browser'")
    return p


def validate_plan(out) -> tuple:
    """-> (nodes, problems). nodes is normalised: ids, worker, depends_on, resource filled in."""
    if not isinstance(out, list) or not out:
        return [], ["the answer must be a non-empty JSON array of sub-goals"]
    if len(out) > MAX_NODES:
        return [], [f"too many sub-goals ({len(out)} > {MAX_NODES}); merge them"]
    problems = [x for i, item in enumerate(out) for x in _problems(item, i)]
    if problems:
        return [], problems
    nodes = []
    for i, item in enumerate(out):
        worker = item.get("worker", "native")
        nodes.append({
            "id": f"n{i + 1}", "node": item["node"].strip(), "app": item["app"].strip(),
            "worker": worker, "flag": item["flag"].strip(),
            "steps": [s.strip() for s in item["steps"]],
            # sequential for now; a real dependency graph can be written here later
            "depends_on": [f"n{i}"] if i else [],
            "resource": "desktop" if worker == "native" else "browser:default",
        })
    return nodes, []


def _screen_text(vision_ctx) -> str:
    if not vision_ctx:
        return "unknown"
    try:
        from vision.adapter import to_prompt
        return to_prompt(vision_ctx, limit=15)[:800]
    except Exception:                                         # noqa: BLE001
        return str(vision_ctx)[:500]


class StrategyProvider:
    def plan(self, task: str, vision_ctx=None, memory_ctx=None, replan_ctx=None) -> List[dict]:
        raise NotImplementedError


class QwenProvider(StrategyProvider):
    def __init__(self, model="qwen3-vl-plus"):
        self.model = model

    def _user(self, task, vision_ctx, memory_ctx, replan_ctx) -> str:
        u = f"User request: {task}\n\nScreen right now:\n{_screen_text(vision_ctx)}"
        if memory_ctx:
            u += f"\n\nAlready done: {json.dumps(memory_ctx, default=str, ensure_ascii=False)[:400]}"
        if replan_ctx:
            done = [n.get("node") for n in replan_ctx.get("completed_nodes") or []]
            u += ("\n\nREPLAN: the previous plan failed."
                  f"\nFailed sub-goal: {replan_ctx.get('failed_node')}"
                  f"\nWhy: {replan_ctx.get('reason')}"
                  f"\nAlready completed (do not redo): {done}"
                  f"\nAttempt: {replan_ctx.get('attempt')}")
        return u

    def plan(self, task: str, vision_ctx=None, memory_ctx=None, replan_ctx=None) -> List[dict]:
        user = self._user(task, vision_ctx, memory_ctx, replan_ctx)
        problems: List[str] = []
        for attempt in (1, 2):
            note = "" if not problems else \
                "\n\nYour previous answer was rejected:\n- " + "\n- ".join(problems) + "\nFix these and answer again."
            try:
                out = llm.chat_json(SYSTEM, user + note, model=self.model, temperature=0.2)
            except llm.LLMUnavailable as e:
                raise PlanError(f"planner has no model: {e}") from e
            except ValueError as e:                           # not JSON
                problems = [str(e)]
                continue
            if isinstance(out, dict) and out.get("clarify"):
                raise PlanError("planner needs more information", clarify=str(out["clarify"]))
            nodes, problems = validate_plan(out)
            if not problems:
                return nodes
        raise PlanError(f"planner gave no valid plan after 2 tries: {problems}")


def get_reasoning_provider() -> StrategyProvider:
    return QwenProvider()
