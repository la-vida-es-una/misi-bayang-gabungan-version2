import React, { useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { DronePatrolService, Point } from '../services/DronePatrolService';

interface MapProps {
  onAreaChange: (points: [number, number][]) => void;
  droneCount: number;
  areaPoints: [number, number][];
}

const defaultPolygon: [number, number][] = [];

// Tarakan, Indonesia
const centerCoord: [number, number] = [3.314, 117.591];

export default function Map({ onAreaChange, droneCount, areaPoints }: MapProps) {
  const mapRef = useRef<HTMLDivElement>(null);
  const leafletMapRef = useRef<L.Map | null>(null);
  const polygonRef = useRef<L.Polygon | null>(null);
  const markerRef = useRef<L.Marker | null>(null);
  const pointsRef = useRef<[number, number][]>([...defaultPolygon]);
  const draggableMarkersRef = useRef<L.Marker[]>([]);

  // Drones state
  const droneMarkersRef = useRef<L.Marker[]>([]);
  const droneTrailRefs = useRef<L.Polyline[]>([]);
  const patrolServiceRef = useRef<DronePatrolService | null>(null);

  // Drone base location: first polygon point if available, else centerCoord
  const droneBase = areaPoints.length > 0 ? areaPoints[0] : centerCoord;
  const droneBaseMarkerRef = useRef<L.Marker | null>(null);

  // Draw drone base marker
  React.useEffect(() => {
    if (!leafletMapRef.current) return;
    if (droneBaseMarkerRef.current) droneBaseMarkerRef.current.remove();
    droneBaseMarkerRef.current = L.marker(droneBase, {
      icon: L.icon({
        iconUrl: 'https://cdn-icons-png.flaticon.com/512/684/684908.png', // Example base icon
        iconSize: [32, 32],
        iconAnchor: [16, 32],
        popupAnchor: [0, -32]
      })
    }).addTo(leafletMapRef.current!);
    droneBaseMarkerRef.current.bindTooltip('Drone Base', {permanent: true, direction: 'top'});
  }, [droneBase, areaPoints]);

  useEffect(() => {
    if (!mapRef.current) return;
    if (leafletMapRef.current) return; // Prevent double init

    // Create map
    const map = L.map(mapRef.current, {
      zoomControl: false,
      dragging: false,
      scrollWheelZoom: false,
      doubleClickZoom: false,
      boxZoom: false,
      keyboard: false,
      touchZoom: false,
    }).setView(centerCoord, 15);
    leafletMapRef.current = map;

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors',
      maxZoom: 15,
      minZoom: 15
    }).addTo(map);

    // Draw initial polygon (empty)
    polygonRef.current = L.polygon(pointsRef.current, {
      color: 'red',
      fillColor: 'red',
      fillOpacity: 0.25,
      weight: 3
    }).addTo(map);

    // Draw marker at center
    markerRef.current = L.marker(centerCoord, {
      icon: L.icon({
        iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png',
        shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
        iconSize: [25, 41],
        iconAnchor: [12, 41],
        popupAnchor: [1, -34],
        shadowSize: [41, 41]
      })
    }).addTo(map).bindTooltip('Facultad de Ciencias', {permanent: true, direction: 'top'});

    // Helper to clear draggable markers
    function clearDraggableMarkers() {
      draggableMarkersRef.current.forEach(m => m.remove());
      draggableMarkersRef.current = [];
    }

    // Helper to add draggable markers for each polygon point
    function addDraggableMarkers() {
      clearDraggableMarkers();
      pointsRef.current.forEach((p, idx) => {
        const marker = L.marker(p, {
          draggable: true,
          icon: L.divIcon({
            className: 'point-marker',
            html: `<div style="width: 14px; height: 14px; background: #f03; border: 2px solid white; border-radius: 50%; box-shadow: 0 0 5px rgba(0,0,0,0.5);"></div>`,
            iconSize: [14, 14],
            iconAnchor: [7, 7]
          })
        }).addTo(map);
        marker.on('drag', (e) => {
          const latlng = (e.target as L.Marker).getLatLng();
          pointsRef.current[idx] = [latlng.lat, latlng.lng];
          if (polygonRef.current) {
            polygonRef.current.setLatLngs(pointsRef.current);
          }
          onAreaChange([...pointsRef.current]);
        });
        draggableMarkersRef.current.push(marker);
      });
    }

    // Click to add points
    map.on('click', (e: L.LeafletMouseEvent) => {
      pointsRef.current.push([e.latlng.lat, e.latlng.lng]);
      onAreaChange([...pointsRef.current]);
      if (polygonRef.current) {
        polygonRef.current.setLatLngs(pointsRef.current);
      }
      addDraggableMarkers();
    });

    // Right-click to clear
    map.on('contextmenu', () => {
      pointsRef.current = [];
      onAreaChange([]);
      if (polygonRef.current) {
        polygonRef.current.setLatLngs([]);
      }
      clearDraggableMarkers();
    });

    // Add draggable markers if points exist (should be empty at first)
    addDraggableMarkers();

    // Cleanup on unmount
    return () => {
      clearDraggableMarkers();
      droneMarkersRef.current.forEach(m => m.remove());
      map.remove();
      leafletMapRef.current = null;
    };
  }, [onAreaChange]);

  // Patrol drones logic (animated)
  React.useEffect(() => {
    if (!leafletMapRef.current) return;
    // Remove old drone markers and trails
    droneMarkersRef.current.forEach(m => m.remove());
    droneMarkersRef.current = [];
    droneTrailRefs.current.forEach(t => t.remove());
    droneTrailRefs.current = [];

    // Polygon must be valid
    const isValidPolygon = areaPoints.length >= 3 && areaPoints.every(([lat, lng]) => Math.abs(lat) <= 90 && Math.abs(lng) <= 180);
    if (droneCount === 0 || !isValidPolygon) return;

    // Setup patrol service
    if (!patrolServiceRef.current || patrolServiceRef.current.getDrones().length !== droneCount) {
      patrolServiceRef.current = new DronePatrolService(
        areaPoints.map(([lat, lng]) => ({ lat, lng })),
        droneCount,
        0.000005, // speed (extremely slow)
      );
      // Set all drones to start from base
      const drones = patrolServiceRef.current.getDrones();
      drones.forEach(drone => {
        drone.position = { lat: droneBase[0], lng: droneBase[1] };
        drone.trail = [{ lat: droneBase[0], lng: droneBase[1] }];
      });
    } else {
      patrolServiceRef.current.setPolygon(areaPoints.map(([lat, lng]) => ({ lat, lng })));
      // Set all drones to start from base
      const drones = patrolServiceRef.current.getDrones();
      drones.forEach(drone => {
        drone.position = { lat: droneBase[0], lng: droneBase[1] };
        drone.trail = [{ lat: droneBase[0], lng: droneBase[1] }];
      });
    }

    // Animation loop
    let running = true;
    function animate() {
      if (!running) return;
      const drones = patrolServiceRef.current!.step();
      // Remove old markers and trails
      droneMarkersRef.current.forEach(m => m.remove());
      droneMarkersRef.current = [];
      droneTrailRefs.current.forEach(t => t.remove());
      droneTrailRefs.current = [];
      // Draw drones and trails
      drones.forEach((drone, idx) => {
        const marker = L.marker([drone.position.lat, drone.position.lng], {
          icon: L.icon({
            iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-blue.png',
            shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
            iconSize: [25, 41],
            iconAnchor: [12, 41],
            popupAnchor: [1, -34],
            shadowSize: [41, 41]
          })
        }).addTo(leafletMapRef.current!);
        marker.bindTooltip(`Drone ${idx+1}`, {permanent: false, direction: 'top'});
        droneMarkersRef.current.push(marker);
        // Draw trail
        const trailLatLngs = drone.trail.map(p => [p.lat, p.lng] as [number, number]);
        const trail = L.polyline(trailLatLngs, {
          color: '#44aaff',
          weight: 3,
          opacity: 0.6,
          dashArray: '6, 8'
        }).addTo(leafletMapRef.current!);
        droneTrailRefs.current.push(trail);
      });
      requestAnimationFrame(animate);
    }
    animate();
    return () => { running = false; };
  }, [droneCount, areaPoints, droneBase]);

  // Grid points visualization state
  const [showGrid, setShowGrid] = React.useState(false);
  const [gridPoints, setGridPoints] = React.useState<Point[]>([]);
  const gridMarkersRef = useRef<L.CircleMarker[]>([]);
  const gridMapRef = useRef<HTMLDivElement>(null);
  const gridLeafletMapRef = useRef<L.Map | null>(null);
  const gridPolygonRef = useRef<L.Polygon | null>(null);
  const gridDotsRef = useRef<L.CircleMarker[]>([]);

  // Effect to compute grid points
  React.useEffect(() => {
    // Only show if polygon is valid
    const isValidPolygon = areaPoints.length >= 3 && areaPoints.every(([lat, lng]) => Math.abs(lat) <= 90 && Math.abs(lng) <= 180);
    if (!isValidPolygon || !patrolServiceRef.current) {
      setGridPoints([]);
      return;
    }
    if (showGrid) {
      const points: Point[] = patrolServiceRef.current.getGridPoints(0.001);
      setGridPoints(points);
    } else {
      setGridPoints([]);
    }
  }, [showGrid, areaPoints, droneCount]);

  // Effect to render grid points and polygon in separate map
  React.useEffect(() => {
    if (!showGrid) {
      // Cleanup grid map
      if (gridLeafletMapRef.current) {
        gridLeafletMapRef.current.remove();
        gridLeafletMapRef.current = null;
      }
      gridDotsRef.current.forEach(m => m.remove());
      gridDotsRef.current = [];
      gridPolygonRef.current = null;
      return;
    }
    if (!gridMapRef.current) return;
    // Remove previous map
    if (gridLeafletMapRef.current) {
      gridLeafletMapRef.current.remove();
      gridLeafletMapRef.current = null;
    }
    // Create new map
    const map = L.map(gridMapRef.current, {
      zoomControl: false,
      dragging: false,
      scrollWheelZoom: false,
      doubleClickZoom: false,
      boxZoom: false,
      keyboard: false,
      touchZoom: false,
    }).setView(centerCoord, 15);
    gridLeafletMapRef.current = map;
    // No tile layer, just white background
    map.getContainer().style.background = '#fff';
    // Draw polygon border only
    if (areaPoints.length >= 3) {
      gridPolygonRef.current = L.polygon(areaPoints, {
        color: '#222',
        fillColor: '#fff',
        fillOpacity: 0,
        weight: 2
      }).addTo(map);
    }
    // Draw grid points as yellow dots
    gridDotsRef.current.forEach(m => m.remove());
    gridDotsRef.current = [];
    gridPoints.forEach((p) => {
      const marker = L.circleMarker([p.lat, p.lng], {
        radius: 3,
        color: '#ffcc00',
        fillColor: '#ffcc00',
        fillOpacity: 1,
        weight: 0
      }).addTo(map);
      gridDotsRef.current.push(marker);
    });
    // Cleanup on unmount
    return () => {
      if (gridLeafletMapRef.current) {
        gridLeafletMapRef.current.remove();
        gridLeafletMapRef.current = null;
      }
      gridDotsRef.current.forEach(m => m.remove());
      gridDotsRef.current = [];
      gridPolygonRef.current = null;
    };
  }, [showGrid, gridPoints, areaPoints]);

  // Survivor state
  const [survivorCount, setSurvivorCount] = React.useState(0);
  const survivorMarkersRef = useRef<L.Marker[]>([]);

  // Place survivors randomly inside polygon when survivorCount changes
  React.useEffect(() => {
    if (!leafletMapRef.current) return;
    // Remove old survivor markers
    survivorMarkersRef.current.forEach(m => m.remove());
    survivorMarkersRef.current = [];
    // Only show if polygon is valid
    const isValidPolygon = areaPoints.length >= 3 && areaPoints.every(([lat, lng]) => Math.abs(lat) <= 90 && Math.abs(lng) <= 180);
    if (!isValidPolygon || survivorCount === 0 || !patrolServiceRef.current) return;
    // Get grid points for placement
    const gridPoints: Point[] = patrolServiceRef.current.getGridPoints(0.001);
    // Pick random points for survivors
    const survivors: Point[] = [];
    for (let i = 0; i < survivorCount && gridPoints.length > 0; i++) {
      const idx = Math.floor(Math.random() * gridPoints.length);
      survivors.push(gridPoints[idx]);
    }
    survivors.forEach((p, idx) => {
      const marker = L.marker([p.lat, p.lng], {
        icon: L.icon({
          iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png',
          shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
          iconSize: [25, 41],
          iconAnchor: [12, 41],
          popupAnchor: [1, -34],
          shadowSize: [41, 41]
        })
      }).addTo(leafletMapRef.current!);
      marker.bindTooltip(`Survivor ${idx+1}`, {permanent: false, direction: 'top'});
      survivorMarkersRef.current.push(marker);
    });
  }, [survivorCount, areaPoints, droneCount]);

  // Render main map and grid map stacked vertically
  return (
    <React.Fragment>
      <div style={{ width: '100%' }}>
        <div style={{ width: '100%', marginBottom: 24, display: 'flex', alignItems: 'center' }}>
          <label style={{ fontWeight: 'bold', marginRight: 12, color: '#d32f2f' }}>Survivor Count (Red):</label>
          <input
            type="number"
            min={0}
            max={100}
            value={survivorCount}
            onChange={e => setSurvivorCount(Number(e.target.value))}
            style={{ width: 60, marginRight: 24, padding: '4px 8px', borderRadius: '6px', border: '1px solid #d32f2f', fontSize: 16, color: '#d32f2f' }}
          />
          <label style={{ fontWeight: 'bold', marginRight: 12 }}>Drone Count:</label>
          <input
            type="number"
            min={0}
            max={100}
            value={droneCount}
            onChange={e => onAreaChange(areaPoints)} // keep droneCount controlled from parent
            style={{ width: 60, marginRight: 24, padding: '4px 8px', borderRadius: '6px', border: '1px solid #44aaff', fontSize: 16 }}
          />
          <button
            style={{ marginLeft: 12, padding: '6px 14px', borderRadius: '6px', background: '#44aaff', color: '#fff', border: 'none', fontWeight: 'bold', cursor: 'pointer' }}
            onClick={() => {
              // Auto-generate 4 random border points, 3 survivors, 2 drones
              const bounds = { minLat: 3.310, maxLat: 3.330, minLng: 117.590, maxLng: 117.610 };
              const autoBorder: [number, number][] = Array.from({ length: 4 }, () => [
                parseFloat((Math.random() * (bounds.maxLat - bounds.minLat) + bounds.minLat).toFixed(5)),
                parseFloat((Math.random() * (bounds.maxLng - bounds.minLng) + bounds.minLng).toFixed(5))
              ]);
              onAreaChange(autoBorder);
              setSurvivorCount(3);
              setDroneCount(2);
            }}
          >Auto Generate</button>
          <button
            style={{ marginLeft: 12, padding: '6px 14px', borderRadius: '6px', background: '#ffcc00', color: '#222', border: 'none', fontWeight: 'bold', cursor: 'pointer' }}
            onClick={() => {
              // Mock send all coordinates to backend
              const borderCoords = areaPoints.map(p => ({ lat: p[0], lng: p[1] }));
              const baseCoord = { lat: droneBase[0], lng: droneBase[1] };
              const survivorCoords = survivorMarkersRef.current.map(m => m.getLatLng());
              const droneCoords = patrolServiceRef.current ? patrolServiceRef.current.getDrones().map(d => d.position) : [];
              const payload = {
                border: borderCoords,
                base: baseCoord,
                survivors: survivorCoords,
                drones: droneCoords
              };
              alert('Mock send to backend:\n' + JSON.stringify(payload, null, 2));
            }}
          >Send All to Backend</button>
        </div>
        <div style={{ width: '100%' }}>
          <div style={{ position: 'relative', width: '100%', height: '600px', minWidth: '700px', minHeight: '500px' }}>
            <div ref={mapRef} style={{ width: '100%', height: '100%', background: '#060d14', borderRadius: '10px', boxShadow: '0 2px 16px rgba(0,0,0,0.15)' }} />
            <button
              style={{ position: 'absolute', top: 16, right: 16, zIndex: 1000, padding: '8px 16px', background: showGrid ? '#ffcc00' : '#222', color: showGrid ? '#222' : '#fff', border: 'none', borderRadius: '6px', fontWeight: 'bold', boxShadow: '0 2px 8px rgba(0,0,0,0.12)', cursor: 'pointer' }}
              onClick={() => setShowGrid(g => !g)}
            >
              {showGrid ? 'Hide Border Points' : 'Show Border Points'}
            </button>
          </div>
          {showGrid && (
            <div style={{ width: '100%', maxWidth: 700, margin: '32px auto 0 auto', height: 420, minHeight: 320, position: 'relative', background: '#fff', borderRadius: '10px', boxShadow: '0 2px 16px rgba(0,0,0,0.15)' }}>
              <div ref={gridMapRef} style={{ width: '100%', height: '100%' }} />
              <div style={{ position: 'absolute', top: 16, left: 16, zIndex: 1000, color: '#222', fontWeight: 'bold', fontSize: 18 }}>Border Points Map</div>
              <div style={{ position: 'absolute', top: 56, left: 16, zIndex: 1000, color: '#222', fontSize: 13, maxHeight: 320, overflowY: 'auto', width: 380 }}>
                <div>Count: {areaPoints.length}</div>
                {areaPoints.map((p, idx) => (
                  <div key={idx}>Border [{p[0].toFixed(5)}, {p[1].toFixed(5)}]</div>
                ))}
                <div style={{ marginTop: 12, fontWeight: 'bold' }}>Drone Base:</div>
                <div>[{droneBase[0].toFixed(5)}, {droneBase[1].toFixed(5)}]</div>
                {survivorCount > 0 && (
                  <div style={{ marginTop: 12, fontWeight: 'bold' }}>Survivors:</div>
                )}
                {survivorMarkersRef.current.map((marker, idx) => {
                  const latlng = marker.getLatLng();
                  return <div key={idx}>Survivor [{latlng.lat.toFixed(5)}, {latlng.lng.toFixed(5)}]</div>;
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </React.Fragment>
  );
}
