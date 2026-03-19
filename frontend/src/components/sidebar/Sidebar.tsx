/**
 * Sidebar -- split panel layout.
 *
 * Top: mission controls (sim setup, zone list, fleet status, end button)
 * Bottom: AI Chat panel (takes remaining height)
 */

import { useMissionContext, isSimSetupInProgress } from "../../context/MissionContext";
import { SimModeEntry } from "./SimModeEntry";
import { DrawZonePanel } from "./DrawZonePanel";
import { MissionLivePanel } from "./MissionLivePanel";
import { EndedPanel } from "./EndedPanel";
import { ChatPanel } from "../shared/CoTDrawer";

export function Sidebar() {
  const { state, enterSimMode } = useMissionContext();

  function renderTopPanel() {
    if (isSimSetupInProgress(state)) return <SimModeEntry />;
    switch (state.phase) {
      case "pending_zone": return <DrawZonePanel />;
      case "running": return <MissionLivePanel />;
      case "ended": return <EndedPanel />;
    }
  }

  const inSim = state.simulationMode;
  const showChat = state.phase === "running" || state.phase === "ended";

  return (
    <aside className="sidebar" style={{ display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <header className="header">
        <h1>MultiUAV Console</h1>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
          {inSim && <span style={{
            fontSize: "0.65rem", fontWeight: 700, letterSpacing: "0.08em",
            color: "#ffaa44", border: "1px solid #ffaa44",
            borderRadius: 3, padding: "1px 6px",
          }}>SIM</span>}
          <p style={{ fontSize: "0.7rem", color: "var(--text-secondary)", margin: 0 }}>
            SAR SWARM v2.0 ·{" "}
            <span style={{ color: phaseColor(state.phase, inSim) }}>
              {phaseLabel(state.phase, state.simulationMode, isSimSetupInProgress(state))}
            </span>
          </p>
        </div>
      </header>

      {/* Top section: mission controls */}
      <section style={{
        flex: showChat ? "0 0 auto" : "1 1 auto",
        overflow: "auto",
        minHeight: 0,
      }}>
        {renderTopPanel()}
      </section>

      {/* Bottom section: AI Chat */}
      {showChat && (
        <section style={{ flex: "1 1 0", minHeight: 180, overflow: "hidden", borderTop: "1px solid var(--border-color)", paddingTop: 8 }}>
          <ChatPanel />
        </section>
      )}

      {/* Enter sim mode button */}
      {!inSim && state.phase === "pending_zone" && (
        <footer className="mission-control">
          <button
            className="btn"
            style={{ borderColor: "#ffaa44", color: "#ffaa44", fontSize: "0.75rem" }}
            onClick={enterSimMode}
          >
            Enter Simulation Mode
          </button>
        </footer>
      )}
    </aside>
  );
}

function phaseLabel(phase: string, simMode: boolean, setupInProgress: boolean): string {
  if (simMode && setupInProgress) return "SIM SETUP";
  switch (phase) {
    case "pending_zone": return simMode ? "READY" : "SETUP";
    case "running": return "RUNNING";
    case "ended": return simMode ? "SIM COMPLETE" : "ENDED";
    default: return phase.toUpperCase();
  }
}

function phaseColor(phase: string, simMode: boolean): string {
  if (simMode) {
    switch (phase) {
      case "running": return "var(--success-color)";
      case "ended": return "var(--warning-color)";
      default: return "var(--warning-color)";
    }
  }
  switch (phase) {
    case "running": return "var(--success-color)";
    case "ended": return "var(--text-secondary)";
    default: return "var(--accent-color)";
  }
}
