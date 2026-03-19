# decisions

## decisions made during v1 development

1. define_map is called silently on launch, never user-facing
1. MissionContext is pure serialisable state — no Leaflet objects
1. MapRefContext holds the Leaflet instance separately (unit test safety)
1. /define_map is simulation-only concern, should be split from /start
   eventually
1. Survivors are seeded inside boundary, not inside zone — zone is search area
   only
1. SSE is the only source of drone position — no client animation loop

## v2 redesign decisions (multi-zone + AI chat)

1. Phase machine simplified: PENDING → RUNNING → ENDED (no global PAUSED)
1. Zone lifecycle is per-zone: idle → scanning → completed (independent of
   global phase)
1. Multiple zones can coexist and be scanned concurrently
1. Grid maintains a dict of ZoneState objects, each with its own mask/coverage
1. Zones are drawn on the map, committed via POST /zone/add, managed via
   right-click context menu
1. Zone selection: click to select, shift/ctrl+click for multi-select
1. Right-click context menu on zones: scan, stop, remove
1. Auto-labeling: Zone A, Zone B, etc.
1. Drone return-to-base is AI-reasoned — engine does NOT auto-recall or
   auto-pause
1. When AI is stopped, drones execute remaining queued path but get no new
   instructions
1. AI agent has pause/resume/prompt injection via REST endpoints
1. Agent CoT (chain-of-thought), tool calls, tool results are broadcast via SSE
1. ChatPanel shows full AI activity: system messages, user messages, CoT, tool
   calls/results
1. User can prompt the AI at any time during a running mission
1. /start no longer requires a zone — it just begins the world tick loop and
   agent
1. Zones can be added and scanned at any time while running
1. New MCP tool: get_zones() for agent to understand zone landscape
1. Agent system prompt updated for multi-zone awareness and intelligent drone
   distribution
