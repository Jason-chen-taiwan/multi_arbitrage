"""
FastAPI Web Dashboard Server

Provides REST API and WebSocket endpoints for real-time monitoring.
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Dict, List
import json
import asyncio
from datetime import datetime
from pathlib import Path
import threading
from queue import Queue


class ConnectionManager:
    """Manage WebSocket connections for real-time updates."""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
    
    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients."""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                disconnected.append(connection)
        
        # Remove disconnected clients
        for conn in disconnected:
            self.active_connections.remove(conn)


# Global state (will be updated by the market maker)
_global_metrics: Optional[Dict] = None
_connection_manager = ConnectionManager()
_metrics_queue: Queue = Queue()
_metrics_lock = threading.Lock()


def create_app(metrics_tracker=None):
    """
    Create FastAPI application.
    
    Args:
        metrics_tracker: MetricsTracker instance (optional)
    """
    app = FastAPI(
        title="StandX Market Maker Dashboard",
        description="Real-time monitoring dashboard for market maker bot",
        version="1.0.0"
    )
    
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Get static files directory
    static_dir = Path(__file__).parent / "static"
    
    # Mount static files
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    
    @app.get("/", response_class=HTMLResponse)
    async def root():
        """Serve the main dashboard page."""
        html_file = static_dir / "index.html"
        if html_file.exists():
            return FileResponse(html_file)
        return HTMLResponse(content="<h1>Dashboard HTML not found</h1>", status_code=404)
    
    @app.get("/api/health")
    async def health():
        """Health check endpoint."""
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "connections": len(_connection_manager.active_connections)
        }
    
    @app.get("/api/metrics")
    async def get_metrics():
        """Get current metrics snapshot."""
        if _global_metrics is None:
            return {
                "error": "No metrics available",
                "timestamp": datetime.now().isoformat()
            }
        
        return {
            **_global_metrics,
            "timestamp": datetime.now().isoformat()
        }
    
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for real-time updates."""
        await _connection_manager.connect(websocket)
        
        try:
            # Send initial data
            with _metrics_lock:
                if _global_metrics:
                    await websocket.send_json({
                        "type": "init",
                        "data": _global_metrics
                    })
            
            # Keep connection alive and broadcast updates
            while True:
                try:
                    # Check for new metrics updates (non-blocking)
                    if not _metrics_queue.empty():
                        metrics_update = _metrics_queue.get_nowait()
                        await _connection_manager.broadcast(metrics_update)
                    
                    # Wait for client message or timeout
                    await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                except asyncio.TimeoutError:
                    # Normal timeout, continue loop
                    pass
                except:
                    break
                    
        except WebSocketDisconnect:
            _connection_manager.disconnect(websocket)
    
    return app


def update_global_metrics(metrics_dict: Dict):
    """
    Update global metrics (called by market maker from any thread).
    Thread-safe function that can be called from synchronous code.
    
    Args:
        metrics_dict: Dictionary of metrics to update
    """
    global _global_metrics
    
    # Thread-safe update of global metrics
    with _metrics_lock:
        _global_metrics = metrics_dict
    
    # Put update in queue for WebSocket broadcast (thread-safe)
    try:
        _metrics_queue.put_nowait({
            "type": "update",
            "data": metrics_dict,
            "timestamp": datetime.now().isoformat()
        })
    except:
        pass  # Queue full, skip this update


def get_connection_manager() -> ConnectionManager:
    """Get the global connection manager."""
    return _connection_manager
