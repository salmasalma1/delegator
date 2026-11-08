from typing import Optional, List, TypedDict

class AgentState(TypedDict, total=False):
    session_id: str
    task_id: str
    status: str
    current_step: int
    total_steps: int
    goal: str
    plan: List[str]
    # Delegation
    nodes: List[dict]  # Hamlet Director nodes: [{node:"Spotify: get link", flag:"link exists", app:"Spotify"}]
    current_node_idx: int
    sub_results: List[dict]
    # Existing
    pending_action_id: Optional[str]
    saved_checkpoint_id: Optional[str]
    auth_status: str
    last_vision_result: Optional[dict]
    last_safety_decision: Optional[dict]
    last_execution_result: Optional[dict]
    last_proposed_action: Optional[dict]
    error: Optional[str]
    # Gateway
    task_source: str  # "voice" | "text"
    # Verification loop
    last_sub_result: Optional[dict]
    verifications: List[dict]     # one entry per node attempt: passed/reason/confidence/method
    replans: int
    max_replans: int
    replan_reason: Optional[str]
    failed_node: Optional[dict]
    escalation_reason: Optional[str]
    escalation: Optional[dict]
    latency_ms: Optional[int]
    plan_round: int
    plan_check: Optional[dict]        # verdict of the pre-execution plan check
    plan_check_retries: int
    requires_user: bool
    after_screenshot: Optional[str]   # post-action screenshot path for the VLM verifier
    verification_summary: Optional[dict]
    # Vision boundary
    screenshot: Optional[object]      # path/bytes handed to the perception module
    vision_scenario: Optional[str]    # test-only fixture selector
    grounding: Optional[dict]         # normalized Top-30 elements for the Director

class TaskRequest(TypedDict, total=False):
    text: str
    source: str  # voice | text
    session_id: str
    task_id: str