"""
"""
import inspect
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

# Bassant's repo ships db_helpers.py at its root. NELLY_CHECKPOINT_MODULE overrides.
STORE_MODULES = ([os.environ["NELLY_CHECKPOINT_MODULE"]] if os.getenv("NELLY_CHECKPOINT_MODULE")
                 else ["db_helpers", "checkpointSaver.db_helpers"])
STORE_MODULE = STORE_MODULES[0]

_warned = set()


def _warn(msg: str):
    if msg not in _warned:
        _warned.add(msg)
        print(f"[checkpoint] {msg}")


# --------------------------------------------------------------------------
# backend resolution
# --------------------------------------------------------------------------
def _store():
    import importlib
    errs = []
    for name in STORE_MODULES:
        try:
            return importlib.import_module(name)
        except Exception as e:                                    # noqa: BLE001
            errs.append(f"{name}: {type(e).__name__}: {e}")
    msg = "checkpoint store not importable -> using the local SHIM, not the team DB. " + " | ".join(errs)
    if os.getenv("NELLY_REQUIRE_STORE") == "1":                   # no silent fallback in real runs
        raise RuntimeError(msg)
    _warn(msg)
    return None


def _shim():
    from persistence import db_shim
    return db_shim


def backend_name() -> str:
    return "store" if _store() is not None else "shim"


# --------------------------------------------------------------------------
# the two tables the store's writer leaves empty
# --------------------------------------------------------------------------
def _bbox_json(bbox_norm) -> Optional[str]:
    if not bbox_norm or len(bbox_norm) != 4:
        return None
    return json.dumps([round(float(v), 4) for v in bbox_norm])   # [x, y, w, h] everywhere


def _fill_missing_rows(db_path: str, checkpoint_id: str, state: dict) -> dict:
    """
    Append `steps` and `audit_log` rows only if the store did not write them.
    Returns what was added, for logging/tests.
    """
    added = {"steps": 0, "audit_log": 0}
    sub = state.get("last_sub_result") or {}
    steps = sub.get("steps_done") or []
    safety = state.get("last_safety_decision")
    latency = state.get("latency_ms")
    if not steps and safety is None and latency is None:
        return added

    src = (state.get("grounding") or {}).get("vision_source")
    try:
        with sqlite3.connect(db_path) as con:
            have = con.execute("SELECT COUNT(*) FROM steps WHERE checkpoint_id = ?",
                               (checkpoint_id,)).fetchone()[0]
            if not have:
                for i, st in enumerate(steps):
                    tgt = st.get("target") or {}
                    con.execute(
                        "INSERT INTO steps (checkpoint_id, step_id, description, app, status, "
                        "bbox_norm, confidence, source) VALUES (?,?,?,?,?,?,?,?)",
                        (checkpoint_id, i, st.get("step"), sub.get("app"), st.get("status"),
                         _bbox_json(tgt.get("bbox_norm")), tgt.get("confidence"), src),
                    )
                    added["steps"] += 1
            have = con.execute("SELECT COUNT(*) FROM audit_log WHERE checkpoint_id = ?",
                               (checkpoint_id,)).fetchone()[0]
            if not have and (safety is not None or latency is not None):
                con.execute(
                    "INSERT INTO audit_log (checkpoint_id, safety_decision, latency_ms, created_at) "
                    "VALUES (?,?,?,?)",
                    (checkpoint_id,
                     json.dumps(safety) if isinstance(safety, dict) else safety,
                     latency,
                     datetime.now(timezone.utc).isoformat(timespec="seconds")),
                )
                added["audit_log"] = 1
            con.commit()
    except sqlite3.Error as e:                     # never break the run
        _warn(f"could not complete steps/audit_log rows: {e}")
    return added


def _write_actions(db_path: str, checkpoint_id: str, state: dict) -> int:
    """
    Action-level rows. The `actions` table is new (requested from Team 3); until it exists in
    the store this does nothing, and the same rows still travel in the state blob.
    Each action_id is written once, however many checkpoints carry it.
    """
    rows = state.get("actions") or []
    if not rows:
        return 0
    n = 0
    try:
        with sqlite3.connect(db_path) as con:
            cols = [r[1] for r in con.execute("PRAGMA table_info(actions)")]
            if not cols:
                return 0
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            for row in rows:
                if "action_id" in cols and con.execute(
                        "SELECT 1 FROM actions WHERE action_id = ?", (row.get("action_id"),)).fetchone():
                    continue
                data = {**row, "checkpoint_id": checkpoint_id, "created_at": now}
                use = {k: v for k, v in data.items() if k in cols and k != "id"}
                con.execute(f"INSERT INTO actions ({', '.join(use)}) VALUES ({', '.join('?' * len(use))})",
                            [json.dumps(v) if isinstance(v, (dict, list)) else v for v in use.values()])
                n += 1
            con.commit()
    except sqlite3.Error as e:                     # never break the run
        _warn(f"could not write actions rows: {e}")
    return n


# --------------------------------------------------------------------------
# public API (agreed 5 functions)
# --------------------------------------------------------------------------
def init_db(path: Optional[str] = None) -> str:
    store = _store()
    if store is not None:
        if os.getenv("NELLY_STORE_PATH_CAPABLE") == "1" and path:
            return store.init_db(path)
        # The unpatched store resolves the file itself (BASE_DIR/agent.db). Respect that —
        # the caller must not assume where the file is.
        return store.init_db()
    return _shim().init_db(path or os.getenv("NELLY_DB", "agent.db"))


def save_checkpoint(state: dict, path: Optional[str] = None) -> str:
    store = _store()
    if store is None:
        return _shim().save_checkpoint(state, path=path or os.getenv("NELLY_DB", "agent.db"))

    try:
        cid = store.save_checkpoint(state, path) if path and _path_capable(store) else store.save_checkpoint(state)
    except TypeError:                                   # unpatched: no `path` parameter
        cid = store.save_checkpoint(state)

    _fill_missing_rows(store.init_db(), cid, state)     # completes steps + audit_log
    _write_actions(store.init_db(), cid, state)         # action level (no-op until the table exists)
    return cid


def _path_capable(mod) -> bool:
    try:
        return "path" in inspect.signature(mod.save_checkpoint).parameters
    except (TypeError, ValueError):
        return False


def load_checkpoint(checkpoint_id: str, path: Optional[str] = None) -> dict:
    store = _store()
    if store is None:
        return _shim().load_checkpoint(checkpoint_id, path=path or os.getenv("NELLY_DB", "agent.db"))
    try:
        return store.load_checkpoint(checkpoint_id, path) if path else store.load_checkpoint(checkpoint_id)
    except TypeError:
        try:
            return store.load_checkpoint(checkpoint_id)
        except ValueError as e:
            raise KeyError(str(e)) from e
    except ValueError as e:                       # legacy: unpatched module
        raise KeyError(str(e)) from e


def get_last_checkpoint(session_id: str, path: Optional[str] = None):
    store = _store()
    if store is None:
        return _shim().get_last_checkpoint(session_id, path=path or os.getenv("NELLY_DB", "agent.db"))
    try:
        return store.get_last_checkpoint(session_id, path) if path else store.get_last_checkpoint(session_id)
    except TypeError:
        return store.get_last_checkpoint(session_id)


def list_checkpoints(session_id: str, path: Optional[str] = None) -> list:
    store = _store()
    if store is None:
        return _shim().list_checkpoints(session_id, path=path or os.getenv("NELLY_DB", "agent.db"))
    try:
        return store.list_checkpoints(session_id, path) if path else store.list_checkpoints(session_id)
    except TypeError:
        return store.list_checkpoints(session_id)


def db_file(path: Optional[str] = None) -> str:
    """Where rows are actually landing (the store's BASE_DIR/agent.db, or ours)."""
    return init_db(path) if path else init_db()