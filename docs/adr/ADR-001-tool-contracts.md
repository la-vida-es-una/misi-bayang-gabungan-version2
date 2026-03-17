# ADR-001 — MCP Tool Contracts and Event Schema

- Status: Accepted
- Date: 2026-03-18
- Owners: Agent Team + MCP Team + Simulation Team

## Context

Current behavior forces agent micro-management (`move_to` + guessed `step`) and creates planner hallucination risk.
The system needs path-level intent, observable execution progress, and deterministic world evolution.

## Decision

Adopt the following MCP contract as canonical.

## Canonical Tools

### 1) `list_drones()`

Returns:

```json
{
    "drones": [
        {
            "id": "drone_alpha",
            "pos": [0, 0],
            "battery": 87.2,
            "state": "explore",
            "queue_length": 4
        }
    ]
}
```

### 2) `assign_path(drone_id, waypoints, scan_at_each=false)`

Request:

```json
{
    "drone_id": "drone_alpha",
    "waypoints": [
        [3, 2],
        [5, 2],
        [5, 5]
    ],
    "scan_at_each": true
}
```

Returns:

```json
{
    "success": true,
    "drone_id": "drone_alpha",
    "accepted_waypoints": 3,
    "est_ticks": 11,
    "battery_cost_estimate": 10.4
}
```

### 3) `recall_drone(drone_id)`

Returns:

```json
{
    "success": true,
    "drone_id": "drone_alpha",
    "est_ticks_to_base": 7
}
```

### 4) `get_world_snapshot()`

Returns full state required for planning:

```json
{
  "tick": 42,
  "drones": [...],
  "survivors": [...],
  "grid": {"width": 30, "height": 30, "obstacles": [[4, 4]]},
  "mission": {"found_count": 2, "total": 6, "complete": false}
}
```

### 5) `step(ticks=1)`

Returns:

```json
{
    "success": true,
    "tick": 43,
    "events": [
        {
            "type": "arrival",
            "drone_id": "drone_alpha",
            "pos": [3, 2]
        },
        {
            "type": "scan_detection",
            "drone_id": "drone_alpha",
            "detections": [
                { "survivor_id": "s1", "x": 4, "y": 2, "confidence": 0.91 }
            ]
        }
    ]
}
```

## Motion and Time Invariants (Binding)

### 1) No Teleport Invariant

Drone position changes are only legal through world stepping.

- `assign_path` must only enqueue intent (waypoints), never mutate final position directly.
- `step()` is the only API allowed to advance physical state.
- Per tick, a drone may move at most its configured speed limit (`max_cells_per_tick`).
- Any tool response that implies immediate arrival after path assignment is invalid.

Formal rule:

For drone position $p_t=(x_t,y_t)$ at tick $t$, movement per tick must satisfy
$|x_{t+1}-x_t|+|y_{t+1}-y_t| \leq v_{\max}$.

### 2) Dual-Clock Execution Model

World time and LLM reasoning time are independent clocks.

- **World clock**: advances by simulation ticks/seconds via `step()`.
- **LLM clock**: background planning process; it must not freeze or rewrite world time.

The orchestrator must run planning as asynchronous background work while the world continues stepping.

### 3) Rolling 3-Step Planning Window

Each drone must always have a 3-step action horizon.

- Initial planning provides 3 upcoming actions per drone.
- Replanning is triggered one step before the end of the active 3-step window.
- Example cadence: think at steps `2, 5, 8, ...` so the next 3 actions are ready before steps `3, 6, 9, ...` end.

Operationally:

1. Execute current 3-step window.
2. At the second step of that window, start background LLM planning for the next 3 steps.
3. Append the next window before the current one is exhausted.

This policy prevents drone idle gaps caused by LLM latency and keeps action continuity without teleport assumptions.

## Event Schema Rules

Each event must include:

- `type` (enum)
- `tick` (int)
- `drone_id` when drone-related

Allowed initial event types:

- `arrival`
- `path_completed`
- `battery_low`
- `battery_critical`
- `scan_detection`
- `recall_started`
- `mission_complete`

## Backward Compatibility and Deprecation

Deprecated tools:

- `move_to(drone_id, x, y)`
- agent-side reliance on manual `thermal_scan` after guessed stepping

Migration policy:

1. Keep deprecated tools for one transition milestone.
2. Emit warning in responses when deprecated tools are used.
3. Remove deprecated tools after integration tests pass for path-based flow.

## Consequences

Positive:

- Agent decisions are state-grounded and less hallucination-prone.
- Reduced micro-control load and cleaner mission traces.
- Clear ownership boundaries across teams.

Trade-offs:

- Requires coordinated refactor of interfaces, MCP tools, and orchestrator loop.
- Temporary dual-support complexity during migration.
