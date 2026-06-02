# System Safety & Diagnostics Guide

## Overview

To prevent random bugs and silent failures (like the video not loading issue from this morning), I've added a comprehensive safety suite to the fusion backend.

---

## 🛡️ Safeguards in Place

### 1. **Startup Validation**
✅ Runs automatically on backend startup

**Checks:**
- `AIS_API_KEY` is set
- `ENABLE_VIDEO_PROCESSING` configuration
- Video directory exists
- Default video file exists
- Device configuration (cuda/cpu)

**What happens:**
- If critical config is missing → backend prints warnings
- Backend continues but logs all issues
- All issues tracked in diagnostic API

**Example output:**
```
╔════ STARTUP VALIDATION ════╗
✅ AIS_API_KEY configured
✅ Video Processing ENABLED
✅ Video library: 2 files found
✅ Default video available: input.avi
✅ Camera location: 1.2800°N, 103.8500°E
✅ Device: cuda
╚════════════════════════════╝
```

---

### 2. **Diagnostics API**
✅ Access anytime at: `http://localhost:9000/api/diagnostics`

**Returns:**
- ✅ Current configuration (what mode, what video, etc)
- ✅ Runtime status (ships, clients, processing state)
- ✅ System health (AIS connected? Video running? Broadcasting?)
- ✅ Critical issues detected
- ✅ Warnings and suggestions

**Example:**
```bash
curl http://localhost:9000/api/diagnostics | jq
```

**Use this when:**
- Video not loading → check `video_processing_active`
- No ships appearing → check `ais_stream_connected`
- System running slow → check `video_queue_size`
- Anything seems broken → look at `troubleshooting` array

---

### 3. **System Health Dashboard**
✅ Visual status page at: `http://localhost:9000/status`

**Shows:**
- Configuration (is video enabled? which mode? what video?)
- Runtime metrics (ships, clients, frames processed)
- System health (AIS connected? Video running? Broadcasting?)
- All issues and troubleshooting suggestions
- **Auto-refreshes every 5 seconds**

**Open this and leave it running** to catch issues in real-time.

---

### 4. **Enhanced Logging**
✅ Better console output tracking state changes

**Log patterns:**
```
✅ Mode switched: ais-only → hybrid [VIDEO_ENABLED=true]
✅ Hybrid Mode Initialized - VIDEO_PATH=input.avi
❌ Video orchestrator init failed: [error details]
🎬 Video selected: input.avi
```

**Watch for:**
- Any messages starting with `❌` = error
- Any messages starting with `⚠️` = warning
- Messages with `MODE SWITCH` = state change
- If video selection doesn't log a state change, something's wrong

---

### 5. **Comprehensive Troubleshooting Guide**
✅ File: `TROUBLESHOOTING.md` (20+ common issues)

**Covers:**
- Video not loading (root causes & solutions)
- No ships appearing
- Backend crashes
- Hybrid mode won't initialize
- Slow performance
- And more...

---

## 🔍 How to Use the Diagnostic System

### Scenario 1: Video Isn't Loading

1. **Open status dashboard:** `http://localhost:9000/status`
2. **Check these in order:**
   - Is `Video Processing` = ON? (green)
   - Is `Current Mode` = "hybrid"? (should be after selecting video)
   - Is `Video File` showing ✅? (not ❌)
3. **Look at troubleshooting suggestions** at bottom of status page
4. **If still stuck:**
   - Call `/api/diagnostics` API directly
   - Look at `critical_issues` array
   - Check `troubleshooting` array for next steps

### Scenario 2: No Ships on Map

1. **Open status dashboard:** `http://localhost:9000/status`
2. **Check:**
   - Is `AIS Stream` = ✅ Connected?
   - Is `AIS Ships` > 0?
3. **If AIS not connected:**
   - Check AIS_API_KEY in start.bat
   - Check network connection
4. **If AIS connected but no ships:**
   - Camera location may be wrong
   - No ships in that area during this time
   - Try a known high-traffic area

### Scenario 3: System Running Slow

1. **Open status dashboard:** `http://localhost:9000/status`
2. **Check:**
   - `Frames Processed` - should increase over time
   - `Queue Size` - should stay < 5
   - `Connected Clients` - how many viewers?
3. **If queue is backed up:**
   - Processing is slower than broadcast rate
   - Solutions: reduce FOV_KM, lower CONFIDENCE_THRESHOLD, or switch to cpu mode

---

## 🚨 What to Do If Something Breaks

### Step 1: Check Status Dashboard
```
http://localhost:9000/status
```
- Look at all red indicators
- Read troubleshooting suggestions
- Check critical issues list

### Step 2: Get Full Diagnostics
```bash
curl http://localhost:9000/api/diagnostics > diag.json
cat diag.json | jq '.troubleshooting'
```

### Step 3: Check start.bat Configuration
Verify these key settings:
```batch
set ENABLE_VIDEO_PROCESSING=true      # ← MUST BE TRUE
set AIS_API_KEY=9d0b24f78...          # ← Must be set
set VIDEO_PATH=...                     # ← Or let it auto-select
set DEVICE=cuda                        # ← Or cpu
```

### Step 4: Restart Backend
```powershell
# Kill current backend (Ctrl+C)
# Then:
.\start.bat
# Select mode 2 (Hybrid)
```

### Step 5: Review Console Logs
Watch console output for:
- ✅ All startup validation checks pass
- ✅ Mode switches log correctly
- ❌ Any error messages
- ⚠️ Any warnings

---

## 📊 Metrics to Monitor

**In Status Dashboard or `/api/diagnostics`:**

| Metric | Good | Warning | Bad |
|--------|------|---------|-----|
| `video_processing_active` | ✅ true | - | ❌ false when should be true |
| `ais_ships_tracked` | > 10 | 3-10 | 0 for long time |
| `video_queue_size` | < 3 | 3-5 | > 10 (backed up) |
| `video_frames_processed` | increasing | - | not increasing |
| `connected_clients` | 1+ | - | 0 when browser open |
| `ais_stream_connected` | true | - | false |

---

## 🔧 Preventing Silent Failures

### What was broken before?
1. `ENABLE_VIDEO_PROCESSING=false` in start.bat
2. Video selection didn't trigger mode switch
3. System failed silently without clear error messages

### How it's fixed:
1. ✅ Startup validation immediately shows if ENABLE_VIDEO_PROCESSING is wrong
2. ✅ Video selection auto-switches to hybrid mode
3. ✅ Status dashboard always shows current state
4. ✅ Diagnostics API reveals any hidden issues

### How to prevent future silent failures:
1. **Keep status dashboard open** while using system
2. **Check `/api/diagnostics`** when anything seems wrong
3. **Review console logs** regularly for ❌ errors
4. **Read troubleshooting guide** if stuck
5. **Update documentation** when you find new issues

---

## 🎯 Quick Reference

| Need | URL/Command |
|------|---|
| System health | `http://localhost:9000/status` |
| API diagnostics | `curl http://localhost:9000/api/diagnostics` |
| Main dashboard | `http://localhost:9000` |
| Mode status | `curl http://localhost:9000/api/mode` |
| Troubleshooting | `TROUBLESHOOTING.md` in project root |

---

## 📝 New Files Added

1. **`TROUBLESHOOTING.md`** - Comprehensive guide with 20+ issues
2. **`fusion_dashboard/frontend/status.html`** - Visual health dashboard
3. **`/api/diagnostics`** - Detailed system diagnostics endpoint
4. **Startup validation** - Runs automatically on boot
5. **Enhanced logging** - Better console output tracking

---

## Example Workflow

### Morning: Startup
```
1. Run: .\start.bat
2. Check console: all ✅ checkmarks?
3. Open: http://localhost:9000/status
4. Verify: Configuration looks right, no red indicators
5. Select video: should auto-switch to hybrid
6. Watch for errors: check console for ❌
```

### During use:
```
1. Keep status dashboard open in background tab
2. If anything seems slow/wrong: 
   - Click "Refresh Status" button
   - Check for red indicators
   - Read troubleshooting suggestions
3. If still stuck:
   - Run diagnostics API
   - Check TROUBLESHOOTING.md
   - Review console logs
```

### If broken:
```
1. Open status dashboard
2. Look at "Critical Issues" 
3. Look at "Troubleshooting Suggestions"
4. Follow the steps
5. If need to fix code, update TROUBLESHOOTING.md too
```

---

## Questions?

**Everything is documented:**
- Status dashboard → Visual health check
- Diagnostics API → Raw system state
- Troubleshooting.md → Solution for each problem
- Console logs → Real-time status

**If adding new features:**
- Add validation in `validate_startup_config()`
- Add to diagnostics API output
- Update TROUBLESHOOTING.md
- Test with status dashboard open
