/**
 * MissionLivePanel -- shown during running phase.
 *
 * Displays: zone list with coverage, drone cards, zone actions, end button.
 * Also allows drawing and committing new zones while running.
 */

import React from "react";
import { useMissionContext } from "../../context/MissionContext";
import { useMission } from "../../hooks/useMission";
import { SimSurvivorsPanel } from "./SimSurvivorsPanel";
import { DroneCard } from "../shared/DroneCard";

const label: React.CSSProperties = {
  fontSize: "0.72rem",
  color: "var(--text-secondary)",
  textTransform: "uppercase",
  letterSpacing: "0.06em",
  marginBottom: 4,
  display: "block",
};

const infoRow: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  fontSize: "0.8rem",
  marginBottom: 6,
};

export function MissionLivePanel() {
  const { state } = useMissionContext();
  const { endMission, addZone, scanZones, stopScanning, removeZone, loading } = useMission();
  const { snapshot, simulationMode, zones, selectedZoneIds, drawingZonePoly } = state;

  const zoneList = Object.values(zones);
  const hasSelection = selectedZoneIds.length > 0;
  const drawingPoints = drawingZonePoly.length;

  const handleCommitZone = async () => {
    if (drawingPoints < 3) return;
    await addZone(drawingZonePoly);
  };

  const handleScanSelected = () => {
    if (hasSelection) scanZones(selectedZoneIds);
  };

  const handleStopSelected = () => {
    const scanning = selectedZoneIds.filter((id) => zones[id]?.status === "scanning");
    if (scanning.length > 0) stopScanning(scanning);
  };

  const handleRemoveSelected = () => {
    selectedZoneIds.forEach((id) => removeZone(id));
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>

      {/* Tick + aggregate coverage */}
      {snapshot && (
        <div className="glass" style={{ padding: 8 }}>
          <div style={infoRow}>
            <span style={{ color: "var(--text-secondary)", fontSize: "0.78rem" }}>Tick</span>
            <span style={{ fontFamily: "monospace" }}>{snapshot.tick}</span>
          </div>
          <div style={infoRow}>
            <span style={{ color: "var(--text-secondary)", fontSize: "0.78rem" }}>Scanning coverage</span>
            <span style={{ color: "var(--success-color)" }}>
              {(snapshot.grid.scanning_coverage_ratio * 100).toFixed(1)}%
            </span>
          </div>
          <div style={{ height: 3, background: "#0d1a2a", borderRadius: 2, overflow: "hidden" }}>
            <div style={{
              width: `${snapshot.grid.scanning_coverage_ratio * 100}%`,
              height: "100%", background: "var(--success-color)", transition: "width .4s",
            }} />
          </div>
        </div>
      )}

      {/* Zone list */}
      {zoneList.length > 0 && (
        <div className="glass" style={{ padding: 8 }}>
          <span style={label}>Zones ({zoneList.length})</span>
          {zoneList.map((z) => (
            <div
              key={z.zone_id}
              style={{
                ...infoRow,
                alignItems: "center",
                background: z.selected ? "rgba(68,170,255,0.08)" : "transparent",
                borderRadius: 3,
                padding: "2px 4px",
                margin: "0 -4px",
                cursor: "pointer",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 6, flex: 1 }}>
                <div style={{
                  width: 8, height: 8, borderRadius: "50%",
                  background: z.color,
                  boxShadow: z.status === "scanning" ? `0 0 6px ${z.color}` : "none",
                }} />
                <span style={{ fontSize: "0.75rem" }}>{z.label}</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{
                  fontSize: "0.65rem",
                  color: z.status === "scanning" ? "var(--success-color)"
                    : z.status === "completed" ? "var(--accent-color)"
                    : "var(--text-secondary)",
                }}>
                  {z.status === "scanning" ? `${(z.coverage_ratio * 100).toFixed(0)}%` : z.status}
                </span>
              </div>
            </div>
          ))}

          {/* Zone actions */}
          {hasSelection && (
            <div style={{ display: "flex", gap: 4, marginTop: 6 }}>
              <button
                className="btn"
                style={{ flex: 1, fontSize: "0.68rem", padding: "5px 4px", borderColor: "var(--success-color)", color: "var(--success-color)" }}
                onClick={handleScanSelected}
              >
                SCAN
              </button>
              <button
                className="btn"
                style={{ flex: 1, fontSize: "0.68rem", padding: "5px 4px", borderColor: "var(--warning-color)", color: "var(--warning-color)" }}
                onClick={handleStopSelected}
              >
                STOP
              </button>
              <button
                className="btn"
                style={{ flex: 1, fontSize: "0.68rem", padding: "5px 4px", borderColor: "var(--danger-color)", color: "var(--danger-color)" }}
                onClick={handleRemoveSelected}
              >
                DEL
              </button>
            </div>
          )}
        </div>
      )}

      {/* Drawing indicator */}
      {drawingPoints > 0 && (
        <div className="glass" style={{ padding: 8 }}>
          <div style={infoRow}>
            <span style={{ color: "var(--text-secondary)", fontSize: "0.78rem" }}>Drawing zone</span>
            <span style={{ color: drawingPoints >= 3 ? "var(--success-color)" : "var(--warning-color)" }}>
              {drawingPoints} pts
            </span>
          </div>
          {drawingPoints >= 3 && (
            <button
              className="btn"
              style={{ fontSize: "0.68rem", padding: "5px", borderColor: "var(--success-color)", color: "var(--success-color)" }}
              onClick={handleCommitZone}
            >
              COMMIT ZONE
            </button>
          )}
        </div>
      )}

      {/* Drone cards */}
      {snapshot && Object.entries(snapshot.drones).map(([id, d]) => (
        <DroneCard key={id} id={id} drone={d} />
      ))}

      {/* Sim survivors */}
      {simulationMode && snapshot && <SimSurvivorsPanel snapshot={snapshot} />}

      <button
        className="btn"
        style={{ borderColor: "var(--danger-color)", color: "var(--danger-color)" }}
        disabled={loading}
        onClick={endMission}
      >
        {loading ? "ENDING..." : "END MISSION"}
      </button>
    </div>
  );
}
