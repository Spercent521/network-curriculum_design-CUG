
import sys
import os
import json
import asyncio
from typing import Callable

# Add the Code directory to sys.path to import Experiment6
# Assuming this file is in Web-Interface/Backend/
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
sys.path.append(os.path.join(PROJECT_ROOT, 'Code', 'Experiment6'))

from network_app import NetworkNode

class WebNetworkNode(NetworkNode):
    def __init__(self, log_callback: Callable[[str], None], topo_callback: Callable[[dict], None]):
        # We don't call super().__init__() immediately because it might start the input loop blocking everything
        # Actually NetworkNode.__init__ just inits vars. The blocking part is start() -> _input_loop
        super().__init__()
        self.log_callback = log_callback
        self.topo_callback = topo_callback
        # We need a way to run the network loop without blocking the API
        # NetworkNode.start() calls _input_loop() which is blocking.
        # We need to override start() or _input_loop().

    def log(self, *args, **kwargs):
        """Redirects print output to WebSocket"""
        sep = kwargs.get('sep', ' ')
        # end = kwargs.get('end', '\n') # We typically send line by line, so we might ignore end or append it.
        full_msg = sep.join(map(str, args))
        # print("DEBUG LOG:", full_msg) # Debugging
        if self.log_callback:
            self.log_callback(full_msg)

    def start(self):
        """Non-blocking start method for Web Interface"""
        self.my_id = "WEB_ADMIN" 
        self.log(f"Starting Node with ID: {self.my_id}")
        
        # Auto-detect ports
        import serial.tools.list_ports
        available = [p.device for p in serial.tools.list_ports.comports()]
        ports = available # Default to 'all'
        
        self.routing_table[self.my_id] = {'cost': 0, 'next_hop_port': 'LOCAL', 'next_hop_id': self.my_id}
        self.running = True

        for p in ports:
            try:
                ser = serial.Serial(p, 9600, timeout=0.1) # Hardcoded baudrate from network_app
                self.active_ports[p] = ser
                self.port_locks[p] = threading.Lock()
                threading.Thread(target=self._listen_port, args=(p,), daemon=True).start()
                self.log(f"[{p}] Listening...")
            except Exception as e:
                self.log(f"[{p}] Failed: {e}")

        # Start background tasks
        threading.Thread(target=self._task_hello, daemon=True).start()
        threading.Thread(target=self._task_broadcast_dv, daemon=True).start()
        threading.Thread(target=self._task_check_timeout, daemon=True).start()

        self.log("\nNode System Ready. Waiting for Web Commands...")
        # self._input_loop() # Disable the blocking input loop

    def broadcast_topology(self):
        if self.topo_callback:
            # Convert routing table to a graph format
            # Nodes: Me + everyone in routing table
            # Links: Me -> neighbor, etc. 
            # This is a simplified view based on routing table
            topo = {
                "id": self.my_id,
                "table": self.routing_table,
                "neighbors": self.neighbors
            }
            self.topo_callback(topo)

    def execute_command(self, cmd_str):
        """Programmatic access to CLI commands"""
        import time
        cmd = cmd_str.strip().split()
        if not cmd: return
        op = cmd[0].lower()
        
        self.log(f"> {cmd_str}")
        
        if op == 'ping':
            if len(cmd)<2: self.log("Usage: ping <ID>")
            else: 
                # Run in a thread to avoid blocking
                threading.Thread(target=self.do_ping, args=(cmd[1],)).start()
        elif op == 'tracert':
            if len(cmd)<2: self.log("Usage: tracert <ID>")
            else: 
                threading.Thread(target=self.do_traceroute, args=(cmd[1],)).start()
        elif op == 'table':
            self.log(json.dumps(self.routing_table, indent=2))
        elif op == 'send': 
            if len(cmd)<3: self.log("Usage: send <ID> <Msg>")
            else:
                payload = f"TRA|{' '.join(cmd[2:])}" # Hardcoded constant from network_app
                self._network_send(cmd[1], payload, 64) 
        else:
            self.log(f"Unknown command: {op}")

import threading
import time
