"""
FastAPI Web Dashboard Server

Provides REST API and WebSocket endpoints for real-time monitoring.
Includes OpenAPI documentation at /docs and /openapi.json.
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
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
    Create FastAPI application with OpenAPI documentation.

    Args:
        metrics_tracker: MetricsTracker instance (optional)

    OpenAPI docs available at:
        - /docs - Swagger UI
        - /redoc - ReDoc UI
        - /openapi.json - OpenAPI schema
    """
    app = FastAPI(
        title="StandX Market Maker Dashboard API",
        description="""
## Overview

Real-time monitoring and control API for the StandX Market Maker bot.

## Features

- **Market Maker Control**: Start, stop, and configure the market maker
- **Position Monitoring**: Real-time position tracking across exchanges
- **Simulation**: Run parameter comparisons with multiple configurations
- **Configuration**: Manage exchange credentials and settings
- **WebSocket**: Real-time data streaming at `/ws`

## Authentication

Currently, no authentication is required. The API is designed for local use.

## WebSocket

Connect to `/ws` for real-time updates. Messages are broadcast every 1 second
with market data, positions, and execution statistics.
        """,
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        openapi_tags=[
            {"name": "config", "description": "Exchange configuration and health checks"},
            {"name": "control", "description": "System control and trading mode"},
            {"name": "market_maker", "description": "Market maker operations"},
            {"name": "simulation", "description": "Parameter comparison simulations"},
            {"name": "referral", "description": "Referral program management"},
        ]
    )
    
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Get static files directories
    static_dir = Path(__file__).parent / "static"
    frontend_dist = Path(__file__).parent / "frontend_dist"

    # Mount static files (legacy)
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Mount React frontend build assets
    if frontend_dist.exists() and (frontend_dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")

    @app.get("/", response_class=HTMLResponse)
    async def root():
        """Serve the main dashboard page (React frontend)."""
        # Prefer React frontend if available
        react_html = frontend_dist / "index.html"
        if react_html.exists():
            return FileResponse(react_html)
        # Fallback to legacy static HTML
        html_file = static_dir / "index.html"
        if html_file.exists():
            return FileResponse(html_file)
        return HTMLResponse(content="<h1>Dashboard HTML not found</h1>", status_code=404)

    # SPA fallback routes - serve index.html for client-side routing
    @app.get("/mm", response_class=HTMLResponse)
    @app.get("/arbitrage", response_class=HTMLResponse)
    @app.get("/settings", response_class=HTMLResponse)
    @app.get("/comparison", response_class=HTMLResponse)
    async def spa_routes():
        """Serve React SPA for client-side routes."""
        react_html = frontend_dist / "index.html"
        if react_html.exists():
            return FileResponse(react_html)
        return HTMLResponse(content="<h1>Frontend not built</h1>", status_code=404)
    
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
