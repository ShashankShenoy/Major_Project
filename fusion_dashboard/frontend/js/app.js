// Fusion Maritime Intelligence System - Multi-Source Sensor Integration

// Global error handler
window.addEventListener('error', (event) => {
  console.error('Global error:', event.error, event.message);
  console.error('Stack:', event.error?.stack);
});

window.addEventListener('unhandledrejection', (event) => {
  console.error('Unhandled rejection:', event.reason);
});

let ws;
try {
  ws = new WebSocket(`ws://${window.location.host}/ws`);
  console.log('WebSocket created successfully');
} catch (e) {
  console.error('WebSocket creation failed:', e);
  ws = null;
}

let map, mapLoaded = false, selectedShip = null, latestShips = [];
let sessionStartTime = null, renderScheduled = false;
let replayMode = false, replayTime = null;
let darkMode = localStorage.getItem('darkMode') === 'true';
let collisionThreshold = 0.01;
let portProximity = 0.1;
let speedAlertThreshold = 15;
let collisionRangeThreshold = 5;
let portProximityThreshold = 10;

// Feature states
let comparisonMode = false;
let comparisonVessels = [];
let measurementMode = false;
let measurementPoints = [];

// Multi-source tracking
let cvDetections = [];
let lstmPredictions = [];
let minCVConfidence = 60;
let anomalyDetectionActive = false;
let detectedAnomalies = [];
let sourceReliability = { ais: 0.95, cv: 0.65, lstm: 0.70 };

// Filter states
let showTracks = true;
let showPredicted = true;
let showArrows = true;
let showHeatmap = false;
let showPorts = false;

function getShipKey(ship) {
  if (!ship) return null;
  if (ship.mmsi !== undefined && ship.mmsi !== null) return `ais_${ship.mmsi}`;
  if (ship.id) return String(ship.id);
  if (ship.name) return `name_${ship.name}`;
  return null;
}

function normalizeUnifiedShip(ship) {
  const pos = Array.isArray(ship.pos)
    ? ship.pos
    : Array.isArray(ship.gps)
      ? [ship.gps[0], ship.gps[1]]
      : (ship.gps_lon !== undefined && ship.gps_lat !== undefined)
        ? [ship.gps_lon, ship.gps_lat]
        : null;

  const track = Array.isArray(ship.track) ? ship.track : [];
  const predicted = Array.isArray(ship.predicted)
    ? ship.predicted
    : Array.isArray(ship.predicted_path_gps)
      ? ship.predicted_path_gps.map(pt => [pt[1], pt[0]])
      : [];

  return {
    ...ship,
    pos,
    track,
    predicted,
    sog: ship.sog ?? ship.speed ?? 0,
    cog: ship.cog ?? ship.heading ?? 0,
    shipKey: getShipKey(ship)
  };
}

function normalizeWsMessage(message) {
  if (message.type === "frame" && Array.isArray(message.ships)) {
    return message.ships
      .map(normalizeUnifiedShip)
      .filter(ship => Array.isArray(ship.pos) && ship.pos.length === 2);
  }

  if (message.type === "unified" && Array.isArray(message.ais_ships)) {
    return message.ais_ships
      .map(ship => ({ ...ship, shipKey: getShipKey(ship) }))
      .filter(ship => Array.isArray(ship.pos) && ship.pos.length === 2);
  }

  if (Array.isArray(message)) {
    return message
      .map(ship => ({ ...ship, shipKey: getShipKey(ship) }))
      .filter(ship => Array.isArray(ship.pos) && ship.pos.length === 2);
  }

  return null;
}

// ─────────────────────────────
// THEME SYSTEM
// ─────────────────────────────

function toggleTheme() {
  darkMode = !darkMode;
  localStorage.setItem('darkMode', darkMode);
  document.body.classList.toggle('dark-mode', darkMode);
  document.querySelector('.theme-toggle').innerText = darkMode ? 'Light' : 'Dark';
}

if (darkMode) {
  document.body.classList.add('dark-mode');
  document.querySelector('.theme-toggle').innerText = 'Light';
}

// ─────────────────────────────
// CHECKBOX SETUP
// ─────────────────────────────

function setupCheckboxes() {
  const tracksCheckbox = document.getElementById('showTracks');
  const predictedCheckbox = document.getElementById('showPredicted');
  const arrowsCheckbox = document.getElementById('showArrows');
  const heatmapCheckbox = document.getElementById('showHeatmap');
  const portsCheckbox = document.getElementById('showPorts');

  if (tracksCheckbox) {
    tracksCheckbox.addEventListener('change', (e) => {
      showTracks = e.target.checked;
      if (map && map.getLayer('tracks-layer')) {
        map.setLayoutProperty('tracks-layer', 'visibility', showTracks ? 'visible' : 'none');
        map.setLayoutProperty('selected-track-layer', 'visibility', showTracks ? 'visible' : 'none');
      }
    });
  }

  if (predictedCheckbox) {
    predictedCheckbox.addEventListener('change', (e) => {
      showPredicted = e.target.checked;
      if (map && map.getLayer('predicted-layer')) {
        map.setLayoutProperty('predicted-layer', 'visibility', showPredicted ? 'visible' : 'none');
        map.setLayoutProperty('selected-predicted-layer', 'visibility', showPredicted ? 'visible' : 'none');
      }
    });
  }

  if (arrowsCheckbox) {
    arrowsCheckbox.addEventListener('change', (e) => {
      showArrows = e.target.checked;
      if (map && map.getLayer('arrows-layer')) {
        map.setLayoutProperty('arrows-layer', 'visibility', showArrows ? 'visible' : 'none');
        map.setLayoutProperty('headings-layer', 'visibility', showArrows ? 'visible' : 'none');
      }
    });
  }

  if (heatmapCheckbox) {
    heatmapCheckbox.addEventListener('change', (e) => {
      showHeatmap = e.target.checked;
      if (map && map.getLayer('heatmap-layer')) {
        map.setLayoutProperty('heatmap-layer', 'visibility', showHeatmap ? 'visible' : 'none');
      }
    });
  }

  if (portsCheckbox) {
    portsCheckbox.addEventListener('change', (e) => {
      showPorts = e.target.checked;
      if (map && map.getLayer('ports-layer')) {
        map.setLayoutProperty('ports-layer', 'visibility', showPorts ? 'visible' : 'none');
      }
    });
  }
}

// ─────────────────────────────
// MAP INITIALIZATION
// ─────────────────────────────

map = new maplibregl.Map({
  container: "map",
  style: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
  center: [103.84, 1.264],
  zoom: 8,
  attributionControl: false
});

map.on("load", () => {
  mapLoaded = true;
  initializeSources();
  initializeLayers();
  setupMapClickHandler();
  setupCheckboxes();
  initializeSearch();
  loadSavedLocations();
});

function initializeSources() {
  const sources = ["ships", "matched-ships", "tracks", "selected-track", "predicted", "selected-predicted",
                   "destination", "headings", "arrows", "speed-circles", "heatmap", "ports", "collision-zones"];

  sources.forEach(src => {
    if (map.getSource(src)) return;
    map.addSource(src, { type: "geojson", data: { type: "FeatureCollection", features: [] } });
  });
}

function initializeLayers() {
  // Create ships-layer first (foundation layer for all others to reference)
  if (!map.getLayer("ships-layer")) {
    map.addLayer({
      id: "ships-layer",
      type: "circle",
      source: "ships",
      paint: {
        "circle-radius": ["case", ["==", ["get", "selected"], 1], 11, 6.5],
        "circle-color": ["get", "risk_color"],
        "circle-stroke-width": ["case", ["==", ["get", "selected"], 1], 3, 1.5],
        "circle-stroke-color": ["case", ["==", ["get", "selected"], 1], "#c084fc", "#d1d5db"]
      }
    });
  }

  // Now add other layers
  if (!map.getLayer("heatmap-layer")) {
    map.addLayer({
      id: "heatmap-layer",
      type: "circle",
      source: "heatmap",
      layout: { visibility: 'none' },
      paint: { "circle-radius": 15, "circle-color": "#2563eb", "circle-opacity": 0.3 }
    }, "ships-layer");
  }

  if (!map.getLayer("collision-layer")) {
    map.addLayer({
      id: "collision-layer",
      type: "circle",
      source: "collision-zones",
      paint: { "circle-radius": 8, "circle-color": "#dc2626", "circle-opacity": 0.4, "circle-stroke-width": 2, "circle-stroke-color": "#dc2626" }
    });
  }

  if (!map.getLayer("tracks-layer")) {
    map.addLayer({
      id: "tracks-layer",
      type: "line",
      source: "tracks",
      paint: { "line-color": "#9ca3af", "line-width": 1, "line-opacity": 0.4 }
    });
  }

  if (!map.getLayer("selected-track-layer")) {
    map.addLayer({
      id: "selected-track-layer",
      type: "line",
      source: "selected-track",
      paint: { "line-color": "#2563eb", "line-width": 2.5, "line-opacity": 0.95 }
    });
  }

  if (!map.getLayer("predicted-layer")) {
    map.addLayer({
      id: "predicted-layer",
      type: "line",
      source: "predicted",
      paint: { "line-color": "#9ca3af", "line-width": 1.5, "line-dasharray": [3, 3], "line-opacity": 0.3 }
    });
  }

  if (!map.getLayer("selected-predicted-layer")) {
    map.addLayer({
      id: "selected-predicted-layer",
      type: "line",
      source: "selected-predicted",
      paint: { "line-color": "#2563eb", "line-width": 2, "line-dasharray": [4, 3], "line-opacity": 0.8 }
    });
  }

  if (!map.getLayer("speed-circles")) {
    map.addLayer({
      id: "speed-circles",
      type: "circle",
      source: "speed-circles",
      paint: { "circle-radius": ["get", "speed_radius"], "circle-color": ["get", "speed_color"], "circle-opacity": 0.15 }
    });
  }

  if (!map.getLayer("matched-ships-glow")) {
    map.addLayer({
      id: "matched-ships-glow",
      type: "circle",
      source: "matched-ships",
      paint: {
        "circle-radius": 10,
        "circle-color": "#fbbf24",
        "circle-opacity": 0.1
      }
    }, "ships-layer");
  }

  if (!map.getLayer("headings-layer")) {
    map.addLayer({
      id: "headings-layer",
      type: "symbol",
      source: "headings",
      layout: { "icon-image": "triangle-15", "icon-size": ["case", ["==", ["get", "selected"], 1], 1.4, 0.9], "icon-rotate": ["get", "heading"], "icon-allow-overlap": true },
      paint: { "icon-color": ["case", ["==", ["get", "selected"], 1], "#2563eb", "#d1d5db"], "icon-opacity": ["case", ["==", ["get", "selected"], 1], 1, 0.5] }
    });
  }

  if (!map.getLayer("arrows-layer")) {
    map.addLayer({
      id: "arrows-layer",
      type: "symbol",
      source: "arrows",
      layout: { "text-field": ["get", "arrow"], "text-size": ["case", ["==", ["get", "selected"], 1], 26, 0], "text-allow-overlap": true },
      paint: { "text-color": "#2563eb", "text-opacity": 0.7, "text-halo-color": "rgba(255, 255, 255, 0.8)", "text-halo-width": 1.5 }
    });
  }

  if (!map.getLayer("destination-layer")) {
    map.addLayer({
      id: "destination-layer",
      type: "circle",
      source: "destination",
      paint: { "circle-radius": 5, "circle-color": "#059669", "circle-stroke-width": 2, "circle-stroke-color": "#2563eb" }
    });
  }

  if (!map.getLayer("ports-layer")) {
    map.addLayer({
      id: "ports-layer",
      type: "symbol",
      source: "ports",
      layout: { "text-field": ["get", "label"], "text-size": 10, "text-allow-overlap": false, visibility: 'none' },
      paint: { "text-color": "#059669", "text-opacity": 0.7 }
    });
  }
}

function setupMapClickHandler() {
  map.on("click", (e) => {
    if (measurementMode) {
      measurementPoints.push([e.lngLat.lng, e.lngLat.lat]);
      if (measurementPoints.length === 2) {
        const dist = Math.sqrt(Math.pow(measurementPoints[1][0] - measurementPoints[0][0], 2) + Math.pow(measurementPoints[1][1] - measurementPoints[0][1], 2)) * 111;
        showToast(`Distance: ${dist.toFixed(2)} km`);
        measurementPoints = [];
      }
      return;
    }
    const features = map.queryRenderedFeatures(e.point, { layers: ["ships-layer"] });
    if (features.length > 0) {
      selectShip(features[0].properties.ship_key || features[0].properties.mmsi);
      return;
    }
    document.getElementById("lat").value = e.lngLat.lat.toFixed(5);
    document.getElementById("lon").value = e.lngLat.lng.toFixed(5);
  });
}

function startTracking() {
  if (ws.readyState !== WebSocket.OPEN) return;
  const lat = parseFloat(document.getElementById("lat").value);
  const lon = parseFloat(document.getElementById("lon").value);
  selectedShip = null;
  latestShips = [];
  renderScheduled = false;
  clearAllLayers();
  sessionStartTime = Date.now();
  ws.send(JSON.stringify({ type: "start", lat, lon }));
  map.flyTo({ center: [lon, lat], zoom: 9 });
}

function clearAllLayers() {
  const empty = { type: "FeatureCollection", features: [] };
  ["ships", "tracks", "selected-track", "predicted", "selected-predicted", "destination",
   "headings", "arrows", "speed-circles", "heatmap", "ports", "collision-zones"].forEach(src => {
    if (map.getSource(src)) map.getSource(src).setData(empty);
  });
  document.getElementById("headerVessels").innerText = "0";
  document.getElementById("noSelectionSection").style.display = 'block';
  document.getElementById("vesselDetailsSection").style.display = 'none';
}

function selectShip(mmsi) {
  selectedShip = mmsi;
  updateVesselDetails();
  scheduleRender();
}

// Global tracking for hybrid mode - must be outside if block
let lastMessageStats = { ais: 0, cv: 0, matched: 0, lstm: 0 };
let lastCameraStatus = null;

if (ws) {
  ws.onopen = () => {
    console.log("Connected to AIS backend");
    // Auto-start tracking at default Singapore Strait location on connect
    setTimeout(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        const lat = parseFloat(document.getElementById('lat')?.value) || 1.264;
        const lon = parseFloat(document.getElementById('lon')?.value) || 103.84;
        sessionStartTime = Date.now();
        ws.send(JSON.stringify({ type: 'start', lat, lon }));
        if (map && mapLoaded) map.flyTo({ center: [lon, lat], zoom: 9 });
        showToast('AIS tracking started — Singapore Strait');
      }
    }, 1200);
  };

  // Auto-activate split view when page loads in hybrid/live mode
  // Uses 'load' event so inline scripts (setViewMode) are guaranteed to be defined
  window.addEventListener('load', () => {
    // Do NOT automatically activate view mode - let user choose
    // The URL parameter is informational only, doesn't trigger automatic actions
  });

  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    
    // Log raw message structure for debugging
    if (message.ships && message.ships.length > 0 && !window.loggedShipStructure) {
      console.log('RAW WEBSOCKET MESSAGE FIRST SHIP:', message.ships[0]);
      console.log('Message type:', message.type);
      console.log('Total ships in message:', message.ships.length);
      window.loggedShipStructure = true;  // Only log once
    }
    
    const normalizedShips = normalizeWsMessage(message);
    if (normalizedShips) {
      latestShips = normalizedShips;
    }
    
    // Store camera status and track stats every message
    if (message.camera_status) {
      lastCameraStatus = message.camera_status;
    }
    
    // Always track hybrid mode statistics (in any mode)
    if (normalizedShips && normalizedShips.length > 0) {
      // Filter ships by source - handle both explicit source field and backward compatibility
      const aisShips = normalizedShips.filter(s => {
        if (!s.source) return s.mmsi !== undefined;  // No source field, assume AIS if has mmsi
        return s.source === 'AIS';
      });
      const cvShips = normalizedShips.filter(s => s.source === 'CAMERA');
      
      // Debug log - DETAILED
      if (normalizedShips.length > 0 && (aisShips.length === 0 || cvShips.length === 0)) {
        const samples = normalizedShips.slice(0, 2).map(s => ({
          id: s.id,
          source: s.source,
          mmsi: s.mmsi,
          hasSource: !!s.source,
          keys: Object.keys(s).slice(0, 6)
        }));
        console.log('Ship filtering debug:', {
          total: normalizedShips.length,
          ais: aisShips.length,
          cv: cvShips.length,
          samples: samples
        });
      }
      
      // Update tracking
      lstmPredictions = cvShips.filter(s => 
        s.predicted && s.predicted.length > 0 && !s.mmsi
      );
      
      lastMessageStats = {
        ais: aisShips.length,
        cv: cvShips.length,
        matched: cvShips.filter(s => s.mmsi).length,
        lstm: lstmPredictions.length
      };
    }
    
    if (message.video_frame) {
      const videoFrame = document.getElementById('videoFrame');
      if (videoFrame) {
        videoFrame.src = 'data:image/jpeg;base64,' + message.video_frame;
        videoFrame.style.display = 'block';
        // Hide placeholder, show live dot
        const placeholder = document.getElementById('videoPlaceholder');
        if (placeholder) placeholder.style.display = 'none';
        const statusDot  = document.getElementById('videoPanelStatusDot');
        const statusText = document.getElementById('videoPanelStatusText');
        if (statusDot)  { statusDot.classList.add('live'); }
        if (statusText) { statusText.textContent = 'LIVE'; }
      }
    }

    scheduleRender();
    updateAnalytics();
    checkAlerts();
    // Always update hybrid details display (it will check the mode itself)
    updateHybridDetailsDisplay();
  };
  
  ws.onerror = (err) => console.error("WebSocket error:", err);
} else {
  console.warn('WebSocket failed to initialize - will retry');
}

// ─────────────────────────────
// ANALYTICS & RISK ASSESSMENT
// ─────────────────────────────

function getRiskScore(ship) {
  let risk = 0;
  if (ship.sog > 20) risk += 2;
  if (ship.sog < 0.5) risk -= 1;
  if (hasCollisionRisk(ship)) risk += 5;
  if (nearPort(ship)) risk += 1;
  return Math.max(0, Math.min(10, risk));
}

function getRiskColor(ship) {
  // If ship is matched to AIS (detected on camera and mapped), show yellow
  if (ship.is_matched_to_ais) {
    return "#fbbf24";  // Fusion yellow
  }
  
  const risk = getRiskScore(ship);
  if (risk <= 2) return "#10b981";    // Green
  if (risk <= 5) return "#3b82f6";    // Blue
  if (risk <= 7) return "#f59e0b";    // Amber
  return "#ef4444";                    // Red
}

function hasCollisionRisk(ship) {
  return latestShips.some(other => {
    if (other.mmsi === ship.mmsi) return false;
    const dist = Math.sqrt(Math.pow(ship.pos[0] - other.pos[0], 2) + Math.pow(ship.pos[1] - other.pos[1], 2));
    return dist < collisionThreshold && Math.abs(ship.cog - other.cog) < 30;
  });
}

function nearPort(ship) {
  const ports = [[103.84, 1.264], [114.17, 22.28], [113.53, 22.16], [121.64, 31.40], [106.87, -6.11], [96.20, 16.87], [104.06, 1.09], [100.59, 13.73]];
  return ports.some(port => Math.sqrt(Math.pow(ship.pos[0] - port[0], 2) + Math.pow(ship.pos[1] - port[1], 2)) < portProximity);
}

function getSpeedColor(speed) {
  if (speed < 1) return "#f59e0b";
  if (speed < 8) return "#2563eb";
  if (speed < 15) return "#059669";
  return "#dc2626";
}

function getArrowSymbol(cog) {
  const dirs = ['↑', '↗', '→', '↘', '↓', '↙', '←', '↖'];
  return dirs[Math.round((cog % 360) / 45) % 8];
}

function updateAnalytics() {
  if (!latestShips.length) return;
  const speeds = latestShips.map(s => s.sog);
  const moving = latestShips.filter(s => s.sog > 1).length;
  const anchored = latestShips.filter(s => s.sog <= 1).length;

  document.getElementById("metricMaxSpeed").innerText = Math.max(...speeds).toFixed(1);
  document.getElementById("metricAvgSpeed").innerText = (speeds.reduce((a, b) => a + b, 0) / speeds.length).toFixed(1);
  document.getElementById("metricMoving").innerText = moving;
  document.getElementById("metricAnchored").innerText = anchored;
  document.getElementById("headerVessels").innerText = latestShips.length;
}

// ─────────────────────────────
// HYBRID MODE DETAILS PANEL
// ─────────────────────────────

function updateHybridModePanel(cameraStatus, stats) {
  const hybridSection = document.getElementById('hybridModeSection');
  if (!hybridSection) return;
  
  const currentMode = localStorage.getItem('selectedMode') || 'ais-only';
  
  // Show panel if in hybrid mode (always, not just when available)
  if (currentMode === 'hybrid') {
    hybridSection.style.display = 'block';
    
    // Update camera status
    const statusText = document.getElementById('cameraStatusText');
    if (statusText) {
      if (cameraStatus && cameraStatus.available) {
        statusText.textContent = 'ACTIVE 🟢';
        statusText.style.color = '#4ade80';
      } else {
        statusText.textContent = 'Waiting for video...';
        statusText.style.color = '#fbbf24';
      }
    }
    
    // Update camera location
    const locText = document.getElementById('cameraLocationText');
    if (locText && cameraStatus) {
      locText.textContent = `${cameraStatus.lat.toFixed(3)}°N, ${cameraStatus.lon.toFixed(3)}°E`;
    }
    
    // Update FOV
    const fovText = document.getElementById('cameraFOVText');
    if (fovText && cameraStatus) {
      fovText.textContent = `${cameraStatus.fov_km.toFixed(1)} km`;
    }
  } else {
    hybridSection.style.display = 'none';
  }
}

function updateHybridDetailsDisplay() {
  const hybridSection = document.getElementById('hybridModeSection');
  if (!hybridSection) return;
  
  const currentMode = localStorage.getItem('selectedMode') || 'ais-only';
  hybridSection.style.display = currentMode === 'hybrid' ? 'block' : 'none';
  
  if (currentMode === 'hybrid') {
    // Update camera status with latest info (if available)
    if (lastCameraStatus) {
      updateHybridModePanel(lastCameraStatus, lastMessageStats);
    }
    
    // Always update counts regardless of camera status
    const aisCountEl = document.getElementById('aisShipCount');
    const cvCountEl = document.getElementById('cvShipCount');
    const matchedEl = document.getElementById('matchedCount');
    const lstmEl = document.getElementById('lstmCount');
    
    if (aisCountEl) aisCountEl.textContent = lastMessageStats.ais;
    if (cvCountEl) cvCountEl.textContent = lastMessageStats.cv;
    if (matchedEl) matchedEl.textContent = lastMessageStats.matched;
    if (lstmEl) lstmEl.textContent = lastMessageStats.lstm;
    
    console.log('Updated hybrid counts:', lastMessageStats);
    
    // Update LSTM ships list
    const lstmList = document.getElementById('lstmShipsList');
    if (lstmList) {
      if (lstmPredictions.length === 0) {
        lstmList.innerHTML = '<div style="color: #999; text-align: center; padding: 10px;">No LSTM predictions yet</div>';
      } else {
        lstmList.innerHTML = lstmPredictions.map(ship => {
          const confidence = ship.confidence ? (ship.confidence * 100).toFixed(0) : 'N/A';
          const pathLength = ship.predicted ? ship.predicted.length : 0;
          const id = ship.id || ship.name || 'Unknown';
          return `
            <div style="background: rgba(255,255,255,0.03); padding: 6px; margin-bottom: 4px; border-radius: 3px; border-left: 3px solid #a78bfa;">
              <div style="color: #a78bfa; font-weight: bold; font-size: 11px;">${id}</div>
              <div style="font-size: 9px; color: #999; margin-top: 2px;">
                <span>Conf: <span style="color: #c4b5fd;">${confidence}%</span></span> | 
                <span>Path: <span style="color: #c4b5fd;">${pathLength} pts</span></span>
                <br>
                <span style="color: #999;">Pos: ${ship.pos ? `${ship.pos[1].toFixed(3)}°, ${ship.pos[0].toFixed(3)}°` : 'N/A'}</span>
              </div>
            </div>
          `;
        }).join('');
      }
    }
  }
}

  // Update session duration
  if (sessionStartTime) {
    const duration = Math.floor((Date.now() - sessionStartTime) / 1000);
    const m = Math.floor(duration / 60).toString().padStart(2, '0');
    const s = (duration % 60).toString().padStart(2, '0');
    const el = document.getElementById("sessionTime");
    if (el) el.innerText = `${m}:${s}`;
  }

  // Update average speed in header
  if (latestShips.length > 0) {
    const speeds = latestShips.map(s => s.sog || 0);
    const avg = speeds.reduce((a, b) => a + b, 0) / speeds.length;
    const speedEl = document.getElementById("headerAvgSpeed");
    if (speedEl) speedEl.innerText = `${avg.toFixed(1)} kts`;
  }

function checkAlerts() {
  let alerts = [];
  let collisionCount = 0;

  latestShips.forEach(ship => {
    if (getRiskScore(ship) > 6) alerts.push(`High risk vessel: ${ship.name}`);
    if (hasCollisionRisk(ship)) collisionCount++;
  });

  if (collisionCount > 0) alerts.unshift(`${collisionCount} potential collision(s) detected`);

  const container = document.getElementById("alertsContainer");
  if (!alerts.length) {
    container.innerHTML = '<div class="alert alert-success"><strong>All Clear</strong><br>No active alerts</div>';
    document.getElementById("headerAlerts").innerText = "0";
  } else {
    container.innerHTML = alerts.map((a) => {
      const isCollision = a.includes('potential collision');
      return `<div class="alert ${isCollision ? 'alert-warning' : 'alert-info'}">${a}</div>`;
    }).join('');
    document.getElementById("headerAlerts").innerText = alerts.length;
  }
}

// ─────────────────────────────
// RENDERING
// ─────────────────────────────

function scheduleRender() {
  if (!mapLoaded || renderScheduled) return;
  renderScheduled = true;
  requestAnimationFrame(() => {
    renderScheduled = false;
    try { renderShips(); } catch (err) { console.error(err); }
  });
}

function renderShips() {
  if (!mapLoaded) return;

  const layers = ['ships', 'matched-ships', 'tracks', 'selected-track', 'predicted', 'selected-predicted', 'destination', 'headings', 'arrows', 'speed-circles', 'collision-zones', 'heatmap'];
  layers.forEach(l => { if (map.getSource(l)) map.getSource(l).setData({ type: 'FeatureCollection', features: [] }); });

  const ships = [], matchedShips = [], tracks = [], selTracks = [], preds = [], selPreds = [];
  const dests = [], headings = [], arrows = [], speedCircles = [], collisions = [], heatmapPoints = [];

  latestShips.forEach(ship => {
    const selected = ship.shipKey === selectedShip ? 1 : 0;
    const riskColor = getRiskColor(ship);

    ships.push({
      type: "Feature",
      geometry: { type: "Point", coordinates: ship.pos },
      properties: { mmsi: ship.mmsi, ship_key: ship.shipKey, selected, risk_color: riskColor }
    });

    // Track matched ships separately for glow effect
    if (ship.is_matched_to_ais) {
      matchedShips.push({
        type: "Feature",
        geometry: { type: "Point", coordinates: ship.pos },
        properties: { mmsi: ship.mmsi, ship_key: ship.shipKey }
      });
    }

    speedCircles.push({
      type: "Feature",
      geometry: { type: "Point", coordinates: ship.pos },
      properties: { speed_radius: Math.max(8, Math.min(20, ship.sog / 2)), speed_color: getSpeedColor(ship.sog) }
    });

    heatmapPoints.push({ type: "Feature", geometry: { type: "Point", coordinates: ship.pos } });

    if (ship.track && ship.track.length > 1) {
      const feat = { type: "Feature", geometry: { type: "LineString", coordinates: ship.track } };
      selected ? selTracks.push(feat) : tracks.push(feat);
    }

    if (ship.predicted && ship.predicted.length > 1) {
      const feat = { type: "Feature", geometry: { type: "LineString", coordinates: ship.predicted } };
      selected ? selPreds.push(feat) : preds.push(feat);
      if (selected) {
        const lastPred = ship.predicted[ship.predicted.length - 1];
        dests.push({ type: "Feature", geometry: { type: "Point", coordinates: lastPred } });
      }
    }

    headings.push({
      type: "Feature",
      geometry: { type: "Point", coordinates: ship.pos },
      properties: { heading: ship.cog || 0, selected }
    });

    if (selected) {
      arrows.push({
        type: "Feature",
        geometry: { type: "Point", coordinates: ship.pos },
        properties: { arrow: getArrowSymbol(ship.cog), selected: 1 }
      });
    }

    if (hasCollisionRisk(ship)) {
      collisions.push({ type: "Feature", geometry: { type: "Point", coordinates: ship.pos } });
    }
  });

  if (map.getSource("ships")) map.getSource("ships").setData({ type: "FeatureCollection", features: ships });
  if (map.getSource("matched-ships")) map.getSource("matched-ships").setData({ type: "FeatureCollection", features: matchedShips });
  if (map.getSource("tracks")) map.getSource("tracks").setData({ type: "FeatureCollection", features: tracks });
  if (map.getSource("selected-track")) map.getSource("selected-track").setData({ type: "FeatureCollection", features: selTracks });
  if (map.getSource("predicted")) map.getSource("predicted").setData({ type: "FeatureCollection", features: preds });
  if (map.getSource("selected-predicted")) map.getSource("selected-predicted").setData({ type: "FeatureCollection", features: selPreds });
  if (map.getSource("destination")) map.getSource("destination").setData({ type: "FeatureCollection", features: dests });
  if (map.getSource("headings")) map.getSource("headings").setData({ type: "FeatureCollection", features: headings });
  if (map.getSource("arrows")) map.getSource("arrows").setData({ type: "FeatureCollection", features: arrows });
  if (map.getSource("speed-circles")) map.getSource("speed-circles").setData({ type: "FeatureCollection", features: speedCircles });
  if (map.getSource("collision-zones")) map.getSource("collision-zones").setData({ type: "FeatureCollection", features: collisions });
  if (map.getSource("heatmap")) map.getSource("heatmap").setData({ type: "FeatureCollection", features: heatmapPoints });
}

// ─────────────────────────────
// VESSEL DETAILS PANEL
// ─────────────────────────────

function updateVesselDetails() {
  const section = document.getElementById("vesselDetailsSection");
  const noSection = document.getElementById("noSelectionSection");

  if (!selectedShip) {
    section.style.display = 'none';
    noSection.style.display = 'block';
    return;
  }

  const ship = latestShips.find(s => s.shipKey === selectedShip);
  if (!ship) return;

  const stats = ship.trackStats || {};
  const risk = getRiskScore(ship);
  const status = ship.sog < 1 ? "Anchored" : "Moving";
  const riskLevel = risk <= 2 ? "Safe" : risk <= 5 ? "Normal" : risk <= 7 ? "Warning" : "Danger";
  const riskColor = getRiskColor(ship);
  const trackDuration = Math.round((stats.duration || 0) / 60);
  const distance = (stats.distance || 0).toFixed(2);
  const lat = ship.pos[1].toFixed(6);
  const lon = ship.pos[0].toFixed(6);
  const fused = fuseDataSources(ship);
  const lstm = lstmPredictions.find(l => l.mmsi === ship.mmsi);

  section.style.display = 'block';
  noSection.style.display = 'none';

  document.getElementById("selectedVesselContent").innerHTML = `
    <div style="margin-bottom: 8px;"><div style="font-size: 14px; font-weight: 700; color: var(--primary);">${ship.name}</div><div style="font-size: 10px; color: var(--text-secondary); font-family: monospace;">MMSI: ${ship.mmsi}</div></div>
    <div style="margin-bottom: 8px; font-size: 10px;"><div style="margin-bottom: 4px; font-weight: 600; text-transform: uppercase; color: var(--text-secondary);">Sources</div>${getSourceBadgeHTML(ship)}<div style="margin-top: 3px; color: var(--text-secondary);">Fused: ${fused.source} (${(fused.confidence * 100).toFixed(0)}%)</div></div>
    <div style="display: flex; gap: 8px; margin-bottom: 8px;"><span class="status-badge status-${ship.sog > 1 ? 'moving' : 'anchored'}"><span class="status-dot"></span>${status}</span><span class="status-badge" style="background: ${riskColor}20; color: ${riskColor};">Risk: ${riskLevel}</span></div>
    <div class="metric-grid" style="margin-bottom: 8px;"><div class="metric-box"><div class="metric-value" style="color: ${getSpeedColor(ship.sog)};">${ship.sog.toFixed(1)}</div><div class="metric-label">Speed (kts)</div></div><div class="metric-box"><div class="metric-value">${ship.cog.toFixed(0)}</div><div class="metric-label">Heading (°)</div></div></div>
    <div style="font-size: 10px; padding: 8px; background: var(--bg-2); border-radius: 4px;"><div style="display: flex; justify-content: space-between; margin-bottom: 4px; padding-bottom: 4px; border-bottom: 1px solid var(--border);"><span>Lat</span><span style="font-family: monospace; font-weight: 600;">${lat}</span></div><div style="display: flex; justify-content: space-between; margin-bottom: 4px; padding-bottom: 4px; border-bottom: 1px solid var(--border);"><span>Lon</span><span style="font-family: monospace; font-weight: 600;">${lon}</span></div><div style="display: flex; justify-content: space-between; margin-bottom: 4px; padding-bottom: 4px; border-bottom: 1px solid var(--border);"><span>Duration</span><span>${trackDuration} min</span></div><div style="display: flex; justify-content: space-between;"><span>Distance</span><span>${distance} km</span></div></div>
    ${lstm ? `<div style="font-size: 10px; margin-top: 8px; padding: 8px; background: rgba(190, 24, 93, 0.1); border-left: 2px solid #be185d; border-radius: 4px;"><div style="font-weight: 600; color: #be185d;">LSTM Prediction: ${(lstm.confidence * 100).toFixed(0)}% confidence</div></div>` : ''}
  `;
}

// ─────────────────────────────
// REPLAY SYSTEM
// ─────────────────────────────

function toggleReplay() {
  replayMode ? pauseReplay() : playReplay();
}

function playReplay() {
  if (!latestShips.length) return;
  replayMode = true;
  if (replayTime === null) replayTime = 0;
  document.getElementById("replayBtn").innerText = "Pause";
  playReplayFrame();
}

function pauseReplay() {
  replayMode = false;
  document.getElementById("replayBtn").innerText = "Replay";
}

function playReplayFrame() {
  if (!replayMode) return;
  const maxLen = Math.max(0, ...latestShips.map(s => s.track ? s.track.length : 0));
  replayTime = (replayTime + 1) % maxLen;
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "replay", index: replayTime }));
  }
  requestAnimationFrame(() => playReplayFrame());
}

// ─────────────────────────────
// SEARCH & LOCATION MANAGEMENT
// ─────────────────────────────

function initializeSearch() {
  const searchBox = document.getElementById('vesselSearch');
  if (!searchBox) return;
  searchBox.addEventListener('input', (e) => {
    const query = e.target.value.toLowerCase();
    const results = document.getElementById('searchResults');
    results.innerHTML = '';
    if (query.length < 2) return;
    const matches = latestShips.filter(s =>
      s.name.toLowerCase().includes(query) || String(s.mmsi ?? s.id ?? '').includes(query)
    ).slice(0, 5);
    matches.forEach(ship => {
      const div = document.createElement('div');
      div.className = 'search-result';
      div.textContent = `${ship.name} (${ship.mmsi})`;
      div.onclick = () => selectVesselFromSearch(ship);
      results.appendChild(div);
    });
  });
}

function selectVesselFromSearch(ship) {
  selectedShip = ship.shipKey;
  document.getElementById('vesselSearch').value = '';
  document.getElementById('searchResults').innerHTML = '';
  if (map && ship.pos) {
    map.flyTo({ center: ship.pos, zoom: 11, duration: 800 });
  }
  renderShips();
  updateVesselDetails();
}

function loadSavedLocations() {
  const saved = JSON.parse(localStorage.getItem('savedLocations') || '[]');
  const container = document.getElementById('savedLocations');
  if (!container) return;
  container.innerHTML = '';
  saved.forEach((loc, idx) => {
    const btn = document.createElement('button');
    btn.className = 'saved-location-btn';
    btn.textContent = `${loc.name} (${loc.lat.toFixed(2)}, ${loc.lon.toFixed(2)})`;
    btn.onclick = () => loadSavedLocation(loc);
    container.appendChild(btn);
  });
}

function saveCurrentLocation() {
  const lat = parseFloat(document.getElementById('lat').value);
  const lon = parseFloat(document.getElementById('lon').value);
  if (!lat || !lon) { showToast('Enter valid coordinates'); return; }
  const saved = JSON.parse(localStorage.getItem('savedLocations') || '[]');
  const name = prompt('Location name:', `Location ${saved.length + 1}`);
  if (!name) return;
  saved.push({ name, lat, lon });
  localStorage.setItem('savedLocations', JSON.stringify(saved));
  loadSavedLocations();
  showToast('Location saved');
}

function loadSavedLocation(loc) {
  document.getElementById('lat').value = loc.lat;
  document.getElementById('lon').value = loc.lon;
  startTracking();
  showToast(`Tracking ${loc.name}`);
}

// ─────────────────────────────
// TOOLS & UTILITIES
// ─────────────────────────────

function enableMeasurementMode() {
  measurementMode = !measurementMode;
  measurementPoints = [];
  if (measurementMode) {
    showToast('Click points on map to measure distance');
    map.getCanvas().style.cursor = 'crosshair';
  } else {
    map.getCanvas().style.cursor = 'grab';
  }
}

function toggleComparisonMode() {
  comparisonMode = !comparisonMode;
  comparisonVessels = [];
  if (comparisonMode) {
    showToast('Select vessels to compare (Ctrl+C)');
  } else {
    const modal = document.getElementById('comparisonModal');
    if (modal) modal.classList.remove('active');
  }
}

function addToComparison() {
  if (!selectedShip) { showToast('Select a vessel first'); return; }
  const ship = latestShips.find(s => s.shipKey === selectedShip);
  if (ship && !comparisonVessels.find(v => v.shipKey === ship.shipKey)) {
    comparisonVessels.push(ship);
    showToast(`Added ${ship.name} to comparison`);
    if (comparisonVessels.length >= 1) showComparisonView();
  }
}

function showComparisonView() {
  const content = document.getElementById('comparisonContent');
  if (!content) return;
  let html = '<div class="comparison-container">';
  comparisonVessels.forEach(ship => {
    const stats = ship.trackStats || {};
    html += `<div class="comparison-item">
      <div style="font-weight: 700; margin-bottom: 8px; color: var(--primary);">${ship.name}</div>
      <div>MMSI: ${ship.mmsi}</div>
      <div>Speed: ${(ship.sog || 0).toFixed(1)} kts</div>
      <div>Course: ${(ship.cog || 0).toFixed(0)}</div>
      <div>Position: ${ship.pos[1].toFixed(4)}, ${ship.pos[0].toFixed(4)}</div>
      <div style="margin-top: 8px; font-size: 10px; color: var(--text-secondary);">
        Track: ${ship.track ? ship.track.length : 0} points<br>
        Distance: ${(stats.distance || 0).toFixed(2)} km<br>
        Duration: ${Math.round((stats.duration || 0) / 60)} min
      </div>
    </div>`;
  });
  html += '</div>';
  content.innerHTML = html;
  const modal = document.getElementById('comparisonModal');
  if (modal) modal.classList.add('active');
}

function goToVessel() {
  if (selectedShip && map) {
    const ship = latestShips.find(s => s.shipKey === selectedShip);
    if (ship && ship.pos) {
      map.flyTo({ center: ship.pos, zoom: 12, duration: 800 });
    }
  }
}

function exportVesselData() {
  if (!selectedShip) return;
  const ship = latestShips.find(s => s.shipKey === selectedShip);
  if (!ship || !ship.track) return;
  let csv = 'Latitude,Longitude,Speed,Course\n';
  ship.track.forEach(pt => {
    csv += `${pt[1]},${pt[0]},${ship.sog || 0},${ship.cog || 0}\n`;
  });
  downloadCSV(csv, `${ship.name.replace(/\s/g, '_')}_track.csv`);
  showToast('Vessel track exported');
}

function downloadSessionData() {
  if (latestShips.length === 0) { showToast('No vessels to export'); return; }
  let csv = 'Vessel Name,MMSI,Latitude,Longitude,Speed,Course,Track Points,Distance (km)\n';
  latestShips.forEach(ship => {
    const stats = ship.trackStats || {};
    csv += `"${ship.name}",${ship.mmsi},${ship.pos[1].toFixed(4)},${ship.pos[0].toFixed(4)},${(ship.sog || 0).toFixed(1)},${(ship.cog || 0).toFixed(0)},${ship.track ? ship.track.length : 0},${(stats.distance || 0).toFixed(2)}\n`;
  });
  downloadCSV(csv, `session_${new Date().toISOString().split('T')[0]}.csv`);
  showToast('Session exported');
}

function downloadCSV(content, filename) {
  const blob = new Blob([content], { type: 'text/csv' });
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  window.URL.revokeObjectURL(url);
}

// ─────────────────────────────
// ALERTS & UI CONTROLS
// ─────────────────────────────

function updateAlertThresholds() {
  const speedInput = document.getElementById('speedAlertThreshold');
  const collisionInput = document.getElementById('collisionRangeThreshold');
  const portInput = document.getElementById('portProximityThreshold');
  if (speedInput) speedAlertThreshold = parseFloat(speedInput.value) || 15;
  if (collisionInput) collisionRangeThreshold = parseFloat(collisionInput.value) || 5;
  if (portInput) portProximityThreshold = parseFloat(portInput.value) || 10;
  showToast('Alert thresholds updated');
}

function showToast(message) {
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}

// Export to window for use in HTML inline scripts
window.showToastImpl = showToast;

function closeModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) modal.classList.remove('active');
}

function showKeyboardShortcuts() {
  const modal = document.getElementById('helpModal');
  if (modal) modal.classList.add('active');
}

// ─────────────────────────────
// KEYBOARD SHORTCUTS
// ─────────────────────────────

document.addEventListener('keydown', (e) => {
  if (e.ctrlKey || e.metaKey) {
    if (e.key === 'f') { e.preventDefault(); const el = document.getElementById('vesselSearch'); if (el) el.focus(); }
    else if (e.key === 's') { e.preventDefault(); saveCurrentLocation(); }
    else if (e.key === 'e') { e.preventDefault(); downloadSessionData(); }
    else if (e.key === 'm') { e.preventDefault(); enableMeasurementMode(); }
    else if (e.key === 'c') { e.preventDefault(); toggleComparisonMode(); }
    else if (e.key === 'h') { e.preventDefault(); showKeyboardShortcuts(); }
  }
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal.active').forEach(m => m.classList.remove('active'));
    if (measurementMode) enableMeasurementMode();
  }
});

// ─────────────────────────────
// UPDATE LOOP
// ─────────────────────────────

setInterval(() => {
  if (sessionStartTime) {
    updateAnalytics();
  }
}, 1000);

// ─────────────────────────────
// MULTI-SOURCE DATA FUSION
// ─────────────────────────────

function initializeMultiSourceSystem() {
  cvDetections = [
    { id: 'cv_001', lat: 1.270, lon: 103.85, confidence: 0.92, timestamp: Date.now(), matched: null },
    { id: 'cv_002', lat: 1.255, lon: 103.82, confidence: 0.78, timestamp: Date.now(), matched: null },
    { id: 'cv_003', lat: 1.280, lon: 103.88, confidence: 0.45, timestamp: Date.now(), matched: null }
  ];
  lstmPredictions = [];
}

function matchCVToAIS() {
  cvDetections.forEach(cvDetection => {
    const matchRadius = 0.05;
    const match = latestShips.find(ship => {
      const dist = Math.sqrt(Math.pow(ship.pos[1] - cvDetection.lat, 2) + Math.pow(ship.pos[0] - cvDetection.lon, 2));
      return dist < matchRadius;
    });
    cvDetection.matched = match ? match.mmsi : null;
  });
}

function generateLSTMPredictions() {
  lstmPredictions = latestShips.map(ship => {
    if (!ship.track || ship.track.length < 3) return null;
    const recent = ship.track.slice(-3);
    const vx = (recent[2][0] - recent[0][0]) / 2;
    const vy = (recent[2][1] - recent[0][1]) / 2;
    return { mmsi: ship.mmsi, predictions: [[recent[2][0] + vx, recent[2][1] + vy], [recent[2][0] + vx * 2, recent[2][1] + vy * 2]], confidence: 0.85 };
  }).filter(p => p !== null);
}

function fuseDataSources(ship) {
  let bestData = { source: 'AIS', confidence: sourceReliability.ais };
  const cvMatch = cvDetections.find(cv => cv.matched === ship.mmsi);
  if (cvMatch && cvMatch.confidence >= minCVConfidence / 100) {
    const weight = cvMatch.confidence * sourceReliability.cv;
    if (weight > bestData.confidence * 0.9) {
      bestData = { source: 'CV+AIS', confidence: Math.max(bestData.confidence, weight) };
    }
  }
  return bestData;
}

function getSourceBadgeHTML(ship) {
  const cvMatch = cvDetections.find(cv => cv.matched === ship.mmsi);
  let html = `<span class="source-badge source-ais">AIS</span>`;
  if (cvMatch && cvMatch.confidence >= minCVConfidence / 100) html += `<span class="source-badge source-cv">CV ${(cvMatch.confidence * 100).toFixed(0)}%</span>`;
  const lstm = lstmPredictions.find(l => l.mmsi === ship.mmsi);
  if (lstm) html += `<span class="source-badge source-lstm">LSTM</span>`;
  return html;
}

function detectAnomalies() {
  detectedAnomalies = [];
  latestShips.forEach(ship => {
    if (ship.track && ship.track.length >= 3) {
      const recent = ship.track.slice(-3);
      const dir1 = Math.atan2(recent[1][1] - recent[0][1], recent[1][0] - recent[0][0]);
      const dir2 = Math.atan2(recent[2][1] - recent[1][1], recent[2][0] - recent[1][0]);
      const angleDiff = Math.abs(dir2 - dir1) * 180 / Math.PI;
      if (angleDiff > 90 && angleDiff < 270) {
        detectedAnomalies.push({ mmsi: ship.mmsi, name: ship.name, type: 'Direction Change', severity: 'medium', value: `${angleDiff.toFixed(0)}°` });
      }
    }
    if (ship.sog > 25) {
      detectedAnomalies.push({ mmsi: ship.mmsi, name: ship.name, type: 'High Speed', severity: 'high', value: `${ship.sog.toFixed(1)} kts` });
    }
  });
}

function toggleAnomalyDetection() {
  anomalyDetectionActive = !anomalyDetectionActive;
  if (anomalyDetectionActive) { detectAnomalies(); showAnomalyView(); showToast('Anomaly detection ON'); }
  else showToast('Anomaly detection OFF');
}

function showAnomalyView() {
  const content = document.getElementById('anomalyContent');
  if (!content) return;
  if (detectedAnomalies.length === 0) {
    content.innerHTML = '<div class="alert alert-success">No anomalies detected</div>';
  } else {
    content.innerHTML = detectedAnomalies.map(anom => {
      const color = anom.severity === 'high' ? '#dc2626' : '#f59e0b';
      return `<div class="anomaly-item" style="border-left: 3px solid ${color};"><div style="font-weight: 700; color: ${color};">${anom.type}</div><div><strong>${anom.name}</strong> (${anom.mmsi})</div><div style="font-size: 10px; color: var(--text-secondary);">${anom.value}</div></div>`;
    }).join('');
  }
  const modal = document.getElementById('anomalyModal');
  if (modal) modal.classList.add('active');
}

function showDataSourceDashboard() {
  const content = document.getElementById('dataSourceContent');
  if (!content) return;
  const unmatchedCV = cvDetections.filter(cv => !cv.matched && cv.confidence >= minCVConfidence / 100);
  const matchedCV = cvDetections.filter(cv => cv.matched);
  let html = `<div style="font-size: 11px; line-height: 1.8;">
    <div style="padding: 12px; background: var(--bg-2); border-radius: 6px; margin-bottom: 12px;">
      <div style="font-weight: 700; margin-bottom: 8px;">System Overview</div>
      <div>AIS Vessels: <strong>${latestShips.length}</strong></div>
      <div>CV Detections: <strong>${cvDetections.length}</strong></div>
      <div>Matched: <strong>${matchedCV.length}</strong></div>
      <div>Unmatched: <strong>${unmatchedCV.length}</strong></div>
    </div>
    <div style="padding: 12px; background: var(--bg-2); border-radius: 6px;">
      <div style="font-weight: 700; margin-bottom: 8px;">Source Reliability Scores</div>
      <div style="margin-bottom: 6px;">AIS: <span style="color: var(--primary); font-weight: 700;">${(sourceReliability.ais * 100).toFixed(0)}%</span></div>
      <div style="margin-bottom: 6px;">Computer Vision: <span style="color: #7c3aed; font-weight: 700;">${(sourceReliability.cv * 100).toFixed(0)}%</span></div>
      <div>LSTM Prediction: <span style="color: #be185d; font-weight: 700;">${(sourceReliability.lstm * 100).toFixed(0)}%</span></div>
    </div>
  </div>`;
  content.innerHTML = html;
  const modal = document.getElementById('dataSourceModal');
  if (modal) modal.classList.add('active');
}

      <div class="metric-grid" style="margin-bottom: 8px;"><div class="metric-box"><div class="metric-value" style="color: ${getSpeedColor(ship.sog)};">${ship.sog.toFixed(1)}</div><div class="metric-label">Speed (kts)</div></div><div class="metric-box"><div class="metric-value">${ship.cog.toFixed(0)}</div><div class="metric-label">Heading (°)</div></div></div>
      <div style="font-size: 10px; padding: 8px; background: var(--bg-2); border-radius: 4px;"><div style="display: flex; justify-content: space-between; margin-bottom: 4px; padding-bottom: 4px; border-bottom: 1px solid var(--border);"><span>Lat</span><span style="font-family: monospace; font-weight: 600;">${lat}</span></div><div style="display: flex; justify-content: space-between; margin-bottom: 4px; padding-bottom: 4px; border-bottom: 1px solid var(--border);"><span>Lon</span><span style="font-family: monospace; font-weight: 600;">${lon}</span></div><div style="display: flex; justify-content: space-between; margin-bottom: 4px; padding-bottom: 4px; border-bottom: 1px solid var(--border);"><span>Duration</span><span>${trackDuration} min</span></div><div style="display: flex; justify-content: space-between;"><span>Distance</span><span>${distance} km</span></div></div>
      ${lstm ? `<div style="font-size: 10px; margin-top: 8px; padding: 8px; background: rgba(190, 24, 93, 0.1); border-left: 2px solid #be185d; border-radius: 4px;"><div style="font-weight: 600; color: #be185d;">LSTM Prediction: ${(lstm.confidence * 100).toFixed(0)}% confidence</div></div>` : ''}
    `;
  };
})();

// ─────────────────────────────
// MODE & VIEW SWITCHING
// ─────────────────────────────

function goToHub() {
  window.location.href = 'http://localhost:8000/';
}

/**
 * setViewMode — controls the right-side view in the map area
 * 'ais'    → map only (no video window)
 * 'live'   → video window shown (CV feed)
 * 'hybrid' → both map + video window
 */
function setViewMode(mode) {
  document.querySelectorAll('.view-mode-btn').forEach(btn => btn.classList.remove('active'));
  const btnMap = { ais: 'btnViewAIS', live: 'btnViewLive', hybrid: 'btnViewHybrid' };
  const activeBtn = document.getElementById(btnMap[mode]);
  if (activeBtn) activeBtn.classList.add('active');

  const videoWindow = document.querySelector('.video-window');
  if (videoWindow) {
    videoWindow.style.display = (mode === 'live' || mode === 'hybrid') ? 'flex' : 'none';
  }
}

/**
 * switchMode — switches between AIS-only and hybrid backend modes.
 * Calls /api/mode on the AIS backend, then updates the UI accordingly.
 */
function switchMode(mode) {
  document.querySelectorAll('.mode-btn').forEach(btn => btn.classList.remove('active'));
  const btnMap = { 'ais-only': 'btnModeAIS', 'hybrid': 'btnModeHybrid' };
  const activeBtn = document.getElementById(btnMap[mode]);
  if (activeBtn) activeBtn.classList.add('active');

  // Call the fusion backend (same origin) to switch mode
  fetch(window.location.origin + '/api/mode', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode })
  })
  .then(r => r.json())
  .then(data => {
    console.log('Mode switch response:', data);
    showToast(`Mode: ${mode === 'ais-only' ? 'AIS Only' : 'Hybrid'}`);
    // In AIS-only mode the video window should be hidden
    if (mode === 'ais-only') setViewMode('ais');
  })
  .catch(e => {
    console.error('Mode switch error:', e);
    showToast('Mode switch failed — check backend');
  });
}

// Initialize systems
setTimeout(() => {
  initializeSearch();
  loadSavedLocations();
  updateAlertThresholds();
  initializeMultiSourceSystem();
  matchCVToAIS();
  generateLSTMPredictions();
  detectAnomalies();

  // Display mode indicator
  const params = new URLSearchParams(window.location.search);
  const currentMode = params.get('mode') || 'hybrid';
  const title = document.querySelector('.system-title span');
  if (title) {
    const modeLabel = currentMode === 'hybrid' ? '🚀 HYBRID' : '📡 AIS-ONLY';
    title.innerHTML = `Maritime Intelligence System <span style="margin-left: 10px; font-size: 12px; opacity: 0.8;">${modeLabel}</span>`;
  }

  // Add mode switcher and Marvis link to top bar
  const viewModeButtons = document.querySelector('.view-mode-buttons');
  if (viewModeButtons && !document.querySelector('.mode-switcher')) {
    const switcher = document.createElement('div');
    switcher.className = 'mode-switcher';
    switcher.style.cssText = 'display: flex; gap: 8px; align-items: center; margin-right: 8px;';

    if (currentMode === 'hybrid') {
      switcher.innerHTML = `
        <a href="http://localhost:5000" target="_blank" style="padding: 6px 12px; background: #10b981; color: white; border-radius: 4px; text-decoration: none; font-size: 12px; white-space: nowrap;">📊 Marvis Analytics</a>
      `;
    }

    switcher.innerHTML += `
      <a href="http://localhost:8000/" style="padding: 6px 12px; background: var(--primary); color: white; border-radius: 4px; text-decoration: none; font-size: 12px;">Change Mode</a>
    `;

    viewModeButtons.parentNode.insertBefore(switcher, viewModeButtons);
  }
  
  // Sync the mode with the backend on startup
  switchMode(currentMode);
}, 500);
