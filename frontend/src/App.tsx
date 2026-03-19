/**
 * App -- root layout.
 *
 * SSE activates once mission is running or ended.
 */

import "./index.css";
import { MissionProvider } from "./context/MissionContext";
import { MapRefProvider } from "./context/MapRefContext";
import { useMissionContext } from "./context/MissionContext";
import { useSSE } from "./hooks/useSSE";
import { MapView } from "./components/map/MapView";
import { Sidebar } from "./components/sidebar/Sidebar";

function Inner() {
  const { state } = useMissionContext();
  const sseActive = state.phase === "running" || state.phase === "ended";

  useSSE(sseActive);

  return (
    <div className="app-container">
      <Sidebar />
      <main className="main-content">
        <div className="map-container">
          <MapView />
        </div>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <MissionProvider>
      <MapRefProvider>
        <Inner />
      </MapRefProvider>
    </MissionProvider>
  );
}
