/**
 * useSSE — opens a single EventSource to /mission/stream.
 *
 * Handles all event types including zone lifecycle and agent CoT events.
 * Dispatches to MissionContext for state updates and chat messages.
 */

import { useEffect, useRef } from "react";
import { useMissionContext, nextChatMsgId } from "../context/MissionContext";
import type {
  WorldSnapshot,
  WorldEvent,
  AgentThinkingEvent,
  AgentToolCallEvent,
  AgentToolResultEvent,
  LatLonTuple,
} from "../types/mission";

const SSE_URL = "/mission/stream";

export function useSSE(active: boolean) {
  const {
    dispatchTick,
    dispatchWorldEvent,
    dispatchMissionEnded,
    addChatMessage,
    dispatchAgentStopped,
    dispatchAgentResumed,
    updateZonesFromSnapshot,
    dispatchDroneTraceUpdate,
    dispatchScanWaypointAdd,
  } = useMissionContext();

  const esRef = useRef<EventSource | null>(null);
  // Track last known positions for trace change detection
  const lastPosRef = useRef<Record<string, string>>({});

  useEffect(() => {
    if (!active) {
      esRef.current?.close();
      esRef.current = null;
      return;
    }

    const es = new EventSource(SSE_URL);
    esRef.current = es;

    es.onmessage = (e: MessageEvent) => {
      let parsed: { event: string; data: unknown };
      try {
        parsed = JSON.parse(e.data as string) as { event: string; data: unknown };
      } catch {
        return;
      }

      const { event, data } = parsed;

      switch (event) {
        case "tick": {
          const snapshot = data as WorldSnapshot;
          dispatchTick(snapshot);
          // Sync zone coverage from snapshot
          if (snapshot.grid?.zones) {
            updateZonesFromSnapshot(snapshot.grid.zones as Record<string, { status: string; coverage_ratio: number; covered_cells: number; total_cells: number }>);
          }
          // Drone trace: append position when it changes
          if (snapshot.drones) {
            for (const [did, drone] of Object.entries(snapshot.drones)) {
              const key = `${drone.lat},${drone.lon}`;
              if (lastPosRef.current[did] !== key) {
                lastPosRef.current[did] = key;
                dispatchDroneTraceUpdate(did, [drone.lat, drone.lon] as LatLonTuple);
              }
            }
          }
          break;
        }

        case "mission_ended":
          dispatchWorldEvent(data as WorldEvent);
          dispatchMissionEnded();
          addChatMessage({
            id: nextChatMsgId(),
            role: "system",
            content: "Mission ended.",
            timestamp: Date.now(),
          });
          break;

        case "mission_resumed":
          dispatchWorldEvent(data as WorldEvent);
          addChatMessage({
            id: nextChatMsgId(),
            role: "system",
            content: "Mission started.",
            timestamp: Date.now(),
          });
          break;

        // Zone lifecycle events
        case "zone_added":
        case "zone_removed":
        case "scan_started":
        case "scan_stopped":
        case "zone_covered":
          dispatchWorldEvent(data as WorldEvent);
          addChatMessage({
            id: nextChatMsgId(),
            role: "system",
            content: `[${event}] ${JSON.stringify(data)}`,
            timestamp: Date.now(),
          });
          break;

        // Agent CoT events
        case "agent_thinking": {
          const thinkData = data as AgentThinkingEvent;
          dispatchWorldEvent(thinkData);
          addChatMessage({
            id: nextChatMsgId(),
            role: "assistant_thinking",
            content: `[tick ${thinkData.tick}] ${thinkData.content}`,
            timestamp: Date.now(),
          });
          break;
        }

        case "agent_tool_call": {
          const tcData = data as AgentToolCallEvent;
          dispatchWorldEvent(tcData);
          addChatMessage({
            id: nextChatMsgId(),
            role: "tool_call",
            content: `[tick ${tcData.tick}] ${tcData.tool}(${JSON.stringify(tcData.args)})`,
            timestamp: Date.now(),
            toolName: tcData.tool,
            toolArgs: tcData.args,
            callId: tcData.call_id,
          });
          // Record scan waypoint for visualization
          if (tcData.tool === "thermal_scan" && tcData.args?.drone_id) {
            const did = tcData.args.drone_id as string;
            const pos = lastPosRef.current[did];
            if (pos) {
              const [lat, lon] = pos.split(",").map(Number);
              dispatchScanWaypointAdd(did, [lat, lon] as LatLonTuple);
            }
          }
          break;
        }

        case "agent_tool_result": {
          const trData = data as AgentToolResultEvent;
          dispatchWorldEvent(trData);
          addChatMessage({
            id: nextChatMsgId(),
            role: "tool_result",
            content: `[tick ${trData.tick}] ${JSON.stringify(trData.result)}`,
            timestamp: Date.now(),
            toolName: trData.tool,
            toolResult: trData.result,
            callId: trData.call_id,
          });
          break;
        }

        case "agent_stopped":
          dispatchWorldEvent(data as WorldEvent);
          dispatchAgentStopped();
          addChatMessage({
            id: nextChatMsgId(),
            role: "system",
            content: "AI agent paused.",
            timestamp: Date.now(),
          });
          break;

        case "agent_resumed":
          dispatchWorldEvent(data as WorldEvent);
          dispatchAgentResumed();
          addChatMessage({
            id: nextChatMsgId(),
            role: "system",
            content: "AI agent resumed.",
            timestamp: Date.now(),
          });
          break;

        case "agent_error": {
          const errData = data as { type: string; tick: number; error: string; detail: string };
          dispatchWorldEvent(data as WorldEvent);
          addChatMessage({
            id: nextChatMsgId(),
            role: "error",
            content: `Agent error: ${errData.error}`,
            timestamp: Date.now(),
          });
          break;
        }

        case "agent_user_message":
          dispatchWorldEvent(data as WorldEvent);
          break;

        case "survivor_found": {
          const sfData = data as { survivor_id: string; drone_id: string };
          dispatchWorldEvent(data as WorldEvent);
          addChatMessage({
            id: nextChatMsgId(),
            role: "system",
            content: `SURVIVOR ${sfData.survivor_id} found by ${sfData.drone_id}!`,
            timestamp: Date.now(),
          });
          break;
        }

        case "battery_low": {
          const blData = data as { drone_id: string; battery: number };
          dispatchWorldEvent(data as WorldEvent);
          addChatMessage({
            id: nextChatMsgId(),
            role: "system",
            content: `WARNING: ${blData.drone_id} battery low at ${Math.round(blData.battery)}%`,
            timestamp: Date.now(),
          });
          break;
        }

        case "drone_scanned": {
          const dsData = data as {
            drone_id: string;
            col: number;
            row: number;
            survivors_found: string[];
            zone_id: string | null;
            coverage_ratio: number;
          };
          dispatchWorldEvent(data as WorldEvent);
          // Record scan waypoint for visualization
          const pos = lastPosRef.current[dsData.drone_id];
          if (pos) {
            const [lat, lon] = pos.split(",").map(Number);
            dispatchScanWaypointAdd(dsData.drone_id, [lat, lon] as LatLonTuple);
          }
          break;
        }

        // Standard drone/world events
        case "drone_moved":
        case "drone_arrived":
        case "drone_charging":
        case "out_of_bounds_rejected":
          dispatchWorldEvent(data as WorldEvent);
          break;

        default:
          break;
      }
    };

    es.onerror = () => {
      console.warn("[SSE] Connection error -- retrying...");
    };

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [
    active,
    dispatchTick,
    dispatchWorldEvent,
    dispatchMissionEnded,
    addChatMessage,
    dispatchAgentStopped,
    dispatchAgentResumed,
    updateZonesFromSnapshot,
    dispatchDroneTraceUpdate,
    dispatchScanWaypointAdd,
  ]);
}
