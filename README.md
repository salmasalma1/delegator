# Delegator — NELLY Orchestrator with Delegation

**Structure (Hamlet mindset, LangGraph implementation)**

- Gateway: `gateway/gateway.py` — Voice (Whisper) or Text → normalized TaskRequest
- Brain: `brain.py` — StrategyProvider (RuleBased now, Qwen qwen3-vl-plus when NELLY_BRAIN=qwen)
- Main Graph: `graph/builder.py` — Director → Delegate (loop) → Verify (with checkpoint)
- Generic Sub: `graph/subgraphs/app_subgraph.py` — reusable for any app (Notepad, Spotify, WhatsApp)

**Run**
```bash
pip install langgraph
python run.py "Create folder NELLY in Explorer and type Hi in Notepad"
NELLY_BRAIN=qwen DASHSCOPE_API_KEY=sk-... python run.py "your task"
```

**Why delegation here**
- Director dynamically splits any task into Nodes with flags (not hardcoded spotify/whatsapp)
- Main delegates to generic app_graph, collects results via AgentState
- Each sub is isolated — failure in Spotify sub does not crash WhatsApp sub (verify per sub)
