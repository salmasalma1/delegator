"""
Safety port: the ONLY door between a worker and the machine.

The worker builds a frozen request, calls `get_safety().check(request)` and acts only on
decision == "approved". Team 3's real Dispatcher plugs in here without touching the worker:

    NELLY_SAFETY_MODULE=<importable.module>   must expose  check(request: dict) -> dict

Decision shape (the same keys the audit log already stores):
    {"decision": "approved" | "denied" | "needs_approval",
     "action_id": str, "reason": str, "mock": bool}

Until Team 3 delivers, MockSafety approves everything EXCEPT a small always-ask list, and every
decision it makes carries mock=True so nobody mistakes it for the real thing.
"""
import importlib
import os

# Actions that must never be auto-approved, even by the mock (Hermes "always-ask" idea).
ALWAYS_ASK = ("delete", "send", "submit", "pay", "purchase", "uninstall", "format")

_warned = [False]


class MockSafety:
    name = "mock"

    def check(self, request: dict) -> dict:
        if not _warned[0]:
            _warned[0] = True
            print("[safety] MOCK safety in use: approving everything except the always-ask list.")
        action = (request.get("action_type") or "").lower()
        text = str((request.get("parameters") or {}).get("text", "")).lower()
        if any(w in action for w in ALWAYS_ASK):
            return {"decision": "needs_approval", "action_id": request.get("action_id"),
                    "reason": f"always-ask action: {action}", "mock": True}
        return {"decision": "approved", "action_id": request.get("action_id"),
                "reason": "mock: low risk", "mock": True}


class _ModuleSafety:
    def __init__(self, mod):
        self.mod, self.name = mod, getattr(mod, "__name__", "external")

    def check(self, request: dict) -> dict:
        d = self.mod.check(request)
        d.setdefault("action_id", request.get("action_id"))
        d.setdefault("mock", False)
        return d


def get_safety():
    name = os.getenv("NELLY_SAFETY_MODULE", "")
    if name:
        try:
            mod = importlib.import_module(name)
            if hasattr(mod, "check"):
                return _ModuleSafety(mod)
            print(f"[safety] {name} has no check(request) -> using mock")
        except Exception as e:                                # noqa: BLE001
            print(f"[safety] cannot import {name}: {e} -> using mock")
    return MockSafety()
