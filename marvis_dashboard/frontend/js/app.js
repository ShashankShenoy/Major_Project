// ─────────────────────────────────────────────────────────────
// Marvis Dashboard — frontend app.js
// Polls /api/results for base64 JPEG frames (video display)
// Polls /api/status for buffer progress (30s LSTM stabilization)
// Polls /api/history for trajectory data (analytics/charts)
// ─────────────────────────────────────────────────────────────

const HISTORY_WINDOW = 60;           // Only last 60 frames — avoids mixing stale/wrap-around data
const ANALYTICS_REFRESH_MS = 5000;
const STATUS_REFRESH_MS = 2000;      // 2s is enough — 1s caused noisy status flicker
const VIDEO_FRAME_REFRESH_MS = 1000;  // match DISPLAY_UPDATE_SECONDS

let analyticsTimer = null;
let statusTimer = null;
let videoFrameTimer = null;
let latestHistoryKey = null;

// ─────────────────────────────
// UTILITY
// ─────────────────────────────

function normalizeShipId(rawId, fallbackIndex) {
  if (typeof rawId === 'number') return rawId;
  if (typeof rawId === 'string') {
    const match = rawId.match(/(\d+)(?!.*\d)/);
    if (match) return Number(match[1]);
  }
  return fallbackIndex;
}

function headingToDir(h) {
  const dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
  return dirs[Math.round((((h % 360) + 360) % 360) / 45) % 8];
}

function normalizeFrame(rawFrame) {
  if (!rawFrame || !Array.isArray(rawFrame.ships)) return null;

  const ships = rawFrame.ships.map((ship, index) => ({
    id: normalizeShipId(ship.id, index),
    raw_id: ship.id ?? index,
    name: ship.name || `Vessel ${index}`,
    center: Array.isArray(ship.center) ? ship.center : (Array.isArray(ship.pos) ? ship.pos : [0, 0]),
    heading: ship.heading ?? ship.cog ?? 0,
    speed: ship.speed ?? ship.sog ?? 0,
    direction: ship.direction || headingToDir(ship.heading ?? ship.cog ?? 0),
    confidence: ship.confidence ?? 0.7,
    prediction_method: ship.prediction_method || 'KINEMATIC',
    predicted_path: Array.isArray(ship.predicted_path)
      ? ship.predicted_path
      : (Array.isArray(ship.predicted_path_gps) ? ship.predicted_path_gps : []),
    gps: Array.isArray(ship.gps)
      ? ship.gps
      : (ship.gps_lat !== undefined && ship.gps_lon !== undefined ? [ship.gps_lat, ship.gps_lon] : null),
    class: ship.class || ship.source || 'vessel'
  }));

  return {
    frame: rawFrame.frame ?? rawFrame.frame_number ?? 0,
    ship_count: rawFrame.ship_count ?? ships.length,
    ships,
    collision_alerts: Array.isArray(rawFrame.collision_alerts) ? rawFrame.collision_alerts : [],
    frame_timestamp: rawFrame.frame_timestamp ?? rawFrame.timestamp ?? null,
    buffer_phase: Boolean(rawFrame.buffer_phase)
  };
}

// ─────────────────────────────
// VIDEO FRAME POLLING
// Fetches /api/results every 1s and updates the <img id="videoFrame">
// with the base64 JPEG encoded frame from the Marvis backend.
// Falls back gracefully if backend is unavailable.
// ─────────────────────────────

async function updateVideoFrame() {
  try {
    const resp = await fetch('/api/results', { cache: 'no-store' });
    if (!resp.ok) return;
    const data = await resp.json();

    if (data && data.video_frame) {
      const img = document.getElementById('videoFrame');
      if (img) {
        img.src = `data:image/jpeg;base64,${data.video_frame}`;
      }

      const statusEl = document.getElementById('videoStatus');
      if (statusEl) {
        if (data.buffer_phase) {
          statusEl.textContent = '⏳ Buffering — LSTM stabilizing…';
        } else {
          statusEl.textContent = `▶ Processing · Frame ${data.frame ?? ''}`;
        }
      }
    }
  } catch (_) {
    // Silent fail — backend may not be ready yet
  }
}

// ─────────────────────────────
// STATUS POLLING
// Fetches /api/status every 1s and updates:
//   - sidebar status label
//   - buffer progress banner (progress bar + text)
// ─────────────────────────────

function updateStatus(status) {
  const sbStatus = document.getElementById('sbStatus');
  const fileInfo = document.getElementById('fileInfo');
  const videoStatus = document.getElementById('videoStatus');
  const bufferBanner = document.getElementById('bufferBanner');
  const bufferText = document.getElementById('bufferText');
  const bufferProgressFill = document.getElementById('bufferProgressFill');
  const bufferPct = document.getElementById('bufferPct');

  if (!status) {
    if (sbStatus) sbStatus.textContent = 'WAITING FOR BACKEND';
    if (fileInfo) fileInfo.textContent = 'Marvis backend unavailable';
    return;
  }

  // Sidebar status
  const state = status.processing
    ? (status.buffer_complete ? 'LIVE ANALYTICS' : 'BUFFERING')
    : 'IDLE';
  if (sbStatus) sbStatus.textContent = `${state} · ${new Date().toLocaleTimeString()}`;

  if (fileInfo) {
    fileInfo.textContent = `${status.buffer_message ?? ''} Frames: ${status.frames_processed}`;
  }

  // Buffer progress banner
  const pct = status.buffer_progress_pct ?? 0;
  if (bufferProgressFill) bufferProgressFill.style.width = `${pct}%`;
  if (bufferPct) bufferPct.textContent = `${pct}%`;

  if (status.buffer_complete) {
    // LSTM active — switch banner to green "active" style
    if (bufferBanner) bufferBanner.className = 'buffer-banner active';
    if (bufferText) bufferText.textContent = `✅ LSTM Active — predictions update every ${status.update_interval_seconds ?? 30}s`;
    if (videoStatus && !videoStatus.textContent.startsWith('▶')) {
      videoStatus.textContent = '▶ Playing prerecorded video';
    }
  } else {
    // Still buffering — amber style with progress
    if (bufferBanner) bufferBanner.className = 'buffer-banner';
    if (bufferText) {
      bufferText.textContent = `⏳ Building 30-second buffer for LSTM stabilization… (${pct}%)`;
    }
    if (videoStatus) {
      videoStatus.textContent = '⏳ Video playing while model buffer stabilizes';
    }
  }

  // Update auto-refresh label (simplified)
  const label = document.getElementById('autoRefreshLabel');
  if (label) {
    const seconds = status.update_interval_seconds ?? 30;
    // find the text node after the checkbox and update it
    const textNodes = [...label.childNodes].filter(n => n.nodeType === 3);
    if (textNodes.length) textNodes[textNodes.length - 1].textContent = ` Auto-refresh (${seconds}s)`;
  }
}

async function refreshStatus() {
  try {
    const resp = await fetch('/api/status', { cache: 'no-store' });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const status = await resp.json();
    updateStatus(status);
  } catch (e) {
    const sbStatus = document.getElementById('sbStatus');
    const fileInfo = document.getElementById('fileInfo');
    const videoStatus = document.getElementById('videoStatus');
    if (sbStatus) sbStatus.textContent = 'BACKEND UNAVAILABLE';
    if (fileInfo) fileInfo.textContent = `⚠ ${e.message}`;
    if (videoStatus) videoStatus.textContent = '❌ Video backend unavailable';
  }
}

// ─────────────────────────────
// HISTORY / ANALYTICS POLLING
// Fetches /api/history every 5s and triggers the chart render
// Only re-renders if the history key (frame count + last frame) changed.
// ─────────────────────────────

async function loadData() {
  try {
    const resp = await fetch('/api/history', { cache: 'no-store' });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

    const data = await resp.json();
    const normalized = Array.isArray(data)
      ? data.map(normalizeFrame).filter(Boolean).slice(-HISTORY_WINDOW)
      : [];

    const historyKey = normalized.length
      ? `${normalized[normalized.length - 1].frame}-${normalized.length}`
      : 'empty';

    // Only re-render if data actually changed
    if (historyKey === latestHistoryKey) return;
    latestHistoryKey = historyKey;
    results = normalized;

    if (!results.length) {
      const fileInfo = document.getElementById('fileInfo');
      if (fileInfo) fileInfo.textContent = 'Waiting for processed frames…';
      return;
    }

    const fileInfo = document.getElementById('fileInfo');
    if (fileInfo) fileInfo.textContent = `✓ Loaded ${results.length} processed frames`;
    render();
  } catch (e) {
    const fileInfo = document.getElementById('fileInfo');
    if (fileInfo) fileInfo.textContent = `⚠ ${e.message}`;
  }
}

// ─────────────────────────────
// TIMER MANAGEMENT
// ─────────────────────────────

function startAnalyticsRefresh() {
  if (analyticsTimer) clearInterval(analyticsTimer);
  analyticsTimer = setInterval(() => {
    if (document.getElementById('autoRefresh')?.checked) {
      loadData();
    }
  }, ANALYTICS_REFRESH_MS);
}

function startStatusRefresh() {
  if (statusTimer) clearInterval(statusTimer);
  statusTimer = setInterval(refreshStatus, STATUS_REFRESH_MS);
}

function startVideoFramePolling() {
  if (videoFrameTimer) clearInterval(videoFrameTimer);
  videoFrameTimer = setInterval(updateVideoFrame, VIDEO_FRAME_REFRESH_MS);
  updateVideoFrame(); // First call immediately — don't wait 1s
}

// ─────────────────────────────
// SIDEBAR INIT
// ─────────────────────────────

// Set the hidden jsonPath to /api/history so loadData() fetches live data
const jsonPathValEl = document.getElementById('jsonPath');
if (jsonPathValEl) jsonPathValEl.value = '/api/history';

// ─────────────────────────────
// AUTO-REFRESH TOGGLE
// ─────────────────────────────

const autoRefreshEl = document.getElementById('autoRefresh');
if (autoRefreshEl) {
  autoRefreshEl.addEventListener('change', e => {
    if (e.target.checked) {
      loadData();
      refreshStatus();
      startAnalyticsRefresh();
    } else if (analyticsTimer) {
      clearInterval(analyticsTimer);
    }
  });
}

// ─────────────────────────────
// KEYBOARD SHORTCUT: R = manual refresh
// ─────────────────────────────

document.addEventListener('keydown', e => {
  if (e.key.toLowerCase() === 'r' && !e.ctrlKey && !e.metaKey) {
    refreshStatus();
    loadData();
    updateVideoFrame();
  }
});

// ─────────────────────────────
// BOOT — start all polling loops
// ─────────────────────────────

startVideoFramePolling();  // Video frames (1s)  — most time-sensitive
refreshStatus();           // Status (immediate first call)
loadData();                // History (immediate first call)
startStatusRefresh();      // Status timer (1s)
startAnalyticsRefresh();   // Analytics timer (5s)
