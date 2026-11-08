"""
Planner — Director (uses Reasoning)
Decides WHAT Nodes to create. Called by director_node.
"""
from typing import List, Optional
from reasoning import get_reasoning_provider

def plan_task(task: str, vision_ctx=None, memory_ctx=None, replan_ctx: Optional[dict] = None) -> List[dict]:
    """Entry for Planner. Returns Nodes with flags: [{node, flag, app, steps}].
    replan_ctx is set only when re-planning after a failed step."""
    provider = get_reasoning_provider()
    return provider.plan(task, vision_ctx, memory_ctx, replan_ctx)
