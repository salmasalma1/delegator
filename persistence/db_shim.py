"""
Fallback checkpoint store, built to the agreed specification.

This is a reference implementation so the orchestrator can keep running when the primary
checkpoint store package is not importable. When it is present, put it on the path and set
NELLY_DB_BACKEND=store — `persistence.audit` prefers it and falls back to this module.

API (identical to the agreed one):
    init_db(path="agent.db")
    save_checkpoint(state) -> checkpoint_id
    load_checkpoint(checkpoint_id) -> AgentState
    get_last_checkpoint(session_id) -> AgentState | None
    list_checkpoints(session_id) -> list[checkpoint_id]
"""
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone

SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
DEFAULT_PATH = os.getenv("NELLY_DB", "agent.db")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_db(path: str = DEFAULT_PATH) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with sqlite3.connect(path) as con:
        con.executescript(open(SCHEMA, encoding="utf-8").read())
    return path


def _connect(path: str):
    return sqlite3.connect(path)


def save_checkpoint(state: dict, path: str = DEFAULT_PATH) -> str:
    """Persist one AgentState snapshot + one row per executed step."""
    init_db(path)
    cid = state.get("saved_checkpoint_id") or str(uuid.uuid4())
    steps = (state.get("last_sub_result") or {}).get("steps_done") or []

    with _connect(path) as con:
        cur = con.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO checkpoints "
            "(checkpoint_id, session_id, task_id, step_number, agent_state_json, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (cid, state.get("session_id"), state.get("task_id"),
             int(state.get("current_node_idx") or 0),
             json.dumps(state, ensure_ascii=False, default=str), _now()),
        )
        for i, s in enumerate(steps):
            tgt = s.get("target") or {}
            cur.execute(
                "INSERT INTO steps (checkpoint_id, step_id, description, app, status, "
                "bbox_norm, confidence, source) VALUES (?,?,?,?,?,?,?,?)",
                (cid, i, s.get("step"), (state.get("last_sub_result") or {}).get("app"),
                 s.get("status"), json.dumps(tgt.get("bbox_norm")) if tgt.get("bbox_norm") else None,
                 tgt.get("confidence"), (state.get("grounding") or {}).get("vision_source")),
            )
        # audit_log: safety decision + latency of the verified step, when present.
        safety = state.get("last_safety_decision")
        if safety or state.get("latency_ms") is not None:
            cur.execute(
                "INSERT INTO audit_log (checkpoint_id, safety_decision, latency_ms, created_at) "
                "VALUES (?,?,?,?)",
                (cid, json.dumps(safety) if isinstance(safety, dict) else safety,
                 state.get("latency_ms"), _now()),
            )
        con.commit()
    return cid


def load_checkpoint(checkpoint_id: str, path: str = DEFAULT_PATH) -> dict:
    init_db(path)
    with _connect(path) as con:
        row = con.execute(
            "SELECT agent_state_json FROM checkpoints WHERE checkpoint_id = ?", (checkpoint_id,)
        ).fetchone()
    if not row:
        raise KeyError(f"checkpoint not found: {checkpoint_id}")
    return json.loads(row[0])


def get_last_checkpoint(session_id: str, path: str = DEFAULT_PATH):
    init_db(path)
    with _connect(path) as con:
        row = con.execute(
            "SELECT checkpoint_id FROM checkpoints WHERE session_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1", (session_id,)
        ).fetchone()
    return load_checkpoint(row[0], path) if row else None


def list_checkpoints(session_id: str, path: str = DEFAULT_PATH) -> list:
    init_db(path)
    with _connect(path) as con:
        return [r[0] for r in con.execute(
            "SELECT checkpoint_id FROM checkpoints WHERE session_id = ? "
            "ORDER BY created_at DESC, rowid DESC", (session_id,)
        )]


def stats(path: str = DEFAULT_PATH) -> dict:
    """Row counts — used by tests and by the 'is it actually writing?' check."""
    init_db(path)
    with _connect(path) as con:
        return {
            "checkpoints": con.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0],
            "steps": con.execute("SELECT COUNT(*) FROM steps").fetchone()[0],
            "audit_log": con.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0],
        }