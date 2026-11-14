"""
Safety port: the ONLY door between a worker and the machine.

The worker builds one frozen request, calls `get_safety().check(request)` and acts only on
decision == "approved". Team 3's real Dispatcher plugs in here without touching the worker:

    NELLY_SAFETY_MODULE=<importable.module>   must expose  check(request: dict) -> dict

Vocabulary = Team 3's frozen SafetyDecision schema (schemas/safety/02_SafetyDecision.schema.json):

    approved | rejected | needs_user_approval | blocked

Older spellings (denied, needs_approval, allow, ask, refuse...) from other notes are mapped to
these and the decision says so (`normalized_from`). An UNKNOWN value, or a backend that raises,
fails CLOSED (blocked), never open.

Patterns taken from Hermes Agent's approval layer (see specs notes):
  * approval scopes (once | session), collapsed to "once" for always-ask targets
  * the approver is bound to one run, not passed through every layer; no approver = the run
    pauses and the reason says so ("a silent default that allows is worse than a loud absence")
  * the human approves a FROZEN proposal; its hash is stored and re-checked before acting
  * a short always-ask list that no scope or mode can bypass
  * the resolved policy mode is written into every decision

Until Team 3 delivers, MockSafety approves low-risk actions and asks for the always-ask list.
Every decision it makes carries mock=True so nobody mistakes it for the real thing.
"""
import hashlib
import importlib
import json
import os
import uuid
from contextlib import contextmanager

APPROVED, REJECTED = "approved", "rejected"
NEEDS_USER_APPROVAL, BLOCKED = "needs_user_approval", "blocked"
DECISIONS = (APPROVED, REJECTED, NEEDS_USER_APPROVAL, BLOCKED)

_LEGACY = {"allow": APPROVED, "approve": APPROVED,
           "ask": NEEDS_USER_APPROVAL, "needs_approval": NEEDS_USER_APPROVAL,
           "deny": REJECTED, "denied": REJECTED, "refuse": REJECTED, "refused": REJECTED}

# Actions that must never be auto-approved, whatever the mode or scope.
ALWAYS_ASK = ("delete", "send", "submit", "pay", "purchase", "uninstall", "format")

# Applications the schema allows; anything else always asks. Override: NELLY_APP_ALLOWLIST=a,b,c
SCHEMA_APPS = ("Chrome", "Edge", "Notepad", "File Explorer", "Basic System Dialog")

# One table = the policy modes (resolved once, written into every decision).
MODES = {
    "standard": "ask only for the always-ask list",
    "strict": "also ask for anything above low risk (demos)",
}

# Static risk table. The WORKER does not judge risk; the real Safety may override this.
_RISK = {"click": ("low", True), "press": ("low", True), "focus_window": ("low", True),
         "type": ("medium", True), "create_folder": ("medium", True), "save_file": ("medium", False)}

_warned = set()


def _warn_once(msg: str):
    if msg not in _warned:
        _warned.add(msg)
        print(msg)


# ---------------------------------------------------------------- helpers
def classify(action_type: str) -> tuple:
    """(risk_level, reversible). Unknown action types are high risk and irreversible."""
    return _RISK.get((action_type or "").lower(), ("high", False))


def freeze(request: dict) -> str:
    """Canonical text of a request. What the human approves is exactly this."""
    return json.dumps(request, sort_keys=True, default=str, ensure_ascii=False)


def proposal_hash(request: dict) -> str:
    return hashlib.sha256(freeze(request).encode("utf-8")).hexdigest()


def policy_mode() -> str:
    m = os.getenv("NELLY_POLICY_MODE", "standard").lower()
    if m not in MODES:
        _warn_once(f"[safety] unknown NELLY_POLICY_MODE={m!r} -> using 'standard'")
        return "standard"
    return m


def _allowed_apps() -> set:
    raw = os.getenv("NELLY_APP_ALLOWLIST")
    names = [a.strip() for a in raw.split(",")] if raw else list(SCHEMA_APPS)
    return {n.lower() for n in names if n}


def normalize_decision(d) -> dict:
    """Force a backend answer into the frozen vocabulary; fail closed on anything else."""
    if not isinstance(d, dict):
        return {"decision": BLOCKED, "reason": f"safety returned {type(d).__name__}, not a decision"}
    raw = str(d.get("decision", "")).strip().lower()
    if raw in DECISIONS:
        return d
    if raw in _LEGACY:
        return {**d, "decision": _LEGACY[raw], "normalized_from": raw}
    return {**d, "decision": BLOCKED, "normalized_from": raw or None,
            "reason": f"unknown safety decision {raw!r}; failing closed"}


# ---------------------------------------------------------------- backends
class MockSafety:
    name = "mock"

    def check(self, request: dict) -> dict:
        _warn_once("[safety] MOCK safety in use: low-risk actions approved, always-ask list asks.")
        action = (request.get("action_type") or "").lower()
        risk, _ = classify(action)
        risk = request.get("risk_level") or risk
        mode = policy_mode()
        base = {"action_id": request.get("action_id"), "task_id": request.get("task_id"),
                "risk_level": risk, "policy_id": "mock-policy", "policy_mode": mode, "mock": True}
        app = (request.get("application") or "").lower()
        if any(w in action for w in ALWAYS_ASK):
            return {**base, "decision": NEEDS_USER_APPROVAL, "always_ask": True,
                    "reason": f"always-ask action: {action}"}
        if app and app not in _allowed_apps():
            return {**base, "decision": NEEDS_USER_APPROVAL, "always_ask": True,
                    "reason": f"application outside the allowlist: {request.get('application')}"}
        if mode == "strict" and risk != "low":
            return {**base, "decision": NEEDS_USER_APPROVAL, "always_ask": False,
                    "reason": f"strict mode: {risk} risk action {action}"}
        return {**base, "decision": APPROVED, "reason": "mock: allowed by policy"}


class _ModuleSafety:
    """Team 3's module. A crash or a nonsense answer is a BLOCK, never an approval."""

    def __init__(self, mod):
        self.mod, self.name = mod, getattr(mod, "__name__", "external")

    def check(self, request: dict) -> dict:
        try:
            d = self.mod.check(request)
        except Exception as e:                                     # noqa: BLE001
            return {"decision": BLOCKED, "action_id": request.get("action_id"), "mock": False,
                    "reason": f"safety module raised {type(e).__name__}: {e}"}
        d = normalize_decision(d)
        d.setdefault("action_id", request.get("action_id"))
        d.setdefault("mock", False)
        return d


# ---------------------------------------------------------------- approver (bound to one run)
_approver = [None]


@contextmanager
def bind_approver(fn):
    """
    Bind the thing that can ask a human, for the duration of ONE run.
        fn(proposal: dict) -> {"granted": bool, "scope": "once" | "session"}
    proposal = {"request": <frozen request>, "hash", "reason", "risk_level", "scopes": [...]}
    Code that never binds one (tests, headless, scheduled runs) has NO approver: the run pauses.
    """
    prev, _approver[0] = _approver[0], fn
    try:
        yield
    finally:
        _approver[0] = prev


def console_approver(proposal: dict) -> dict:
    """The simplest approver: ask on the terminal. Reading the answer never defaults to yes."""
    req = proposal["request"]
    print("\n[approval needed]")
    print(f"  action : {req.get('action_type')}  on {req.get('application')}  target={req.get('target_element_id')}")
    print(f"  params : {req.get('parameters')}")
    print(f"  why    : {proposal.get('reason')}   (risk: {proposal.get('risk_level')}, hash {proposal['hash'][:10]})")
    scopes = proposal.get("scopes") or ["once"]
    opts = "[y] allow once" + ("  [s] allow for this session" if "session" in scopes else "") + "  [n] deny"
    try:
        ans = input(f"  {opts} > ").strip().lower()
    except EOFError:
        return {"granted": False, "scope": "once"}
    if ans == "y":
        return {"granted": True, "scope": "once"}
    if ans == "s" and "session" in scopes:
        return {"granted": True, "scope": "session"}
    return {"granted": False, "scope": "once"}


# ---------------------------------------------------------------- the gate
class Gate:
    """Wraps any backend: freezes the proposal, applies scopes, asks the bound approver."""

    def __init__(self, backend):
        self.backend = backend
        self.name = getattr(backend, "name", "backend")
        self.session_grants = {}                    # (action_type, application) -> approval_id

    @staticmethod
    def _key(req: dict) -> tuple:
        return ((req.get("action_type") or "").lower(), (req.get("application") or "").lower())

    def check(self, request: dict) -> dict:
        h = proposal_hash(request)
        d = dict(normalize_decision(self.backend.check(request)))
        d["proposal_hash"] = h
        d.setdefault("policy_mode", policy_mode())
        if d["decision"] != NEEDS_USER_APPROVAL:
            return d

        always = bool(d.get("always_ask"))
        key = self._key(request)
        if not always and key in self.session_grants:
            return {**d, "decision": APPROVED, "approval_scope": "session",
                    "approval_id": self.session_grants[key],
                    "reason": f"{d.get('reason')} (allowed earlier for this session)"}

        approver = _approver[0]
        if approver is None:
            return {**d, "approver": "none",
                    "reason": f"{d.get('reason')} (no approver bound: the run pauses)"}

        scopes = ["once"] if always else ["once", "session"]          # never offer a scope we would discard
        answer = approver({"request": json.loads(freeze(request)), "hash": h, "reason": d.get("reason"),
                           "risk_level": d.get("risk_level"), "scopes": scopes}) or {}
        approval_id = str(uuid.uuid4())
        if not answer.get("granted"):
            return {**d, "decision": REJECTED, "approval_id": approval_id, "approval_scope": "once",
                    "reason": f"{d.get('reason')} (user said no)"}
        scope = answer.get("scope") if answer.get("scope") in scopes else "once"
        if scope == "session":
            self.session_grants[key] = approval_id
        return {**d, "decision": APPROVED, "approval_id": approval_id, "approval_scope": scope,
                "reason": f"{d.get('reason')} (user approved, {scope})"}


_gate = [None]


def reset():
    """Forget session grants and the cached gate (tests, or a new session)."""
    _gate[0] = None


def get_safety() -> Gate:
    if _gate[0] is not None:
        return _gate[0]
    backend = None
    name = os.getenv("NELLY_SAFETY_MODULE", "")
    if name:
        try:
            mod = importlib.import_module(name)
            if hasattr(mod, "check"):
                backend = _ModuleSafety(mod)
            else:
                print(f"[safety] {name} has no check(request) -> using mock")
        except Exception as e:                                    # noqa: BLE001
            print(f"[safety] cannot import {name}: {e} -> using mock")
    _gate[0] = Gate(backend or MockSafety())
    return _gate[0]
