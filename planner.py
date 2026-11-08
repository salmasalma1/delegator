"""
Planner — Director (uses Reasoning)
Decides WHAT Nodes to create. Called by director_node.
"""
from typing import List
from reasoning import get_reasoning_provider

def plan_task(task: str, vision_ctx=None, memory_ctx=None) -> List[dict]:
    """Entry for Planner. Returns Nodes with flags: [{node, flag, app, steps}]"""
    provider = get_reasoning_provider()
    return provider.plan(task, vision_ctx, memory_ctx)