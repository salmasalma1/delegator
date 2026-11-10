# Delegator — NELLY Orchestrator with Delegation

Team 2 (orchestration and planning) of NELLY, a voice/text Windows desktop agent that works by looking at the
screen. The Orchestrator plans, a Delegator carries each sub-goal to a worker, the worker does it, and every
sub-goal is verified before the next one starts.

```
TaskRequest -> Director (plan) -> Plan check -> Delegate -> Worker -> Verify step -> next | replan | escalate -> Finalize
```

## Layout

| Path | Role |
|---|---|
| `gateway/gateway.py` | Voice (Whisper) or text -> normalized `TaskRequest` |
| `reasoning.py`, `planner.py` | The planner's brain (Qwen `qwen3-vl-plus`): request -> nodes with flags; validated, one self-correction, no silent fallback |
| `graph/builder.py` | Wires the graph: director -> plan_check -> delegate -> verify_step -> (delegate / director / escalate / finalize) |
| `graph/state.py` | `AgentState` (declare every new state key here) |
| `graph/nodes/director.py` | Plans; on replan keeps verified nodes and re-plans from the failed one |
| `graph/nodes/plan_check.py` | Checks the plan matches the request before anything runs |
| `graph/nodes/delegate.py` | Runs ONE node via the worker (carrier, no LLM) |
| `graph/subgraphs/app_subgraph.py` | The worker: look -> decide one action -> safety -> act, in a loop (steps are hints) |
| `graph/action_decider.py` | LLM picks one allowed action and an on-screen element id; invalid answers are rejected |
| `graph/safety_port.py` | The only door to the machine; Team 3's Dispatcher plugs in via `NELLY_SAFETY_MODULE` (mock until then) |
| `graph/nodes/verify.py`, `verifier.py` | Per-node verify (VLM on a fresh screenshot, rule fallback) and finalize |
| `persistence/` | Checkpoint/audit seam: redaction, then Team 3's `db_helpers` store (shim fallback) |
| `vision/` | Adapter around Team 1's vision output |
| `schemas/`, `specs/` | Frozen contracts and integration notes |
| `tools/` | Smoke tests |

## Run

```bash
pip install -r requirements.txt
cp .env.example .env          # then put your own DASHSCOPE_API_KEY in .env (never commit it)
python run.py "your task"
```

With no `DASHSCOPE_API_KEY` the system still runs, but honestly: the planner cannot plan (it fails instead of
guessing), the plan check and verifier are marked `skipped`/rule-only, and the worker uses the legacy
one-action-per-step parser. Anything not really executed is reported as `dry_run`, never `completed`.

## Settings (environment variables)

| Variable | Meaning |
|---|---|
| `DASHSCOPE_API_KEY`, `DASHSCOPE_BASE_URL` | Qwen access |
| `NELLY_VERIFIER=rule` | Force the offline structural verifier |
| `NELLY_MAX_ACTIONS` | Worker leash per sub-goal (default 8) |
| `NELLY_ACTION_DECIDER=legacy` | Force the old prefix parser |
| `NELLY_SAFETY_MODULE` | Module exposing `check(request)` for the real Safety |
| `NELLY_CHECKPOINT_MODULE`, `NELLY_REQUIRE_STORE=1` | Which store to import; fail instead of using the shim |
| `NELLY_PERSIST=0` | Turn persistence off |
| `NELLY_GRAPH_DB` | LangGraph checkpoint file (separate from the store's `agent.db`) |

## Design rules

- One planner. The Delegator never plans or judges.
- A node's `steps` are hints; the worker decides each real action from the live screen.
- The worker never judges success: Verify does, on a fresh screenshot.
- Replans are capped (2). A plan that does not match the request is re-planned once, then escalated.
- Skipped, mocked or legacy behaviour is always labelled, never hidden.
