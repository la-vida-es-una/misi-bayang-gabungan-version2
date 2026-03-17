# Redesign Analysis — Misi Bayang SAR Drone System

> Based on `studi_kasus.txt` (Study Case 3: First Responder of the Future) and deep
> analysis of the previous codebase.

---

## 1. What the Study Case Actually Requires

From `studi_kasus.txt`:

| Requirement             | Exact Wording |
| ----------------------- | -- |
| Simulation only         | "No physical hardware is required. Participants can use a 2D grid or a simple Python-based environment."                                                                   |
| MCP mandatory           | "All communication between the Agent (the LLM) and the Drones (the code) must be handled via the Model Context Protocol (MCP). Hard-coding drone movements is prohibited." |
| Chain-of-Thought        | "The agent explains its logic before executing the tools."                                                                                                                 |
| Dynamic fleet discovery | "The agent must not have hard-coded drone IDs. It must use the MCP discovery mechanism."                                                                                   |
| Resource management     | "Managing multiple drones, ensuring search coverage is optimized, and drones are recalled for 'charging' before battery failure."                                          |
| Tools required          | `move_to(x,y)`, `get_battery_status()`, `thermal_scan()` — minimum.                                                                                                        |

Mesa is listed only as a **suggestion** ("Mesa or a FastAPI mock environment") — it is not mandatory.
The study case says nothing about survivors being "rescued" by drones — only "detected."

---

## 2. previous Implementation — Critical Design Flaws

### 2.1 Battery Model is Too Simple

**previous behavior (`drone_agent.py:163-164`):**

```python
def _drain_battery(self) -> None:
    self.battery = max(0.0, self.battery - self.battery_drain)
```

- Flat 0.9%/tick regardless of activity
- Thermal scanner drains nothing extra
- Hovering stationary costs same as flying at full speed
- `self.low_battery = 20%` is stored but **never read by any FSM code** — a dead field

**What it should be (user's spec):**

| Drone Activity         | Battery Drain Rate                 |
| ---------------------- | ---------------------------------- |
| Stationary hover       | Low baseline (e.g. 0.3%/tick)      |
| Moving to waypoint     | Higher (e.g. 0.8%/tick)            |
| Thermal scanner active | +0.5%/tick on top of movement cost |

This makes resource management decisions non-trivial — the LLM must actually reason
about which drones to task with scanning vs. repositioning.

### 2.2 Survivor State is Physically Wrong

**previous states (`survivor.py:10-13`):**

```
UNSEEN → FOUND → RESCUED
```

RESCUED is triggered when a drone _physically occupies the same cell_.
**This is nonsensical** — a search drone is not a rescue helicopter. Its job is to
locate survivors and broadcast their coordinates to ground teams. A drone flying over
a survivor does not rescue them.

**Correct states:**

```
missing → found
```

- `missing`: not yet detected by any drone scan
- `found`: thermal scan confirmed the location; coordinates broadcast to command

Once found, the survivor entry stays in the world map permanently as a reference
point. There is no physical "pickup" mechanic.

### 2.3 LLM Command Format is Indirect and Hallucination-Prone

**previous flow:**

```
LLM calls move_to(drone_id, x, y)   ← single target
LLM calls step(N)                    ← must guess N
LLM calls thermal_scan(drone_id)     ← may forget to call this
```

Problems:

- The LLM must call `step(N)` with a correct N for the drone to arrive — it must
  calculate travel distance without knowing actual path length (obstacles exist).
- `move_to` returns the **target** as if the drone is already there, not the previous
  position. LLM frequently believes the drone arrived when it has not.
- The LLM must poll every drone individually with `get_battery_status` to know if
  they arrived. If it skips this, it hallucinates positions.

**User's proposed format:**

```python
(drone_id, [(x1,y1), (x2,y2), (x3,y3), ...])
```

One LLM call submits an entire planned **path** for a drone. The simulation executes
the path autonomously tick-by-tick. The LLM does not need to guess `step(N)` each
time — it submits its full intention in one structured output.

### 2.4 Idle Drones Still Drain Battery

If the LLM is "thinking" between tool calls, the simulation is not stepping — but if
`step(N)` is called while drones have no waypoint, they sit still and drain battery
at full rate. The LLM has no awareness of when its reasoning is causing resource waste.

### 2.5 Single `ainvoke` Creates a Blind Spot

The entire mission is one `ainvoke()` call (`orchestrator.py:253`). There is no outer
loop that can:

- Inject fresh battery warnings mid-mission
- Alert the LLM that a drone has arrived
- Notify that battery dropped below threshold

The LLM must proactively query everything. Any state it doesn't query is stale.

### 2.6 Mesa Adds Complexity Without Clear Benefit

Mesa's `shuffle_do("step")` calls agents in random order each tick. This introduces
non-determinism that makes debugging harder. The project only needs:

- A dictionary of drone objects with position, battery, state, waypoint queue
- A grid (a 2D array or set of positions) for obstacle/survivor placement
- A `world.step()` that advances all drones one tick

This is ~100 lines of pure Python. Mesa adds the `Agent`, `Model`, `MultiGrid` class
hierarchy, module-level imports, and the shuffle semantics — all overhead that is a
source of subtle bugs and confusion for an LLM trying to generate this code.

### 2.7 Multi-Survivor Scan Truncation

`real_mcp_client.py:113-116`:

```python
if detected and detections:
    det = detections[0]  # Only first survivor returned
```

If two survivors are within scan radius, only one is reported. The LLM will miss the
second. This bug is silent — the LLM receives a success response and never knows.

### 2.8 No Arrival Notification

Drone silently clears `_llm_waypoint` on arrival (`drone_agent.py:108-109`). The LLM
has no event or callback. It must call `get_battery_status` on each drone to discover
arrival. If it doesn't, it re-sends `move_to` to a drone that is already at the target.

---

## 3. Proposed Architecture (No Mesa)

### 3.1 Simulation Layer — Pure Python

```
world/
  grid.py       — 2D grid: set of obstacle cells, dict of survivors, dict of drones
  drone.py      — Drone dataclass: id, pos, battery, state, waypoint_queue
  survivor.py   — Survivor dataclass: id, pos, status (missing|found)
  physics.py    — Battery drain rules, movement rules
  world.py      — World class: step(), add_drone(), add_survivor(), get_state()
```

**Drone movement with waypoint queue:**

```python
@dataclass
class Drone:
    id: str
    pos: tuple[int, int]
    battery: float          # 0.0 – 100.0
    state: Literal["explore", "return", "idle"]
    waypoint_queue: list[tuple[int, int]]   # LLM-submitted path
    scanner_active: bool = False
```

Each `world.step()`:

1. For each drone in `explore` state:
    - If waypoint_queue is non-empty, move one step toward `waypoint_queue[0]`
    - If arrived at `waypoint_queue[0]`, pop it
    - If `scanner_active`, run thermal scan on previous cell
2. Drain battery based on activity
3. If any drone battery ≤ 5%, force it to `return` state

**Battery drain physics:**

```python
DRAIN_HOVER   = 0.3   # %/tick — stationary, scanner off
DRAIN_MOVE    = 0.8   # %/tick — moving, scanner off
DRAIN_SCAN    = 0.5   # additional %/tick when scanner_active=True
```

### 3.2 LLM Command Format

The MCP tool `assign_path` accepts:

```python
def assign_path(drone_id: str, waypoints: list[tuple[int,int]], scan_at_each: bool = False) -> dict:
    """
    Assigns a sequence of waypoints to a drone.
    The drone will visit each waypoint in order, moving one cell per tick.
    If scan_at_each=True, thermal scanner activates at every waypoint cell.
    Returns estimated ticks to complete the path.
    """
```

LLM output example:

```
I observe CHARLIE is at (2,2) with 68% battery. Sector C (top-right quadrant)
is unexplored. Because CHARLIE has sufficient battery for a 15-cell path (est.
~24 ticks at 0.8%/tick = 19.2% total), I will send CHARLIE on a sweep path
through (10,18), (15,18), (18,15), (18,10) with scanning at each stop.

assign_path("drone_charlie", [(10,18),(15,18),(18,15),(18,10)], scan_at_each=True)
```

This gives the LLM full control over the route shape and scan strategy in one call,
and forces it to reason about battery cost upfront.

### 3.3 Lookahead / Pipeline Thinking

**User's spec:**

> "One step before the last step, the LLM is given info about whether steps 1–4 all
> succeeded. If yes, it can confidently assume step 5 will succeed and add 5 more
> steps going forward."

Implementation: The orchestrator maintains a **path execution stream**:

```
╔══════════════════════════════════════════════════════════╗
║  LLM submits:  [(A→path1), (B→path2), (C→path3)]       ║
║                                                          ║
║  Simulation runs path1/path2/path3 conpreviously          ║
║                  ↓                                       ║
║  When progress > 80% of submitted steps completed:       ║
║    → notify LLM in background with previous world state   ║
║    → LLM extends plan (adds 5 more waypoints/drones)     ║
║    → appended to existing path queues                    ║
╚══════════════════════════════════════════════════════════╝
```

In the orchestrator, this is implemented as an outer async loop:

```python
async def run_mission(goal: str):
    while not mission_complete():
        # Query previous state
        state = await mcp.get_world_snapshot()

        # LLM plans next N steps
        commands = await llm.plan(state, goal)
        # commands = [("drone_alpha", [(x1,y1),(x2,y2)]), ...]

        # Submit all paths
        for drone_id, path in commands:
            await mcp.assign_path(drone_id, path)

        # Run simulation ticks until 80% of submitted steps complete
        # (i.e., before last path segment begins executing)
        while path_completion() < 0.8:
            await mcp.step(1)
            await asyncio.sleep(0.1)

        # At 80%: LLM gets fresh state and plans again
        # → paths are extended before drones go idle
```

This eliminates idle time between LLM thinking rounds and eliminates the battery
waste of drones sitting still waiting for the LLM to issue the next command.

### 3.4 MCP Tool Surface (Minimal and Unambiguous)

| Tool                                             | Arguments              | Returns                                     |
| ------------------------------------------------ | ---------------------- | ------------------------------------------- |
| `list_drones()`                                  | —                      | `[{id, pos, battery, state, queue_length}]` |
| `assign_path(drone_id, waypoints, scan_at_each)` | str, list[tuple], bool | `{est_ticks, battery_cost_estimate}`        |
| `recall_drone(drone_id)`                         | str                    | `{success, est_ticks_to_base}`              |
| `get_world_snapshot()`                           | —                      | full world state                            |
| `step(ticks)`                                    | int                    | `{tick, events: [{type, drone_id, ...}]}`   |

Key changes from previous implementation:

- **`step()` returns events** — arrival notifications, scan detections, battery
  warnings are all in the response. LLM learns about arrivals without polling.
- **`assign_path` returns cost estimate** — LLM can validate its own battery math
  before committing.
- **No single-cell `move_to`** — forces path-level thinking, not micro-management.

---

## 4. Summary of Changes vs. previous Implementation

| Aspect                        | previous                     | Proposed                               |
| ----------------------------- | --------------------------- | -------------------------------------- |
| Simulation framework          | Mesa 3.x                    | Pure Python dataclasses                |
| Battery drain                 | Flat 0.9%/tick              | Activity-based (hover/move/scan)       |
| Survivor states               | `unseen → found → rescued`  | `missing → found`                      |
| Rescue mechanic               | Drone walks over survivor   | Does not exist (drone = sensor only)   |
| LLM command unit              | Single `move_to(x,y)`       | `(drone_id, [(x1,y1),...])` path tuple |
| LLM awareness of arrival      | Must poll each drone        | `step()` returns arrival events        |
| Idle drones between LLM calls | Drain battery doing nothing | 80% lookahead re-triggers planning     |
| Multi-survivor scan           | Returns only first          | Returns all in radius                  |
| `step()` return value         | `{success, new_tick}` only  | `{tick, events[]}` with all delta      |

---

## 5. Known Bugs in previous Codebase (for reference)

| File                 | Line    | Bug                                                                                                                    |
| -------------------- | ------- | ---------------------------------------------------------------------------------------------------------------------- |
| `orchestrator.py`    | 23–24   | `from langchain.agents import create_agent as create_react_agent` — wrong import, not LangGraph's `create_react_agent` |
| `real_mcp_client.py` | 101–104 | `move_to` returns target coords as if drone is there; drone has not moved                                              |
| `real_mcp_client.py` | 113–116 | `detections[0]` — silently drops all but first survivor in scan radius                                                 |
| `drone_agent.py`     | 49, 55  | `self.low_battery = 20.0` stored but never read by FSM                                                                 |
| `drone_agent.py`     | 85      | Battery drained even when drone is stationary with no waypoint                                                         |
| `sensors.py`         | 43      | Confidence is always hardcoded 0.95, never actually computed                                                           |
| `battery.py`         | 51–56   | Alerts stored in `context.world._alerts` as dynamic attribute, not queryable via any MCP tool                          |
| `world.py`           | 148–152 | `mission_complete` only visible in snapshot, no dedicated tool                                                         |
