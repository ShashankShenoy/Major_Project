#!/bin/bash

# AIS Maritime Tracking Dashboard - Startup Script
# Runs all three components: Backend, CV Processor, and Frontend

set -e

# Set AIS API Key
export AIS_API_KEY="3493cfbd66acfed5d1ea65b5fb5c5353b88ef4b4"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Project paths
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$PROJECT_DIR/ais_dashboard/backend"
FRONTEND_DIR="$PROJECT_DIR/ais_dashboard/frontend"

echo -e "${BLUE}╔════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   AIS Maritime Tracking Dashboard - Startup        ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════╝${NC}\n"

# Check Python is installed
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python 3 not found. Please install Python 3.8+${NC}"
    exit 1
fi

# Check required directories
if [ ! -d "$BACKEND_DIR" ]; then
    echo -e "${RED}❌ Backend directory not found: $BACKEND_DIR${NC}"
    exit 1
fi

if [ ! -d "$FRONTEND_DIR" ]; then
    echo -e "${RED}❌ Frontend directory not found: $FRONTEND_DIR${NC}"
    exit 1
fi

# Cleanup function
cleanup() {
    echo -e "\n${YELLOW}🛑 Shutting down...${NC}"

    # Kill all background processes
    jobs -p | xargs -r kill 2>/dev/null

    echo -e "${GREEN}✅ All services stopped${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

# Check AIS_API_KEY
if [ -z "$AIS_API_KEY" ]; then
    echo -e "${YELLOW}⚠️  AIS_API_KEY environment variable not set${NC}"
    echo -e "${YELLOW}   Set it with: export AIS_API_KEY='your_key'${NC}\n"
    read -p "Enter AIS API key (or press Enter to skip): " AIS_KEY
    if [ -n "$AIS_KEY" ]; then
        export AIS_API_KEY="$AIS_KEY"
    else
        echo -e "${YELLOW}⚠️  Continuing without API key - Backend will fail${NC}"
    fi
fi

echo -e "${GREEN}✅ Configuration:${NC}"
echo -e "   Project: $PROJECT_DIR"
echo -e "   Backend: http://localhost:8000"
echo -e "   Frontend: http://localhost:3000"
if [ -n "$AIS_API_KEY" ]; then
    echo -e "   AIS API Key: ${AIS_API_KEY:0:10}..."
fi
echo ""

# Start Backend
echo -e "${BLUE}1️⃣  Starting Backend (Port 8000)...${NC}"
cd "$BACKEND_DIR"

if [ ! -f "ais_backend_multi.py" ]; then
    echo -e "${RED}❌ Backend file not found: $BACKEND_DIR/ais_backend_multi.py${NC}"
    exit 1
fi

python3 ais_backend_multi.py &
BACKEND_PID=$!
echo -e "${GREEN}✅ Backend started (PID: $BACKEND_PID)${NC}\n"

# Wait for backend to start
sleep 2

# Start Frontend
echo -e "${BLUE}2️⃣  Starting Frontend (Port 3000)...${NC}"
cd "$FRONTEND_DIR"

python3 -m http.server 3000 &
FRONTEND_PID=$!
echo -e "${GREEN}✅ Frontend started (PID: $FRONTEND_PID)${NC}\n"

# Optional: Start CV Processor
echo -e "${YELLOW}Optional: Start CV Processor (app.py)?${NC}"
read -p "Start CV processor on port 8765? (y/n): " START_CV

if [ "$START_CV" = "y" ] || [ "$START_CV" = "Y" ]; then
    echo -e "${BLUE}3️⃣  Starting CV Processor (Port 8765)...${NC}"
    cd "$PROJECT_DIR"

    if [ -f "app.py" ]; then
        python3 app.py &
        CV_PID=$!
        echo -e "${GREEN}✅ CV Processor started (PID: $CV_PID)${NC}\n"
    else
        echo -e "${YELLOW}⚠️  app.py not found. Skipping CV processor${NC}\n"
    fi
fi

# Status
echo -e "${GREEN}╔════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║            🚀 All Services Running!               ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════╝${NC}\n"

echo -e "${YELLOW}📍 Dashboard URLs:${NC}"
echo -e "   Frontend: ${BLUE}http://localhost:3000${NC}"
echo -e "   Backend:  ${BLUE}ws://localhost:8000/ws${NC}"
if [ -n "$CV_PID" ]; then
    echo -e "   CV:       ${BLUE}ws://localhost:8765${NC}"
fi

echo -e "\n${YELLOW}📋 Process IDs:${NC}"
echo -e "   Backend:  $BACKEND_PID"
echo -e "   Frontend: $FRONTEND_PID"
if [ -n "$CV_PID" ]; then
    echo -e "   CV:       $CV_PID"
fi

echo -e "\n${YELLOW}⚙️  Commands:${NC}"
echo -e "   View logs:     tail -f backend.log"
echo -e "   Stop services: Press Ctrl+C"
echo -e "   Monitor:       ps aux | grep python\n"

# Keep script running
wait $BACKEND_PID
