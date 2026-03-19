/**
 * DrawZonePanel -- pre-start setup panel.
 *
 * Zones drawn here are stored locally (pendingZones) until the user
 * hits START MISSION. They are registered with the backend during the
 * startMission flow (after define_map succeeds), not before.
 */

import React from "react";
import { useMissionContext } from "../../context/MissionContext";
import { useMission } from "../../hooks/useMission";

const label: React.CSSProperties = {
  fontSize: "0.72rem",
  color: "var(--text-secondary)",
  textTransform: "uppercase",
  letterSpacing: "0.06em",
  marginBottom: 4,
  display: "block",
};

const errorBox: React.CSSProperties = {
  background: "rgba(255,68,68,.1)",
  border: "1px solid var(--danger-color)",
  borderRadius: 4,
  padding: "8px 10px",
  fontSize: "0.78rem",
  color: "var(--danger-color)",
  marginBottom: 12,
};

const infoRow: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  fontSize: "0.8rem",
  marginBottom: 6,
};

export function DrawZonePanel() {
  const { state, removePendingZone } = useMissionContext();
  const { startMission, addZone, loading, error } = useMission();

  const pendingCount = state.pendingZones.length;
  const drawingPoints = state.drawingZonePoly.length;

  // Commit drawn zone — stored locally, sent to backend only after mission starts
  const handleCommitZone = async () => {
    if (drawingPoints < 3) return;
    await addZone(state.drawingZonePoly);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      <div className="glass" style={{ padding: 12, marginBottom: 14 }}>
        <span style={label}>Draw search zones</span>
        <div style={{ fontSize: "0.78rem", color: "var(--text-secondary)", lineHeight: 1.5 }}>
          Click the map to place zone boundary points.<br />
          Right-click to clear. Double-click or use button to commit.
        </div>
        <div style={{ ...infoRow, marginTop: 10 }}>
          <span style={{ color: "var(--text-secondary)", fontSize: "0.78rem" }}>Drawing points</span>
          <span style={{ color: drawingPoints >= 3 ? "var(--success-color)" : "var(--warning-color)" }}>
            {drawingPoints} {drawingPoints >= 3 ? "ok" : "(min 3)"}
          </span>
        </div>
        <div style={infoRow}>
          <span style={{ color: "var(--text-secondary)", fontSize: "0.78rem" }}>Zones ready</span>
          <span style={{ color: pendingCount > 0 ? "var(--success-color)" : "var(--text-secondary)" }}>
            {pendingCount}
          </span>
        </div>

        {drawingPoints >= 3 && (
          <button
            className="btn"
            style={{ borderColor: "var(--success-color)", color: "var(--success-color)", fontSize: "0.75rem", marginTop: 6 }}
            onClick={handleCommitZone}
            disabled={loading}
          >
            COMMIT ZONE
          </button>
        )}
      </div>

      {/* Pending zone list */}
      {pendingCount > 0 && (
        <div className="glass" style={{ padding: 10, marginBottom: 14 }}>
          <span style={label}>Zones (will register on start)</span>
          {state.pendingZones.map((z, i) => (
            <div key={i} style={{ ...infoRow, alignItems: "center" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <div style={{ width: 8, height: 8, borderRadius: "50%", background: z.color }} />
                <span style={{ fontSize: "0.78rem" }}>Zone {String.fromCharCode(65 + i)}</span>
                <span style={{ fontSize: "0.7rem", color: "var(--text-secondary)" }}>
                  ({z.points.length} pts)
                </span>
              </div>
              <button
                onClick={() => removePendingZone(i)}
                style={{
                  background: "none",
                  border: "none",
                  color: "var(--danger-color)",
                  cursor: "pointer",
                  fontSize: "0.75rem",
                  padding: "0 4px",
                }}
                title="Remove zone"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}

      {error && <div style={errorBox}>{error}</div>}

      <button
        className="btn btn-primary"
        disabled={loading}
        onClick={() => startMission()}
      >
        {loading ? "STARTING..." : "START MISSION"}
      </button>
    </div>
  );
}
