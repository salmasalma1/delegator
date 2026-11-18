# Validation Test Matrix

Tests below are acceptance requirements for the Plan Validator. They are not claims that implementation already exists.

| ID | Input/setup | Expected result |
|---|---|---|
| T-SCH-01 | Empty root array | Reject `PV-SCH-001` |
| T-SCH-02 | Root is an object instead of array | Reject schema |
| T-SCH-03 | Missing each required Node field (parameterized) | Reject schema |
| T-SCH-04 | Wrong type for each field (parameterized) | Reject schema |
| T-SCH-05 | Unknown Director field | Reject contract drift |
| T-ID-01 | Duplicate Node IDs | Reject `PV-ID-002` |
| T-ID-02 | Empty Node ID | Reject `PV-ID-001` |
| T-DEP-01 | Self-dependency | Reject `PV-DEP-001` |
| T-DEP-02 | Missing dependency reference | Reject `PV-DEP-002` |
| T-DEP-03 | Duplicate dependency ID | Reject `PV-DEP-003` |
| T-DEP-04 | Two-node cycle | Reject `PV-DEP-004` |
| T-DEP-05 | Multi-node cycle | Reject `PV-DEP-004` |
| T-DEP-06 | Valid DAG with non-topological array order | Accept; scheduler uses graph |
| T-DEP-07 | Single-node simple task | Accept |
| T-ASSIGN-01 | Unknown/disabled Worker | Reject |
| T-ASSIGN-02 | Unsupported resource | Reject |
| T-ASSIGN-03 | App/Worker/resource mismatch | Reject |
| T-ASSIGN-04 | Required adapter unavailable | Block dispatch |
| T-SAFE-01 | Requested capability outside policy | Reject |
| T-SAFE-02 | Director attempts to self-assert approval | Approval remains required |
| T-SAFE-03 | Direct arbitrary host Python/Shell execution request | Reject or route only to approved sandbox policy |
| T-RES-01 | Desktop resource lock already held | Wait/block; do not run concurrent desktop Worker |
| T-RES-02 | Node count exceeds configured maximum | Reject |
| T-GATE-01 | Invalid report with fake Delegator spy | Assert Delegator dispatch count is zero |
| T-GATE-02 | Valid deterministic report | Semantic check runs next |
| T-GATE-03 | Semantic check skipped | Report remains `skipped`; configured policy decides, never convert to pass |
| T-VERIFY-01 | Worker reports success but no evidence | Node is not marked verified |
| T-REPLAN-01 | Replacement plan has validation errors | Old active plan remains active; replacement not activated |
| T-REPLAN-02 | Worker holds stale plan version | Worker cannot take another action |

## Required test properties

- Deterministic validator tests must not call an LLM.
- Registry-dependent tests use explicit fake registries.
- Tests assert both the returned report and side effects (especially that invalid plans never reach Delegator).
- Add property/fuzz tests for malformed IDs, dependency graphs, duplicate keys, and deeply nested/unexpected JSON.
- Benchmark validation latency on realistic and maximum-sized plans.
