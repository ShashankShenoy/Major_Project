# FUSION DASHBOARD COMPREHENSIVE AUDIT REPORT
**Date:** June 2, 2026 | **System:** Maritime Intelligence Fusion Dashboard

---

## 📋 DIRECTORY STRUCTURE OVERVIEW

### Backend Files (7 files)
| File | Size | Purpose |
|------|------|---------|
| **fusion_backend.py** | ~1500 lines | Main unified backend (AIS + Video + LSTM) |
| **ais_backend_multi.py** | ~200 lines | Alternate AIS-only backend variant |
| **data_models.py** | ~240 lines | Pydantic data schemas |
| **video_orchestrator.py** | ~600 lines | Video processing (YOLO + DeepOcSort + LSTM) |
| **lstm_integration.py** | ~280 lines | LSTM prediction engine |
| **cv_matcher.py** | ~160 lines | Computer Vision to AIS matching |
| **requirements.txt** | 13 deps | Dependencies (FastAPI, torch, ultralytics, etc.) |

### Frontend Files (8 files)
| File | Purpose |
|------|---------|
| **index.html** | Main dashboard with map & controls |
| **hub.html** | Navigation hub (MARVIS branding) |
| **mode-selector.html** | Mode selection interface |
| **status.html** | System health dashboard |
| **app.js** | Main dashboard logic (~800 lines) |
| **app-enhanced.js** | Enhanced multi-source dashboard (~350 lines) |
| **app-minimal.js** | Minimal dashboard variant (~180 lines) |
| **multisource.js** | Multi-source fusion & anomaly detection (~450 lines) |

---

## 🔴 CRITICAL ISSUES (Severity High+)

### ISSUE #1: Multiple Conflicting JavaScript Implementations
**Severity:** CRITICAL | **Impact:** Unpredictable behavior, data loss

**Problem:** Three separate JavaScript applications with significant overlap and conflicting expectations:

- `app-enhanced.js`: Expects `ais_ships`, `cv_detected_ships`, `matched_ships`, `lstm_predictions` arrays
- `app.js`: Expects unified `ships` array with `source` field
- `app-minimal.js`: Simplified version with basic `ships` array

All can be loaded simultaneously, creating competing WebSocket listeners and event handlers.

**Evidence:**
```javascript
// app-enhanced.js (line ~30)
if (data.ais_ships && Array.isArray(data.ais_ships)) {
  aisShips = {};
  data.ais_ships.forEach(ship => { aisShips[ship.id] = ship; });
}

// app.js (line ~60)
const normalizedShips = normalizeWsMessage(message);
if (normalizedShips) {
  latestShips = normalizedShips;
}
```

**Recommendation:** 
- Keep single `app.js` with feature flags for enhanced/minimal modes
- Remove unused variants or explicitly disable them in HTML

---

### ISSUE #2: WebSocket Data Structure Mismatch
**Severity:** CRITICAL | **Impact:** Silent data loss, misaligned displays

**Problem:** Backend sends unified format but frontend has multiple incompatible parsers:

**Backend Message Format** (fusion_backend.py, line ~450):
```python
unified_msg = {
    "type": "frame",
    "ships": [
        {
            "id": "ais_123456789" or "cam_00001",
            "source": "AIS" or "CAMERA",
            "gps": [lon, lat],  # ← Position is [lon, lat]
            "track": [[lon, lat], ...],
            "predicted": [],
            "mmsi": 123456789
        }
    ]
}
```

**Frontend expects (app.js, line ~90):**
```javascript
const lat = ship.pos[1];  // Assumes [lon, lat] order
const lon = ship.pos[0];

// BUT multisource.js expects (line ~40):
cvDetection.gps_lat  // Separate fields
cvDetection.gps_lon
```

**Additional Coordinate Order Issues:**
- Backend: `gps: [lon, lat]`
- Frontend normalizes: `ship.pos` expecting `[lon, lat]`
- But retrieves: `ship.pos[1]` as lat (correct)
- Yet `multisource.js` uses: `cvMatch.lat`, `cvMatch.lon` (different structure)

**Recommendation:**
- Define canonical JSON schema in OpenAPI/Swagger
- Backend: Document exact field names and coordinate order
- Frontend: Add schema validation on message receive
- Frontend: Single normalization function for all message types

---

### ISSUE #3: Missing WebSocket Reconnection Logic
**Severity:** CRITICAL | **Impact:** Stale connections, frozen UI

**Problem:** Frontend WebSocket has no automatic reconnection:

**Current Code** (app.js, line ~15):
```javascript
ws.onerror = (e) => console.error('WebSocket error:', e);
ws.onclose = () => console.warn('WebSocket closed');  // ❌ No action taken
```

**Problems:**
1. Connection drop not detected by UI
2. No automatic reconnection attempts
3. No heartbeat to detect dead connections
4. Functions call `ws.send()` without checking `readyState` (e.g., `startTracking()`)

**Specific Vulnerability:**
```javascript
function startTracking() {
    if (ws.readyState !== WebSocket.OPEN) return;  // ✓ Only this checks
    ws.send(JSON.stringify({type: "start", lat, lon}));
}

// But these don't check:
function setMode(mode) {
    ws.send(JSON.stringify({type: "set_mode", mode}));  // ❌ Can throw
}
```

**Recommendation:**
- Implement WebSocket wrapper with auto-reconnect (exponential backoff)
- Add heartbeat/ping mechanism (30-second interval)
- Show connection status in UI
- Queue messages when disconnected

---

### ISSUE #4: Mode Switching Error Recovery Incomplete
**Severity:** HIGH | **Impact:** Partial state corruption, resource leak

**Problem:** Heavy ML model loading on mode switch lacks proper error recovery:

**Current Code** (fusion_backend.py, line ~850):
```python
try:
    config = VideoProcessingConfig(...)
    video_orchestrator = await create_video_orchestrator(config)
    await video_orchestrator.initialize(video_frame_queue)  # Can fail here
    await start_video_processing()  # Or here
except Exception as e:
    print(f"❌ Video orchestrator init failed: {e}")
    video_orchestrator = None  # ❌ State left partially initialized
    current_mode = "ais-only"  # Rolled back, but models may be in VRAM
    return {"success": False, ...}
```

**Issues:**
1. If `initialize()` fails midway, models loaded but orchestrator marked as None
2. CUDA memory allocated but not explicitly freed
3. Video processing task created but reference not cleaned up
4. Subsequent mode switches operate on stale state

**Recommendation:**
- Use atomic state transitions (success-or-fully-rollback)
- Explicit CUDA cleanup on failure
- Track all resource allocations

---

## 🟠 HIGH-PRIORITY ISSUES

### ISSUE #5: CV-to-AIS Matching Duplicated (Backend & Frontend)
**Severity:** HIGH | **Impact:** Desynchronized match results

**Problem:** Same matching logic implemented twice with potential divergence:

**Backend Version** (cv_matcher.py):
```python
def match_cv_to_ais(cv_detection, ais_ships, match_radius_km=5.5):
    best_match = None
    best_distance = match_radius_km
    for mmsi, ais_ship in ais_ships.items():
        latest_pos = ais_ship["history"][-1]
        distance = calculate_distance_km(cv_detection.gps_lat, ais_lat)
        if distance < best_distance:
            best_match = (mmsi, distance)
    return best_match
```

**Frontend Version** (multisource.js, line ~40):
```javascript
function matchCVToAIS() {
  cvDetections.forEach(cvDetection => {
    const matchRadius = 0.5;  // ❌ WRONG: This is degrees, not km!
    const match = latestShips.find(ship => {
      const dist = haversineDistance(...);
      return dist < matchRadius;  // Will almost never match correctly
    });
  });
}
```

**The Bug:**
- Backend uses kilometers (5.5 km = ~0.05 degrees)
- Frontend uses degrees (0.5 degrees = ~55 km at equator!)
- Results are incompatible

**Recommendation:**
- Remove frontend matching entirely
- Trust server-provided `matched_to_ais` field
- Only use frontend matching for preview/UI feedback, not truth

---

### ISSUE #6: Hardcoded Match Radius Values in Multiple Locations
**Severity:** HIGH | **Impact:** Inconsistent CV-to-AIS matching

**Conflicting Values Found:**

| Location | Value | Unit | Context |
|----------|-------|------|---------|
| `fusion_backend.py` line 51 | `5.5` | km | Primary config |
| `fusion_backend.py` line 62 | `CV_MATCH_RADIUS_KM` | env var | Runtime config |
| `video_orchestrator.py` line ~150 | `80.0` | pixels | Track assignment |
| `cv_matcher.py` line ~15 | Parameter default `5.5` | km | Function level |
| `multisource.js` line ~40 | `0.5` | degrees | Frontend bug |

**Problem:** No single source of truth. Changes to one don't propagate to others.

**Example Conflict:**
```python
# Backend config
CV_MATCH_RADIUS_KM = float(os.getenv("CV_MATCH_RADIUS_KM", "5.5"))

# Inside video_orchestrator (different unit!)
max_match_distance = 80.0  # pixels!

# Frontend (wrong unit entirely!)
const matchRadius = 0.5;  // degrees not km
```

**Recommendation:**
- Single config file or environment variable
- Convert all to kilometers at module load
- Pass as parameter to functions, don't hardcode

---

### ISSUE #7: Video Frame Queue Memory Accumulation
**Severity:** HIGH | **Impact:** Memory leak, eventual OOM crash

**Problem:** Video queue bounded but no backpressure mechanism:

**Code** (fusion_backend.py, line ~130):
```python
video_frame_queue = asyncio.Queue(maxsize=100)  # Arbitrary limit

# In unified_broadcaster:
while not video_frame_queue.empty():
    f = video_frame_queue.get_nowait()
    if getattr(f, 'video_frame', None):
        video_frame_b64 = f.video_frame  # ~300KB per frame
```

**Math:**
- 100 frames × 300KB per frame = 30MB minimum
- If broadcaster lags behind processor, queue fills instantly
- Long videos (1-2 hours) can accumulate gigabytes

**No Safeguards:**
- Queue maxsize is arbitrary (not based on memory)
- No frame dropping policy
- No backpressure to slow down video processor
- No monitoring or alerts

**Recommendation:**
- Implement adaptive queue sizing based on memory
- Drop frames if queue full (with logging)
- Add memory monitoring

---

## 🟡 MEDIUM-PRIORITY ISSUES

### ISSUE #8: Inconsistent API Endpoint Design
**Severity:** MEDIUM | **Impact:** Frontend confusion, wrong calls

**Two Endpoints for Same Function:**

**Endpoint 1** (fusion_backend.py, line ~800):
```python
@app.post("/api/mode/{mode}")
async def set_mode(mode: str):
    # Usage: POST /api/mode/hybrid
```

**Endpoint 2** (fusion_backend.py, line ~815):
```python
@app.post("/api/mode")
async def set_mode_from_body(request: Request):
    payload = await request.json()
    mode = payload.get("mode")
    # Calls set_mode(mode) internally
    # Usage: POST /api/mode with {"mode": "hybrid"}
```

**Additional Endpoint:**
```python
@app.get("/api/mode")
async def get_mode():
    # Separate GET endpoint (read-only)
```

**Problems:**
1. Three endpoints for mode functionality
2. Endpoint 2 calls Endpoint 1 internally (unnecessary hop)
3. Frontend might use wrong one
4. No clear documentation in code

**Recommendation:**
- Keep single canonical endpoint: `POST /api/mode/{mode}`
- Deprecate body-based variant
- Document all endpoints in OpenAPI spec

---

### ISSUE #9: CUDA Memory Cleanup Incomplete
**Severity:** MEDIUM | **Impact:** Cumulative VRAM degradation

**Problem:** CUDA memory not properly released on mode switch:

**Code** (fusion_backend.py, line ~880):
```python
elif current_mode == "ais-only" and video_orchestrator is not None:
    video_orchestrator.stop()  # ❌ Doesn't unload models
    await cancel_video_processing_task()
    video_orchestrator = None
    
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()  # Only clears cache, not models
    except:
        pass  # Silent failure
```

**Issues:**
1. `stop()` method doesn't unload YOLO model
2. `torch.cuda.empty_cache()` only clears cache, not allocated tensors
3. Exception silently caught (may hide import errors)
4. No verification that memory was freed

**Impact:** After repeated mode switches, VRAM accumulates until OOM

**Recommendation:**
- Explicitly unload models in `VideoOrchestrator.stop()`
- Move CUDA cleanup to destructor
- Add memory tracking/logging

---

### ISSUE #10: State Synchronization in JavaScript Global Variables
**Severity:** MEDIUM | **Impact:** Inconsistent UI display, stale data

**Problem:** Multiple independent state arrays not synchronized:

**Code** (app.js, line ~15):
```javascript
let cvDetections = [];          // Initialized from demo data
let lstmPredictions = [];       // Updated each message
let latestShips = [];           // Updated each message
let selectedShip = null;        // Updated on click

// When message arrives:
if (normalizedShips && normalizedShips.length > 0) {
    latestShips = normalizedShips;  // ✓ Updated
    
    lstmPredictions = cvShips.filter(s =>
        s.predicted && s.predicted.length > 0 && !s.mmsi
    );  // ❌ Derived, not cumulative
    
    // cvDetections never updated from message!
}
```

**Issues:**
1. `cvDetections` initialized from demo data, never updated
2. `lstmPredictions` re-derived each message (loses history)
3. When tracking area changes, stale data remains
4. `selectedShip` becomes orphaned if ship disappears

**Symptoms:**
- Old CV detections visible after new tracking area
- LSTM predictions flicker
- Selecting ship, changing area, selection still shows old ship

**Recommendation:**
- Derive all state from latest message
- Use React/Vue for reactive state (or implement custom state management)
- Clear stale data on tracking area change

---

### ISSUE #11: Missing Input Validation
**Severity:** MEDIUM | **Impact:** Invalid data causes crashes

**Backend Validation** (fusion_backend.py, line ~620):
```python
lat = msg.get("lat")
lon = msg.get("lon")

if lat is None or lon is None:
    continue  # ✓ Checks presence

if not (-90 <= lat <= 90 and -180 <= lon <= 180):
    continue  # ✓ Checks range

# But doesn't verify types are numeric
# Could receive {"lat": "abc", "lon": null}
```

**Frontend Validation** (app.js, line ~200):
```javascript
const lat = parseFloat(document.getElementById("lat").value);
const lon = parseFloat(document.getElementById("lon").value);
// ❌ No check if parseFloat returned NaN
ws.send(JSON.stringify({type: "start", lat, lon}));
```

**Recommendation:**
- Add type checking: `isinstance(lat, (int, float))`
- Frontend: Check for NaN after parseFloat
- Use Pydantic validation on backend
- Add JSDoc type hints on frontend

---

### ISSUE #12: Video Processing Task Not Properly Tracked
**Severity:** MEDIUM | **Impact:** Tasks left running, resource waste

**Problem** (fusion_backend.py, line ~280):
```python
async def start_video_processing():
    global video_processing_task
    
    await cancel_video_processing_task()
    
    print(f"🎬 Starting video processing...")
    video_processing_task = asyncio.create_task(
        video_orchestrator.process_video(VIDEO_PATH)
    )  # ❌ If exception occurs after this, reference updated but task orphaned
```

**Risk:** If exception thrown between line 287 and 290, task created but not tracked properly

**Recommendation:**
```python
try:
    video_processing_task = asyncio.create_task(...)
except Exception as e:
    video_processing_task = None
    raise
```

---

## 🟢 FILE INTERACTION ANALYSIS

### Dependency Graph

```
index.html
├── MapLibre GL library
├── app.js (primary)
│   └── Requires: normalizeUnifiedShip(), getShipKey()
├── multisource.js
│   ├── Modifies: cvDetections, lstmPredictions
│   ├── Calls: matchCVToAIS(), detectAnomalies()
│   └── Issue: Duplicate CV-to-AIS logic
├── app-enhanced.js (CONFLICTING)
│   └── Separate WebSocket handler
└── app-minimal.js (CONFLICTING)
    └── Separate WebSocket handler

Backend (Port 9000)
├── fusion_backend.py (main)
│   ├── Routes: /ws, /api/mode/{mode}, /api/videos, etc.
│   ├── imports video_orchestrator.py
│   ├── imports cv_matcher.py
│   ├── imports lstm_integration.py
│   └── imports data_models.py
├── video_orchestrator.py
│   ├── Uses: YOLO, DeepOcSort, LSTMEngine
│   ├── Produces: ShipDetection objects
│   └── Issue: 80.0 pixel match distance hardcoded
├── lstm_integration.py
│   ├── LSTMEngine class
│   └── Manages: ship trajectory history
└── cv_matcher.py
    ├── CVMatcher class
    └── match_radius_km parameter
```

### Data Flow

1. **AIS Stream** → `persistent_ais_stream()` → updates `ships` dict
2. **Video File** → `video_orchestrator.process_video()` → produces `FrameOutput`
3. **FrameOutput** → `video_frame_queue` → `unified_broadcaster()` 
4. **Unified Message** → `ws.send_json()` → Frontend WebSocket
5. **Frontend** → `normalizeWsMessage()` → `latestShips` → Map render

---

## 📊 QUALITY METRICS

| Metric | Status | Notes |
|--------|--------|-------|
| **Code Duplication** | 🔴 High | CV matching in backend + frontend |
| **Configuration Centralization** | 🔴 Poor | Match radius in 5 locations |
| **Error Handling** | 🔴 Incomplete | Mode switch errors not recoverable |
| **WebSocket Resilience** | 🔴 None | No reconnection logic |
| **Memory Management** | 🟡 Risky | CUDA cleanup incomplete, queue unbounded |
| **API Design** | 🟡 Inconsistent | Multiple mode endpoints |
| **State Management** | 🟡 Weak | Global variables, no synchronization |
| **Type Safety** | 🟡 Partial | Pydantic backend, no frontend validation |
| **Documentation** | 🟡 Minimal | No API schema, comment-based only |
| **Testing** | ❌ None | No test suite visible |

---

## ✅ PRIORITY RECOMMENDATIONS

### 🔴 P0 - Fix Before Production
1. **Consolidate JavaScript** → Merge app.js, app-enhanced.js, app-minimal.js
2. **Document WebSocket Schema** → Define exact message format with examples
3. **Add WebSocket Reconnection** → Implement with exponential backoff + heartbeat
4. **Fix Mode Switch Error Handling** → Atomic transitions with full rollback

### 🟠 P1 - Fix This Sprint
5. **Remove Duplicate CV Matching** → Client-side matching for preview only
6. **Centralize Configuration** → Single source for all constants
7. **Fix Memory Leaks** → Proper CUDA cleanup, queue backpressure
8. **Add Input Validation** → Backend type checking, frontend NaN checks

### 🟡 P2 - Fix This Quarter
9. **Implement Proper State Management** → Consider MobX/Redux or custom store
10. **Add Unit Tests** → Focus on WebSocket message handling, data models
11. **Create API Documentation** → OpenAPI/Swagger spec
12. **Monitor and Alert** → Add logging for failures

---

## 📝 SUMMARY

**Total Issues Found:** 12 (Critical: 4, High: 5, Medium: 3)

**Most Risky Areas:**
1. Multiple conflicting JavaScript implementations
2. WebSocket data structure mismatches
3. Incomplete error handling in mode switching
4. Missing reconnection logic

**Estimated Effort to Fix:**
- P0 items: 2-3 weeks
- P1 items: 1-2 weeks  
- P2 items: 2-3 weeks

**Risk if Not Fixed:** Production instability, data loss on WebSocket disconnection, VRAM exhaustion after repeated mode switches
