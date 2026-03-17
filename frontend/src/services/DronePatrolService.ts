// ...existing code...
// DronePatrolService.ts
// Handles drone movement and trail logic for patrolling a polygon area

export interface Point {
  lat: number;
  lng: number;
}

export interface DroneState {
  position: Point;
  trail: Point[];
}

export class DronePatrolService {
    // Returns all grid points inside the polygon
    public getGridPoints(gridStep: number = 0.001): Point[] {
      if (!this.polygon || this.polygon.length < 3) return [];
      let minLat = Math.min(...this.polygon.map((p: Point) => p.lat));
      let maxLat = Math.max(...this.polygon.map((p: Point) => p.lat));
      let minLng = Math.min(...this.polygon.map((p: Point) => p.lng));
      let maxLng = Math.max(...this.polygon.map((p: Point) => p.lng));
      const points: Point[] = [];
      for (let lat = minLat; lat <= maxLat; lat += gridStep) {
        for (let lng = minLng; lng <= maxLng; lng += gridStep) {
          if (this.pointInPolygon({ lat, lng }, this.polygon)) {
            points.push({ lat, lng });
          }
        }
      }
      return points;
    }
  private polygon: Point[];
  private droneCount: number;
  private speed: number;
  private drones: DroneState[];
  private t: number;
  private patrolWaypoints: Point[][];
  private waypointIdx: number[];

  constructor(polygon: Point[], droneCount: number, speed = 0.0000000000005) {
    this.polygon = polygon;
    this.droneCount = droneCount;
    this.speed = speed;
    this.t = 0;
    this.patrolWaypoints = this.generatePatrolWaypoints(polygon, droneCount);
    this.waypointIdx = Array(droneCount).fill(0);
    this.drones = this.initDrones();
  }

  private initDrones(): DroneState[] {
    const drones: DroneState[] = [];
    for (let i = 0; i < this.droneCount; i++) {
      const wp = this.patrolWaypoints[i][0] || { lat: 0, lng: 0 };
      drones.push({ position: wp, trail: [wp] });
    }
    return drones;
  }

  // Generate grid waypoints inside polygon for each drone
  private generatePatrolWaypoints(polygon: Point[], droneCount: number): Point[][] {
    // Bounding box
    if (polygon.length < 3) return Array(droneCount).fill([]);
    let minLat = Math.min(...polygon.map(p => p.lat));
    let maxLat = Math.max(...polygon.map(p => p.lat));
    let minLng = Math.min(...polygon.map(p => p.lng));
    let maxLng = Math.max(...polygon.map(p => p.lng));
    // Simple grid
    const gridStep = 0.001;
    const points: Point[] = [];
    for (let lat = minLat; lat <= maxLat; lat += gridStep) {
      for (let lng = minLng; lng <= maxLng; lng += gridStep) {
        if (this.pointInPolygon({ lat, lng }, polygon)) {
          points.push({ lat, lng });
        }
      }
    }
    // Split points among drones
    const perDrone = Math.ceil(points.length / droneCount);
    const result: Point[][] = [];
    for (let i = 0; i < droneCount; i++) {
      result.push(points.slice(i * perDrone, (i + 1) * perDrone));
    }
    // If not enough, fill with random
    for (let i = 0; i < droneCount; i++) {
      if (result[i].length === 0 && points.length > 0) {
        result[i].push(points[Math.floor(Math.random() * points.length)]);
      }
    }
    return result;
  }

  // Point-in-polygon (ray casting)
  private pointInPolygon(point: Point, polygon: Point[]): boolean {
    let inside = false;
    for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
      const xi = polygon[i].lat, yi = polygon[i].lng;
      const xj = polygon[j].lat, yj = polygon[j].lng;
      const intersect = ((yi > point.lng) !== (yj > point.lng)) &&
        (point.lat < (xj - xi) * (point.lng - yi) / (yj - yi) + xi);
      if (intersect) inside = !inside;
    }
    return inside;
  }

  // Call this every animation frame
  step() {
    const n = this.droneCount;
    for (let i = 0; i < n; i++) {
      const waypoints = this.patrolWaypoints[i];
      if (!waypoints || waypoints.length === 0) continue;
      let idx = this.waypointIdx[i];
      let curr = this.drones[i].position;
      let next = waypoints[idx];
      // Move towards next waypoint
      const dist = this.dist(curr, next);
      // Smoother movement: only switch waypoint if very close, interpolate otherwise
      const stepSize = this.speed * 2;
      let ratio = dist === 0 ? 0 : Math.min(1, stepSize / dist);
      // If very close, snap to waypoint and only then pick next
      if (dist < stepSize) {
        ratio = 1;
      }
      const moveLat = curr.lat + (next.lat - curr.lat) * ratio;
      const moveLng = curr.lng + (next.lng - curr.lng) * ratio;
      const pos = { lat: moveLat, lng: moveLng };
      this.drones[i].position = pos;
      this.drones[i].trail.push(pos);
      if (this.drones[i].trail.length > 100) {
        this.drones[i].trail.shift();
      }
      // Only pick next waypoint after fully arriving (no jump)
      if (ratio === 1 && dist < stepSize) {
        let newIdx = idx;
        while (waypoints.length > 1 && newIdx === idx) {
          newIdx = Math.floor(Math.random() * waypoints.length);
        }
        this.waypointIdx[i] = newIdx;
      }
    }
    return this.drones;
  }

  getPolygonLength(pts: Point[]): number {
    let len = 0;
    for (let i = 1; i < pts.length; i++) {
      len += this.dist(pts[i - 1], pts[i]);
    }
    if (pts.length > 2) {
      len += this.dist(pts[pts.length - 1], pts[0]);
    }
    return len;
  }

  getPointAlongPolygon(pts: Point[], distTarget: number): Point {
    let dist = 0;
    for (let i = 1; i < pts.length; i++) {
      const segLen = this.dist(pts[i - 1], pts[i]);
      if (dist + segLen >= distTarget) {
        const ratio = (distTarget - dist) / segLen;
        return {
          lat: pts[i - 1].lat + (pts[i].lat - pts[i - 1].lat) * ratio,
          lng: pts[i - 1].lng + (pts[i].lng - pts[i - 1].lng) * ratio,
        };
      }
      dist += segLen;
    }
    // Close the polygon
    if (pts.length > 2) {
      const segLen = this.dist(pts[pts.length - 1], pts[0]);
      if (dist + segLen >= distTarget) {
        const ratio = (distTarget - dist) / segLen;
        return {
          lat: pts[pts.length - 1].lat + (pts[0].lat - pts[pts.length - 1].lat) * ratio,
          lng: pts[pts.length - 1].lng + (pts[0].lng - pts[pts.length - 1].lng) * ratio,
        };
      }
    }
    return pts[0];
  }

  dist(a: Point, b: Point): number {
    return Math.sqrt((a.lat - b.lat) ** 2 + (a.lng - b.lng) ** 2);
  }

  setPolygon(polygon: Point[]) {
    this.polygon = polygon;
    // Update waypoints, but keep drone positions/trails
    this.patrolWaypoints = this.generatePatrolWaypoints(polygon, this.droneCount);
    // If drones exist, keep their positions/trails
    if (this.drones && this.drones.length === this.droneCount) {
      // No-op, keep positions
    } else {
      this.drones = this.initDrones();
    }
  }

  setDroneCount(count: number) {
    this.droneCount = count;
    this.drones = this.initDrones();
  }

  getDrones(): DroneState[] {
    return this.drones;
  }
}
