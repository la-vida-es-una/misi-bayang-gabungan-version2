# SAR Swarm Backend

Offline-first, MCP-first autonomous drone swarm for search and rescue.

## Stack
| Component | Technology |
|-----------|-----------|
| LLM | Ollama `llama3` (local) |
| MCP Server | `fastmcp` |
| REST API | `FastAPI` + `uvicorn` |
| World Engine | Pure Python `asyncio` |
| Grid | `shapely` + `numpy` |

## Quick Start

```bash
# 1. Install dependencies
cd backend
uv sync

# 2. Start Ollama with llama3
ollama pull llama3
ollama serve   # runs on localhost:11434

# 3. Start backend
uv run python main.py
```

## API

### Start a mission
```http
POST /mission/start
Content-Type: application/json

{
  "geojson_polygon": {
    "type": "Polygon",
    "coordinates": [[[107.60,-6.95],[107.65,-6.95],[107.65,-6.90],[107.60,-6.90],[107.60,-6.95]]]
  },
  "mission_text": "Scan the South-East quadrant for thermal signatures",
  "drones": ["drone_1", "drone_2", "drone_3"],
  "survivors": [
    {"id": "s1", "lon": 107.62, "lat": -6.91}
  ]
}
```

### Check world state
```http
GET /mission/state
```

### MCP tools (used by agent only)
```
POST /mcp/call   { "tool": "move_to", "arguments": {"drone_id":"drone_1","x":5,"y":3} }
POST /mcp/call   { "tool": "get_battery_status", "arguments": {"drone_id":"drone_1"} }
POST /mcp/call   { "tool": "thermal_scan", "arguments": {"drone_id":"drone_1"} }
POST /mcp/call   { "tool": "get_world_state", "arguments": {} }
POST /mcp/call   { "tool": "list_drones", "arguments": {} }
POST /mcp/call   { "tool": "get_pending_events", "arguments": {} }
```

## Architecture

```
POST /mission/start
        │
        ▼
mission/receiver.py  ──► Grid(polygon)  ──► WorldEngine
        │                                        │
        ├──► world tick loop (every 0.5s)        │ step() → events
        │         └──► engine.step()             │
        │               └──► push_events()       │
        │                         │              │
        └──► agent loop (every 2s)│              │
                  └──► CommandAgent              │
                            │                    │
                            ▼                    │
                     Ollama llama3               │
                            │                    │
                            ▼                    │
                     MCP tool calls ◄────────────┘
                     (move_to / thermal_scan / ...)
```

## Constraint compliance
- ✅ No teleportation — Bresenham path walked 1 cell/tick
- ✅ MCP-grounded — LLM only calls MCP tools, never engine directly
- ✅ Survivor lifecycle: missing → found only
- ✅ move_to = path assignment, not instant position change
- ✅ step() returns events list
- ✅ World tick (0.5s) ≠ Agent tick (2s) — separate async tasks
- ✅ Rolling 3-step window with replan at ≤1 remaining
- ✅ Battery recall = agent responsibility via move_to(base)
- ✅ Offline-first — Ollama llama3, no cloud dependency
