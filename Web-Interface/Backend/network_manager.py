from typing import Dict, List, Optional
import time
import json
import asyncio

class NetworkManager:
    """
    Manages the global state of the network for visualization.
    Receives reports from nodes and aggregates them.
    """
    def __init__(self):
        # Nodes state: { node_id: { last_seen, routing_table, neighbors, logs } }
        self.nodes: Dict[str, dict] = {}
        self.lock = asyncio.Lock()
        
        # Command Queue: { node_id: [cmd1, cmd2] }
        self.pending_commands: Dict[str, List[str]] = {}

    async def update_node(self, node_id: str, data: dict):
        async with self.lock:
            self.nodes[node_id] = {
                "last_seen": time.time(),
                "routing_table": data.get("routing_table", {}),
                "neighbors": data.get("neighbors", []),
                "ip": data.get("ip", ""), # Virtual IP/ID
                "details": data
            }
            # Initialize command queue if needed
            if node_id not in self.pending_commands:
                self.pending_commands[node_id] = []

    async def get_commands(self, node_id: str) -> List[str]:
        async with self.lock:
            cmds = self.pending_commands.get(node_id, [])
            self.pending_commands[node_id] = []
            return cmds

    async def queue_command(self, node_id: str, command: str):
        async with self.lock:
            if node_id == "BROADCAST":
                for nid in self.nodes:
                    self.pending_commands.setdefault(nid, []).append(command)
            else:
                self.pending_commands.setdefault(node_id, []).append(command)

    async def get_topology(self):
        """
        Constructs a graph format suitable for frontend (e.g., react-force-graph).
        nodes: [{id, idx, val, ...}]
        links: [{source, target, label...}]
        """
        async with self.lock:
            graph_nodes = []
            graph_links = []
            
            # Filter out stale nodes (e.g., > 10 seconds silent) ? 
            # For now, keep them but mark inactive?
            current_time = time.time()
            
            known_ids = set(self.nodes.keys())
            
            for nid, info in self.nodes.items():
                is_active = (current_time - info["last_seen"]) < 5.0
                graph_nodes.append({
                    "id": nid,
                    "name": nid,
                    "val": 10 if is_active else 5,
                    "color": "#4CAF50" if is_active else "#9E9E9E",
                })
                
                neighbors = info.get("neighbors", [])
                for neighbor_id in neighbors:
                    # Check if neighbor is unknown, if so, add a ghost node
                    if neighbor_id not in known_ids and neighbor_id != 'LOCAL':
                        known_ids.add(neighbor_id)
                        graph_nodes.append({
                            "id": neighbor_id,
                            "name": f"{neighbor_id} (?)",
                            "val": 5,
                            "color": "#FFC107" # Yellow for unknown/offline
                        })

                    # Add link
                    if neighbor_id != 'LOCAL':
                        graph_links.append({
                            "source": nid,
                            "target": neighbor_id,
                            "color": "#FFF"
                        })

            return {
                "nodes": graph_nodes,
                "links": graph_links
            }

    async def get_node_details(self, node_id: str):
        async with self.lock:
            return self.nodes.get(node_id, {})

# Global instance
manager = NetworkManager()
