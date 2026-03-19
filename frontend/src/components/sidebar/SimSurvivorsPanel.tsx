import { useState } from "react";

// ── SimSurvivorsPanel (sim mode only, inside live panel) ──────────────────────

import type { WorldSnapshot } from "../../types/mission";

export function SimSurvivorsPanel({ snapshot }: { snapshot: WorldSnapshot }) {
  const [show, setShow] = useState(true);
  const survivors = Object.entries(snapshot.survivors);
  const found = survivors.filter(([, s]) => s.status === "found").length;
  const missing = survivors.filter(([, s]) => s.status === "missing").length;

  return (
    <div style={{
      background: "rgba(255,170,68,.05)",
      border: "1px solid rgba(255,170,68,.25)",
      borderRadius: 4, padding: "8px 10px",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: show ? 8 : 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: "0.65rem", color: "#ffaa44", fontWeight: 700, letterSpacing: "0.06em" }}>
            SIM SURVIVORS
          </span>
          <span style={{ fontSize: "0.7rem", color: "var(--success-color)" }}>{found} found</span>
          <span style={{ fontSize: "0.7rem", color: "var(--text-secondary)" }}>{missing} missing</span>
        </div>
        <button
          style={{ background: "none", border: "none", color: "#ffaa44", cursor: "pointer", fontSize: "0.72rem" }}
          onClick={() => setShow((s) => !s)}
        >
          {show ? "hide" : "show"}
        </button>
      </div>

      {show && survivors.map(([id, s]) => (
        <div key={id} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.72rem", marginBottom: 2 }}>
          <span style={{ color: "var(--text-secondary)" }}>{id}</span>
          <span style={{ color: s.status === "found" ? "var(--success-color)" : "var(--danger-color)" }}>
            {s.status}
          </span>
        </div>
      ))}
    </div>
  );
}

