/**
 * All sidebar phase panels.
 * DefineMapPanel is removed — replaced by auto map-canvas bounds.
 * EndedPanel now splits: real mode (minimal) vs sim mode (full summary).
 */

import React from "react";
import { useMissionContext } from "../../context/MissionContext";

// ── Shared styles ─────────────────────────────────────────────────────────────

const infoRow: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  fontSize: "0.8rem",
  marginBottom: 6,
};


// ── EndedPanel ────────────────────────────────────────────────────────────────

export function EndedPanel() {
  const { state, reset, simReset, exitSimMode } = useMissionContext();
  const inSim = state.simulationMode;

  const endEvent = state.eventLog.find((e) => e.type === "mission_ended") as
    | { type: "mission_ended"; survivors_found: number; total_survivors: number; zones_completed: number }
    | undefined;

  // Real mode: minimal
  if (!inSim) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div className="glass" style={{ padding: 14 }}>
          <div style={{ color: "var(--text-secondary)", fontSize: "0.85rem", marginBottom: 8 }}>
            Mission ended.
          </div>
          {state.snapshot && (
            <div style={infoRow}>
              <span style={{ color: "var(--text-secondary)", fontSize: "0.8rem" }}>Total ticks</span>
              <span style={{ fontFamily: "monospace" }}>{state.snapshot.tick}</span>
            </div>
          )}
        </div>
        <button className="btn" onClick={reset}>NEW MISSION</button>
      </div>
    );
  }

  // Sim mode: full summary + replay options
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {/* Sim complete banner */}
      <div style={{
        background: "rgba(255,170,68,.08)",
        border: "1px solid rgba(255,170,68,.4)",
        borderRadius: 4, padding: 14,
      }}>
        <div style={{
          fontSize: "0.65rem", fontWeight: 700, letterSpacing: "0.08em",
          color: "#ffaa44", border: "1px solid #ffaa44",
          borderRadius: 3, padding: "1px 6px", display: "inline-block", marginBottom: 8,
        }}>
          SIMULATION COMPLETE
        </div>

        {endEvent && (
          <>
            <div style={infoRow}>
              <span style={{ color: "#8ab4d6", fontSize: "0.8rem" }}>Survivors found</span>
              <span style={{
                color: endEvent.survivors_found === endEvent.total_survivors
                  ? "var(--success-color)"
                  : "var(--warning-color)",
                fontWeight: 700,
              }}>
                {endEvent.survivors_found} / {endEvent.total_survivors}
              </span>
            </div>
            <div style={infoRow}>
              <span style={{ color: "#8ab4d6", fontSize: "0.8rem" }}>Zones completed</span>
              <span>{endEvent.zones_completed}</span>
            </div>
          </>
        )}

        {state.snapshot && (
          <div style={infoRow}>
            <span style={{ color: "#8ab4d6", fontSize: "0.8rem" }}>Total ticks</span>
            <span style={{ fontFamily: "monospace" }}>{state.snapshot.tick}</span>
          </div>
        )}
      </div>

      <button
        style={{
          width: "100%", padding: 10,
          border: "1px solid #ffaa44",
          background: "#ffaa44", color: "#050a0f",
          fontSize: "0.78rem", fontWeight: 700,
          letterSpacing: "0.08em", textTransform: "uppercase" as const,
          borderRadius: 4, cursor: "pointer",
        }}
        onClick={simReset}
      >
        ⚗ Simulate Again
      </button>

      <button
        style={{
          width: "100%", padding: 10,
          border: "1px solid rgba(255,170,68,.3)",
          background: "transparent", color: "rgba(255,170,68,.7)",
          fontSize: "0.78rem", fontWeight: 700,
          letterSpacing: "0.08em", textTransform: "uppercase" as const,
          borderRadius: 4, cursor: "pointer",
        }}
        onClick={() => { exitSimMode(); reset(); }}
      >
        Exit Simulation Mode
      </button>
    </div>
  );
}

