# System Review: Issues & Improvements

## 🚨 CRITICAL ISSUES (Production Blockers)

### 1. **WebSocket Connection Leaks** [PRIORITY 1]
- **File:** `ais_backend_multi.py` line 624-746
- **Impact:** Memory grows unbounded; stale connections accumulate
- **Fix:** Add connection timeout, heartbeat mechanism, proper cleanup
- **Effort:** 1 hour
```python
# Add to websocket_endpoint:
async def connection_timeout():
    try:
        while True:
            await asyncio.sleep(300)  # 5 min timeout
            if not ws.connected:
                clients.discard(ws)
    except:
        pass
```

### 2. **CV JSON Polling Race Condition** [PRIORITY 2]
- **File:** `ais_backend_multi.py` line 103-137
- **Impact:** Data corruption, inconsistent state between cv_ships and camera_status
- **Fix:** Add file locking or threading.Lock()
- **Effort:** 2 hours
```python
import fcntl
import threading

cv_lock = threading.Lock()

def load_cv_detections():
    global camera_status, cv_ships
    with cv_lock:
        with open(CV_OUTPUT_PATH, 'r') as f:
            # Read safely
```

### 3. **Backend Disconnection - No Fallback** [PRIORITY 3]
- **File:** `app.js` line 348
- **Impact:** Silent data staleness; user unaware backend is down
- **Fix:** Implement reconnection with exponential backoff + UI alert
- **Effort:** 2 hours
```javascript
let reconnectAttempts = 0;
function reconnectWebSocket() {
    const delay = Math.min(30000, 1000 * Math.pow(2, reconnectAttempts));
    setTimeout(() => {
        ws = new WebSocket(...);
        reconnectAttempts++;
    }, delay);
}
```

### 4. **Memory Leak in Event Listeners** [PRIORITY 4]
- **File:** `app.js` line 1142-1152
- **Impact:** Browser performance degrades after view mode switches
- **Fix:** Store references, remove before re-adding
- **Effort:** 30 minutes

### 5. **No Input Validation on GPS Coordinates** [PRIORITY 5]
- **File:** `ais_backend_multi.py` line 649-669
- **Impact:** Invalid tracking area silently breaks AIS subscription
- **Fix:** Add bounds checking (-90 to 90 lat, -180 to 180 lon)
- **Effort:** 30 minutes

### 6. **CV Detection Rendering Without Bounds Checking** [PRIORITY 6]
- **File:** `app.js` line 510-534
- **Impact:** Runtime errors crash rendering
- **Fix:** Add defensive null checks, validate GPS before rendering
- **Effort:** 1 hour

---

## ⚠️ IMPORTANT ISSUES (Next Sprint)

### 7. **Dictionary Iteration Race Condition**
- **File:** `ais_backend_multi.py` line 517
- **Severity:** Crashes broadcaster intermittently
- **Fix:** Copy dict before iteration or use lock

### 8. **Wrong Distance Metric in CV-AIS Matching**
- **File:** Both backend & frontend
- **Issue:** Euclidean distance in lat/lon is incorrect; should use Haversine
- **Impact:** Wrong vessel matching in certain regions
- **Fix:** Implement Haversine formula

### 9. **Search Not Handling Large Fleets**
- **Issue:** No debouncing; no array change detection
- **Fix:** Add 200ms debounce; create search index

### 10. **CSV Export Missing Field Escaping**
- **Issue:** Special characters break CSV parsing
- **Fix:** Use proper CSV quoting for all fields

### 11. **Stale Ship Cleanup in Receive Loop**
- **Issue:** O(n) cleanup on every message; inefficient
- **Fix:** Move to separate 30-second background task

### 12. **View Mode Switching Race Condition**
- **Issue:** Multiple WebSocket connections created on rapid clicks
- **Fix:** Use state machine; lock connectVideoStream()

### 13. **Alert Threshold Validation Missing**
- **Issue:** User can enter negative/invalid values
- **Fix:** Validate ranges before applying

### 14. **Prediction Fails With < 5 Points**
- **Issue:** No feedback when predictions unavailable
- **Fix:** Show confidence score; indicate "insufficient data"

### 15. **Camera Status Updated On Every Message**
- **Issue:** DOM thrashing; unnecessary reflows
- **Fix:** Only update if status changed

---

## 💡 IMPROVEMENTS (Backlog)

### Architecture Improvements:
- [ ] Replace polling with file watcher (watchdog) or message queue
- [ ] Implement level-of-detail rendering (limit historical data size)
- [ ] Add state persistence to localStorage
- [ ] Implement structured logging (prometheus metrics)

### UX Improvements:
- [ ] Add keyboard shortcuts for view modes (1/2/3)
- [ ] Loading indicators during long operations
- [ ] Health check endpoint (`GET /health`)
- [ ] Theme system with CSS variables
- [ ] GPS coordinate validation & anomaly flagging
- [ ] Vessel count limit with spatial indexing (quadtree)

### Data Quality:
- [ ] Improve LSTM predictions (use actual model or Kalman filter)
- [ ] Add time-to-collision calculation
- [ ] Implement anomaly severity weighting
- [ ] Multiple export formats (JSON, GeoJSON, KML)
- [ ] Adaptive rate limiting + message compression

---

## 📊 QUICK WINS (High Impact, Low Effort)

1. **CSV Field Escaping** - 10 min - Prevents export failures
2. **Search Input Debouncing** - 15 min - Fixes UI freezing
3. **Health Check Endpoint** - 20 min - Enables monitoring
4. **Event Listener Cleanup** - 30 min - Fixes performance regression
5. **Input Validation** - 30 min - Prevents invalid state
6. **Camera Status Dirty Flag** - 15 min - Reduces DOM thrashing

---

## 🛠️ RECOMMENDED FIX ORDER

**Week 1 (Critical):**
- Day 1-2: Fix WebSocket leaks + reconnection
- Day 2-3: Fix CV polling race condition
- Day 3-4: Add input validation
- Day 4-5: Fix event listener leak

**Week 2 (Important):**
- Day 1: Fix distance metric (Haversine)
- Day 2: Dictionary iteration race condition
- Day 3: View mode switching race condition
- Day 4: Search debouncing + CSV escaping
- Day 5: Health check endpoint

**Week 3+ (Backlog):**
- Implement monitoring
- Improve predictions
- Add state persistence
- Performance optimizations

---

## 🎯 TESTING CHECKLIST

After fixes, verify:
- [ ] Backend survives 1 hour with 100+ vessels without memory growth
- [ ] Frontend remains smooth after 50 view mode switches
- [ ] WebSocket reconnects gracefully after 5-min disconnect
- [ ] Invalid GPS coordinates show error message
- [ ] CSV export with special characters is parseable
- [ ] Camera online/offline toggle doesn't crash frontend
- [ ] Search works smoothly with 1000+ vessels
- [ ] No console errors after 10 minutes of normal use
