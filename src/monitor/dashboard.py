"""
Real-time dashboard for market maker monitoring.
"""

import os
from decimal import Decimal
from datetime import datetime
from typing import Optional, Dict
from .metrics import MetricsTracker


class Dashboard:
    """
    Real-time monitoring dashboard for market maker.
    """
    
    def __init__(self, metrics: MetricsTracker):
        """
        Initialize dashboard.
        
        Args:
            metrics: MetricsTracker instance
        """
        self.metrics = metrics
        self.last_display_time = 0
        self.display_interval = 30  # seconds
    
    def clear_screen(self):
        """Clear terminal screen."""
        os.system('clear' if os.name == 'posix' else 'cls')
    
    def format_number(self, value: float, decimals: int = 2, prefix: str = '', suffix: str = '') -> str:
        """Format number with prefix/suffix."""
        return f"{prefix}{value:,.{decimals}f}{suffix}"
    
    def format_percentage(self, value: float, decimals: int = 1) -> str:
        """Format percentage."""
        return f"{value:.{decimals}f}%"
    
    def format_pnl(self, value: Decimal) -> str:
        """Format PnL with color indicator."""
        val = float(value)
        if val > 0:
            return f"🟢 ${val:+,.2f}"
        elif val < 0:
            return f"🔴 ${val:+,.2f}"
        else:
            return f"⚪ ${val:+,.2f}"
    
    def display_header(self, strategy_name: str = "Market Maker"):
        """Display dashboard header."""
        print("╔" + "═" * 78 + "╗")
        print(f"║ 📊 {strategy_name:^74} ║")
        print(f"║ {datetime.now().strftime('%Y-%m-%d %H:%M:%S'):^76} ║")
        print("╠" + "═" * 78 + "╣")
    
    def display_performance_metrics(self):
        """Display performance metrics section."""
        print("║ 💰 Performance Metrics" + " " * 54 + "║")
        print("╠" + "─" * 78 + "╣")
        
        # Runtime
        runtime = self.metrics.runtime_hours
        print(f"║   運行時間: {runtime:,.2f} 小時" + " " * (66 - len(f"{runtime:,.2f}")) + "║")
        
        # PnL
        realized = float(self.metrics.realized_pnl)
        unrealized = float(self.metrics.unrealized_pnl)
        total = float(self.metrics.total_pnl)
        
        print(f"║   已實現 PnL: {self.format_pnl(self.metrics.realized_pnl)}" + 
              " " * (63 - len(self.format_pnl(self.metrics.realized_pnl))) + "║")
        print(f"║   未實現 PnL: {self.format_pnl(self.metrics.unrealized_pnl)}" + 
              " " * (63 - len(self.format_pnl(self.metrics.unrealized_pnl))) + "║")
        print(f"║   總 PnL:     {self.format_pnl(self.metrics.total_pnl)}" + 
              " " * (63 - len(self.format_pnl(self.metrics.total_pnl))) + "║")
        
        # Return on runtime
        if runtime > 0:
            hourly_pnl = total / runtime
            print(f"║   時均 PnL: ${hourly_pnl:+,.2f}/hr" + 
                  " " * (59 - len(f"{hourly_pnl:+,.2f}")) + "║")
        
        print("╠" + "─" * 78 + "╣")
    
    def display_position_metrics(self, mark_price: Optional[Decimal] = None):
        """Display position metrics section."""
        print("║ 📍 Position & Volume" + " " * 57 + "║")
        print("╠" + "─" * 78 + "╣")
        
        # Position
        position = float(self.metrics.current_position)
        position_str = f"{position:+,.4f} BTC"
        print(f"║   當前倉位: {position_str}" + " " * (64 - len(position_str)) + "║")
        
        # Position value
        if mark_price:
            position_value = abs(position) * float(mark_price)
            print(f"║   倉位價值: ${position_value:,.2f}" + 
                  " " * (61 - len(f"{position_value:,.2f}")) + "║")
        
        # Volume
        volume = float(self.metrics.total_volume)
        print(f"║   累計成交量: {volume:,.4f} BTC" + 
              " " * (60 - len(f"{volume:,.4f}")) + "║")
        
        # Inventory turnover
        turnover = self.metrics.inventory_turnover
        print(f"║   庫存周轉率: {turnover:.2f} 次/小時" + 
              " " * (57 - len(f"{turnover:.2f}")) + "║")
        
        print("╠" + "─" * 78 + "╣")
    
    def display_order_metrics(self):
        """Display order metrics section."""
        print("║ 📋 Order Statistics" + " " * 58 + "║")
        print("╠" + "─" * 78 + "╣")
        
        # Order counts
        total = self.metrics.total_orders
        filled = self.metrics.filled_orders
        cancelled = self.metrics.cancelled_orders
        
        print(f"║   總訂單數: {total:,}" + " " * (64 - len(f"{total:,}")) + "║")
        print(f"║   成交訂單: {filled:,}" + " " * (64 - len(f"{filled:,}")) + "║")
        print(f"║   取消訂單: {cancelled:,}" + " " * (64 - len(f"{cancelled:,}")) + "║")
        
        # Fill rate
        fill_rate = self.metrics.fill_rate * 100
        fill_indicator = "🟢" if fill_rate > 70 else "🟡" if fill_rate > 40 else "🔴"
        print(f"║   成交率: {fill_indicator} {fill_rate:.1f}%" + 
              " " * (62 - len(f"{fill_rate:.1f}")) + "║")
        
        # Average spread
        avg_spread = float(self.metrics.average_spread_bps)
        if avg_spread > 0:
            print(f"║   平均價差: {avg_spread:.2f} bps" + 
                  " " * (59 - len(f"{avg_spread:.2f}")) + "║")
        
        print("╠" + "─" * 78 + "╣")
    
    def display_uptime_metrics(self):
        """Display uptime metrics section (for Uptime Program)."""
        if self.metrics.total_checks == 0:
            return
        
        print("║ ⏱️  Uptime Program Status" + " " * 52 + "║")
        print("╠" + "─" * 78 + "╣")
        
        uptime = self.metrics.uptime_percentage
        
        # Determine tier
        if uptime >= 70:
            tier = "🟢 Boosted (1.0x)"
            multiplier = 1.0
        elif uptime >= 50:
            tier = "🟡 Standard (0.5x)"
            multiplier = 0.5
        else:
            tier = "⚪ Inactive (0x)"
            multiplier = 0.0
        
        print(f"║   正常運行時間: {uptime:.1f}%" + 
              " " * (61 - len(f"{uptime:.1f}")) + "║")
        print(f"║   獎勵層級: {tier}" + " " * (60 - len(tier)) + "║")
        
        # Qualified checks
        qualified = self.metrics.qualified_checks
        total = self.metrics.total_checks
        print(f"║   符合資格: {qualified}/{total} 次檢查" + 
              " " * (57 - len(f"{qualified}/{total}")) + "║")
        
        # Estimated Maker Hours (assuming average 2 BTC orders)
        avg_size = 2.0  # BTC
        estimated_hours_per_hour = (avg_size / 2) * multiplier
        monthly_estimate = estimated_hours_per_hour * 24 * 30
        
        print(f"║   預估 Maker Hours: {estimated_hours_per_hour:.2f}/小時 "
              f"({monthly_estimate:.0f}/月)" + 
              " " * (40 - len(f"{estimated_hours_per_hour:.2f}") - len(f"{monthly_estimate:.0f}")) + "║")
        
        # Fee tier progress
        runtime = self.metrics.runtime_hours
        if runtime >= 504:
            fee_tier = "💎 MM2 (2.0 bps taker + 0.5 bps maker)"
        elif runtime >= 360:
            fee_tier = "⭐ MM1 (2.25 bps taker + 0.25 bps maker)"
        else:
            progress_mm1 = (runtime / 360) * 100
            progress_mm2 = (runtime / 504) * 100
            fee_tier = f"⚡ 進度: MM1 {progress_mm1:.1f}% | MM2 {progress_mm2:.1f}%"
        
        print(f"║   費率層級: {fee_tier}" + " " * (62 - len(fee_tier)) + "║")
        
        print("╠" + "─" * 78 + "╣")
    
    def display_footer(self):
        """Display dashboard footer."""
        last_update = datetime.fromtimestamp(self.metrics.last_update)
        update_str = last_update.strftime('%H:%M:%S')
        print(f"║ 最後更新: {update_str}" + " " * (65 - len(update_str)) + "║")
        print("╚" + "═" * 78 + "╝")
    
    def display_full_dashboard(
        self,
        strategy_name: str = "Market Maker",
        mark_price: Optional[Decimal] = None,
        clear: bool = False
    ):
        """
        Display complete dashboard.
        
        Args:
            strategy_name: Name of trading strategy
            mark_price: Current mark price (optional)
            clear: Whether to clear screen before display
        """
        if clear:
            self.clear_screen()
        
        self.display_header(strategy_name)
        self.display_performance_metrics()
        self.display_position_metrics(mark_price)
        self.display_order_metrics()
        self.display_uptime_metrics()
        self.display_footer()
    
    def display_compact(
        self,
        strategy_name: str = "Market Maker",
        mark_price: Optional[Decimal] = None
    ):
        """
        Display compact dashboard (single line summary).
        
        Args:
            strategy_name: Name of trading strategy
            mark_price: Current mark price (optional)
        """
        runtime = self.metrics.runtime_hours
        pnl = float(self.metrics.total_pnl)
        position = float(self.metrics.current_position)
        uptime = self.metrics.uptime_percentage if self.metrics.total_checks > 0 else 0
        
        pnl_indicator = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪"
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] "
              f"{strategy_name} | "
              f"運行: {runtime:.1f}h | "
              f"PnL: {pnl_indicator}${pnl:+,.2f} | "
              f"倉位: {position:+.4f} | "
              f"成交率: {self.metrics.fill_rate*100:.1f}% | "
              f"正常運行: {uptime:.1f}%")
    
    def should_display(self, force: bool = False) -> bool:
        """
        Check if dashboard should be displayed.
        
        Args:
            force: Force display regardless of interval
            
        Returns:
            True if should display
        """
        import time
        current_time = time.time()
        
        if force or (current_time - self.last_display_time >= self.display_interval):
            self.last_display_time = current_time
            return True
        
        return False
    
    def set_display_interval(self, seconds: int):
        """
        Set dashboard display interval.
        
        Args:
            seconds: Interval in seconds
        """
        self.display_interval = max(1, seconds)
