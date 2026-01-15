
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import asyncio
import json
import threading
from bridge import WebNetworkNode

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global Node Instance
node_instance = None
active_websockets = []

def broadcast_log(msg: str):
    print(f"[NODE] {msg}")
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
    global node_instance, loop
    loop = asyncio.get_event_loop()
    
    # Initialize Node
    # We pass the broadcast functions as callbacks
    node_instance = WebNetworkNode(
        log_callback=broadcast_log,
        topo_callback=broadcast_topo
    )
    
    # Start the node in a separate thread
    t = threading.Thread(target=node_instance.start, daemon=True)
    t.start()
    
    # We might need to give it some time to init serial? 
    # The original code asks for ID input at start().
    # Wait! NetworkNode.start() usually has input() inside for ID? 
    # Let's check network_app.py implementation of start() and __init__
    # If it asks for input(), we need to handle that.

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_websockets.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message['type'] == 'command':
                cmd = message['data']
                if node_instance:
                    node_instance.execute_command(cmd)
                    
    except WebSocketDisconnect:
        active_websockets.remove(websocket)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
