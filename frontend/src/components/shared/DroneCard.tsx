import type { DroneState } from "../../types/mission";

export function DroneCard({ id, drone }: { id: string; drone: DroneState }) {
  const bColor =
    drone.battery > 50 ? "var(--success-color)"
      : drone.battery > 25 ? "var(--warning-color)"
        : "var(--danger-color)";

  return (
    <div className="glass" style={{ padding: "8px 10px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
        <span style={{ fontSize: "0.8rem", fontWeight: 600 }}>{id}</span>
        <span style={{ fontSize: "0.72rem", color: "var(--text-secondary)" }}>{drone.status}</span>
      </div>
      <div style={{ height: 4, background: "#1a2a3a", borderRadius: 2, overflow: "hidden" }}>
        <div style={{
          width: `${drone.battery}%`, height: "100%",
          background: bColor, transition: "width .4s",
        }} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4, fontSize: "0.7rem", color: "var(--text-secondary)" }}>
        <span>{drone.battery.toFixed(0)}%</span>
        <span>{drone.path_remaining} steps left</span>
      </div>
    </div>
  );
}
