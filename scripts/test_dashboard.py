"""
Dashboard Test Script

Test the monitoring dashboard with simulated data.
"""

import sys
import time
import random
from pathlib import Path
from decimal import Decimal

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.monitor import MetricsTracker, Dashboard


def simulate_market_making(duration_seconds: int = 60):
    """
    Simulate market making activity with dashboard display.
    
    Args:
        duration_seconds: How long to run the simulation
    """
    # Initialize metrics and dashboard
    metrics = MetricsTracker()
    dashboard = Dashboard(metrics)
    
    # Configuration
    mark_price = Decimal('95000.00')
    base_spread = Decimal('0.0008')  # 8 bps
    order_size = Decimal('2.0')
    
    print("🚀 Starting Market Maker Dashboard Simulation")
    print(f"⏱️  Will run for {duration_seconds} seconds")
    print("="*80)
    time.sleep(2)
    
    start_time = time.time()
    iteration = 0
    
    while time.time() - start_time < duration_seconds:
        iteration += 1
        
        # Simulate market movements
        price_change = Decimal(str(random.uniform(-100, 100)))
        mark_price += price_change
        
        # Simulate orders
        if random.random() > 0.3:  # 70% chance to place orders
            metrics.record_order()
            
            # 50% chance order gets filled
            if random.random() > 0.5:
                side = 'buy' if random.random() > 0.5 else 'sell'
                trade_price = mark_price * (Decimal('1') + Decimal(str(random.uniform(-0.0001, 0.0001))))
                spread_bps = abs((trade_price - mark_price) / mark_price) * Decimal('10000')
                pnl = Decimal(str(random.uniform(-5, 10)))  # Slightly profitable on average
                
                metrics.update_trade(
                    side=side,
                    price=trade_price,
                    size=order_size,
                    pnl=pnl,
                    spread_bps=spread_bps
                )
                
                # Update position
                position_change = order_size if side == 'buy' else -order_size
                new_position = metrics.current_position + position_change
                metrics.update_position(new_position)
        
        # Simulate order cancellations
        if random.random() > 0.9:  # 10% chance
            metrics.record_order(cancelled=True)
        
        # Update unrealized PnL
        unrealized = Decimal(str(random.uniform(-20, 25)))
        metrics.update_unrealized_pnl(unrealized)
        
        # Record uptime checks (simulate 75% uptime)
        if iteration % 2 == 0:  # Check every 2 iterations
            qualified = random.random() > 0.25  # 75% qualified
            metrics.record_uptime_check(qualified)
        
        # Display dashboard
        if iteration == 1:
            # First iteration - show full dashboard
            dashboard.display_full_dashboard(
                strategy_name="Uptime Market Maker (Test Mode)",
                mark_price=mark_price,
                clear=True
            )
        elif dashboard.should_display():
            # Periodic full dashboard
            dashboard.display_full_dashboard(
                strategy_name="Uptime Market Maker (Test Mode)",
                mark_price=mark_price,
                clear=True
            )
        else:
            # Compact display
            dashboard.display_compact(
                strategy_name="Test MM",
                mark_price=mark_price
            )
        
        # Sleep to simulate real trading interval
        time.sleep(2)
    
    # Final summary
    print("\n" + "="*80)
    print("📊 Simulation Complete - Final Summary")
    print("="*80)
    
    dashboard.display_full_dashboard(
        strategy_name="Uptime Market Maker (Test Mode) - FINAL",
        mark_price=mark_price,
        clear=False
    )
    
    # Print detailed summary
    summary = metrics.get_summary()
    print(f"\n📈 Detailed Metrics:")
    for key, value in summary.items():
        print(f"   {key}: {value}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Test Market Maker Dashboard')
    parser.add_argument('--duration', type=int, default=60,
                      help='Simulation duration in seconds (default: 60)')
    
    args = parser.parse_args()
    
    try:
        simulate_market_making(duration_seconds=args.duration)
    except KeyboardInterrupt:
        print("\n\n⚠️  Simulation stopped by user")
