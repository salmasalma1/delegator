"""
Checkpoint/audit seam.

Switch backends with one env var:
    NELLY_DB=<path to agent.db>       where rows are written
    NELLY_DB_BACKEND=store|shim       default: store if importable, else shim

The checkpoint store owns the schema. We only call the agreed API:
    init_db / save_checkpoint / load_checkpoint / get_last_checkpoint / list_checkpoints
"""
import importlib
import os

from persistence.redact import redact

_backend = None
_backend_name = None
_warned = set()

# the checkpoint store package first (its real import name), then our spec-compliant shim.
CANDIDATE_MODULES = ("persistence.checkpoint_adapter", "checkpoint_sqlite", "db_helpers",
                     "sqlite_saver", "persistence.db_shim")


def _load():
    """Prefer the store's module if present, otherwise our spec-compliant shim."""
    global _backend, _backend_name
    if _backend is not None:
        return _backend
    forced = os.getenv("NELLY_DB_BACKEND", "").lower()
    order = list(CANDIDATE_MODULES)
    if forced == "shim":
        order = ["persistence.db_shim"]
    elif forced in ("store", "module", "adapter"):
        order = ["persistence.checkpoint_adapter"]

    for name in order:
        try:
            mod = importlib.import_module(name)
            if all(hasattr(mod, fn) for fn in ("init_db", "save_checkpoint", "load_checkpoint")):
                _backend, _backend_name = mod, name
                return mod
        except ImportError:
            continue
    from persistence import db_shim
    _backend, _backend_name = db_shim, "persistence.db_shim"
    return _backend


def backend_name() -> str:
    _load()
    return _backend_name


def db_path() -> str | None:
    """
    Where the store lives. Default ON — persistence must not be opt-in, or a normal run
    silently writes nothing. Disable explicitly with NELLY_PERSIST=0 or NELLY_DB=off.
    """
    if os.getenv("NELLY_PERSIST", "1") in ("0", "false", "off"):
        return None
    p = os.getenv("NELLY_DB", "agent.db")
    return None if p.lower() == "off" else p


def enabled() -> bool:
    return db_path() is not None


def _init(be):
    """The store's init_db may take a path or nothing; both are fine."""
    path = db_path()
    try:
        return be.init_db(path)
    except TypeError:
        return be.init_db()


def record(state: dict) -> str | None:
    """
    Save one checkpoint after a node is verified. No-op when persistence is disabled,
    and NEVER raises into the graph — persistence must not break execution.
    """
    if not enabled():
        return None
    try:
        state = redact(state)          # the store keeps whatever it is given
        be = _load()
        _init(be)
        if _backend_name == "persistence.db_shim":
            return be.save_checkpoint(state, path=db_path())
        # the store's own init_db() decides the file; do not pass a path it may not accept.
        cid = be.save_checkpoint(state)
        _report_once(be)
        return cid
    except Exception as e:                                    # noqa: BLE001
        key = f"{type(e).__name__}:{e}"
        if key not in _warned:
            _warned.add(key)
            print(f"[audit] checkpoint NOT saved ({_backend_name}): {key}")
        return None


def _report_once(be):
    """Tell the user once, in the log, which file is actually receiving rows."""
    if "file" in _warned:
        return
    _warned.add("file")
    try:
        print(f"[checkpoint] rows are being written to: {be.init_db()}")
    except Exception:
        pass


def resume(session_id: str):
    """Load the latest state for a session (kill/restart resume)."""
    if not enabled():
        return None
    try:
        be = _load()
        kw = {"path": db_path()} if _backend_name == "persistence.db_shim" else {}
        return be.get_last_checkpoint(session_id, **kw)
    except Exception:
        return None


def stats() -> dict:
    if not enabled():
        return {}
    from persistence import db_shim
    return db_shim.stats(db_path())