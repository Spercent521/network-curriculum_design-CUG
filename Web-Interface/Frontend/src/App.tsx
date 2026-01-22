import React, { useEffect, useState, useRef, useCallback } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { Terminal } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import 'xterm/css/xterm.css';

// Graph Interfaces
interface GraphData {
  nodes: { id: string, name: string, val: number, color?: string }[];
  links: { source: string, target: string, color?: string }[];
}

function App() {
  // --- Layout State ---
  const [terminalHeight, setTerminalHeight] = useState(300); // Initial height in px
  const [graphDimensions, setGraphDimensions] = useState({ width: window.innerWidth, height: window.innerHeight - 300 });
  
  // --- Data State ---
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], links: [] });
  
  // --- Refs ---
  const ws = useRef<WebSocket | null>(null);
  const termRef = useRef<HTMLDivElement | null>(null);
  const xtermRef = useRef<Terminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const isResizing = useRef(false);

  // --- WebSocket Setup ---
  useEffect(() => {
    // Dynamic WebSocket URL
    // Automatically determines protocol (ws/wss) and host (matches the page's host:port)
    // This allows the app to work on any port (8000, 10000, etc.) or domain.
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    
    // For development (Vite default port 5173), we check URL param ?port=XXXX or default to localhost:8000
    // For production (served by python), window.location.host is correct (e.g. localhost:10000)
    let host = window.location.host;
    if (window.location.port === '5173') {
        const params = new URLSearchParams(window.location.search);
        const devPort = params.get('port') || '8000';
        // Fix: Use the current page's hostname (IP) instead of forcing localhost
        // This ensures that when accessing via http://192.168.x.x:5173, we connect to ws://192.168.x.x:8000
        host = `${window.location.hostname}:${devPort}`;
    }
    
    ws.current = new WebSocket(`${protocol}//${host}/ws`);
    
    ws.current.onopen = () => {
      xtermRef.current?.writeln("\x1b[1;32m[System] Connected to Network Backend.\x1b[0m");
    };

    ws.current.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === 'log') {
        const text = msg.data.replace(/\n/g, '\r\n');
        xtermRef.current?.write(text);
      } else if (msg.type === 'topo') {
        updateGraph(msg.data);
      }
    };

    ws.current.onclose = () => {
      xtermRef.current?.writeln("\r\n\x1b[1;31m[System] Disconnected from Backend.\x1b[0m");
    }

    return () => {
      ws.current?.close();
    };
  }, []);

  // --- Terminal Setup ---
  useEffect(() => {
    if (!termRef.current) return;

    // Dispose old if exists (strict mode double mount)
    if (xtermRef.current) {
        // xtermRef.current.dispose();
        // fitAddonRef.current = null;
        // reuse checks?
        return;
    }

    const term = new Terminal({
      cursorBlink: true,
      fontFamily: '"Cascadia Code", "JetBrains Mono", Consolas, "Courier New", monospace',
      fontSize: 14,
      lineHeight: 1.2,
      letterSpacing: 0,
      theme: {
        background: '#0d1117',
        foreground: '#c9d1d9',
        cursor: '#58a6ff',
        selectionBackground: 'rgba(88, 166, 255, 0.3)',
        black: '#0d1117',
        red: '#ff7b72',
        green: '#3fb950',
        yellow: '#d29922',
        blue: '#58a6ff',
        magenta: '#bc8cff',
        cyan: '#39c5cf',
        white: '#b1bac4',
        brightBlack: '#484f58',
        brightRed: '#ffa198',
        brightGreen: '#56d364',
        brightYellow: '#e3b341',
        brightBlue: '#79c0ff',
        brightMagenta: '#d2a8ff',
        brightCyan: '#56d4dd',
        brightWhite: '#f0f6fc'
      }
    });
    
    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    
    // Add inner padding via CSS wrapper instead of term option? 
    // Actually xterm doesn't have easy padding. We rely on container.
    term.open(termRef.current);
    try {
        fitAddon.fit();
    } catch(e) {}
    
    xtermRef.current = term;
    fitAddonRef.current = fitAddon;

    term.onData(data => {
      if (ws.current && ws.current.readyState === WebSocket.OPEN) {
        ws.current.send(JSON.stringify({ type: 'command', data: data }));
      }
    });

    const resizeObserver = new ResizeObserver(() => {
        try { fitAddon.fit(); } catch(e) {}
    });
    
    if (termRef.current) {
        resizeObserver.observe(termRef.current);
    }

    // Initial branding
    term.writeln("\x1b[1;36m=== Network Experiment Console ===\x1b[0m");
    term.writeln("Connecting...");

    return () => {
      // Cleanup handled by react strict mode caveat often overrides this
      // term.dispose();
      // resizeObserver.disconnect();
    };
  }, []);

  // --- Graph Update Logic ---
  const updateGraph = (topo: any) => {
    // Backend sends pre-calculated nodes/links
    // { nodes: [...], links: [...] }
    if (topo && Array.isArray(topo.nodes) && Array.isArray(topo.links)) {
        // Defensive: Filter links that point to non-existent nodes to prevent crashes
        const validNodeIds = new Set(topo.nodes.map((n:any) => n.id));
        
        const safeLinks = topo.links.filter((l: any) => 
            validNodeIds.has(l.source) && validNodeIds.has(l.target)
        );

        // React-Force-Graph expects mutable objects but we receive new immutable JSON every time.
        // We pass it directly.
        setGraphData({
            nodes: topo.nodes,
            links: safeLinks
        });
    } else {
        console.warn("Received invalid topo data:", topo);
    }
  };

  // --- Resizing Logic ---
  const startResizing = useCallback((mouseDownEvent: React.MouseEvent) => {
    isResizing.current = true;
    document.body.style.cursor = 'row-resize';
    document.body.style.userSelect = 'none';
  }, []);

  const stopResizing = useCallback(() => {
    isResizing.current = false;
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  }, []);

  const resize = useCallback((mouseMoveEvent: MouseEvent) => {
    if (isResizing.current) {
      const newHeight = window.innerHeight - mouseMoveEvent.clientY;
      if (newHeight > 50 && newHeight < window.innerHeight - 50) {
        setTerminalHeight(newHeight);
      }
    }
  }, []);

  useEffect(() => {
    window.addEventListener("mousemove", resize);
    window.addEventListener("mouseup", stopResizing);
    
    return () => {
      window.removeEventListener("mousemove", resize);
      window.removeEventListener("mouseup", stopResizing);
    };
  }, [resize, stopResizing]);

  // Adjust graph on layout change
  useEffect(() => {
      setGraphDimensions({
          width: window.innerWidth,
          height: window.innerHeight - terminalHeight
      });
      // Also fit terminal
      if(fitAddonRef.current) {
          try { fitAddonRef.current.fit(); } catch(e) {}
      }
  }, [terminalHeight]); // Also trigger on window resize via another effect if needed, but react-force-graph usually handles window resize if passed dim?
  
  useEffect(() => {
     const handleResize = () => {
        setGraphDimensions({
            width: window.innerWidth,
            height: window.innerHeight - terminalHeight
        });
        if(fitAddonRef.current) try { fitAddonRef.current.fit(); } catch(e) {}
     };
     window.addEventListener('resize', handleResize);
     return () => window.removeEventListener('resize', handleResize);
  }, [terminalHeight]);


  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', overflow: 'hidden', background: '#0d1117', color: '#fff' }}>
      
      {/* Top: Graph Visualization */}
      <div style={{ height: graphDimensions.height, overflow: 'hidden', position: 'relative' }}>
        <div style={{ position: 'absolute', top: 10, left: 10, zIndex: 10, background: 'rgba(0,0,0,0.5)', padding: '5px 10px', borderRadius: 4, fontFamily: 'Segoe UI' }}>
            <span style={{color: '#4ade80'}}>●</span> Graph Visualization
        </div>
        <ForceGraph2D
          width={graphDimensions.width}
          height={graphDimensions.height}
          graphData={graphData}
          // nodeLabel="name" // Disabled in favor of canvas object
          nodeColor={node => (node as any).color || '#60a5fa'}
          nodeRelSize={6}
          linkColor={() => '#30363d'}
          backgroundColor="#0d1117"
          nodeCanvasObject={(node: any, ctx, globalScale) => {
            const label = node.name || node.id;
            const fontSize = 12/globalScale;
            ctx.font = `${fontSize}px Sans-Serif`;
            const textWidth = ctx.measureText(label).width;
            const bckgDimensions = [textWidth, fontSize].map(n => n + fontSize * 0.2); 

            // Draw Dot
            ctx.beginPath();
            ctx.arc(node.x, node.y, 5, 0, 2 * Math.PI, false);
            ctx.fillStyle = node.color || '#60a5fa';
            ctx.fill();

            // Draw Text Background
            ctx.fillStyle = 'rgba(0, 0, 0, 0.8)';
            ctx.fillRect(node.x - bckgDimensions[0] / 2, node.y - bckgDimensions[1] / 2 - 10, bckgDimensions[0], bckgDimensions[1]);

            // Draw Text
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillStyle = '#fff';
            ctx.fillText(label, node.x, node.y - 10);
            
            // Interaction area
            node.__bckgDimensions = bckgDimensions; 
          }}
          nodePointerAreaPaint={(node: any, color, ctx) => {
             ctx.fillStyle = color;
             const bckgDimensions = node.__bckgDimensions;
             bckgDimensions && ctx.fillRect(node.x - bckgDimensions[0] / 2, node.y - bckgDimensions[1] / 2 - 10, bckgDimensions[0], bckgDimensions[1]);
          }}
        />
      </div>

      {/* Resizer Handle */}
      <div
        onMouseDown={startResizing}
        style={{
          height: '6px',
          cursor: 'row-resize',
          background: '#010409',
          borderTop: '1px solid #30363d',
          borderBottom: '1px solid #30363d',
          zIndex: 20,
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center'
        }}
      >
        <div style={{width: 30, height: 2, background: '#30363d', borderRadius: 1}}></div>
      </div>

      {/* Bottom: Terminal */}
      <div style={{ height: terminalHeight, background: '#0d1117', padding: '0 0px', position: 'relative', display: 'flex', flexDirection: 'column' }}>
         <div style={{
            padding: '4px 10px',
            background: '#161b22',
            borderBottom: '1px solid #30363d',
            fontSize: '11px',
            color: '#8b949e',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            height: '24px',
            flexShrink: 0
         }}>
             <span>TERMINAL</span>
             <span>bash</span>
         </div>
         <div style={{ flex: 1, padding: '10px', minHeight: 0 }}>
             <div ref={termRef} style={{ width: '100%', height: '100%' }} />
         </div>
      </div>
    </div>
  );
}

export default App;
