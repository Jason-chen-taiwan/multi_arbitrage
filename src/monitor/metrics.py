"""
Performance metrics tracking system.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Dict
from datetime import datetime
import time


@dataclass
class TradeMetrics:
    """Individual trade metrics."""
    timestamp: datetime
    side: str  # 'buy' or 'sell'
    price: Decimal
    size: Decimal
    pnl: Decimal
    spread_bps: Decimal
    

@dataclass
class MetricsTracker:
    """
    Track and calculate trading performance metrics.
    """
    
    # Core metrics
    total_volume: Decimal = Decimal('0')
    realized_pnl: Decimal = Decimal('0')
    unrealized_pnl: Decimal = Decimal('0')
    current_position: Decimal = Decimal('0')
    
    # Order metrics
    total_orders: int = 0
    filled_orders: int = 0
    cancelled_orders: int = 0
    
    # Spread metrics
    spreads: List[Decimal] = field(default_factory=list)
    
    # Position tracking
    position_changes: int = 0
    last_position: Decimal = Decimal('0')
    
    # Trade history
    trades: List[TradeMetrics] = field(default_factory=list)
    
    # Timing
    start_time: float = field(default_factory=time.time)
    last_update: float = field(default_factory=time.time)
    
    # Uptime metrics (for Uptime Program)
    qualified_checks: int = 0
    total_checks: int = 0
    
    def update_trade(
        self,
        side: str,
        price: Decimal,
        size: Decimal,
        pnl: Decimal = Decimal('0'),
        spread_bps: Decimal = Decimal('0')
    ):
        """Record a trade."""
        trade = TradeMetrics(
            timestamp=datetime.now(),
            side=side,
            price=price,
            size=size,
            pnl=pnl,
            spread_bps=spread_bps
        )
        
        self.trades.append(trade)
        self.total_volume += size
        self.realized_pnl += pnl
        self.filled_orders += 1
        
        if spread_bps > 0:
            self.spreads.append(spread_bps)
        
        self.last_update = time.time()
    
    def update_position(self, new_position: Decimal):
        """Update current position."""
        if new_position != self.current_position:
            if self.last_position != Decimal('0'):
                self.position_changes += 1
            self.last_position = self.current_position
            self.current_position = new_position
    
    def update_unrealized_pnl(self, pnl: Decimal):
        """Update unrealized PnL."""
        self.unrealized_pnl = pnl
        self.last_update = time.time()
    
    def record_order(self, filled: bool = False, cancelled: bool = False):
        """Record order statistics."""
        self.total_orders += 1
        if filled:
            self.filled_orders += 1
        if cancelled:
            self.cancelled_orders += 1
    
    def record_uptime_check(self, qualified: bool):
        """Record uptime qualification check."""
        self.total_checks += 1
        if qualified:
            self.qualified_checks += 1
    
    @property
    def fill_rate(self) -> float:
        """Calculate order fill rate."""
        if self.total_orders == 0:
            return 0.0
        return self.filled_orders / self.total_orders
    
    @property
    def average_spread_bps(self) -> Decimal:
        """Calculate average spread in basis points."""
        if not self.spreads:
            return Decimal('0')
        return sum(self.spreads) / len(self.spreads)
    
    @property
    def inventory_turnover(self) -> float:
        """Calculate inventory turnover rate."""
        runtime_hours = (time.time() - self.start_time) / 3600
        if runtime_hours == 0:
            return 0.0
        return self.position_changes / runtime_hours
    
    @property
    def total_pnl(self) -> Decimal:
        """Total PnL (realized + unrealized)."""
        return self.realized_pnl + self.unrealized_pnl
    
    @property
    def runtime_hours(self) -> float:
        """Total runtime in hours."""
        return (time.time() - self.start_time) / 3600
    
    @property
    def uptime_percentage(self) -> float:
        """Calculate uptime percentage."""
        if self.total_checks == 0:
            return 0.0
        return (self.qualified_checks / self.total_checks) * 100
    
    def get_summary(self) -> Dict:
        """Get comprehensive metrics summary."""
        return {
            'runtime_hours': self.runtime_hours,
            'total_volume': float(self.total_volume),
            'realized_pnl': float(self.realized_pnl),
            'unrealized_pnl': float(self.unrealized_pnl),
            'total_pnl': float(self.total_pnl),
            'current_position': float(self.current_position),
            'total_orders': self.total_orders,
            'filled_orders': self.filled_orders,
            'cancelled_orders': self.cancelled_orders,
            'fill_rate': self.fill_rate,
            'average_spread_bps': float(self.average_spread_bps),
            'inventory_turnover': self.inventory_turnover,
            'uptime_percentage': self.uptime_percentage,
            'total_trades': len(self.trades)
        }
