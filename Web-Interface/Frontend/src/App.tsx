
import React, { useEffect, useState, useRef } from 'react';
import ForceGraph2D from 'react-force-graph-2d';

// Simple interface for graph data
interface GraphData {
  nodes: { id: string, name: string, val: number }[];
  links: { source: string, target: string }[];
}

function App() {
  const [logs, setLogs] = useState<string[]>([]);
  const [cmd, setCmd] = useState("");
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], links: [] });
  const ws = useRef<WebSocket | null>(null);

  useEffect(() => {
    // Connect to Backend
    ws.current = new WebSocket("ws://localhost:8000/ws");
    
    ws.current.onopen = () => {
      addLog("System: Connected to Network Node Backend.");
    };

    ws.current.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === 'log') {
        addLog(msg.data);
      } else if (msg.type === 'topo') {
        updateGraph(msg.data);
      }
    };

    return () => {
      ws.current?.close();
    };
  }, []);

  const addLog = (text: string) => {
    setLogs(prev => [...prev.slice(-100), text]); // Keep last 100 lines
  };

  const updateGraph = (topo: any) => {
    // Transform backend topology data to graph format
    // topo.table = { "B": {cost:1, ...}, ... }
    const nodes = [{ id: topo.id, name: topo.id + " (Me)", val: 10 }];
    const links: any[] = [];
    
    // Add neighbors from routing table as nodes and links
    Object.keys(topo.table).forEach(dest => {
       if (dest !== topo.id) {
           nodes.push({ id: dest, name: dest, val: 5 });
           // If direct neighbor (cost 1 or defined in neighbors), add link
           // Simplified visualization
           links.push({ source: topo.id, target: dest });
       }
    });

    setGraphData({ nodes, links });
  };

  const sendCommand = (e: React.FormEvent) => {
    e.preventDefault();
    if (!ws.current || !cmd) return;
    
    ws.current.send(JSON.stringify({ type: 'command', data: cmd }));
    setCmd("");
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', fontFamily: 'monospace' }}>
      <div style={{ padding: '10px', background: '#333', color: '#fff' }}>
        <h2>Network Admin Console (Experiment 6)</h2>
      </div>
      
      <div style={{ flex: 1, display: 'flex' }}>
        {/* Graph Area */}
        <div style={{ flex: 2, borderRight: '1px solid #ccc', position: 'relative' }}>
            <ForceGraph2D
                graphData={graphData}
                nodeLabel="name"
                nodeAutoColorBy="id"
                linkDirectionalArrowLength={3.5}
                linkDirectionalArrowRelPos={1}
            />
        </div>

        {/* Console Area */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: '#1e1e1e', color: '#0f0' }}>
            <div style={{ flex: 1, overflowY: 'auto', padding: '10px' }}>
                {logs.map((L, i) => (
                    <div key={i}>{L}</div>
                ))}
            </div>
            <form onSubmit={sendCommand} style={{ display: 'flex', borderTop: '1px solid #555' }}>
                <span style={{ padding: '10px' }}>&gt;</span>
                <input 
                    value={cmd}
                    onChange={e => setCmd(e.target.value)}
                    style={{ flex: 1, background: 'transparent', border: 'none', color: '#fff', outline: 'none', padding: '10px' }}
                    placeholder="Enter command (e.g., ping B)"
                />
            </form>
        </div>
      </div>
    </div>
  )
}

export default App
