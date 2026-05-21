#!/bin/bash
# Maritime Intelligence System - Single Command Startup (Linux/Mac)
# Starts AIS Backend (8000), Marvis Backend (5000), and opens browser

# Configuration
export AIS_API_KEY="3493cfbd66acfed5d1ea65b5fb5c5353b88ef4b4"
export VIDEO_PATH="C:\Users\91944\MajorProject\data\videos\input.avi"
export ENABLE_VIDEO_PROCESSING="true"
export DEVICE="cuda"
export CAMERA_LAT="1.2800"
export CAMERA_LON="103.8500"
export FOV_KM="2.0"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Paths
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$PROJECT_DIR/ais_dashboard/backend"
MARVIS_BACKEND_DIR="$PROJECT_DIR/marvis_dashboard/backend"

echo ""
echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     Maritime Intelligence System - Unified Startup        ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}\n"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ ERROR: Python 3 not found${NC}"
    exit 1
fi

# Check video exists
if [ ! -f "$VIDEO_PATH" ]; then
    echo -e "${RED}❌ ERROR: Video not found: $VIDEO_PATH${NC}"
    exit 1
fi

# Cleanup function
cleanup() {
    echo -e "\n${YELLOW}🛑 Shutting down...${NC}"
    jobs -p | xargs -r kill 2>/dev/null || true
    echo -e "${GREEN}✅ All services stopped${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

# Start AIS Backend
echo -e "${BLUE}[1/2] Starting AIS Backend (Port 8000)...${NC}"
cd "$BACKEND_DIR"

if [ ! -f "ais_backend_unified.py" ]; then
    echo -e "${RED}❌ ERROR: ais_backend_unified.py not found${NC}"
    exit 1
fi

python3 -m uvicorn ais_backend_unified:app --reload --port 8000 &
BACKEND_PID=$!
echo -e "${GREEN}✅ Backend started (PID: $BACKEND_PID)${NC}"

sleep 2

# Start Marvis Backend
echo -e "${BLUE}[2/2] Starting Marvis Backend (Port 5000)...${NC}"
cd "$MARVIS_BACKEND_DIR"

if [ -f "marvis_api.py" ]; then
    python3 marvis_api.py &
    MARVIS_PID=$!
    echo -e "${GREEN}✅ Marvis started (PID: $MARVIS_PID)${NC}"
    sleep 2
fi

# Display info
echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                 ✅ All Services Started!                  ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}\n"

echo -e "${YELLOW}🎬 System Status:${NC}"
echo -e "   ${BLUE}• AIS Backend:     http://localhost:8000${NC}"
echo -e "   ${BLUE}• Marvis Backend:  http://localhost:5000${NC}"
echo -e "   ${BLUE}• Video:           Processing in background${NC}"
echo ""

echo -e "${YELLOW}🚀 Next Steps:${NC}"
echo "   1. Mode selector will open in browser..."
echo "   2. Select \"AIS-Only\" or \"Hybrid (Video + AIS)\""
echo "   3. In Hybrid: Click \"📊 Marvis Analytics\" for charts"
echo ""

# Open browser
echo -e "${YELLOW}🌐 Opening browser...${NC}"
if command -v xdg-open &> /dev/null; then
    xdg-open http://localhost:8000/ 2>/dev/null &
elif command -v open &> /dev/null; then
    open http://localhost:8000/ 2>/dev/null &
fi

echo ""
echo -e "${YELLOW}⏹️  To stop:${NC}"
echo "   • Press Ctrl+C in this terminal"
echo ""

echo -e "${YELLOW}📊 Dashboards:${NC}"
echo "   • AIS Dashboard:   http://localhost:8000/dashboard"
echo "   • Marvis Dashboard: http://localhost:5000"
echo ""

# Wait
wait $BACKEND_PID

