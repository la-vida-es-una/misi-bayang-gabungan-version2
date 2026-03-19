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
  } = useMissionContext();

  const esRef = useRef<EventSource | null>(null);

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
            content: thinkData.content,
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
            content: `${tcData.tool}(${JSON.stringify(tcData.args)})`,
            timestamp: Date.now(),
            toolName: tcData.tool,
            toolArgs: tcData.args,
          });
          break;
        }

        case "agent_tool_result": {
          const trData = data as AgentToolResultEvent;
          dispatchWorldEvent(trData);
          addChatMessage({
            id: nextChatMsgId(),
            role: "tool_result",
            content: JSON.stringify(trData.result),
            timestamp: Date.now(),
            toolName: trData.tool,
            toolResult: trData.result,
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

        case "agent_user_message":
          dispatchWorldEvent(data as WorldEvent);
          break;

        // Standard drone/world events
        case "drone_moved":
        case "drone_arrived":
        case "drone_charging":
        case "battery_low":
        case "survivor_found":
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
  ]);
}
