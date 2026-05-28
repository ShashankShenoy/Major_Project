// Minimal Fusion Dashboard - Debugged Version

console.log('✅ app-minimal.js loaded');

// Setup error tracking
window.addEventListener('error', (e) => console.error('Error:', e.message, e.error));

// Global state
let ws = null;
let map = null;
let mapLoaded = false;
let latestShips = [];

// Initialize WebSocket
function initWebSocket() {
  try {
    ws = new WebSocket(`ws://${window.location.host}/ws`);
    
    ws.onopen = () => {
      console.log('✅ WebSocket connected');
      // Start tracking Singapore Strait
      const msg = { type: 'start', lat: 1.264, lon: 103.84 };
      ws.send(JSON.stringify(msg));
    };
    
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.ships) {
        latestShips = data.ships;
        console.log(`📊 Received ${data.ships.length} ships`);
        if (map && mapLoaded) {
          renderShips();
        }
      }
    };
    
    ws.onerror = (e) => console.error('WebSocket error:', e);
    ws.onclose = () => console.warn('WebSocket closed');
    
  } catch (e) {
    console.error('Failed to create WebSocket:', e);
  }
}

// Initialize map
function initMap() {
  try {
    console.log('Initializing map...');
    map = new maplibregl.Map({
      container: 'map',
      style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
      center: [103.84, 1.264],
      zoom: 8
    });
    
    map.on('load', () => {
      mapLoaded = true;
      console.log('✅ Map loaded');
      
      // Add ship layer
      map.addSource('ships', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] }
      });
      
      map.addLayer({
        id: 'ships-layer',
        type: 'circle',
        source: 'ships',
        paint: {
          'circle-radius': 8,
          'circle-color': '#22c55e',
          'circle-stroke-width': 2,
          'circle-stroke-color': '#fff'
        }
      });
    });
    
  } catch (e) {
    console.error('Failed to initialize map:', e);
  }
}

function renderShips() {
  if (!map || !mapLoaded) return;
  
  const features = latestShips
    .filter(s => s.pos && s.pos.length === 2)
    .map(s => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: s.pos },
      properties: { mmsi: s.mmsi, name: s.name || 'Unknown' }
    }));
  
  const source = map.getSource('ships');
  if (source) {
    source.setData({ type: 'FeatureCollection', features });
  }
}

// Start on page load
document.addEventListener('DOMContentLoaded', () => {
  console.log('🚀 Starting Fusion Dashboard');
  initWebSocket();
  initMap();
});

console.log('✅ Initialization functions registered');
