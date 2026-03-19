/**
 * DrawZonePanel -- pre-start setup panel.
 *
 * In the new flow, this panel lets the user:
 *   1. Draw zones on the map (optional before start)
 *   2. Launch the mission (starts world ticks + agent)
 *
 * Zones can also be added after the mission starts.
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
  const { state } = useMissionContext();
  const { startMission, addZone, loading, error } = useMission();

  const zoneCount = Object.keys(state.zones).length;
  const drawingPoints = state.drawingZonePoly.length;

  // Commit the drawn zone to the backend
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
          <span style={{ color: "var(--text-secondary)", fontSize: "0.78rem" }}>Zones registered</span>
          <span>{zoneCount}</span>
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

      {/* Zone list */}
      {zoneCount > 0 && (
        <div className="glass" style={{ padding: 10, marginBottom: 14 }}>
          <span style={label}>Zones</span>
          {Object.values(state.zones).map((z) => (
            <div key={z.zone_id} style={{ ...infoRow, alignItems: "center" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <div style={{ width: 8, height: 8, borderRadius: "50%", background: z.color }} />
                <span style={{ fontSize: "0.78rem" }}>{z.label}</span>
              </div>
              <span style={{ fontSize: "0.7rem", color: "var(--text-secondary)" }}>{z.status}</span>
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
