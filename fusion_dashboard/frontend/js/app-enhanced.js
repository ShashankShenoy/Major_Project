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
        
        // Handle AIS ships
        if (data.ais_ships && Array.isArray(data.ais_ships)) {
          aisShips = {};
          data.ais_ships.forEach(ship => {
            aisShips[ship.id] = ship;
          });
          console.log(`📊 Received ${data.ais_ships.length} AIS ships`);
        }
        
        // Handle CV detected ships
        if (data.cv_detected_ships && Array.isArray(data.cv_detected_ships)) {
          cvShips = {};
          data.cv_detected_ships.forEach(ship => {
            cvShips[ship.id] = ship;
          });
          console.log(`📹 Received ${data.cv_detected_ships.length} CV ships`);
        }
        
        // Handle matched ships
        if (data.matched_ships && Array.isArray(data.matched_ships)) {
          matchedShips = new Set(data.matched_ships.map(m => m.ais_id));
          console.log(`🔗 Matched ${data.matched_ships.length} ships`);
        }
        
        // Handle LSTM predictions
        if (data.lstm_predictions && Array.isArray(data.lstm_predictions)) {
          lstmPredictions = data.lstm_predictions;
          console.log(`🚀 Received ${data.lstm_predictions.length} LSTM predictions`);
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
    const msg = { type: 'camera_location', lat, lon };
    ws.send(JSON.stringify(msg));
    console.log(`📍 Sent camera location: ${lat}, ${lon}`);
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
        data: { type: 'FeatureCollection', features: [] }
      });
      
      map.addSource('cv-ships', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] }
      });
      
      map.addSource('lstm-predictions', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] }
      });
      
      // Add AIS ships layer
      map.addLayer({
        id: 'ais-ships-layer',
        type: 'circle',
        source: 'ais-ships',
        paint: {
          'circle-radius': [
            'case',
            ['boolean', ['feature-state', 'matched'], false],
            10,
            8
          ],
          'circle-color': [
            'case',
            ['boolean', ['feature-state', 'matched'], false],
            '#eab308', // Yellow for matched
            '#22c55e'  // Green for AIS only
          ],
          'circle-stroke-width': 2,
          'circle-stroke-color': '#fff'
        }
      });
      
      // Add CV ships layer
      map.addLayer({
        id: 'cv-ships-layer',
        type: 'circle',
        source: 'cv-ships',
        paint: {
          'circle-radius': 6,
          'circle-color': '#f97316', // Orange for CV only
          'circle-stroke-width': 2,
          'circle-stroke-color': '#fff'
        }
      });
      
      // Add LSTM predictions layer
      map.addLayer({
        id: 'lstm-layer',
        type: 'line',
        source: 'lstm-predictions',
        paint: {
          'line-color': '#3b82f6',
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
      
    });
    
  } catch (e) {
    console.error('Failed to initialize map:', e);
  }
}

function renderAllShips() {
  if (!map || !mapLoaded) return;
  
  // Build AIS features
  const aisFeatures = Object.values(aisShips)
    .filter(s => s.gps && s.gps.length === 2)
    .map(s => ({
      type: 'Feature',
      id: s.id,
      geometry: { type: 'Point', coordinates: s.gps },
      properties: { 
        mmsi: s.mmsi, 
        name: s.name || 'Unknown',
        source: 'AIS',
        sog: s.sog,
        cog: s.cog
      }
    }));
  
  // Build CV features
  const cvFeatures = Object.values(cvShips)
    .filter(s => s.gps && s.gps.length === 2)
    .map(s => ({
      type: 'Feature',
      id: s.id,
      geometry: { type: 'Point', coordinates: s.gps },
      properties: { 
        id: s.id,
        name: s.name || 'CV Detection',
        source: 'CV',
        confidence: s.confidence
      }
    }));
  
  // Build LSTM prediction features (lines)
  const lstmFeatures = lstmPredictions
    .filter(pred => pred.path && pred.path.length > 1)
    .map((pred, idx) => ({
      type: 'Feature',
      id: `lstm_${idx}`,
      geometry: { 
        type: 'LineString', 
        coordinates: pred.path 
      },
      properties: { predicted: true }
    }));
  
  // Update sources
  const aisSource = map.getSource('ais-ships');
  if (aisSource) {
    aisSource.setData({ 
      type: 'FeatureCollection', 
      features: aisFeatures 
    });
    
    // Set feature state for matched ships
    aisFeatures.forEach(feature => {
      const isMatched = matchedShips.has(feature.id);
      map.setFeatureState(
        { source: 'ais-ships', id: feature.id },
        { matched: isMatched }
      );
    });
  }
  
  const cvSource = map.getSource('cv-ships');
  if (cvSource) {
    cvSource.setData({ 
      type: 'FeatureCollection', 
      features: cvFeatures 
    });
  }
  
  const lstmSource = map.getSource('lstm-predictions');
  if (lstmSource) {
    lstmSource.setData({ 
      type: 'FeatureCollection', 
      features: lstmFeatures 
    });
  }
}

function updateCameraStatus() {
  const statusEl = document.getElementById('cameraStatusText');
  const locationEl = document.getElementById('cameraLocationText');
  const fovEl = document.getElementById('cameraFOVText');
  
  if (statusEl) statusEl.textContent = cameraStatus.status || 'Idle';
  if (locationEl && cameraStatus.location && cameraStatus.location.length === 2) {
    const lat = cameraStatus.location[0];
    const lon = cameraStatus.location[1];
    locationEl.textContent = `${lat.toFixed(2)}°N, ${lon.toFixed(2)}°E`;
  }
  if (fovEl && cameraStatus.fov_radius) {
    fovEl.textContent = `${cameraStatus.fov_radius} km`;
  }
}

function updateVideoFrame(frameData) {
  const videoContainer = document.getElementById('videoFrame');
  if (videoContainer && frameData) {
    let img = videoContainer.querySelector('img');
    if (!img) {
      img = document.createElement('img');
      img.style.cssText = 'width: 100%; height: 100%; object-fit: cover;';
      videoContainer.innerHTML = ''; // Clear placeholder text
      videoContainer.appendChild(img);
    }
    img.src = `data:image/jpeg;base64,${frameData}`;
  }
}

function updateHybridDetailsDisplay() {
  const aisCount = Object.keys(aisShips).length;
  const cvCount = Object.keys(cvShips).length;
  const matchedCount = matchedShips.size;
  const lstmCount = lstmPredictions.length;
  
  const aisEl = document.getElementById('aisShipCount');
  const cvEl = document.getElementById('cvShipCount');
  const matchedEl = document.getElementById('matchedCount');
  const lstmEl = document.getElementById('lstmCount');
  
  if (aisEl) aisEl.textContent = aisCount;
  if (cvEl) cvEl.textContent = cvCount;
  if (matchedEl) matchedEl.textContent = matchedCount;
  if (lstmEl) lstmEl.textContent = lstmCount;
  
  // Update LSTM predictions list
  const lstmListEl = document.getElementById('lstmShipsList');
  if (lstmListEl) {
    if (lstmPredictions.length > 0) {
      lstmListEl.innerHTML = lstmPredictions
        .map(pred => `<div style="padding:4px; font-size:12px;">🚀 ${pred.ship_name || 'Ship'} - ${pred.confidence?.toFixed(1) || 'N/A'}%</div>`)
        .join('');
    } else {
      lstmListEl.innerHTML = '<div style="color: #999; text-align: center; padding: 10px;">No LSTM predictions yet</div>';
    }
  }
}

// Handle Load Video button
function setupVideoLoading() {
  let btn = null;
  const allBtns = document.querySelectorAll('button');
  btn = Array.from(allBtns).find(b => b.textContent.includes('Load') || b.textContent.includes('▶'));
  
  if (btn) {
    btn.addEventListener('click', () => {
      const videoSelect = document.querySelector('select');
      if (videoSelect && videoSelect.value && videoSelect.value !== 'Loading videos…') {
        const videoName = videoSelect.value.split('(')[0].trim();
        console.log(`🎬 Loading video: ${videoName}`);
        
        // Send video load command to backend
        if (ws && ws.readyState === WebSocket.OPEN) {
          const msg = { 
            type: 'load_video', 
            video_file: videoName 
          };
          ws.send(JSON.stringify(msg));
          console.log('✅ Video load request sent to backend');
        } else {
          console.error('WebSocket not connected');
        }
      } else {
        console.warn('No video selected');
      }
    });
    console.log('✅ Video load handler attached');
  } else {
    console.warn('Load button not found, retrying in 1s');
    setTimeout(setupVideoLoading, 1000);
  }
}

// Start on page load
document.addEventListener('DOMContentLoaded', () => {
  console.log('🚀 Starting Fusion Dashboard (Enhanced)');
  initWebSocket();
  initMap();
  setupVideoLoading();
});

console.log('✅ Initialization functions registered');
