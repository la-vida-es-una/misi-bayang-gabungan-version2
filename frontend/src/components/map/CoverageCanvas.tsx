import { useEffect } from "react";
import L from "leaflet";
import type { WorldSnapshot } from "../../types/mission";


export function CoverageCanvas({
  map,
  snapshot,
}: {
  map: L.Map;
  snapshot: WorldSnapshot;
}) {

  useEffect(() => {
    if (!map || !snapshot) return;
    // Coverage overlay is informational only — placeholder for full
    // cell-by-cell rendering which requires grid origin geo coords from backend.
    // The backend currently returns coverage_ratio in grid.bounds.
    // Full per-cell rendering will be wired when the backend exposes
    // the list of covered cell geo-centres via SSE or state endpoint.
    // For now we render a coverage % badge on the map corner.
    return;
  }, [map, snapshot]);

  return null;
}
