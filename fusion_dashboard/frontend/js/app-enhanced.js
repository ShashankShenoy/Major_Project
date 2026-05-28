// Fusion Maritime Intelligence System - Enhanced Version

console.log('✅ app-enhanced.js loaded');

// Setup error tracking
window.addEventListener('error', (e) => console.error('Error:', e.message, e.error));

// Global state
let ws = null;
let map = null;
let mapLoaded = false;
let latestShips = [];
let aisShips = {};
let cvShips = {};
let matchedShips = new Set();
let lstmPredictions = [];
let cameraStatus = { status: 'Idle', location: [1.264, 103.84], fov_radius: 2.0 };

// Default Singapore Strait location
const DEFAULT_LOCATION = { lat: 1.264, lon: 103.84 };

// Initialize WebSocket
function initWebSocket() {
  try {
    ws = new WebSocket(`ws://${window.location.host}/ws`);
    
    ws.onopen = () => {
      console.log('✅ WebSocket connected');
      // Send default location to start tracking
      sendCameraLocation(DEFAULT_LOCATION.lat, DEFAULT_LOCATION.lon);
    };
    
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        
        if (data.type === "frame" && data.ships) {
          aisShips = {};
          cvShips = {};
          matchedShips = new Set();
          lstmPredictions = [];
          
          data.ships.forEach(ship => {
            if (ship.source === "CAMERA") {
              // Populate gps array so it gets rendered by the map
              if (ship.gps_lat !== undefined && ship.gps_lon !== undefined) {
                ship.gps = [ship.gps_lon, ship.gps_lat];
              }
              cvShips[ship.id] = ship;
              if (ship.is_matched_to_ais && ship.matched_ais_mmsi) {
                matchedShips.add(String(ship.matched_ais_mmsi));
              }
            } else if (ship.source === "AIS") {
              aisShips[ship.mmsi || ship.id] = ship;
            }
            
            // Extract LSTM from predicted_path_gps
            if (ship.predicted_path_gps && ship.predicted_path_gps.length > 0) {
              lstmPredictions.push({
                mmsi: ship.mmsi || ship.id,
                path: ship.predicted_path_gps.map(p => [p[1], p[0]]) // to [lon, lat] for MapLibre
              });
            }
          });
          
          latestShips = data.ships;
        }
        
        // Handle camera status
        if (data.camera_status) {
          cameraStatus = data.camera_status;
          updateCameraStatus();
        }
        
        // Handle video frame
        if (data.video_frame) {
          updateVideoFrame(data.video_frame);
        }
        
        // Update UI
        updateHybridDetailsDisplay();
        
        // Render all ships
        if (map && mapLoaded) {
          renderAllShips();
        }
        
      } catch (e) {
        console.error('Error processing message:', e);
      }
    };
    
    ws.onerror = (e) => console.error('WebSocket error:', e);
    ws.onclose = () => console.warn('WebSocket closed');
    
  } catch (e) {
    console.error('Failed to create WebSocket:', e);
  }
}

function sendCameraLocation(lat, lon) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    const msg = { type: 'start', lat, lon };
    ws.send(JSON.stringify(msg));
    console.log(`📍 Sent tracking start: ${lat}, ${lon}`);
  }
}

// Initialize map
function initMap() {
  try {
    console.log('Initializing map...');
    map = new maplibregl.Map({
      container: 'map',
      style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
      center: [DEFAULT_LOCATION.lon, DEFAULT_LOCATION.lat],
      zoom: 8
    });
    
    map.on('load', () => {
      mapLoaded = true;
      console.log('✅ Map loaded');
      
      // Add geojson sources for different layers
      map.addSource('ais-ships', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
        promoteId: 'id'
      });
      
      map.addSource('cv-ships', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
        promoteId: 'id'
      });
      
      map.addSource('lstm-predictions', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] }
      });
      
      map.addSource('collision-zones', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] }
      });
      
      // Add collision zones layer (underneath ships so it doesn't hide their outlines)
      map.addLayer({
        id: 'collision-zones',
        type: 'circle',
        source: 'collision-zones',
        paint: {
          "circle-radius": 12,
          "circle-color": "#dc2626",
          "circle-opacity": 0.4,
          "circle-stroke-width": 0
        }
      });
      
      // Add AIS ships layer
      map.addLayer({
        id: 'ais-ships-layer',
        type: 'circle',
        source: 'ais-ships',
        paint: {
          'circle-radius': [
            'case',
            ['boolean', ['feature-state', 'selected'], false],
            11,
            6.5
          ],
          'circle-color': '#22c55e', // Green for ALL ships
          'circle-stroke-width': 2,
          'circle-stroke-color': [
            'case',
            ['boolean', ['get', 'matched'], false],
            '#eab308', // Yellow outline for matched
            '#ffffff'  // Default white outline
          ]
        }
      });
      
      // Add CV ships layer
      map.addLayer({
        id: 'cv-ships-layer',
        type: 'circle',
        source: 'cv-ships',
        paint: {
          'circle-radius': 6.5,
          'circle-color': '#22c55e', // Green for all
          'circle-stroke-width': 2,
          'circle-stroke-color': '#eab308' // Yellow outline since CV is mapped from camera
        }
      });
      
      // Add LSTM predictions layer
      map.addLayer({
        id: 'lstm-layer',
        type: 'line',
        source: 'lstm-predictions',
        paint: {
          'line-color': ['get', 'color'],
          'line-width': 2,
          'line-dasharray': [4, 4]
        }
      });
      
      // Add tracks layer
      map.addLayer({
        id: 'tracks-layer',
        type: 'line',
        source: 'ais-ships',
        paint: {
          'line-color': '#6366f1',
          'line-width': 1,
          'line-opacity': 0.5
        }
      });
      
    }); // Close map.on('load')
    
  } catch (e) {
    console.error('Failed to initialize map:', e);
  }
}

function renderAllShips() {
  if (!map || !mapLoaded) return;
  
  const allShips = [...Object.values(aisShips), ...Object.values(cvShips)].filter(s => s.gps && s.gps.length === 2);
  
  // Calculate risk for a ship
  const getRisk = (ship) => {
    return allShips.some(other => {
      if (other.id === ship.id) return false;
      const dist = Math.sqrt(Math.pow(ship.gps[0] - other.gps[0], 2) + Math.pow(ship.gps[1] - other.gps[1], 2));
      return dist < 0.01 && Math.abs((ship.cog || 0) - (other.cog || 0)) < 30;
    });
  };
  
  const collisions = [];
  
  // Build AIS features
  const aisFeatures = Object.values(aisShips)
    .filter(s => s.gps && s.gps.length === 2)
    .map(s => {
      const hasRisk = getRisk(s);
      if (hasRisk) collisions.push({ type: 'Feature', geometry: { type: 'Point', coordinates: s.gps } });
      return {
        type: 'Feature',
        id: s.id,
        geometry: { type: 'Point', coordinates: s.gps },
        properties: { 
          mmsi: s.mmsi, 
          name: s.name || 'Unknown',
          source: 'AIS',
          sog: s.sog,
          cog: s.cog,
          risk: hasRisk,
          matched: matchedShips.has(String(s.mmsi || s.id))
        }
      };
    });
  
  // Build CV features
  const cvFeatures = Object.values(cvShips)
    .filter(s => s.gps && s.gps.length === 2)
    .map(s => {
      const hasRisk = getRisk(s);
      if (hasRisk) collisions.push({ type: 'Feature', geometry: { type: 'Point', coordinates: s.gps } });
      return {
        type: 'Feature',
        id: s.id,
        geometry: { type: 'Point', coordinates: s.gps },
        properties: { 
          id: s.id,
          name: s.name || 'CV Detection',
          source: 'CV',
          confidence: s.confidence,
          risk: hasRisk,
          matched: false
        }
      };
    });
  
  // Build LSTM prediction features (lines)
  const lstmFeatures = lstmPredictions
    .filter(pred => pred.path && pred.path.length > 1)
    .map((pred, idx) => {
      // Generate a unique color based on mmsi or id
      const idStr = String(pred.mmsi || idx);
      const hash = idStr.split('').reduce((a,b)=>{a=((a<<5)-a)+b.charCodeAt(0);return a&a},0);
      const color = `hsl(${Math.abs(hash) % 360}, 80%, 60%)`;
      return {
        type: 'Feature',
        id: `lstm_${idx}`,
        geometry: { 
          type: 'LineString', 
          coordinates: pred.path 
        },
        properties: { predicted: true, color: color }
      };
    });
  
  // Update sources
  const aisSource = map.getSource('ais-ships');
  const cvSource = map.getSource('cv-ships');
  const colSource = map.getSource('collision-zones');
  
  if (aisSource) aisSource.setData({ type: 'FeatureCollection', features: aisFeatures });
  if (cvSource) cvSource.setData({ type: 'FeatureCollection', features: cvFeatures });
  if (colSource) colSource.setData({ type: 'FeatureCollection', features: collisions });
  
  const lstmSource = map.getSource('lstm-predictions');
  if (lstmSource) {
    lstmSource.setData({ 
      type: 'FeatureCollection', 
      features: lstmFeatures 
    });
  }
  
  // Update Analytics Metrics
  const speeds = allShips.map(s => s.sog || 0);
  const maxSpeed = speeds.length ? Math.max(...speeds) : 0;
  const avgSpeed = speeds.length ? (speeds.reduce((a, b) => a + b, 0) / speeds.length) : 0;
  const movingCount = allShips.filter(s => (s.sog || 0) > 1).length;
  const anchoredCount = allShips.length - movingCount;
  
  const maxSpeedEl = document.getElementById("metricMaxSpeed");
  const avgSpeedEl = document.getElementById("metricAvgSpeed");
  const movingEl = document.getElementById("metricMoving");
  const anchoredEl = document.getElementById("metricAnchored");
  const headerVesselsEl = document.getElementById("headerVessels");
  const headerAlertsEl = document.getElementById("headerAlerts");
  const headerAvgSpeedEl = document.getElementById("headerAvgSpeed");
  
  if (maxSpeedEl) maxSpeedEl.innerText = maxSpeed.toFixed(1);
  if (avgSpeedEl) avgSpeedEl.innerText = avgSpeed.toFixed(1);
  if (movingEl) movingEl.innerText = movingCount;
  if (anchoredEl) anchoredEl.innerText = anchoredCount;
  if (headerVesselsEl) headerVesselsEl.innerText = allShips.length;
  if (headerAlertsEl) headerAlertsEl.innerText = collisions.length;
  if (headerAvgSpeedEl) headerAvgSpeedEl.innerText = `${avgSpeed.toFixed(1)} kts`;
}

function updateCameraStatus() {
  const statusEl = document.getElementById('cameraStatusText');
  const locationEl = document.getElementById('cameraLocationText');
  const fovEl = document.getElementById('cameraFOVText');
  
  if (statusEl) {
    statusEl.textContent = cameraStatus.available ? 'Active 🟢' : 'Idle ⚪';
    statusEl.style.color = cameraStatus.available ? '#4ade80' : '#9ca3af';
  }
  if (locationEl && cameraStatus.lat !== undefined && cameraStatus.lon !== undefined) {
    locationEl.textContent = `${cameraStatus.lat.toFixed(2)}°N, ${cameraStatus.lon.toFixed(2)}°E`;
  }
  if (fovEl && cameraStatus.fov_km !== undefined) {
    fovEl.textContent = `${cameraStatus.fov_km} km`;
  }
}

function updateVideoFrame(frameData) {
  const img = document.getElementById('videoFrame');
  if (img && frameData) {
    img.style.display = 'block';
    img.src = `data:image/jpeg;base64,${frameData}`;
    const placeholder = document.getElementById('videoPlaceholder');
    if (placeholder) placeholder.style.display = 'none';
  }
}

function updateHybridDetailsDisplay() {
  const aisCount = Object.keys(aisShips).length;
  const cvCount = Object.keys(cvShips).length;
  const matchedCount = matchedShips.size;
  const lstmCount = lstmPredictions.length;
  
  const aisEl = document.getElementById('aisShipCountNew');
  const cvEl = document.getElementById('cvShipCountNew');
  const matchedEl = document.getElementById('matchedCountNew');
  const lstmEl = document.getElementById('lstmCountNew');
  
  if (aisEl) aisEl.innerText = aisCount;
  if (cvEl) cvEl.innerText = cvCount;
  if (matchedEl) matchedEl.innerText = matchedCount;
  if (lstmEl) lstmEl.innerText = lstmCount;
  
  console.log(`[DEBUG UI] Vessels: ${aisCount + cvCount}, AIS: ${aisCount}, CV: ${cvCount}, Matched: ${matchedCount}, LSTM: ${lstmCount}`);
  
  // Update LSTM predictions list
  const lstmListEl = document.getElementById('lstmShipsList');
  if (lstmListEl) {
    if (lstmPredictions.length > 0) {
      lstmListEl.innerHTML = lstmPredictions
        .map(pred => `<div style="padding:4px; font-size:12px;">🚀 ${pred.mmsi || 'Ship'}</div>`)
        .join('');
    } else {
      lstmListEl.innerHTML = '<div style="color: #999; text-align: center; padding: 10px;">No LSTM predictions yet</div>';
    }
  }
}

// Handle Load Video button (Handled by index.html switchVideo)
function setupVideoLoading() {
  console.log('✅ Video loading handled by index.html switchVideo()');
}

// Start on page load
document.addEventListener('DOMContentLoaded', () => {
  console.log('🚀 Starting Fusion Dashboard (Enhanced)');
  initWebSocket();
  initMap();
  setupVideoLoading();
});

console.log('✅ Initialization functions registered');
