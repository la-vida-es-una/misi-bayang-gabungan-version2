# Engineering Governance Plan — Non-Hallucinatory Development

This document defines how this project is developed so behavior is driven by explicit contracts and verification, not by AI improvisation.

## 1) Core Values (Non-Negotiable)

1. **Protocol truth over model belief**
    - Agent decisions are valid only when based on tool-returned state.
    - No assumption of arrival, battery, survivor detection, or mission progress without MCP evidence.

2. **Simulation as source of truth**
    - The world state is owned by simulation code, not by agent memory.
    - MCP tools expose state deltas/events so the agent does not guess hidden transitions.

3. **Deterministic and replayable behavior**
    - Same seed + same tool call sequence must produce same mission trace.
    - Randomized execution order is disallowed unless explicitly modeled and logged.

4. **Path-level planning, not tick guessing**
    - Agent issues intent (`assign_path`) instead of micromanaging physics (`move_to` + guessed `step`).
    - Simulation executes motion and emits progress events.

5. **Safety and resource realism**
    - Battery costs must reflect activity (hover/move/scan).
    - Low/critical battery thresholds must trigger explicit state transitions and events.

6. **Drones detect, do not rescue**
    - Survivor lifecycle is `missing -> found`.
    - No “walk-over rescue” mechanics in swarm drones.

## 2) Architectural Decisions (Binding)

### A. Module Ownership

- `backend/world/*` (new): pure Python simulation domain (grid, drone, survivor, world loop).
- `backend/mcp_server/*`: protocol adapter only (validates input/output and forwards to world).
- `backend/agent/*`: planner/orchestrator only (never mutates simulation directly).

**Rule:** No cross-layer shortcuts. Agent never imports world internals. World never depends on LLM classes.

### B. Mandatory MCP Tool Surface (target)

- `list_drones()`
- `assign_path(drone_id, waypoints, scan_at_each=False)`
- `recall_drone(drone_id)`
- `get_world_snapshot()`
- `step(ticks=1)` returning `{tick, events:[...]}`

**Rule:** New behavior must be exposed through MCP tools before agent prompt updates.

### C. Event-Driven Execution

`step()` must return events (examples):

- `arrival`
- `battery_low`
- `battery_critical`
- `scan_detection`
- `path_completed`
- `mission_complete`

**Rule:** If agent logic needs information, the info must be in tool return payloads/events, not hidden in logs.

## 3) Contract-First Development Rules

Before implementing behavior, define/update typed contracts:

1. `agent/interfaces.py` typed dicts or dataclasses for all tool requests/responses.
2. MCP tool docstrings with strict semantics (what is guaranteed vs estimated).
3. Event schema (required keys, enum types, units).

### Required semantics examples

- `assign_path` returns estimate only (`est_ticks`, `battery_cost_estimate`), never fake final position.
- `thermal_scan` returns all detections in range; never truncates to first element.
- `step` is the only function that advances world time.

## 4) Anti-Hallucination Guardrails

1. **No hidden state transitions**
    - Any state change used by planner must be observable from MCP outputs.

2. **No implied success**
    - Tool responses must include explicit `success`/`error` and structured reasons.

3. **No prompt-only guarantees**
    - If prompt says “do X”, code must enforce with contracts/tests (prompt is guidance, not enforcement).

4. **No dead configuration fields**
    - Every threshold/config field must have at least one code path and one test that exercises it.

5. **No lossy payload transforms**
    - Adapters cannot drop detections/events unless schema says so.

## 5) Quality Gates (Must Pass Before Merge)

### Gate 1 — Contract tests

- Validate request/response shape for each MCP tool.
- Reject malformed drone IDs, invalid waypoints, out-of-grid coordinates.

### Gate 2 — Determinism tests

- Fixed seed replay test for mission traces.
- Same command stream => same state snapshots/events.

### Gate 3 — Physics and state tests

- Battery drain by activity: hover/move/scan.
- Survivor state: only `missing -> found`.
- Recall behavior at low/critical thresholds.

### Gate 4 — Integration tests (agent ↔ MCP)

- Dynamic discovery with no hard-coded drone IDs.
- Agent receives arrival/battery via events, not polling assumptions.

### Gate 5 — Regression tests for previous failures

- `move_to`-style arrival hallucination cannot occur.
- Multi-survivor scan returns all detections.
- Single-shot orchestration blind spot prevented by outer loop.

## 6) Development Workflow Policy

Every feature PR must include:

1. **Decision note**
    - Which core value is being improved and which risk is reduced.

2. **Contract diff**
    - API/schema changes first, implementation second.

3. **Evidence**
    - Test output for affected gates.

4. **Mission-log sample**
    - One short trace showing planner reasoning grounded in MCP returns.

## 7) Phased Roadmap (Planning-Only)

### Phase 0 — Freeze and baseline

- Freeze current tool semantics and capture failing/fragile behaviors as regression tests.

### Phase 1 — World refactor (pure Python)

- Introduce `world` package with deterministic step loop and activity-based battery model.

### Phase 2 — MCP contract upgrade

- Add `assign_path`, eventful `step`, and snapshot tool.
- Keep temporary compatibility layer for old tools only during migration.

### Phase 3 — Orchestrator redesign

- Replace single `ainvoke` with iterative loop and 80% lookahead replanning trigger.
- Agent plans paths; simulation reports events.

### Phase 4 — Hardening

- Complete gates, benchmark trace quality, remove deprecated tools (`move_to` direct micro-control).

## 8) Definition of Done (Project-Level)

This project is considered “competition-ready” only when:

1. All drone control is through MCP tools.
2. Agent uses runtime discovery (no hard-coded IDs).
3. Path-level planning works for 3–5 drones with battery-aware allocation.
4. Step events provide arrival, battery, and detection deltas.
5. Mission logs show reasoning grounded in observed state, not assumptions.
6. Test gates pass consistently on clean runs.

## 9) Immediate Next Artifact (Recommended)

Create `docs/adr/ADR-001-tool-contracts.md` to lock:

- final MCP tool names,
- event payload schema,
- deprecation timeline for old `move_to` flow.
