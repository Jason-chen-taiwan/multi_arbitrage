"""
Web Dashboard Server Launcher

Start the web dashboard server for real-time monitoring.
"""

import sys
import argparse
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import uvicorn
from src.web import create_app


def main():
    """Start the web dashboard server."""
    parser = argparse.ArgumentParser(description='StandX Market Maker Web Dashboard')
    parser.add_argument('--host', type=str, default='0.0.0.0',
                      help='Host to bind (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=8000,
                      help='Port to bind (default: 8000)')
    parser.add_argument('--reload', action='store_true',
                      help='Enable auto-reload (development mode)')
    
    args = parser.parse_args()
    
    print("="*60)
    print("🌐 StandX Market Maker Web Dashboard")
    print("="*60)
    print(f"📡 Starting server on http://{args.host}:{args.port}")
    print(f"🔗 Open in browser: http://localhost:{args.port}")
    print("="*60)
    
    # Create app
    app = create_app()
    
    # Run server
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info"
    )


if __name__ == "__main__":
    main()
