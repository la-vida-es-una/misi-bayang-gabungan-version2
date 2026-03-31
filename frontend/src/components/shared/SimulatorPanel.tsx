/**
 * SimulatorPanel — floating panel for simulation mode controls.
 *
 * Contains:
 * - SIM SURVIVORS list with found/missing counts
 * - Toggle button to show/hide missing survivors on map
 * - Toggle button to show/hide spawn rectangle on map
 */

import { useState } from "react";
import { useMissionContext } from "../../context/MissionContext";
import type { WorldSnapshot } from "../../types/mission";

export function SimulatorPanel({ snapshot }: { snapshot: WorldSnapshot | null }) {
  const { state, toggleShowMissingSurvivors, toggleShowSpawnRect } = useMissionContext();
  const [collapsed, setCollapsed] = useState(false);

  const survivors = snapshot ? Object.entries(snapshot.survivors) : [];
  const found = survivors.filter(([, s]) => s.status === "found").length;
  const missing = survivors.filter(([, s]) => s.status === "missing").length;

  // Filter survivors based on visibility toggle
  const visibleSurvivors = state.showMissingSurvivors
    ? survivors
    : survivors.filter(([, s]) => s.status === "found");

  return (
    <div
      style={{
        position: "absolute",
        top: 12,
        right: 12,
        zIndex: 1000,
        background: "rgba(10, 20, 35, 0.95)",
        border: "1px solid rgba(255, 170, 68, 0.3)",
        borderRadius: 6,
        padding: "10px 12px",
        minWidth: 180,
        boxShadow: "0 4px 12px rgba(0, 0, 0, 0.4)",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: collapsed ? 0 : 10,
        }}
      >
        <span
          style={{
            fontSize: "0.7rem",
            color: "#ffaa44",
            fontWeight: 700,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
          }}
        >
          Simulator
        </span>
        <button
          style={{
            background: "none",
            border: "none",
            color: "#ffaa44",
            cursor: "pointer",
            fontSize: "0.72rem",
            padding: "2px 6px",
          }}
          onClick={() => setCollapsed((c) => !c)}
        >
          {collapsed ? "+" : "−"}
        </button>
      </div>

      {!collapsed && (
        <>
          {/* Survivors section */}
          <div
            style={{
              background: "rgba(255, 170, 68, 0.05)",
              border: "1px solid rgba(255, 170, 68, 0.2)",
              borderRadius: 4,
              padding: "8px 10px",
              marginBottom: 10,
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                marginBottom: 8,
              }}
            >
              <span
                style={{
                  fontSize: "0.65rem",
                  color: "#ffaa44",
                  fontWeight: 600,
                  letterSpacing: "0.06em",
                }}
              >
                SIM SURVIVORS
              </span>
              <span style={{ fontSize: "0.68rem", color: "var(--success-color)" }}>
                {found} found
              </span>
              <span style={{ fontSize: "0.68rem", color: "var(--text-secondary)" }}>
                {missing} missing
              </span>
            </div>

            {visibleSurvivors.length > 0 ? (
              visibleSurvivors.map(([id, s]) => (
                <div
                  key={id}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    fontSize: "0.72rem",
                    marginBottom: 2,
                  }}
                >
                  <span style={{ color: "var(--text-secondary)" }}>{id}</span>
                  <span
                    style={{
                      color:
                        s.status === "found"
                          ? "var(--success-color)"
                          : "var(--danger-color)",
                    }}
                  >
                    {s.status}
                  </span>
                </div>
              ))
            ) : (
              <div style={{ fontSize: "0.7rem", color: "var(--text-secondary)", fontStyle: "italic" }}>
                {snapshot ? "No survivors to show" : "Waiting for mission..."}
              </div>
            )}
          </div>

          {/* Toggle buttons */}
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <button
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                background: state.showMissingSurvivors
                  ? "rgba(68, 255, 136, 0.1)"
                  : "rgba(255, 68, 68, 0.08)",
                border: `1px solid ${state.showMissingSurvivors ? "rgba(68, 255, 136, 0.3)" : "rgba(255, 68, 68, 0.3)"}`,
                borderRadius: 4,
                padding: "6px 10px",
                cursor: "pointer",
                fontSize: "0.7rem",
                color: state.showMissingSurvivors
                  ? "var(--success-color)"
                  : "var(--danger-color)",
              }}
              onClick={toggleShowMissingSurvivors}
            >
              <span>Missing Survivors</span>
              <span style={{ fontWeight: 600 }}>
                {state.showMissingSurvivors ? "SHOW" : "HIDE"}
              </span>
            </button>

            <button
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                background: state.showSpawnRect
                  ? "rgba(68, 255, 136, 0.1)"
                  : "rgba(255, 68, 68, 0.08)",
                border: `1px solid ${state.showSpawnRect ? "rgba(68, 255, 136, 0.3)" : "rgba(255, 68, 68, 0.3)"}`,
                borderRadius: 4,
                padding: "6px 10px",
                cursor: "pointer",
                fontSize: "0.7rem",
                color: state.showSpawnRect
                  ? "var(--success-color)"
                  : "var(--danger-color)",
              }}
              onClick={toggleShowSpawnRect}
            >
              <span>Spawn Rectangle</span>
              <span style={{ fontWeight: 600 }}>
                {state.showSpawnRect ? "SHOW" : "HIDE"}
              </span>
            </button>
          </div>
        </>
      )}
    </div>
  );
}
