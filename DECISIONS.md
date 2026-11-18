# Open Decisions - Team Approval Required

These are deliberately unresolved. The Validator must not invent answers.

| ID | Decision | Recommended default | Why it matters |
|---|---|---|---|
| D-01 | Exact JSON type and format of `id` | Keep non-empty string in v1; move to UUID only with migration | Avoid rejecting existing IDs |
| D-02 | Meaning and allowed values of `flag` | Treat as opaque scalar; document exact semantics before enforcing | It must not be mistaken for risk/approval |
| D-03 | Exact shape of `steps` items | Confirm whether strings, objects, or both are emitted | Schema must match real Planner normalization |
| D-04 | Step count mismatch: Planner prompt says 1-4 while implementation allows up to 6 | Align prompt and code; v1 schema temporarily allows max 6 | Prevent silent prompt/runtime drift |
| D-05 | `app` nullable/required semantics | Keep required key with string-or-null until registry contract is confirmed | Some Nodes may not target a GUI app |
| D-06 | Resource enum values | Derive from current registry; do not invent enum values | Resource strings must match runtime adapters |
| D-07 | Worker registry identity | Confirm if `worker` is a type, instance name, or model/agent alias | Determines resolution and availability checks |
| D-08 | Semantic Plan Check `skipped` policy | Never call it passed; block high-risk plans; allow low-risk only under explicit policy | Current fail-open behavior must be visible |
| D-09 | Node acceptance criteria | Add explicit field in a versioned schema when Director supports it | Enables deterministic Node verification |
| D-10 | Plan metadata/versioning | Add an envelope in v2 or store it in orchestration metadata | Needed for atomic replanning and stale-worker protection |
| D-11 | Allowed tools and action risk | Resolve via trusted registries in v1; consider explicit scoped references later | Avoid LLM-created permissions |
| D-12 | Runtime status enum | Reconcile actual code lifecycle with team statuses before making an enum | Avoid breaking persistence/state transitions |

## Approval record

For each decision, record: selected option, owner, date, migration impact, and tests required. Once approved, update the JSON Schema, rule catalogue, and tests in the same change.
