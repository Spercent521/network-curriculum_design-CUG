
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn
import asyncio
import json
import threading
import os
from terminal_session import TerminalSession

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Set paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(BASE_DIR, '../Frontend/dist')

# Global Node Instance
terminal_instance = None
active_websockets = []

def broadcast_log(msg: str):
    # print(f"[TERM] {msg}") # Optional server-side logging
    for websocket in active_websockets:
        asyncio.run_coroutine_threadsafe(
            websocket.send_json({"type": "log", "data": msg}), 
            loop
        )

def broadcast_topo(data: dict):
    for websocket in active_websockets:
        asyncio.run_coroutine_threadsafe(
            websocket.send_json({"type": "topo", "data": data}), 
            loop
        )

@app.on_event("startup")
async def startup_event():
    global terminal_instance, loop
    loop = asyncio.get_event_loop()
    
    # Initialize Terminal Session
    terminal_instance = TerminalSession(
        log_callback=broadcast_log,
        topo_callback=broadcast_topo
    )

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_websockets.append(websocket)
    
    # Send initial menu if needed, or recent logs?
    # TerminalSession handles its own internal buffer/state if we wanted to show history,
    # but for now, just joining a session might show nothing until next update or we trigger a menu redraw.
    # We can force a menu redraw for the new user if we want, but that might disturb existing output.
    # Let's just tap in.
    
    # If the user just joined, maybe we should show the menu if idle?
    # terminal_instance.show_menu() # Might duplicate if multiple users
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message['type'] == 'command':
                cmd = message['data']
                if terminal_instance:
                    terminal_instance.write(cmd)
                    
    except WebSocketDisconnect:
        active_websockets.remove(websocket)

# Serve React App
# Verify dist directory exists to avoid errors if not built
if os.path.exists(DIST_DIR):
    app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="static")
else:
    print(f"Warning: React Build directory not found at {DIST_DIR}")

if __name__ == "__main__":
    import sys
    port = 8000
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"Invalid port: {sys.argv[1]}, using default 8000")
            
    print(f"Starting Backend on 0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
