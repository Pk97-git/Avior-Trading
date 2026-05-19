#!/bin/bash
# Get directory of this script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Start Backend
echo "Starting Backend..."
cd "$DIR/backend"

# Try to activate venv if it exists
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
elif [ -f "../venv/bin/activate" ]; then
    source ../venv/bin/activate
fi

# Run uvicorn (try path or python module)
if command -v uvicorn &> /dev/null; then
    uvicorn app.main:app --reload --port 8000 &
else
    python3 -m uvicorn app.main:app --reload --port 8000 &
fi
BACKEND_PID=$!

# Start Frontend
echo "Starting Frontend..."
cd "$DIR/frontend"
npm run dev &
FRONTEND_PID=$!

echo "OmniTrader Stack Running"
echo "Backend: http://localhost:8000"
echo "Frontend: http://localhost:5173"
echo "Press Ctrl+C to stop"

# Trap Ctrl+C
trap "kill $BACKEND_PID $FRONTEND_PID; exit" INT
wait
