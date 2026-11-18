# NELLY Plan Validator - Team Handoff Pack

**Status:** Draft v0.1 for team review  
**Date:** 2026-11-18  
**Scope:** Director plan validation before Delegator execution

This pack defines a compatibility-first proposal for a deterministic Plan Validator. It is designed around the current normalized Director Node shape observed in the Delegator repository. It is **not yet an implementation** and must be approved by the team before becoming a runtime contract.

## Files

- `docs/PLAN_VALIDATOR_DESIGN_SPEC.md` - design, architecture, responsibilities, and decisions.
- `docs/VALIDATION_RULES.md` - rule catalogue with stable rule IDs.
- `docs/INTEGRATION_CONTRACT.md` - proposed runtime integration and fail-safe behavior.
- `schemas/director-plan-v1.schema.json` - JSON Schema for current normalized Director output.
- `schemas/plan-validation-report-v1.schema.json` - JSON Schema for validation output.
- `examples/valid-director-plan.json` - illustrative valid plan (placeholder app/worker values; verify against the real registry).
- `tests/VALIDATION_TEST_MATRIX.md` - test scenarios required before enabling the gate.
- `DECISIONS.md` - unresolved team decisions; do not silently assume these are settled.

## Important compatibility notes

1. The v1 input is a **JSON array of Nodes**, matching the current normalized Director output described during repository review. It does not require a new `{plan_id, task_id, version, nodes}` envelope.
2. The known normalized Node fields are `id`, `node`, `app`, `worker`, `flag`, `steps`, `depends_on`, and `resource`.
3. `steps` is interpreted as high-level natural-language intent/hints. The Worker owns screen-aware low-level execution strategy and action selection.
4. `flag` is retained as an opaque compatibility field. The Validator must not infer risk, authorization, or approval from it until its meaning and allowed values are documented.
5. Runtime fields such as `status` and `history` are deliberately not part of the Director input schema. Validate the plan before runtime mutation, or define a separate runtime-state schema.
6. This pack does not claim that repository files have been modified. Add these files to the repository only after team review and integration checks.

## Suggested destination in the repository

```text
docs/
  PLAN_VALIDATOR_DESIGN_SPEC.md
  VALIDATION_RULES.md
  INTEGRATION_CONTRACT.md
schemas/
  director-plan-v1.schema.json
  plan-validation-report-v1.schema.json
examples/
  valid-director-plan.json
tests/
  VALIDATION_TEST_MATRIX.md
```

## Review process

1. Agree on all entries in `DECISIONS.md`.
2. Confirm schema compatibility against real planner output and normalized Nodes.
3. Implement schema parsing and deterministic structural rules.
4. Add rule tests and verify invalid plans never reach the Delegator.
5. Integrate with the existing semantic Plan Check without treating `skipped` as `passed`.
