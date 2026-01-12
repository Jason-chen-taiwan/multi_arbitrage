"""
Base Strategy Class

Abstract base class for all market making strategies.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
from decimal import Decimal
from dataclasses import dataclass
import asyncio

from ..exchange import BaseExchange, OrderBook, Order, Position, OrderSide, OrderType
from ..monitor import MetricsTracker, Dashboard


@dataclass
class Quote:
    """Price quote for one side of the order book."""
    price: Decimal
    size: Decimal
    side: OrderSide


@dataclass
class StrategyMetrics:
    """Strategy performance metrics."""
    total_trades: int = 0
    total_volume: Decimal = Decimal('0')
    realized_pnl: Decimal = Decimal('0')
    unrealized_pnl: Decimal = Decimal('0')
    total_fees: Decimal = Decimal('0')
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: Decimal = Decimal('0')


class BaseStrategy(ABC):
    """
    Abstract base class for market making strategies.
    
    All strategy implementations must inherit from this class.
    """
    
    def __init__(self, exchange: BaseExchange, config: Dict):
        """
        Initialize strategy.
        
        Args:
            exchange: Exchange connector instance
            config: Strategy configuration
        """
        self.exchange = exchange
        self.config = config
        self.symbol = config['symbol']
        
        # State
        self.is_running = False
        self.active_orders: List[Order] = []
        self.current_position: Optional[Position] = None
        
        # Metrics (legacy for backward compatibility)
        self.metrics = StrategyMetrics()
        
        # New metrics tracker and dashboard
        self.metrics_tracker = MetricsTracker()
        self.dashboard = Dashboard(self.metrics_tracker)
        
        # Configuration
        self.base_spread = Decimal(str(config.get('base_spread', 0.001)))
        self.order_size = Decimal(str(config.get('order_size', 0.01)))
        self.max_position = Decimal(str(config.get('max_position', 0.5)))
        self.refresh_interval = config.get('refresh_interval', 5)
        
        # Dashboard configuration
        self.dashboard_mode = config.get('dashboard_mode', 'full')  # 'full', 'compact', or 'minimal'
        self.dashboard_interval = config.get('dashboard_interval', 30)  # seconds
        self.dashboard.set_display_interval(self.dashboard_interval)
    
    async def start(self):
        """Start the strategy."""
        self.is_running = True
        print(f"🚀 Starting strategy: {self.__class__.__name__}")
        
        try:
            await self.on_start()
            
            while self.is_running:
                await self.run_iteration()
                await asyncio.sleep(self.refresh_interval)
                
        except Exception as e:
            print(f"❌ Strategy error: {e}")
            raise
        finally:
            await self.stop()
    
    async def stop(self):
        """Stop the strategy."""
        self.is_running = False
        print(f"🛑 Stopping strategy: {self.__class__.__name__}")
        
        await self.on_stop()
        
        # Cancel all active orders
        if self.config.get('cancel_all_on_stop', True):
            await self.cancel_all_orders()
    
    async def run_iteration(self):
        """Run one strategy iteration."""
        try:
            # Update state
            await self.update_state()
            
            # Calculate new quotes
            quotes = await self.calculate_quotes()
            
            # Manage orders
            await self.manage_orders(quotes)
            
            # Update metrics
            await self.update_metrics()
            
        except Exception as e:
            print(f"❌ Iteration error: {e}")
    
    async def update_state(self):
        """Update strategy state from exchange."""
        # Update position
        self.current_position = await self.exchange.get_position(self.symbol)
        
        # Update active orders
        self.active_orders = await self.exchange.get_open_orders(self.symbol)
    
    async def manage_orders(self, new_quotes: List[Quote]):
        """
        Manage orders based on new quotes.
        
        This cancels outdated orders and places new ones.
        """
        # Cancel existing orders
        await self.cancel_all_orders()
        
        # Place new orders
        for quote in new_quotes:
            try:
                order = await self.exchange.place_order(
                    symbol=self.symbol,
                    side=quote.side,
                    order_type=OrderType.LIMIT,
                    qty=quote.size,
                    price=quote.price
                )
                print(f"📝 Placed {quote.side.value} order: {quote.size} @ {quote.price}")
            except Exception as e:
                print(f"❌ Failed to place order: {e}")
    
    async def cancel_all_orders(self):
        """Cancel all active orders."""
        if self.active_orders:
            count = await self.exchange.cancel_all_orders(self.symbol)
            if count > 0:
                print(f"🗑️  Cancelled {count} orders")
    
    async def update_metrics(self):
        """Update strategy metrics."""
        # Get recent trades
        trades = await self.exchange.get_trades(self.symbol, limit=100)
        
        self.metrics.total_trades = len(trades)
        self.metrics.total_volume = sum(t.qty for t in trades)
        self.metrics.realized_pnl = sum(t.realized_pnl for t in trades)
        self.metrics.total_fees = sum(t.fee for t in trades)
        
        if self.current_position:
            self.metrics.unrealized_pnl = self.current_position.unrealized_pnl
    
    def get_current_inventory(self) -> Decimal:
        """Get current inventory (position size)."""
        if not self.current_position:
            return Decimal('0')
        
        qty = self.current_position.qty
        if self.current_position.side == OrderSide.SELL:
            qty = -qty
        
        return qty
    
    def check_risk_limits(self) -> bool:
        """
        Check if current state is within risk limits.
        
        Returns:
            True if within limits, False otherwise
        """
        inventory = abs(self.get_current_inventory())
        
        # Check position limit
        if inventory > self.max_position:
            print(f"⚠️  Position limit exceeded: {inventory} > {self.max_position}")
            return False
        
        return True
    
    @abstractmethod
    async def calculate_quotes(self) -> List[Quote]:
        """
        Calculate price quotes for market making.
        
        Must be implemented by strategy subclass.
        
        Returns:
            List of Quote objects (buy and sell quotes)
        """
        pass
    
    async def on_start(self):
        """
        Called when strategy starts.
        
        Override to add custom initialization logic.
        """
        pass
    
    async def on_stop(self):
        """
        Called when strategy stops.
        
        Override to add custom cleanup logic.
        """
        pass
