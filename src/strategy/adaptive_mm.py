"""
Adaptive Market Making Strategy

An advanced market making strategy that dynamically adjusts spreads and sizes
based on market volatility, order book depth, and other market microstructure signals.
"""

from typing import List
from decimal import Decimal
from collections import deque
import statistics

from .base import BaseStrategy, Quote
from ..exchange import OrderSide, OrderBook


class AdaptiveMarketMaker(BaseStrategy):
    """
    Adaptive Market Making Strategy.
    
    Features:
    - Dynamic spread adjustment based on volatility
    - Order book imbalance detection
    - Inventory management with asymmetric quoting
    - Market regime detection
    """
    
    def __init__(self, exchange, config):
        """
        Initialize adaptive market maker.
        
        Additional config parameters:
            - volatility_window: Window for volatility calculation (default: 20)
            - volatility_multiplier: Spread adjustment factor (default: 2.0)
            - min_spread: Minimum spread (default: 0.0005)
            - max_spread: Maximum spread (default: 0.005)
            - ob_imbalance_threshold: Order book imbalance threshold (default: 0.3)
        """
        super().__init__(exchange, config)
        
        self.volatility_window = config.get('volatility_window', 20)
        self.volatility_multiplier = Decimal(str(config.get('volatility_multiplier', 2.0)))
        self.min_spread = Decimal(str(config.get('min_spread', 0.0005)))
        self.max_spread = Decimal(str(config.get('max_spread', 0.005)))
        self.ob_imbalance_threshold = Decimal(str(config.get('ob_imbalance_threshold', 0.3)))
        
        # Price history for volatility calculation
        self.price_history = deque(maxlen=self.volatility_window)
        
        print(f"🧠 Adaptive Market Maker Configuration:")
        print(f"   Symbol: {self.symbol}")
        print(f"   Base Spread: {self.base_spread * 100:.3f}%")
        print(f"   Spread Range: {self.min_spread * 100:.3f}% - {self.max_spread * 100:.3f}%")
        print(f"   Volatility Window: {self.volatility_window}")
        print(f"   Volatility Multiplier: {self.volatility_multiplier}")
    
    async def calculate_quotes(self) -> List[Quote]:
        """
        Calculate adaptive quotes based on market conditions.
        
        Strategy:
        1. Measure market volatility
        2. Detect order book imbalance
        3. Calculate dynamic spread
        4. Apply inventory skew
        5. Generate quotes
        """
        # Get order book
        orderbook = await self.exchange.get_orderbook(self.symbol)
        
        if not orderbook.mid_price:
            print("⚠️  No mid price available")
            return []
        
        mid_price = orderbook.mid_price
        
        # Update price history
        self.price_history.append(float(mid_price))
        
        # Calculate market signals
        volatility = self._calculate_volatility()
        ob_imbalance = self._calculate_orderbook_imbalance(orderbook)
        
        # Calculate dynamic spread
        dynamic_spread = self._calculate_dynamic_spread(volatility, ob_imbalance)
        
        # Calculate inventory adjustment
        inventory = self.get_current_inventory()
        inventory_adjustment = self._calculate_inventory_adjustment(inventory, mid_price)
        
        # Calculate imbalance adjustment
        imbalance_adjustment = self._calculate_imbalance_adjustment(ob_imbalance, mid_price)
        
        # Generate quotes
        half_spread = dynamic_spread / 2
        
        # Base prices with all adjustments
        bid_price = mid_price * (1 - half_spread) - inventory_adjustment - imbalance_adjustment
        ask_price = mid_price * (1 + half_spread) - inventory_adjustment + imbalance_adjustment
        
        # Calculate adaptive order sizes
        bid_size = self._calculate_adaptive_size(OrderSide.BUY, inventory, ob_imbalance)
        ask_size = self._calculate_adaptive_size(OrderSide.SELL, inventory, ob_imbalance)
        
        quotes = [
            Quote(price=bid_price, size=bid_size, side=OrderSide.BUY),
            Quote(price=ask_price, size=ask_size, side=OrderSide.SELL)
        ]
        
        # Display info
        self._display_adaptive_info(
            mid_price, volatility, ob_imbalance, 
            dynamic_spread, inventory, quotes
        )
        
        return quotes
    
    def _calculate_volatility(self) -> float:
        """
        Calculate realized volatility from price history.
        
        Uses standard deviation of log returns.
        """
        if len(self.price_history) < 2:
            return 0.0
        
        # Calculate log returns
        returns = []
        for i in range(1, len(self.price_history)):
            ret = (self.price_history[i] - self.price_history[i-1]) / self.price_history[i-1]
            returns.append(ret)
        
        # Calculate volatility as standard deviation
        if len(returns) < 2:
            return 0.0
        
        vol = statistics.stdev(returns)
        
        # Annualize (assuming 5 second refresh * 12 per minute * 60 * 24 * 365)
        periods_per_year = (365 * 24 * 60 * 60) / self.refresh_interval
        annualized_vol = vol * (periods_per_year ** 0.5)
        
        return annualized_vol
    
    def _calculate_orderbook_imbalance(self, orderbook: OrderBook) -> Decimal:
        """
        Calculate order book imbalance.
        
        Positive imbalance = more buy pressure
        Negative imbalance = more sell pressure
        
        Returns:
            Imbalance ratio between -1 and 1
        """
        if not orderbook.bids or not orderbook.asks:
            return Decimal('0')
        
        # Sum top N levels
        N = 5
        bid_volume = sum(size for _, size in orderbook.bids[:N])
        ask_volume = sum(size for _, size in orderbook.asks[:N])
        
        total_volume = bid_volume + ask_volume
        if total_volume == 0:
            return Decimal('0')
        
        # Imbalance: (bids - asks) / (bids + asks)
        imbalance = (bid_volume - ask_volume) / total_volume
        
        return imbalance
    
    def _calculate_dynamic_spread(self, volatility: float, imbalance: Decimal) -> Decimal:
        """
        Calculate dynamic spread based on market conditions.
        
        Higher volatility → wider spread
        Higher imbalance → wider spread on imbalanced side
        """
        # Base spread adjustment from volatility
        vol_adjustment = Decimal(str(volatility)) * self.volatility_multiplier
        dynamic_spread = self.base_spread * (1 + vol_adjustment)
        
        # Imbalance adjustment (widen spread when uncertain)
        imbalance_adjustment = abs(imbalance) * Decimal('0.5')
        dynamic_spread = dynamic_spread * (1 + imbalance_adjustment)
        
        # Clamp to min/max
        dynamic_spread = max(self.min_spread, min(self.max_spread, dynamic_spread))
        
        return dynamic_spread
    
    def _calculate_inventory_adjustment(self, inventory: Decimal, mid_price: Decimal) -> Decimal:
        """
        Calculate price adjustment based on inventory.
        
        Large inventory → push prices to reduce position
        """
        if self.max_position == 0:
            return Decimal('0')
        
        inventory_ratio = inventory / self.max_position
        
        # Exponential penalty for large positions
        if abs(inventory_ratio) > Decimal('0.5'):
            penalty_multiplier = Decimal('2')
        else:
            penalty_multiplier = Decimal('1')
        
        adjustment = inventory_ratio * Decimal('0.003') * mid_price * penalty_multiplier
        
        return adjustment
    
    def _calculate_imbalance_adjustment(self, imbalance: Decimal, mid_price: Decimal) -> Decimal:
        """
        Calculate price adjustment based on order book imbalance.
        
        Positive imbalance (buy pressure) → raise quotes
        Negative imbalance (sell pressure) → lower quotes
        """
        if abs(imbalance) < self.ob_imbalance_threshold:
            return Decimal('0')
        
        # Adjust prices in direction of imbalance
        adjustment = imbalance * Decimal('0.001') * mid_price
        
        return adjustment
    
    def _calculate_adaptive_size(
        self, 
        side: OrderSide, 
        inventory: Decimal, 
        imbalance: Decimal
    ) -> Decimal:
        """
        Calculate adaptive order size based on position and market conditions.
        """
        base_size = self.order_size
        
        # Inventory-based sizing
        inventory_ratio = inventory / self.max_position if self.max_position > 0 else Decimal('0')
        
        if side == OrderSide.BUY:
            # Reduce buy size if long, increase if short
            size_multiplier = Decimal('1') - (inventory_ratio * Decimal('0.7'))
            
            # Increase buy size if sell pressure detected
            if imbalance < -self.ob_imbalance_threshold:
                size_multiplier *= Decimal('1.2')
                
        else:  # SELL
            # Reduce sell size if short, increase if long
            size_multiplier = Decimal('1') + (inventory_ratio * Decimal('0.7'))
            
            # Increase sell size if buy pressure detected
            if imbalance > self.ob_imbalance_threshold:
                size_multiplier *= Decimal('1.2')
        
        # Clamp multiplier
        size_multiplier = max(Decimal('0.1'), min(Decimal('2.0'), size_multiplier))
        
        return base_size * size_multiplier
    
    def _display_adaptive_info(
        self,
        mid_price: Decimal,
        volatility: float,
        imbalance: Decimal,
        spread: Decimal,
        inventory: Decimal,
        quotes: List[Quote]
    ):
        """Display adaptive strategy information."""
        print(f"\n🧠 Adaptive Market Making Status")
        print(f"   Mid Price: ${mid_price:,.2f}")
        print(f"   Volatility: {volatility*100:.2f}%")
        print(f"   OB Imbalance: {imbalance:+.3f} {'📈 BUY' if imbalance > 0 else '📉 SELL' if imbalance < 0 else '⚖️  NEUTRAL'}")
        print(f"   Dynamic Spread: {spread*100:.3f}% (base: {self.base_spread*100:.3f}%)")
        print(f"   Position: {inventory:+.4f} ({(inventory/self.max_position*100):+.1f}% of max)")
        
        bid = [q for q in quotes if q.side == OrderSide.BUY][0]
        ask = [q for q in quotes if q.side == OrderSide.SELL][0]
        
        bid_spread_bps = ((mid_price - bid.price) / mid_price) * 10000
        ask_spread_bps = ((ask.price - mid_price) / mid_price) * 10000
        
        print(f"\n   Buy:  {bid.size:.4f} @ ${bid.price:,.2f} (-{bid_spread_bps:.1f} bps)")
        print(f"   Sell: {ask.size:.4f} @ ${ask.price:,.2f} (+{ask_spread_bps:.1f} bps)")
        
        print(f"\n   PnL: Realized ${self.metrics.realized_pnl:+,.2f} | "
              f"Unrealized ${self.metrics.unrealized_pnl:+,.2f}")
        print("   " + "="*60)
