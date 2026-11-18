# Integration Contract - Plan Validator

## Required order

1. Receive Director output.
2. Normalize to the current Node array contract.
3. Run deterministic Plan Validator.
4. If errors exist: stop; do not call Delegator.
5. If deterministic validation passes: run the existing semantic Plan Check.
6. Apply the configured policy to semantic status (`passed`, `failed`, `skipped`, `error`). A skipped check must remain visibly skipped.
7. Only after all mandatory gates pass, hand the plan to Delegator.
8. Delegator selects dependency-ready Nodes and dispatches them to Worker.
9. Worker executes locally and returns structured outcome/evidence.
10. Verification layer marks the Node `verified` only when its goal is supported by evidence.

## Gate invariant

`Delegator.dispatch(plan)` must be unreachable when the deterministic validation report contains any blocking error.

Do not rely on a UI convention or an LLM's self-assessment to enforce this invariant. Enforce it in the orchestration code path and test it with a spy/fake Delegator.

## Suggested report example

```json
{
  "valid": false,
  "decision": "rejected",
  "errors": [
    {
      "code": "PV-DEP-004",
      "category": "dependency",
      "node_id": "node-03",
      "field_path": "[2].depends_on",
      "message": "Dependency cycle detected: node-01 -> node-03 -> node-01"
    }
  ],
  "warnings": [],
  "approval_requirements": [],
  "semantic_check": {
    "status": "not_run",
    "reason": "Deterministic validation failed."
  }
}
```

## Error handling

- Malformed plan: reject with a parse/schema error; do not attempt execution.
- Registry unavailable: do not assume a tool/Worker is safe or available. Treat required lookup failures as blocking, or use an explicitly configured offline mode that cannot dispatch.
- Semantic checker timeout/error: preserve `error` or `skipped`; do not rewrite it to `passed`. Whether delegation can continue is controlled by explicit policy in `DECISIONS.md`.
- Worker action result without evidence: do not automatically mark Node verified.
- Replanning: validate the replacement plan fully before atomic activation. Cancel/stop stale execution before another side effect.

## Suggested public interface

```python
report = plan_validator.validate(normalized_nodes, context=validation_context)

if not report.valid:
    return reject_plan(report)

semantic_result = semantic_plan_check.check(user_request, normalized_nodes)

if not semantic_policy.allows(semantic_result, report):
    return reject_plan_or_request_repair(report, semantic_result)

return delegator.dispatch(normalized_nodes)
```

`validation_context` should expose trusted registries and runtime policy, not mutable instructions from the LLM. The example is conceptual; adapt naming to the repository's actual interfaces.
