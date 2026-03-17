import React from 'react';
import './index.css';
import Map from './components/Map';


interface Drone {
  id: string;
  battery: number;
  status: 'idle' | 'flying' | 'searching' | 'returning';
}

export default function App() {
  const [areaPoints, setAreaPoints] = React.useState<[number, number][]>([]);
  const [droneCount, setDroneCount] = React.useState(0);

  return (
    <div className="app-container">
      <aside className="sidebar">
        <header className="header">
          <h1>MultiUAV Console</h1>
          <p style={{fontSize: '0.7rem', color: 'var(--text-secondary)', marginTop: '4px'}}>
            INTERFACE MOCKUP v2.0
          </p>
        </header>

        <section className="nav-section">
          <div className="section-title" style={{fontSize: '0.75rem', fontWeight: 'bold', marginBottom: '12px', color: 'var(--text-secondary)', textTransform: 'uppercase'}}>
            Mock Controls
          </div>
          <div className="mock-controls" style={{display: 'flex', flexDirection: 'column', gap: '10px'}}>
            <button className="btn" style={{textAlign: 'left', fontSize: '0.8rem'}}>
              📡 CONNECT DATA LINK
            </button>
            <button className="btn" style={{textAlign: 'left', fontSize: '0.8rem'}}>
              🛰️ SYNC SATELLITE TILE
            </button>
            <button className="btn" style={{textAlign: 'left', fontSize: '0.8rem'}}>
              🔍 ANALYZE SECTOR
            </button>
            <div className="glass" style={{padding: '12px', marginTop: '10px'}}>
              <div style={{fontSize: '0.7rem', color: 'var(--text-secondary)', marginBottom: '8px', textTransform: 'uppercase'}}>
                System Status
              </div>
              <div style={{display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.8rem'}}>
                <div style={{width: '8px', height: '8px', borderRadius: '50%', background: 'var(--success-color)'}}></div>
                <span>SYSTEM READY</span>
              </div>
            </div>
          </div>
        </section>
        <footer className="mission-control">
          <button className="btn btn-primary" onClick={() => alert('Mock Action Triggered')}>
            MOCK ACTION
          </button>
        </footer>
      </aside>

      <main className="main-content">
        <div className="map-container">
          {/* Map will be here */}
          <div style={{
            position: 'absolute', 
            top: '20px', 
            right: '20px', 
            zIndex: 1000, 
            padding: '10px 15px',
            background: 'rgba(10, 20, 35, 0.9)',
            border: '1px solid var(--border-color)',
            borderRadius: '4px',
            fontSize: '0.8rem'
          }}>
            <div style={{color: 'var(--accent-color)', marginBottom: '4px'}}>MOCK PARAMETERS</div>
            <div style={{color: 'var(--text-secondary)'}}>Shaded Area: <span style={{color: 'var(--text-primary)'}}>{areaPoints.length > 0 ? `${areaPoints.length} points` : 'Pending Selection'}</span></div>
            <div style={{color: 'var(--text-secondary)', marginTop: '4px', fontSize: '0.7rem'}}>
              Click map to shade area. Right-click to clear.
            </div>
            <div style={{marginTop: '10px'}}>
              <label htmlFor="droneCount" style={{color: 'var(--text-secondary)', fontSize: '0.8rem', marginRight: '8px'}}>Drone Number:</label>
              <input
                id="droneCount"
                type="number"
                min={0}
                max={4}
                value={droneCount}
                onChange={e => setDroneCount(Math.max(0, Math.min(4, Number(e.target.value))))}
                style={{width: '50px', fontSize: '0.9rem', padding: '2px 6px', borderRadius: '4px', border: '1px solid var(--border-color)', background: '#1a2330', color: 'var(--text-primary)'}}
              />
            </div>
          </div>
          <Map onAreaChange={setAreaPoints} droneCount={droneCount} areaPoints={areaPoints} />
        </div>
      </main>
    </div>
  );
}
