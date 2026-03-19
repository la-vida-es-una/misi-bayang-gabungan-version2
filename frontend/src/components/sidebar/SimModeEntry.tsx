/**
 * SimModeEntry — the 3-step simulation setup wizard.
 *
 * Rendered in the sidebar when simulationMode=true and simSetupStep !== "done".
 * Everything here is amber-coloured and clearly marked [SIM].
 *
 * Steps:
 *   base      → user clicks map to place fake base
 *   boundary  → user draws rectangle OR clicks "Use Map Canvas"
 *   survivors → slider for count → Seed & Continue
 */

import React from "react";
import {
  useMissionContext,
  type SimSetupStep,
} from "../../context/MissionContext";

// ── Shared sim styles ─────────────────────────────────────────────────────────

export const SIM_BADGE: React.CSSProperties = {
  display: "inline-block",
  fontSize: "0.65rem",
  fontWeight: 700,
  letterSpacing: "0.08em",
  color: "#ffaa44",
  border: "1px solid #ffaa44",
  borderRadius: 3,
  padding: "1px 6px",
  marginBottom: 10,
};

const simCard: React.CSSProperties = {
  background: "rgba(255,170,68,0.05)",
  border: "1px solid rgba(255,170,68,0.3)",
  borderRadius: 4,
  padding: 12,
  marginBottom: 12,
};

const simBtn: React.CSSProperties = {
  width: "100%",
  padding: "10px",
  border: "1px solid #ffaa44",
  background: "rgba(255,170,68,0.1)",
  color: "#ffaa44",
  fontSize: "0.78rem",
  fontWeight: 700,
  letterSpacing: "0.08em",
  textTransform: "uppercase" as const,
  borderRadius: 4,
  cursor: "pointer",
  marginBottom: 8,
};

const simBtnPrimary: React.CSSProperties = {
  ...simBtn,
  background: "#ffaa44",
  color: "#050a0f",
};

const backBtn: React.CSSProperties = {
  ...simBtn,
  background: "transparent",
  border: "1px solid rgba(255,170,68,0.3)",
  color: "rgba(255,170,68,0.6)",
  fontSize: "0.72rem",
  marginBottom: 0,
};

const label: React.CSSProperties = {
  fontSize: "0.72rem",
  color: "#8ab4d6",
  textTransform: "uppercase" as const,
  letterSpacing: "0.06em",
  marginBottom: 6,
  display: "block",
};

// ── Step indicator ────────────────────────────────────────────────────────────

const STEPS: { key: SimSetupStep; label: string }[] = [
  { key: "base", label: "Base" },
  { key: "boundary", label: "Boundary" },
  { key: "survivors", label: "Survivors" },
];

function StepIndicator({ current }: { current: SimSetupStep }) {
  const idx = STEPS.findIndex((s) => s.key === current);
  return (
    <div style={{ display: "flex", gap: 6, marginBottom: 16, alignItems: "center" }}>
      {STEPS.map((s, i) => (
        <React.Fragment key={s.key}>
          <div style={{
            display: "flex", alignItems: "center", gap: 4,
            opacity: i > idx ? 0.35 : 1,
          }}>
            <div style={{
              width: 18, height: 18, borderRadius: "50%",
              background: i < idx ? "#ffaa44" : i === idx ? "transparent" : "transparent",
              border: `1px solid ${i <= idx ? "#ffaa44" : "rgba(255,170,68,0.3)"}`,
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: "0.6rem", fontWeight: 700,
              color: i < idx ? "#050a0f" : "#ffaa44",
            }}>
              {i < idx ? "✓" : i + 1}
            </div>
            <span style={{ fontSize: "0.68rem", color: i === idx ? "#ffaa44" : "#8ab4d6" }}>
              {s.label}
            </span>
          </div>
          {i < STEPS.length - 1 && (
            <div style={{ flex: 1, height: 1, background: i < idx ? "#ffaa44" : "rgba(255,170,68,0.2)" }} />
          )}
        </React.Fragment>
      ))}
    </div>
  );
}

// ── Step: Base ────────────────────────────────────────────────────────────────

function StepBase() {
  const { state, exitSimMode } = useMissionContext();
  const placed = state.simConfig.base !== null;

  return (
    <div>
      <StepIndicator current="base" />
      <div style={simCard}>
        <span style={label}>Step 1 — Place fake base</span>
        <div style={{ fontSize: "0.78rem", color: "#8ab4d6", lineHeight: 1.6 }}>
          Click anywhere on the map to place the drone base location.
        </div>
        {placed && (
          <div style={{
            marginTop: 10, fontSize: "0.75rem",
            color: "#ffaa44", fontWeight: 600,
          }}>
            ✓ Base placed at {state.simConfig.base![0].toFixed(4)},
            {" "}{state.simConfig.base![1].toFixed(4)}
          </div>
        )}
        {!placed && (
          <div style={{
            marginTop: 10, display: "flex", alignItems: "center", gap: 6,
            fontSize: "0.72rem", color: "rgba(255,170,68,0.5)",
          }}>
            <div style={{
              width: 8, height: 8, borderRadius: "50%",
              border: "1px solid #ffaa44", animation: "pulse 1.5s infinite",
            }} />
            Waiting for map click…
          </div>
        )}
      </div>
      <button style={backBtn} onClick={exitSimMode}>
        ← Exit Simulation Mode
      </button>
    </div>
  );
}

// ── Step: Boundary ────────────────────────────────────────────────────────────

function StepBoundary() {
  const { state, simSetBoundary, simBack } = useMissionContext();
  const hasRect = state.simConfig.boundaryRect !== null &&
    (state.simConfig.boundaryRect?.length ?? 0) >= 2;

  return (
    <div>
      <StepIndicator current="boundary" />
      <div style={simCard}>
        <span style={label}>Step 2 — Survivor spawn area</span>
        <div style={{ fontSize: "0.78rem", color: "#8ab4d6", lineHeight: 1.6, marginBottom: 10 }}>
          Draw a rectangle on the map where survivors will be seeded,
          or use the entire visible map area.
        </div>

        {hasRect ? (
          <div style={{ fontSize: "0.75rem", color: "#ffaa44", fontWeight: 600, marginBottom: 10 }}>
            ✓ Rectangle drawn ({state.simConfig.boundaryRect!.length} points)
            <button
              style={{ ...backBtn, display: "inline", width: "auto", padding: "2px 8px", marginLeft: 8, fontSize: "0.68rem" }}
              onClick={() => simSetBoundary(null)}
            >
              clear
            </button>
          </div>
        ) : (
          <div style={{
            display: "flex", alignItems: "center", gap: 6,
            fontSize: "0.72rem", color: "rgba(255,170,68,0.5)", marginBottom: 10,
          }}>
            <div style={{ width: 8, height: 8, border: "1px solid #ffaa44", borderRadius: 1 }} />
            Click + drag on map to draw rectangle…
          </div>
        )}

        <button style={simBtnPrimary} onClick={() => simSetBoundary(null)}>
          Use Full Map Canvas
        </button>
      </div>

      <button style={backBtn} onClick={simBack}>← Back</button>
    </div>
  );
}

// ── Step: Survivors ───────────────────────────────────────────────────────────

function StepSurvivors() {
  const { state, simSetSurvivorCount, simConfirmSurvivors, simBack } = useMissionContext();
  const count = state.simConfig.survivorCount;

  return (
    <div>
      <StepIndicator current="survivors" />
      <div style={simCard}>
        <span style={label}>Step 3 — Survivor count</span>
        <div style={{ fontSize: "0.78rem", color: "#8ab4d6", marginBottom: 12, lineHeight: 1.6 }}>
          Survivors will be randomly placed inside the spawn area.
          They are hidden from view until discovered by a drone.
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 4 }}>
          <input
            type="range" min={1} max={10} value={count}
            onChange={(e) => simSetSurvivorCount(Number(e.target.value))}
            style={{ flex: 1, accentColor: "#ffaa44" }}
          />
          <span style={{ fontSize: "1rem", fontWeight: 700, color: "#ffaa44", minWidth: 20 }}>
            {count}
          </span>
        </div>
        <div style={{ fontSize: "0.68rem", color: "rgba(255,170,68,0.5)", marginBottom: 0 }}>
          {count} survivor{count !== 1 ? "s" : ""} will be seeded
        </div>
      </div>

      <button style={simBtnPrimary} onClick={simConfirmSurvivors}>
        Seed Survivors & Continue →
      </button>
      <button style={backBtn} onClick={simBack}>← Back</button>
    </div>
  );
}

// ── Main export ───────────────────────────────────────────────────────────────

export function SimModeEntry() {
  const { state } = useMissionContext();

  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      <div style={{ marginBottom: 14 }}>
        <span style={SIM_BADGE}>SIMULATION SETUP</span>
        <div style={{ fontSize: "0.75rem", color: "#8ab4d6", lineHeight: 1.5 }}>
          Configure the fake environment. This does not reflect real operations.
        </div>
      </div>

      {state.simSetupStep === "base" && <StepBase />}
      {state.simSetupStep === "boundary" && <StepBoundary />}
      {state.simSetupStep === "survivors" && <StepSurvivors />}
    </div>
  );
}
