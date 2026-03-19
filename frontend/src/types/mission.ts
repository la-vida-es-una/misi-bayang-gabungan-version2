// ── Mission phase ─────────────────────────────────────────────────────────────
// Simplified: no "paused" phase. Zone lifecycle is per-zone.

export type MissionPhase =
  | "pending_map"     // no map defined yet
  | "pending_zone"    // map defined, can draw zones (pre-start)
  | "running"         // world ticking, zones can be added/scanned any time
  | "ended";

// ── Zone ──────────────────────────────────────────────────────────────────────

export type ZoneStatus = "idle" | "scanning" | "completed";

export interface ZoneInfo {
  zone_id: string;
  label: string;
  status: ZoneStatus;
  total_cells: number;
  covered_cells: number;
  coverage_ratio: number;
}

// Client-side zone state (extends backend zone info with UI state)
export interface ZoneClientState extends ZoneInfo {
  polygon: LatLonTuple[];  // original polygon points (frontend [lat,lon] convention)
  color: string;           // assigned display color
  selected: boolean;       // currently selected on map
}

// ── World entities ────────────────────────────────────────────────────────────

export interface DroneState {
  col: number;
  row: number;
  lat: number;
  lon: number;
  battery: number;
  status: "idle" | "moving" | "scanning" | "charging";
  path_remaining: number;
}

export interface SurvivorState {
  col: number;
  row: number;
  lat: number;
  lon: number;
  status: "missing" | "found";
}

export interface GridBounds {
  cols: number;
  rows: number;
  cell_size_m: number;
  master_cells: number;
  zone_count: number;
  zones: Record<string, ZoneInfo>;
  scanning_coverage_ratio: number;
}

export interface WorldSnapshot {
  tick: number;
  phase: "pending" | "running" | "ended";
  grid: GridBounds;
  base: { col: number; row: number };
  drones: Record<string, DroneState>;
  survivors: Record<string, SurvivorState>;
}

// ── SSE events ────────────────────────────────────────────────────────────────

export interface SSEEnvelope<T = unknown> {
  event: string;
  data: T;
}

export interface TickEvent extends WorldSnapshot {}

export interface DroneMovedEvent {
  type: "drone_moved";
  drone_id: string;
  from_col: number;
  from_row: number;
  to_col: number;
  to_row: number;
}

export interface DroneArrivedEvent {
  type: "drone_arrived";
  drone_id: string;
  col: number;
  row: number;
}

export interface SurvivorFoundEvent {
  type: "survivor_found";
  drone_id: string;
  survivor_id: string;
  col: number;
  row: number;
}

export interface BatteryLowEvent {
  type: "battery_low";
  drone_id: string;
  battery: number;
}

export interface ZoneAddedEvent {
  type: "zone_added";
  zone_id: string;
  label: string;
  zone_cells: number;
}

export interface ZoneRemovedEvent {
  type: "zone_removed";
  zone_id: string;
}

export interface ScanStartedEvent {
  type: "scan_started";
  zone_ids: string[];
}

export interface ScanStoppedEvent {
  type: "scan_stopped";
  zone_ids: string[];
}

export interface ZoneCoveredEvent {
  type: "zone_covered";
  zone_id: string;
  total_cells: number;
}

export interface MissionResumedEvent {
  type: "mission_resumed";
}

export interface MissionEndedEvent {
  type: "mission_ended";
  survivors_found: number;
  total_survivors: number;
  zones_completed: number;
}

export interface OutOfBoundsRejectedEvent {
  type: "out_of_bounds_rejected";
  drone_id: string;
  col: number;
  row: number;
}

export interface DroneChargingEvent {
  type: "drone_charging";
  drone_id: string;
  battery: number;
}

// Agent visibility events
export interface AgentThinkingEvent {
  type: "agent_thinking";
  tick: number;
  content: string;
}

export interface AgentToolCallEvent {
  type: "agent_tool_call";
  tick: number;
  tool: string;
  args: Record<string, unknown>;
}

export interface AgentToolResultEvent {
  type: "agent_tool_result";
  tick: number;
  tool: string;
  result: Record<string, unknown>;
}

export interface AgentStoppedEvent {
  type: "agent_stopped";
}

export interface AgentResumedEvent {
  type: "agent_resumed";
}

export interface AgentUserMessageEvent {
  type: "agent_user_message";
  content: string;
}

export type WorldEvent =
  | DroneMovedEvent
  | DroneArrivedEvent
  | SurvivorFoundEvent
  | BatteryLowEvent
  | ZoneAddedEvent
  | ZoneRemovedEvent
  | ScanStartedEvent
  | ScanStoppedEvent
  | ZoneCoveredEvent
  | MissionResumedEvent
  | MissionEndedEvent
  | OutOfBoundsRejectedEvent
  | DroneChargingEvent
  | AgentThinkingEvent
  | AgentToolCallEvent
  | AgentToolResultEvent
  | AgentStoppedEvent
  | AgentResumedEvent
  | AgentUserMessageEvent;

// ── Chat messages ─────────────────────────────────────────────────────────────

export type ChatMessageRole =
  | "system"
  | "user"
  | "assistant_thinking"
  | "tool_call"
  | "tool_result"
  | "assistant";

export interface ChatMessage {
  id: string;
  role: ChatMessageRole;
  content: string;
  timestamp: number;
  toolName?: string;
  toolArgs?: Record<string, unknown>;
  toolResult?: Record<string, unknown>;
}

// ── REST request/response types ───────────────────────────────────────────────

export interface LatLon {
  lat: number;
  lon: number;
}

// Polygon as GeoJSON — coords in [lat, lon] order (frontend convention)
export interface GeoJSONPolygon {
  type: "Polygon";
  coordinates: [number, number][][];
}

export interface DefineMapRequest {
  geojson_polygon: GeoJSONPolygon;
  drone_ids: string[];
  survivor_count: number;
  base: LatLon;
  cell_size_m: number;
}

export interface DefineMapResponse {
  mission_id: string;
  grid_bounds: GridBounds;
  base: { col: number; row: number; lat: number; lon: number };
  drone_ids: string[];
  survivors: Array<{ id: string; lat: number; lon: number; status: string }>;
}

export interface StartMissionRequest {
  mission_text: string;
}

export interface StartMissionResponse {
  ok: boolean;
  phase: string;
}

export interface ZoneAddResponse {
  ok: boolean;
  zone_id: string;
  zone: ZoneInfo;
}

// ── Map drawing ───────────────────────────────────────────────────────────────

// Frontend polygon points are always [lat, lon] tuples
export type LatLonTuple = [number, number];
