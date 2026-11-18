# Plan Validator Rule Catalogue

**Status:** Draft v0.1. Blocking rules should be deterministic wherever possible.

| Rule ID | Category | Rule | Severity | Expected behavior |
|---|---|---|---|---|
| PV-SCH-001 | Schema | Root input must be a non-empty JSON array | Error | Reject otherwise |
| PV-SCH-002 | Schema | Every Node must contain the current required fields | Error | Reject missing fields |
| PV-SCH-003 | Schema | Field types and configured size limits must be valid | Error | Reject invalid types/bounds |
| PV-SCH-004 | Schema | Unknown Director fields are not accepted in v1 | Error | Reject and update contract intentionally |
| PV-ID-001 | Identity | Node IDs must be non-empty | Error | Reject |
| PV-ID-002 | Identity | Node IDs must be unique within the plan | Error | Reject duplicates |
| PV-DEP-001 | Dependency | A Node cannot depend on itself | Error | Reject |
| PV-DEP-002 | Dependency | Every dependency ID must exist in the same plan | Error | Reject missing reference |
| PV-DEP-003 | Dependency | Dependency IDs must not be duplicated | Error | Reject duplicates |
| PV-DEP-004 | Dependency | Dependency graph must be acyclic | Error | Reject cycles |
| PV-DEP-005 | Runtime | A Node is dispatch-ready only after all dependencies are verified | Runtime gate | Keep Node waiting otherwise |
| PV-ASSIGN-001 | Assignment | Worker ID/type must resolve in trusted Worker registry | Error | Reject unknown/disabled Worker |
| PV-ASSIGN-002 | Assignment | Resource must resolve in trusted resource registry | Error | Reject unknown resource |
| PV-ASSIGN-003 | Assignment | App, Worker, and resource must be mutually compatible | Error | Reject incompatible assignment |
| PV-ASSIGN-004 | Assignment | Required adapter must be available | Error or configured warning | Do not dispatch without required adapter |
| PV-SAFE-001 | Safety | Capabilities must be within system/task policy | Error | Reject out-of-scope plan |
| PV-SAFE-002 | Safety | Risk is derived from tool/action policy, not Director assertion | Policy | Ignore untrusted risk claims |
| PV-SAFE-003 | Safety | Plan validation cannot grant approval | Policy | Require runtime approval where policy says so |
| PV-SAFE-004 | Safety | No arbitrary generated Python/Shell execution on the host | Error | Reject direct host-code execution requests |
| PV-SAFE-005 | Safety | Approval is bound to exact action and parameters | Runtime gate | Re-approve materially changed action |
| PV-RES-001 | Resource | One Worker owns a Desktop session at a time | Runtime gate | Acquire exclusive lock |
| PV-RES-002 | Resource | Node/time/retry/tool budgets must be within configured limits | Error | Reject over-budget plan |
| PV-RES-003 | Resource | MVP scheduler dispatches one Node at a time unless parallel policy is explicitly enabled | Runtime policy | Keep current sequential behavior |
| PV-GOAL-001 | Semantic | Node decomposition should cover the user request | Semantic check | Preserve result from existing Plan Check |
| PV-GOAL-002 | Semantic | No unrelated or unnecessary Nodes | Semantic check | Preserve result from existing Plan Check |
| PV-GOAL-003 | Semantic | Each Node has a clear expected outcome/evidence path | Warning in v1; future error | Require explicit field in future schema |
| PV-REPORT-001 | Reporting | Every error/warning has stable code, category, message, and optional node/path | Contract | Return structured report |
| PV-REPORT-002 | Reporting | `skipped` semantic check is never represented as `passed` | Error in report handling | Preserve actual semantic status |

## Severity semantics

- **Error:** blocking; the plan must not be sent to Delegator.
- **Warning:** recorded; can be escalated by policy.
- **Runtime gate:** checked again when the Node is about to execute because availability/approval/locks can change.
- **Semantic check:** distinct from deterministic validation and must not silently override or conceal schema/safety errors.

## Important v1 limitations

The current Node contract does not include explicit `allowed_tools`, `risk_level`, `acceptance_criteria`, `timeout_seconds`, or `max_attempts`. Rules that require these values must use trusted runtime registries/configuration until the team approves a versioned contract extension. Do not make the Director emit these fields ad hoc.
