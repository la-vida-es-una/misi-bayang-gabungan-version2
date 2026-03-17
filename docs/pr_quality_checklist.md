# PR Quality Checklist — Agentic Swarm SAR

Use this checklist for every PR. A PR is not mergeable if any required item is unchecked.

## A. Core Value Alignment (Required)

- [ ] Change strengthens at least one core value from `engineering_governance_plan.md`.
- [ ] No behavior relies on agent assumptions without MCP-observable evidence.
- [ ] No new hidden state transition is introduced.

## B. Contract Integrity (Required)

- [ ] MCP request/response schema is defined or updated first.
- [ ] Tool semantics are explicit (estimate vs confirmed state is unambiguous).
- [ ] Adapter layers do not drop detections/events.

## C. Simulation Correctness (Required)

- [ ] Survivor lifecycle remains `missing -> found` only.
- [ ] Battery logic matches activity-based drain model.
- [ ] Low/critical battery thresholds are exercised by tests.

## D. Agent Reliability (Required)

- [ ] No hard-coded drone IDs in planner flow.
- [ ] Planner consumes events/snapshots instead of polling assumptions.
- [ ] Mission loop supports replanning before drones go idle.

## E. Testing Evidence (Required)

- [ ] Contract tests added/updated for changed MCP tools.
- [ ] At least one determinism/replay test covers affected flow.
- [ ] Regression test included for any previously known bug touched by this PR.

## F. Operational Clarity (Required)

- [ ] Mission log output clearly links reasoning to observed tool state.
- [ ] Deprecated APIs (if used) produce warnings and migration note.
- [ ] Documentation updated in `docs/` for any behavior or interface change.
