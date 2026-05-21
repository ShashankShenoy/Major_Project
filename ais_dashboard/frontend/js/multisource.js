// Multi-source fusion, CV integration, and anomaly detection

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
    const matchRadius = 0.5; // 0.5 km
    const match = latestShips.find(ship => {
      if (!ship.pos || ship.pos.length < 2) return false;
      const dist = haversineDistance(
        cvDetection.gps_lat || cvDetection.lat,
        cvDetection.gps_lon || cvDetection.lon,
        ship.pos[1],
        ship.pos[0]
      );
      return dist < matchRadius;
    });
    cvDetection.matched = match ? match.mmsi : null;
  });
}

function haversineDistance(lat1, lon1, lat2, lon2) {
  if (!lat1 || !lon1 || !lat2 || !lon2) return Infinity;
  const R = 6371;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
    Math.sin(dLon/2) * Math.sin(dLon/2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
  return R * c;
}

function generateLSTMPredictions() {
  lstmPredictions = latestShips.map(ship => {
    if (!ship.track || ship.track.length < 3) return null;
    const recent = ship.track.slice(-3);
    const vx = (recent[2][0] - recent[0][0]) / 2;
    const vy = (recent[2][1] - recent[0][1]) / 2;
    return {
      mmsi: ship.mmsi,
      predictions: [
        [recent[2][0] + vx, recent[2][1] + vy],
        [recent[2][0] + vx * 2, recent[2][1] + vy * 2],
        [recent[2][0] + vx * 3, recent[2][1] + vy * 3]
      ],
      confidence: 0.85
    };
  }).filter(p => p !== null);
}

function fuseDataSources(ship) {
  let bestData = {
    source: 'AIS',
    pos: ship.pos,
    confidence: sourceReliability.ais,
    timestamp: ship.lastUpdate
  };

  const cvMatch = cvDetections.find(cv => cv.matched === ship.mmsi);
  if (cvMatch && cvMatch.confidence >= minCVConfidence / 100) {
    const weight = cvMatch.confidence * sourceReliability.cv;
    if (weight > bestData.confidence * 0.9) {
      bestData = {
        source: 'CV+AIS',
        pos: [
          (ship.pos[0] + cvMatch.lon) / 2,
          (ship.pos[1] + cvMatch.lat) / 2
        ],
        confidence: Math.max(bestData.confidence, weight),
        timestamp: Date.now()
      };
    }
  }

  return bestData;
}

function getSourceBadgeHTML(ship) {
  const cvMatch = cvDetections.find(cv => cv.matched === ship.mmsi);
  let html = `<span class="source-badge source-ais">AIS</span>`;
  if (cvMatch && cvMatch.confidence >= minCVConfidence / 100) {
    html += `<span class="source-badge source-cv">CV ${(cvMatch.confidence * 100).toFixed(0)}%</span>`;
  }
  const lstm = lstmPredictions.find(l => l.mmsi === ship.mmsi);
  if (lstm) {
    html += `<span class="source-badge source-lstm">LSTM</span>`;
  }
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
        detectedAnomalies.push({
          mmsi: ship.mmsi,
          name: ship.name,
          type: 'Sudden Direction Change',
          severity: 'medium',
          value: `${angleDiff.toFixed(0)} degree turn`,
          timestamp: Date.now()
        });
      }
    }

    if (ship.sog > 25) {
      detectedAnomalies.push({
        mmsi: ship.mmsi,
        name: ship.name,
        type: 'Excessive Speed',
        severity: 'high',
        value: `${ship.sog.toFixed(1)} knots`,
        timestamp: Date.now()
      });
    }

    const cvMatch = cvDetections.find(cv => cv.matched === ship.mmsi);
    if (cvMatch && cvMatch.confidence < 0.5) {
      detectedAnomalies.push({
        mmsi: ship.mmsi,
        name: ship.name,
        type: 'Low CV Confidence',
        severity: 'low',
        value: `${(cvMatch.confidence * 100).toFixed(0)}% confidence`,
        timestamp: Date.now()
      });
    }
  });

  const unmatchedCV = cvDetections.find(cv => !cv.matched && cv.confidence > 0.7);
  if (unmatchedCV) {
    detectedAnomalies.push({
      mmsi: 'UNKNOWN',
      name: 'Unknown Vessel',
      type: 'Unmatched Detection',
      severity: 'medium',
      value: `CV only (${(unmatchedCV.confidence * 100).toFixed(0)}%)`,
      timestamp: Date.now()
    });
  }
}

function toggleAnomalyDetection() {
  anomalyDetectionActive = !anomalyDetectionActive;
  if (anomalyDetectionActive) {
    detectAnomalies();
    showAnomalyView();
    showToast('Anomaly detection enabled');
  } else {
    showToast('Anomaly detection disabled');
  }
}

function showAnomalyView() {
  const content = document.getElementById('anomalyContent');
  if (!content) return;

  if (detectedAnomalies.length === 0) {
    content.innerHTML = '<div class="alert alert-success">No anomalies detected</div>';
    const modal = document.getElementById('anomalyModal');
    if (modal) modal.classList.add('active');
    return;
  }

  let html = '';
  detectedAnomalies.forEach(anom => {
    const color = anom.severity === 'high' ? '#dc2626' : anom.severity === 'medium' ? '#f59e0b' : '#0891b2';
    html += `<div class="anomaly-item" style="border-left: 3px solid ${color};">
      <div style="font-weight: 700; margin-bottom: 4px; color: ${color};">${anom.type}</div>
      <div style="margin-bottom: 2px;"><strong>${anom.name}</strong> (${anom.mmsi})</div>
      <div style="font-size: 10px; color: var(--text-secondary);">${anom.value}</div>
    </div>`;
  });

  content.innerHTML = html;
  const modal = document.getElementById('anomalyModal');
  if (modal) modal.classList.add('active');
}

function showDataSourceDashboard() {
  const content = document.getElementById('dataSourceContent');
  if (!content) return;

  const unmatchedCV = cvDetections.filter(cv => !cv.matched && cv.confidence >= minCVConfidence / 100);
  const matchedCV = cvDetections.filter(cv => cv.matched);

  let html = `<div style="font-size: 11px; line-height: 1.8;">
    <div style="margin-bottom: 16px; padding: 12px; background: var(--bg-2); border-radius: 6px;">
      <div style="font-weight: 700; margin-bottom: 8px;">Data Sources Overview</div>
      <div style="margin-bottom: 4px;"><strong>AIS Vessels:</strong> ${latestShips.length}</div>
      <div style="margin-bottom: 4px;"><strong>CV Detections:</strong> ${cvDetections.length}</div>
      <div style="margin-bottom: 4px;"><strong>Matched (AIS + CV):</strong> ${matchedCV.length}</div>
      <div><strong>Unmatched CV:</strong> ${unmatchedCV.length}</div>
    </div>

    <div style="margin-bottom: 16px; padding: 12px; background: var(--bg-2); border-radius: 6px;">
      <div style="font-weight: 700; margin-bottom: 8px;">Source Reliability</div>
      <div style="margin-bottom: 8px;">
        <div style="display: flex; justify-content: space-between; margin-bottom: 2px;">
          <span>AIS</span>
          <span style="color: var(--primary);">${(sourceReliability.ais * 100).toFixed(0)}%</span>
        </div>
        <div class="confidence-bar"><div class="confidence-fill" style="width: ${sourceReliability.ais * 100}%;"></div></div>
      </div>
      <div style="margin-bottom: 8px;">
        <div style="display: flex; justify-content: space-between; margin-bottom: 2px;">
          <span>Computer Vision</span>
          <span style="color: #7c3aed;">${(sourceReliability.cv * 100).toFixed(0)}%</span>
        </div>
        <div class="confidence-bar"><div class="confidence-fill" style="width: ${sourceReliability.cv * 100}%;"></div></div>
      </div>
      <div>
        <div style="display: flex; justify-content: space-between; margin-bottom: 2px;">
          <span>LSTM Prediction</span>
          <span style="color: #be185d;">${(sourceReliability.lstm * 100).toFixed(0)}%</span>
        </div>
        <div class="confidence-bar"><div class="confidence-fill" style="width: ${sourceReliability.lstm * 100}%;"></div></div>
      </div>
    </div>

    <div style="margin-bottom: 16px; padding: 12px; background: var(--bg-2); border-radius: 6px;">
      <div style="font-weight: 700; margin-bottom: 8px;">Unmatched Detections</div>
      ${unmatchedCV.length === 0
        ? '<div style="color: var(--text-secondary);">All CV detections matched to AIS</div>'
        : unmatchedCV.map(cv => `<div style="margin-bottom: 6px; padding: 6px; background: var(--bg-3); border-radius: 4px;">
            Lat: ${cv.lat.toFixed(4)}, Lon: ${cv.lon.toFixed(4)}<br>
            Confidence: ${(cv.confidence * 100).toFixed(0)}%
          </div>`).join('')
      }
    </div>
  </div>`;

  content.innerHTML = html;
  const modal = document.getElementById('dataSourceModal');
  if (modal) modal.classList.add('active');
}

function getEnhancedVesselDetailsHTML(ship) {
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

  return `
    <div style="margin-bottom: 12px;">
      <div style="font-size: 14px; font-weight: 700; color: var(--primary); margin-bottom: 4px;">${ship.name}</div>
      <div style="font-size: 11px; color: var(--text-secondary); font-family: monospace;">MMSI: ${ship.mmsi}</div>
    </div>

    <div style="margin-bottom: 12px;">
      <div style="font-size: 10px; text-transform: uppercase; color: var(--text-secondary); margin-bottom: 6px; font-weight: 600;">Data Sources</div>
      <div>${getSourceBadgeHTML(ship)}</div>
      <div style="font-size: 10px; color: var(--text-secondary); margin-top: 4px;">Fused: ${fused.source} (${(fused.confidence * 100).toFixed(0)}%)</div>
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
        <div class="metric-value">${ship.cog.toFixed(0)}</div>
        <div class="metric-label">Heading (°)</div>
      </div>
    </div>

    <div style="font-size: 11px; margin-bottom: 12px; padding: 10px; background: var(--bg-2); border-radius: 6px;">
      <div style="display: flex; justify-content: space-between; margin-bottom: 8px; padding-bottom: 8px; border-bottom: 1px solid var(--border);">
        <span style="color: var(--text-secondary);">Latitude</span>
        <span style="color: var(--text-primary); font-family: monospace; font-weight: 600;">${lat}</span>
      </div>
      <div style="display: flex; justify-content: space-between; margin-bottom: 8px; padding-bottom: 8px; border-bottom: 1px solid var(--border);">
        <span style="color: var(--text-secondary);">Longitude</span>
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

    ${lstm ? `<div style="font-size: 11px; margin-bottom: 12px; padding: 10px; background: rgba(190, 24, 93, 0.1); border-radius: 6px; border-left: 3px solid #be185d;">
      <div style="font-weight: 600; margin-bottom: 4px; color: #be185d;">LSTM Prediction</div>
      <div style="color: var(--text-secondary);">Next predicted positions available<br>Confidence: ${(lstm.confidence * 100).toFixed(0)}%</div>
    </div>` : ''}
  `;
}
