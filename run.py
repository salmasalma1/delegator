"""Run delegator — supports voice/text gateway"""
from graph.builder import build_graph
from gateway.gateway import normalize_task
import os
import sys
import uuid


def run_task(text: str, source: str = "text"):
    graph = build_graph()
    init = normalize_task(text, source=source, task_id=str(uuid.uuid4()), session_id=str(uuid.uuid4()))
    # Use thread_id for checkpoint
    config = {"configurable": {"thread_id": init["session_id"]}}
    result = None
    # A person at the terminal can answer approvals. Headless runs have NO approver: the run pauses.
    from graph import safety_port
    asker = safety_port.console_approver if (sys.stdin.isatty() and not os.getenv("NELLY_NO_PROMPT")) else None
    with safety_port.bind_approver(asker):
        for event in graph.stream(init, config=config):
            result = event
            print(event)
    # Final state
    final = graph.get_state(config).values
    print("\n=== FINAL ===")
    print(f"Goal: {final.get('goal')}")
    print(f"Status: {final.get('status')}")
    print(f"Nodes: {final.get('nodes')}")
    print(f"Sub results: {final.get('sub_results')}")
    return final


if __name__ == "__main__":
    import sys
    argv = sys.argv[1:]
    if not argv:
        
        print('where is the task?')
        
        sys.exit(2)
    run_task(" ".join(argv), source="text")