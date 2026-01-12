"""
Market Maker with Web Dashboard Integration

Example of running market maker with web dashboard monitoring.
"""

import os
import sys
import asyncio
import threading
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import uvicorn
from src.web import create_app
from src.web.api import update_global_metrics
from src.monitor import MetricsTracker


def start_web_dashboard(port=8000):
    """
    Start web dashboard in a separate thread.
    
    Args:
        port: Port to run dashboard on
    """
    app = create_app()
    
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )
    server = uvicorn.Server(config)
    
    print(f"\n🌐 Web Dashboard: http://localhost:{port}")
    print("="*60)
    
    # Run in event loop
    asyncio.run(server.serve())


def simulate_market_maker_with_dashboard(duration=300):
    """
    Simulate market maker with web dashboard.
    
    Args:
        duration: Simulation duration in seconds
    """
    import time
    import random
    from decimal import Decimal
    
    # Start dashboard in background thread
    dashboard_thread = threading.Thread(
        target=start_web_dashboard,
        args=(8000,),
        daemon=True
    )
    dashboard_thread.start()
    
    # Give dashboard time to start
    time.sleep(2)
    
    # Initialize metrics
    metrics = MetricsTracker()
    
    print("\n🚀 Starting Market Maker Simulation")
    print(f"⏱️  Duration: {duration} seconds")
    print("="*60)
    
    start_time = time.time()
    iteration = 0
    
    try:
        while time.time() - start_time < duration:
            iteration += 1
            
            # Simulate trading activity
            if random.random() > 0.3:
                side = 'buy' if random.random() > 0.5 else 'sell'
                price = Decimal(str(random.uniform(94000, 96000)))
                size = Decimal('2.0')
                pnl = Decimal(str(random.uniform(-5, 10)))
                spread = Decimal(str(random.uniform(5, 10)))
                
                metrics.update_trade(side, price, size, pnl, spread)
                metrics.record_order(filled=True)
                
                # Update position
                pos_change = size if side == 'buy' else -size
                new_pos = metrics.current_position + pos_change
                metrics.update_position(new_pos)
            
            # Simulate order placement
            if random.random() > 0.5:
                metrics.record_order()
            
            # Update unrealized PnL
            unrealized = Decimal(str(random.uniform(-20, 30)))
            metrics.update_unrealized_pnl(unrealized)
            
            # Record uptime check (75% qualified)
            if iteration % 3 == 0:
                qualified = random.random() > 0.25
                metrics.record_uptime_check(qualified)
            
            # Update dashboard
            metrics_dict = metrics.get_summary()
            update_global_metrics(metrics_dict)
            
            # Console output
            if iteration % 10 == 0:
                print(f"[{time.strftime('%H:%M:%S')}] "
                      f"Iteration {iteration} | "
                      f"PnL: ${metrics.total_pnl:+,.2f} | "
                      f"Position: {float(metrics.current_position):+.4f} BTC | "
                      f"Uptime: {metrics.uptime_percentage:.1f}%")
            
            time.sleep(2)
    
    except KeyboardInterrupt:
        print("\n\n⚠️  Simulation stopped by user")
    
    print("\n" + "="*60)
    print("✅ Simulation Complete")
    print("="*60)
    
    # Keep dashboard running
    print("\n💡 Dashboard is still running. Press Ctrl+C to exit.")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Market Maker with Web Dashboard')
    parser.add_argument('--duration', type=int, default=300,
                      help='Simulation duration in seconds (default: 300)')
    parser.add_argument('--port', type=int, default=8000,
                      help='Dashboard port (default: 8000)')
    
    args = parser.parse_args()
    
    print("="*60)
    print("📊 Market Maker + Web Dashboard")
    print("="*60)
    
    simulate_market_maker_with_dashboard(duration=args.duration)
