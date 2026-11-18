# NELLY Plan Schema & Validation Rules - Design Specification

**Document status:** Draft v0.1 - for team review  
**Date:** 2026-11-18  
**Applies to:** Director output before Delegator dispatch

## 1. Executive summary

NELLY needs a deterministic validation boundary between plan generation and execution. The Director creates a high-level Node plan. The Plan Validator checks whether that plan is structurally valid, internally consistent, compatible with the registered execution capabilities, and safe to hand to the existing orchestration flow.

The Validator does not execute Nodes, write Worker action sequences, verify on-screen outcomes, or grant runtime permission. Its success means only that the plan passed the configured pre-dispatch checks.

## 2. Existing contract and compatibility boundary

The current normalized Director output is represented as a JSON array of Node objects with these known fields:

| Field | Draft interpretation | Validation responsibility |
|---|---|---|
| `id` | Stable identifier for this Node | Required, non-empty, unique within this plan |
| `node` | Human-readable Node objective/description | Required, non-empty |
| `app` | Target application/context, if applicable | Required key; string or null; resolve when available |
| `worker` | Worker assignment/type | Required, non-empty; must resolve to an enabled Worker |
| `flag` | Existing legacy/compatibility marker | Required key; preserve as opaque scalar until semantics are agreed |
| `steps` | High-level natural-language execution hints | Required non-empty list; never treat as exact UI action sequence |
| `depends_on` | IDs of prerequisite Nodes | Required list; all references must exist; graph must be acyclic |
| `resource` | Required execution resource category | Required, non-empty; resolve against resource registry when available |

The v1 schema intentionally keeps the current array-of-Nodes contract. It does not introduce mandatory top-level `plan_id`, `task_id`, `version`, timestamps, global budgets, or per-Node `acceptance_criteria` fields because those were not confirmed as part of the current normalized output.

### Runtime-only data

The repository also has runtime lifecycle information such as `status` and `history`. These are not Director-authored planning fields. The Validator should run on the normalized plan before runtime state is attached or mutated. Runtime state requires its own contract and transition tests.

## 3. Responsibility boundaries

### Director / Planner

Owns global understanding and high-level decomposition:
- Converts the user's task into one or more Nodes.
- Defines each Node's objective and natural-language hints.
- Defines dependencies and ordering constraints.
- Selects the intended app, Worker type, and resource category.
- Does not author exact clicks, coordinates, keypresses, screenshot-specific targets, or arbitrary executable scripts.

Simple tasks may legitimately produce a single Node. Do not force multi-Node decomposition when one Node is sufficient.

### Plan Validator

A deterministic pre-dispatch gate:
- Validates JSON/schema shape and field types.
- Checks IDs, dependency references, cycles, and graph consistency.
- Resolves Worker, app, and resource references using trusted registries.
- Applies policy-derived capability and safety checks.
- Emits a structured report containing errors and warnings.
- Does not repair or silently rewrite the Director's plan.

### Existing semantic Plan Check

Checks whether the proposed decomposition covers the user's request, avoids unrelated work, and is semantically coherent. It is different from schema/structural validation. A skipped semantic check must be reported as `skipped`, never represented as a pass.

### Delegator

Schedules and dispatches eligible Nodes to Worker runtime(s). It must not receive a plan that failed mandatory deterministic validation. The MVP may remain sequential; the design should preserve explicit dependencies and resource ownership for future parallelism.

### Worker

Owns local, screen-aware execution:
- Observes the current environment.
- Creates the detailed step-by-step action strategy for its assigned Node.
- Executes only through approved tool interfaces.
- Verifies each action from fresh evidence.
- Performs bounded local recovery inside the Node's goal and constraints.
- Reports evidence and outcome to the verification layer.

The Worker may adapt local steps when the UI changes, but may not change the Node goal, dependencies, allowed scope, or permissions. Changes that affect the global plan return to the Director.

## 4. Proposed architecture

```text
User Request
    |
    v
Director / Planner
    |
    v
Normalize current Director output
    |
    v
Deterministic Plan Validator  ---- invalid ----> Reject / repair request / replan
    |
  valid
    v
Existing semantic Plan Check
    |
    v
Delegator
    |
    v
Worker Runtime (local strategy -> action -> observe -> step verification)
    |
    v
Node Verification
    |
    v
Task Finalization
```

The Validator must be a hard gate for deterministic errors. The semantic check remains a separate layer and must preserve its actual result (`passed`, `failed`, `skipped`, or `error`). The policy for what to do when the semantic check is skipped is an explicit team decision; see `DECISIONS.md`.

## 5. Validation layers

### Layer A - Parsing and schema

- Valid JSON only; reject malformed JSON and duplicate object keys.
- Root must be a non-empty array of Nodes.
- Required current fields must exist with supported types.
- Unknown fields are rejected in the Director v1 contract to expose contract drift. Runtime metadata must be stripped before validation or validated with a separate schema.
- Enforce sensible upper bounds to protect the orchestration runtime.

### Layer B - Identity and dependency graph

- Node IDs must be unique and non-empty.
- A Node cannot depend on itself.
- Every dependency must refer to an existing Node ID.
- Duplicate dependency IDs are invalid.
- Dependency graph must be a DAG; reject cycles.
- Do not require the JSON list to be topologically sorted unless the Delegator explicitly depends on list order. The scheduler should use the graph.
- A Node is ready only when all prerequisite Nodes are `verified`, not merely when their tool calls returned successfully.

### Layer C - Assignment and capability resolution

- `worker` must resolve to an enabled Worker type in the trusted Worker registry.
- `resource` must resolve to a supported resource type.
- `app` must be compatible with the selected Worker/resource where applicable.
- Required adapters must be available before dispatch.
- Do not let the LLM invent tool IDs, capabilities, or permission grants. Resolve them from trusted registries.
- Because the current Node contract does not expose `allowed_tools`, this v1 checks Worker/resource compatibility. Per-Node tool allowlists are a future contract extension, not an assumed existing field.

### Layer D - Safety and policy

- Derive risk from the requested operation and trusted tool metadata; do not trust an LLM-supplied risk label.
- Verify that requested capabilities are within task-level and system-level policy.
- Identify actions that require approval, but do not treat plan validation as user approval.
- Never execute arbitrary Director-generated Python/Shell code directly on the user's machine.
- Prefer approved tools with explicit argument schemas. Any future code execution must use a sandbox with limited permissions/resources and an explicit review/approval path.
- Approval must bind to the concrete action and parameters at runtime. A materially changed action may require fresh approval.

### Layer E - Feasibility and resources

- Enforce maximum Node count, hint count, time budget, retry budget, and tool-call budget when these values are provided by trusted runtime configuration.
- Detect missing adapters and unavailable resources before dispatch.
- Enforce exclusive ownership for a Desktop session; do not allow multiple Workers to control the same desktop concurrently.
- In the MVP, sequential execution is acceptable. For future parallel execution, schedule only dependency-ready Nodes and enforce resource locks/conflict checks.

## 6. `steps` semantics: critical distinction

The current field is named `steps`, but the architecture assigns detailed, screen-dependent action planning to the Worker. To avoid a responsibility conflict:

- Director `steps` = high-level hints, intended subgoals, or constraints expressed in natural language.
- Worker execution strategy = concrete actions chosen after observing the current screen/state.
- Worker action trace = what was actually executed, with timestamps and evidence.

The Validator must reject or flag content that attempts to turn Director hints into arbitrary executable scripts or hard-coded screen coordinates. Renaming `steps` to `execution_hints` could improve clarity in a future version, but must be coordinated as a breaking contract change.

## 7. Validation result contract

The report schema is defined in `schemas/plan-validation-report-v1.schema.json`.

Recommended decisions:
- `approved_for_delegation`: all mandatory deterministic checks passed. This does not mean the task is complete, a Node is verified, or a sensitive action has user approval.
- `rejected`: one or more blocking validation errors exist.
- `needs_repair`: a repair/replanning cycle is explicitly supported and the current plan must not be dispatched as-is.

Errors block delegation. Warnings do not block by themselves unless a configured policy elevates them. Approval requirements are notices for runtime authorization; they are not approvals.

## 8. Status and verification semantics

Keep execution mode, step status, verification status, and Node lifecycle separate.

Recommended Worker step model:
- `execution_mode`: `live` or `dry_run`.
- `status`: `pending`, `running`, `succeeded`, `failed`, `blocked`, `awaiting_approval`, `cancelled`.
- `verification_status`: `not_checked`, `passed`, `failed`, `uncertain`.

`dry_run` is a mode, not a success state. A dry-run step can complete its simulation but must not be represented as a real-world verified outcome.

Node lifecycle statuses should remain aligned with the existing repository contract. The team's proposed terms include `pending`, `running`, `awaiting_approval`, `needs_input`, `verified`, `failed`, and `superseded`; `blocked` and `cancelled` may be added only after transition behavior is specified. Do not merge Node lifecycle statuses into the Director Plan Schema.

## 9. Replanning and stale-plan protection

The current v1 input schema does not require a version envelope. For orchestration hardening, add plan versioning in a compatible later change:
- Every accepted plan revision gets a monotonically increasing version.
- A replaced Node is marked `superseded`; its history remains auditable.
- New plans pass the full Validator before activation.
- Plan activation is atomic. Workers holding a stale plan version must stop before taking another action.
- Reuse old outputs only when they still satisfy the new Node's goal and evidence requirements; otherwise invalidate them explicitly.

## 10. Rollout plan

1. Confirm `DECISIONS.md` and compare the schema with real normalized Planner output.
2. Implement parsing and schema validation only; test current valid fixtures.
3. Implement deterministic ID/dependency/DAG rules.
4. Add registry-backed Worker/app/resource checks.
5. Add safety preflight and resource feasibility checks.
6. Integrate a hard gate before Delegator dispatch.
7. Add observability, plan-version protection, recovery, fuzz tests, and latency benchmarks.

Do not combine all phases into one large change. Each phase should pass its focused tests before the next layer is added.

## 11. Non-goals

- Replacing the Director/Planner.
- Moving detailed execution strategy from Worker to Director.
- Replacing the existing semantic Plan Check.
- Executing generated Python/Shell code on the user's machine.
- Granting user approval or bypassing the Safety layer.
- Implementing parallel execution in the first Validator milestone.
