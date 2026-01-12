"""
Risk Manager

Monitors and enforces risk limits for trading strategies.
"""

from typing import Dict, Optional
from decimal import Decimal
from dataclasses import dataclass
import time

from ..exchange import Position, Balance


@dataclass
class RiskLimits:
    """Risk limit configuration."""
    max_position_value: Decimal  # Maximum position value in USD
    max_leverage: int  # Maximum leverage
    max_daily_loss: Decimal  # Maximum daily loss in USD
    max_trade_loss: Decimal  # Maximum loss per trade
    max_drawdown: Decimal  # Maximum drawdown percentage
    max_open_orders: int  # Maximum number of open orders


@dataclass
class RiskMetrics:
    """Current risk metrics."""
    position_value: Decimal = Decimal('0')
    current_leverage: Decimal = Decimal('0')
    daily_pnl: Decimal = Decimal('0')
    max_daily_pnl: Decimal = Decimal('0')
    current_drawdown: Decimal = Decimal('0')
    open_orders_count: int = 0
    equity: Decimal = Decimal('0')


class RiskManager:
    """
    Risk management system for trading strategies.
    
    Monitors positions, P&L, and other risk metrics to ensure
    trading stays within defined risk parameters.
    """
    
    def __init__(self, limits: RiskLimits):
        """
        Initialize risk manager.
        
        Args:
            limits: Risk limit configuration
        """
        self.limits = limits
        self.metrics = RiskMetrics()
        
        # State tracking
        self.daily_start_equity: Optional[Decimal] = None
        self.daily_reset_time = self._get_next_daily_reset()
        self.peak_equity = Decimal('0')
        self.is_halted = False
        self.halt_reason: Optional[str] = None
        
        print(f"🛡️  Risk Manager Initialized")
        print(f"   Max Position Value: ${self.limits.max_position_value:,.0f}")
        print(f"   Max Daily Loss: ${self.limits.max_daily_loss:,.0f}")
        print(f"   Max Drawdown: {self.limits.max_drawdown * 100:.1f}%")
    
    def update_metrics(
        self,
        position: Optional[Position],
        balance: Balance,
        open_orders_count: int
    ):
        """
        Update current risk metrics.
        
        Args:
            position: Current position
            balance: Current balance
            open_orders_count: Number of open orders
        """
        # Update position metrics
        if position:
            self.metrics.position_value = position.position_value
            self.metrics.current_leverage = Decimal(str(position.leverage))
        else:
            self.metrics.position_value = Decimal('0')
            self.metrics.current_leverage = Decimal('0')
        
        # Update balance metrics
        self.metrics.equity = balance.equity
        self.metrics.open_orders_count = open_orders_count
        
        # Initialize daily tracking
        if self.daily_start_equity is None:
            self.daily_start_equity = balance.equity
            self.peak_equity = balance.equity
        
        # Check for daily reset
        if time.time() >= self.daily_reset_time:
            self._reset_daily_metrics(balance.equity)
        
        # Calculate daily P&L
        self.metrics.daily_pnl = balance.equity - self.daily_start_equity
        
        # Track peak equity and drawdown
        if balance.equity > self.peak_equity:
            self.peak_equity = balance.equity
            self.metrics.max_daily_pnl = max(self.metrics.max_daily_pnl, self.metrics.daily_pnl)
        
        # Calculate current drawdown from peak
        if self.peak_equity > 0:
            self.metrics.current_drawdown = (
                (self.peak_equity - balance.equity) / self.peak_equity
            )
    
    def check_risk_limits(self) -> tuple[bool, Optional[str]]:
        """
        Check if current state violates risk limits.
        
        Returns:
            Tuple of (is_within_limits, violation_reason)
        """
        if self.is_halted:
            return False, self.halt_reason
        
        # Check position value limit
        if self.metrics.position_value > self.limits.max_position_value:
            reason = (f"Position value ${self.metrics.position_value:,.0f} exceeds "
                     f"limit ${self.limits.max_position_value:,.0f}")
            return False, reason
        
        # Check leverage limit
        if self.metrics.current_leverage > self.limits.max_leverage:
            reason = (f"Leverage {self.metrics.current_leverage}x exceeds "
                     f"limit {self.limits.max_leverage}x")
            return False, reason
        
        # Check daily loss limit
        if self.metrics.daily_pnl < -self.limits.max_daily_loss:
            reason = (f"Daily loss ${abs(self.metrics.daily_pnl):,.2f} exceeds "
                     f"limit ${self.limits.max_daily_loss:,.0f}")
            self._halt_trading(reason)
            return False, reason
        
        # Check drawdown limit
        if self.metrics.current_drawdown > self.limits.max_drawdown:
            reason = (f"Drawdown {self.metrics.current_drawdown*100:.2f}% exceeds "
                     f"limit {self.limits.max_drawdown*100:.1f}%")
            self._halt_trading(reason)
            return False, reason
        
        # Check open orders limit
        if self.metrics.open_orders_count > self.limits.max_open_orders:
            reason = (f"Open orders {self.metrics.open_orders_count} exceeds "
                     f"limit {self.limits.max_open_orders}")
            return False, reason
        
        return True, None
    
    def can_open_position(self, side: str, size: Decimal, price: Decimal) -> bool:
        """
        Check if a new position can be opened.
        
        Args:
            side: Order side ('buy' or 'sell')
            size: Order size
            price: Order price
            
        Returns:
            True if position can be opened
        """
        # Calculate potential position value
        new_position_value = size * price
        total_position_value = self.metrics.position_value + new_position_value
        
        return total_position_value <= self.limits.max_position_value
    
    def _halt_trading(self, reason: str):
        """
        Halt all trading due to risk violation.
        
        Args:
            reason: Reason for halt
        """
        self.is_halted = True
        self.halt_reason = reason
        print(f"\n⛔ TRADING HALTED: {reason}\n")
    
    def resume_trading(self):
        """Resume trading after manual intervention."""
        self.is_halted = False
        self.halt_reason = None
        print("✅ Trading resumed")
    
    def _reset_daily_metrics(self, current_equity: Decimal):
        """Reset daily tracking metrics."""
        self.daily_start_equity = current_equity
        self.peak_equity = current_equity
        self.metrics.daily_pnl = Decimal('0')
        self.metrics.max_daily_pnl = Decimal('0')
        self.daily_reset_time = self._get_next_daily_reset()
        
        print(f"\n📅 Daily metrics reset. Starting equity: ${current_equity:,.2f}\n")
    
    @staticmethod
    def _get_next_daily_reset() -> int:
        """Get timestamp for next daily reset (midnight UTC)."""
        current_time = time.time()
        seconds_per_day = 86400
        next_midnight = ((current_time // seconds_per_day) + 1) * seconds_per_day
        return int(next_midnight)
    
    def get_risk_summary(self) -> str:
        """
        Get formatted risk summary.
        
        Returns:
            Formatted string with risk metrics
        """
        summary = f"""
╔══════════════════════════════════════════════════════════╗
║                     RISK SUMMARY                          ║
╠══════════════════════════════════════════════════════════╣
║ Position Value:   ${self.metrics.position_value:>10,.2f} / ${self.limits.max_position_value:>10,.0f} ║
║ Leverage:         {self.metrics.current_leverage:>10.1f}x / {self.limits.max_leverage:>10}x ║
║ Daily P&L:        ${self.metrics.daily_pnl:>10,.2f} (Limit: ${self.limits.max_daily_loss:,.0f}) ║
║ Drawdown:         {self.metrics.current_drawdown*100:>10.2f}% (Limit: {self.limits.max_drawdown*100:.1f}%) ║
║ Open Orders:      {self.metrics.open_orders_count:>10} / {self.limits.max_open_orders:>10} ║
║ Equity:           ${self.metrics.equity:>10,.2f} ║
║ Peak Equity:      ${self.peak_equity:>10,.2f} ║
║ Status:           {'🔴 HALTED' if self.is_halted else '🟢 ACTIVE':>21} ║
╚══════════════════════════════════════════════════════════╝
"""
        return summary
