/**
 * MapRefContext — shares the Leaflet map instance across the component tree.
 *
 * Why a separate context and not part of MissionContext:
 *   MissionContext is pure serialisable state (reducible, testable).
 *   A Leaflet Map instance is a mutable imperative object — it must never
 *   enter the reducer. Keeping it separate preserves the unit-testability
 *   of MissionContext and avoids re-renders from map mutations.
 *
 * Usage:
 *   MapView calls setMap(leafletMapInstance) on init.
 *   useMission calls getMapBounds() to read current viewport bounds.
 *   SimModeEntry wizard calls panTo() to centre on sim base.
 */

import {
  createContext,
  useCallback,
  useContext,
  useRef,
  type ReactNode,
} from "react";
import type L from "leaflet";
import type { LatLonTuple } from "../types/mission";

interface MapRefContextValue {
  setMap: (map: L.Map) => void;
  getMap: () => L.Map | null;
  getMapBounds: () => LatLonTuple[] | null;  // 4-corner rectangle of current viewport
  panTo: (lat: number, lon: number) => void;
  fitBounds: (points: LatLonTuple[]) => void;
}

const MapRefContext = createContext<MapRefContextValue | null>(null);

export function MapRefProvider({ children }: { children: ReactNode }) {
  const mapRef = useRef<L.Map | null>(null);

  const setMap = useCallback((map: L.Map) => {
    mapRef.current = map;
  }, []);

  const getMap = useCallback((): L.Map | null => {
    return mapRef.current;
  }, []);

  /**
   * Returns the current map viewport as a closed 4-corner rectangle
   * in [lat, lon] tuples — ready to pass directly to toGeoJSON().
   */
  const getMapBounds = useCallback((): LatLonTuple[] | null => {
    const map = mapRef.current;
    if (!map) return null;
    const b = map.getBounds();
    return [
      [b.getNorthWest().lat, b.getNorthWest().lng],
      [b.getNorthEast().lat, b.getNorthEast().lng],
      [b.getSouthEast().lat, b.getSouthEast().lng],
      [b.getSouthWest().lat, b.getSouthWest().lng],
    ];
  }, []);

  const panTo = useCallback((lat: number, lon: number) => {
    mapRef.current?.panTo([lat, lon]);
  }, []);

  const fitBounds = useCallback((points: LatLonTuple[]) => {
    if (!mapRef.current || points.length === 0) return;
    const latLngs = points.map(([lat, lon]) => [lat, lon] as [number, number]);
    mapRef.current.fitBounds(latLngs, { padding: [40, 40] });
  }, []);

  return (
    <MapRefContext.Provider value={{ setMap, getMap, getMapBounds, panTo, fitBounds }}>
      {children}
    </MapRefContext.Provider>
  );
}

export function useMapRef(): MapRefContextValue {
  const ctx = useContext(MapRefContext);
  if (!ctx) throw new Error("useMapRef must be used inside MapRefProvider");
  return ctx;
}
