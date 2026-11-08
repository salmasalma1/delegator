"""
Boundary validation — every VisionResult crossing the vision boundary must pass the shared schema.
Failure here is a CONTRACT failure, not a bug in the Orchestrator.
"""
import json
import os
from typing import Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.getenv(
    "NELLY_VISION_SCHEMA",
    os.path.join(os.path.dirname(_HERE), "schemas", "vision", "02_VisionResult.schema.json"),
)


def load_schema(path: str = SCHEMA_PATH) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def validate_vision_result(raw: dict, path: str = SCHEMA_PATH) -> Tuple[bool, list]:
    """Returns (ok, errors). Missing jsonschema/schema => soft pass with a note."""
    schema = load_schema(path)
    if schema is None:
        return True, [f"schema_not_found:{path}"]
    try:
        import jsonschema
    except ImportError:
        missing = [k for k in schema.get("required", []) if k not in raw]
        return (not missing), [f"jsonschema_missing; missing_required={missing}"]
    v = jsonschema.Draft202012Validator(schema)
    errs = [f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in v.iter_errors(raw)]
    return (not errs), errs


def extra_keys(raw: dict, path: str = SCHEMA_PATH) -> list:
    """Keys vision module sends that the contract does not allow (additionalProperties=false)."""
    schema = load_schema(path)
    if schema is None:
        return []
    allowed = set(schema.get("properties", {}))
    return sorted(k for k in raw if k not in allowed)
