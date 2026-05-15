// Enterprise Maritime Intelligence System - Fixed

const ws = new WebSocket("ws://localhost:8000/ws");

let map, mapLoaded = false, selectedShip = null, latestShips = [];
let sessionStartTime = null, renderScheduled = false;
let replayMode = false, replayTime = null;
let darkMode = localStorage.getItem('darkMode') === 'true';
let collisionThreshold = 0.01;
let portProximity = 0.1;

// Filter states
let showTracks = true;
let showPredicted = true;
let showArrows = true;
let showHeatmap = false;
let showPorts = false;

// ─────────────────────────────
// THEME SYSTEM
// ─────────────────────────────

function toggleTheme() {
  darkMode = !darkMode;
  localStorage.setItem('darkMode', darkMode);
  document.body.classList.toggle('dark-mode', darkMode);
  document.querySelector('.theme-toggle').innerText = darkMode ? '☀️' : '🌙';
}

if (darkMode) {
  document.body.classList.add('dark-mode');
  document.querySelector('.theme-toggle').innerText = '☀️';
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
});

function initializeSources() {
  const sources = ["ships", "tracks", "selected-track", "predicted", "selected-predicted",
                   "destination", "headings", "arrows", "speed-circles", "heatmap", "ports", "collision-zones"];

  sources.forEach(src => {
    if (map.getSource(src)) return;
    map.addSource(src, { type: "geojson", data: { type: "FeatureCollection", features: [] } });
  });
}

function initializeLayers() {
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

  if (!map.getLayer("ships-layer")) {
    map.addLayer({
      id: "ships-layer",
      type: "circle",
      source: "ships",
      paint: {
        "circle-radius": ["case", ["==", ["get", "selected"], 1], 11, 6.5],
        "circle-color": ["get", "risk_color"],
        "circle-stroke-width": ["case", ["==", ["get", "selected"], 1], 3, 1.5],
        "circle-stroke-color": ["case", ["==", ["get", "selected"], 1], "#2563eb", "#d1d5db"]
      }
    });
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
    const features = map.queryRenderedFeatures(e.point, { layers: ["ships-layer"] });
    if (features.length > 0) {
      selectShip(features[0].properties.mmsi);
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

ws.onopen = () => console.log("Connected");
ws.onmessage = (event) => {
  latestShips = JSON.parse(event.data);
  scheduleRender();
  updateAnalytics();
  checkAlerts();
};
ws.onerror = (err) => console.error("Error:", err);

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
  const risk = getRiskScore(ship);
  if (risk <= 2) return "#16a34a";
  if (risk <= 5) return "#2563eb";
  if (risk <= 7) return "#f59e0b";
  return "#dc2626";
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
  document.getElementById("headerAvgSpeed").innerText = (speeds.reduce((a, b) => a + b, 0) / speeds.length).toFixed(1);

  if (sessionStartTime) {
    const elapsed = Math.round((Date.now() - sessionStartTime) / 1000);
    const mins = Math.floor(elapsed / 60), secs = elapsed % 60;
    document.getElementById("sessionTime").innerText = `${mins}:${secs.toString().padStart(2, '0')}`;
  }
}

function checkAlerts() {
  let alerts = [];
  let collisionCount = 0;

  latestShips.forEach(ship => {
    if (getRiskScore(ship) > 6) alerts.push(`⚠️ High risk vessel ${ship.name}`);
    if (hasCollisionRisk(ship)) collisionCount++;
  });

  if (collisionCount > 0) alerts.unshift(`🚨 ${collisionCount} potential collision(s) detected`);

  const container = document.getElementById("alertsContainer");
  if (!alerts.length) {
    container.innerHTML = '<div class="alert alert-success"><strong>✓ All Clear</strong><br>No active alerts</div>';
    document.getElementById("headerAlerts").innerText = "0";
  } else {
    container.innerHTML = alerts.map((a) => {
      const isCollision = a.includes('🚨');
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

  const ships = [], tracks = [], selTracks = [], preds = [], selPreds = [];
  const dests = [], headings = [], arrows = [], speedCircles = [], collisions = [], heatmapPoints = [];

  latestShips.forEach(ship => {
    const selected = ship.mmsi === selectedShip ? 1 : 0;
    const riskColor = getRiskColor(ship);

    ships.push({
      type: "Feature",
      geometry: { type: "Point", coordinates: ship.pos },
      properties: { mmsi: ship.mmsi, selected, risk_color: riskColor }
    });

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

  const ship = latestShips.find(s => s.mmsi === selectedShip);
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

  section.style.display = 'block';
  noSection.style.display = 'none';

  document.getElementById("selectedVesselContent").innerHTML = `
    <div style="margin-bottom: 12px;">
      <div style="font-size: 14px; font-weight: 700; color: var(--primary); margin-bottom: 4px;">${ship.name}</div>
      <div style="font-size: 11px; color: var(--text-secondary); font-family: monospace;">MMSI: ${ship.mmsi}</div>
    </div>

    <div style="display: flex; gap: 10px; margin-bottom: 12px;">
      <span class="status-badge status-${ship.sog > 1 ? 'moving' : 'anchored'}">
        <span class="status-dot"></span> ${status}
      </span>
      <span class="status-badge" style="background: ${riskColor}20; color: ${riskColor};">
        Risk: ${riskLevel}
      </span>
    </div>

    <div class="metric-grid" style="margin-bottom: 12px;">
      <div class="metric-box">
        <div class="metric-value" style="color: ${getSpeedColor(ship.sog)};">${ship.sog.toFixed(1)}</div>
        <div class="metric-label">Speed (kts)</div>
      </div>
      <div class="metric-box">
        <div class="metric-value">${ship.cog.toFixed(0)}°</div>
        <div class="metric-label">Heading</div>
      </div>
    </div>

    <div style="font-size: 11px; margin-bottom: 12px; padding: 10px; background: var(--bg-2); border-radius: 6px;">
      <div style="display: flex; justify-content: space-between; margin-bottom: 8px; padding-bottom: 8px; border-bottom: 1px solid var(--border);">
        <span style="color: var(--text-secondary);">Position</span>
        <span style="color: var(--text-primary); font-family: monospace; font-weight: 600;">${lat}</span>
      </div>
      <div style="display: flex; justify-content: space-between; margin-bottom: 8px; padding-bottom: 8px; border-bottom: 1px solid var(--border);">
        <span style="color: var(--text-secondary);"></span>
        <span style="color: var(--text-primary); font-family: monospace; font-weight: 600;">${lon}</span>
      </div>
      <div style="display: flex; justify-content: space-between; margin-bottom: 8px; padding-bottom: 8px; border-bottom: 1px solid var(--border);">
        <span style="color: var(--text-secondary);">Track Duration</span>
        <span style="color: var(--text-primary); font-family: monospace; font-weight: 600;">${trackDuration} min</span>
      </div>
      <div style="display: flex; justify-content: space-between;">
        <span style="color: var(--text-secondary);">Distance Traveled</span>
        <span style="color: var(--text-primary); font-family: monospace; font-weight: 600;">${distance} km</span>
      </div>
    </div>
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
// UPDATE LOOP
// ─────────────────────────────

setInterval(() => {
  if (sessionStartTime) {
    updateAnalytics();
  }
}, 1000);
