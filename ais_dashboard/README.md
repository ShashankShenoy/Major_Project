# AIS Maritime Dashboard - Professional Edition

## ✨ Major Improvements

### 1. **Professional UI/UX**
- **Two-column layout**: Map on left, control panel + ship details on right
- **Modern dark theme**: Dark navy/black with orange (#FF6B35) accent color
- **Smooth animations**: Gradient buttons, hover effects, pulse animations
- **Professional typography**: Proper hierarchy, monospace for technical data
- **Real-time status indicators**: Connection status, tracking state

### 2. **Fixed State Management Issues**
- ✅ **Proper cleanup**: When selecting new tracking area, all old ships clear completely
- ✅ **Selected ship reset**: `selectedShip` set to null before clearing layers
- ✅ **Debounced rendering**: Prevents multiple renders per WebSocket message
- ✅ **Session validation**: Each tracking session has unique ID to prevent stale data

### 3. **Full Path Visualization**
- **Selected ship path**: Bright orange (#FF6B35) full track history (3px width)
- **Other ships paths**: Cyan (#00ffaa) tracks with opacity (1.5px width)
- **Predicted paths**: Orange dashed lines for future trajectory
- **Heading indicators**: Triangle icons showing ship direction (COG)
- **Distinct layers**: Selected track in separate map layer for visual clarity

### 4. **Comprehensive Ship Details Panel**
When you click a ship, displays:
- **Ship Identity**: Name and MMSI
- **Position**: Latitude/Longitude with 6 decimal precision
- **Movement**: Speed (knots) and Course/Heading (degrees) in metric boxes
- **Track History**:
  - Duration (minutes)
  - Distance traveled (km)
  - Average speed (knots)
  - Points tracked
- **Last Update**: Exact time and seconds ago

### 5. **Enhanced Backend Data**
Each ship broadcast now includes:
- `track`: **Full history** (not just 30 points) - all tracked positions
- `trackStats`: Object containing:
  - `duration`: Seconds ship has been tracked
  - `distance`: Total km traveled
  - `points`: Number of historical position points
- `lastUpdate`: Unix timestamp of last position update
- `time`: Server broadcast time

### 6. **Performance Optimizations**
- **Render debouncing**: RequestAnimationFrame throttling prevents frame drops
- **Efficient GeoJSON updates**: Only non-empty feature collections sent
- **Memory management**: Full history stored but rendered efficiently
- **Smooth 60 FPS interactions**: Optimized layer updates

## How to Run

### Prerequisites
```bash
pip install -r ais_dashboard/backend/requirements.txt
```

### Set Environment Variable
```bash
# Linux/Mac
export AIS_API_KEY="your_aisstream_api_key"

# Windows (Command Prompt)
set AIS_API_KEY=your_aisstream_api_key

# Windows (PowerShell)
$env:AIS_API_KEY="your_aisstream_api_key"
```

### Start Backend
```bash
cd ais_dashboard/backend
python ais_backend_multi.py
```

The server runs on `http://localhost:8000`

### Open Frontend
Open in browser: `file:///c/Users/91944/MajorProject/ais_dashboard/frontend/index.html`

Or use a simple HTTP server:
```bash
cd ais_dashboard/frontend
python -m http.server 8080
# Open http://localhost:8080
```

## Feature Usage

### Tracking Ships
1. Enter latitude/longitude or click on the map
2. Click "Track Area" button
3. Ships within ±0.5° will appear on the map
4. Ship count updates in real-time

### Viewing Ship Details
1. Click any ship on the map (green dot)
2. Right sidebar shows comprehensive details
3. Ship's full track path highlights in orange
4. Click another ship to switch selection

### Replay Mode
1. Click "▶ Replay" button to start playback
2. Ships animate through their historical positions
3. Track history rebuilds as replay progresses
4. Click "⏸ Pause" to stop

## Technical Architecture

### Frontend
- **Framework**: Vanilla JavaScript (no dependencies except MapLibre GL)
- **Map Library**: MapLibre GL v4.7.1
- **Communication**: WebSocket to backend
- **State Management**: Global state with proper cleanup
- **Rendering**: RequestAnimationFrame with debouncing

### Backend
- **Framework**: FastAPI with async/await
- **WebSocket**: Real-time bidirectional communication
- **Data Source**: AISStream.io maritime API
- **Calculation**: Numpy for trajectory prediction
- **Metrics**: Distance calculation using haversine formula

### Map Layers (5 total)
1. **tracks-layer**: Other ships' historical paths (cyan)
2. **selected-track-layer**: Selected ship's full path (orange)
3. **predicted-layer**: Future trajectory for all ships (orange dashed)
4. **ships-layer**: Ship position circles (cyan/orange)
5. **headings-layer**: Direction indicators (triangles)

## Integration with CV & LSTM

The AIS system is designed to integrate with your computer vision and LSTM components:

1. **CV Detection**: Ship detection from video feed provides lat/lon
2. **AIS Mapping**: These coordinates match against real-time AIS ships
3. **Fallback**: If no AIS match, LSTM prediction module engages
4. **Unified Dashboard**: All sources display on same map interface

For now, the dashboard focuses on the AIS component which provides authoritative, real-time maritime data. The CV and LSTM integration will be added in next phase.

## Key Improvements Over Previous Version

| Feature | Before | After |
|---------|--------|-------|
| State Cleanup | Partial, stale ships visible | Complete, full clear on new track |
| Ship Info | 4 fields (name, MMSI, SOG, COG) | 12+ fields with metrics |
| Path Display | All paths same color/style | Selected ship path highlighted |
| UI Professional | Basic layout | Modern dark theme with gradients |
| History Display | 30 points trimmed | Full history stored & displayed |
| Performance | Possible frame drops | Smooth 60 FPS with debouncing |
| Error Handling | Bare exception clauses | Specific exception types |
| Security | API key printed to console | API key validation, no logging |

## Future Enhancements

- [ ] CSV export of ship tracking data
- [ ] GeoJSON export for external GIS tools
- [ ] Time-range filtering (last 1h, 6h, 24h)
- [ ] Ship type classification
- [ ] Port detection and docking alerts
- [ ] Multi-area tracking (simultaneous multiple boxes)
- [ ] CV integration for vessel detection
- [ ] LSTM prediction as AIS fallback
- [ ] Database persistence for historical analysis
