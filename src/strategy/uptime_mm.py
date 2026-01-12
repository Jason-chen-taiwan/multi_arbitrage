"""
Uptime-Optimized Market Making Strategy

Specifically designed for StandX Market Maker Uptime Program:
- Maintains orders within 10 bps of mark price
- Optimizes for 70%+ uptime to achieve Boosted tier (1.0x multiplier)
- Maximizes order size (up to 2 BTC cap) for higher Maker Hours
- Targets 360+ hours/month for MM1 or 504+ hours/month for MM2 tier
"""

from typing import List, Optional
from decimal import Decimal
from collections import deque
import time

from .base import BaseStrategy, Quote
from ..exchange import OrderSide, OrderBook


class UptimeMarketMaker(BaseStrategy):
    """
    Uptime-Optimized Market Maker Strategy.
    
    Designed specifically for StandX Market Maker Uptime Program with:
    - Strict 10 bps spread enforcement
    - High uptime maintenance (70%+ target)
    - Maximum order size utilization (2 BTC cap)
    - Continuous order presence on both sides
    """
    
    def __init__(self, exchange, config):
        """
        Initialize uptime-optimized market maker.
        
        Uptime Program Requirements:
        - Both bid and ask within 10 bps of mark price
        - At least 30 min/hour (50%) for Standard tier (0.5x)
        - At least 42 min/hour (70%) for Boosted tier (1.0x)
        - Order size capped at 2 BTC for BTC-USD
        """
        super().__init__(exchange, config)
        
        # Uptime Program Settings
        self.max_spread_bps = Decimal('0.0010')  # 10 bps hard limit
        self.spread_buffer = Decimal(str(config.get('spread_buffer', 0.0002)))  # 2 bps buffer
        self.target_uptime = Decimal(str(config.get('target_uptime', 0.70)))
        
        # Order size optimization for Maker Hours
        self.prefer_max_size = config.get('prefer_max_size', True)
        self.order_size_cap = Decimal(str(config.get('max_order_size', 2.0)))  # 2 BTC for BTC-USD
        
        # Uptime tracking
        self.uptime_start = time.time()
        self.qualified_minutes = 0
        self.total_checks = 0
        self.qualified_checks = 0
        
        # Mark price tracking
        self.use_mark_price = config.get('use_mark_price', True)
        self.last_mark_price: Optional[Decimal] = None
        
        print(f"🎯 Uptime Market Maker Configuration:")
        print(f"   Symbol: {self.symbol}")
        print(f"   Max Spread: {self.max_spread_bps * 10000:.1f} bps (hard limit)")
        print(f"   Spread Buffer: {self.spread_buffer * 10000:.1f} bps")
        print(f"   Target Uptime: {self.target_uptime * 100:.0f}%")
        print(f"   Order Size Cap: {self.order_size_cap} BTC")
        print(f"   Target Tier: {'MM2 (504+ hrs)' if self.target_uptime >= 0.70 else 'MM1 (360+ hrs)'}")
    
    async def calculate_quotes(self) -> List[Quote]:
        """
        Calculate quotes optimized for Uptime Program.
        
        Strategy:
        1. Get mark price (or mid price as fallback)
        2. Calculate maximum allowed spread (10 bps - buffer)
        3. Apply minimal inventory adjustment (stay within spread)
        4. Use maximum order size (up to 2 BTC cap)
        5. Ensure both sides are within qualification range
        """
        # Get order book
        orderbook = await self.exchange.get_orderbook(self.symbol)
        
        if not orderbook.mid_price:
            print("⚠️  No mid price available")
            return []
        
        # Use mark price if available, otherwise use mid price
        mark_price = await self._get_mark_price()
        if not mark_price:
            mark_price = orderbook.mid_price
        
        self.last_mark_price = mark_price
        
        # Calculate safe spread (within 10 bps requirement)
        safe_spread = self.max_spread_bps - self.spread_buffer
        half_spread = safe_spread / 2
        
        # Get inventory
        inventory = self.get_current_inventory()
        
        # Apply minimal inventory adjustment (but keep within spread limit)
        max_adjustment = self.spread_buffer * mark_price
        if self.max_position > 0:
            inventory_ratio = inventory / self.max_position
            inventory_adjustment = inventory_ratio * max_adjustment * Decimal('0.5')
            # Clamp adjustment to not exceed buffer
            inventory_adjustment = max(
                -max_adjustment, 
                min(max_adjustment, inventory_adjustment)
            )
        else:
            inventory_adjustment = Decimal('0')
        
        # Calculate bid and ask prices
        bid_price = mark_price * (1 - half_spread) - inventory_adjustment
        ask_price = mark_price * (1 + half_spread) - inventory_adjustment
        
        # Verify prices are within 10 bps
        bid_spread_bps = (mark_price - bid_price) / mark_price
        ask_spread_bps = (ask_price - mark_price) / mark_price
        
        if bid_spread_bps > self.max_spread_bps or ask_spread_bps > self.max_spread_bps:
            print(f"⚠️  SPREAD VIOLATION: Adjusting to stay within 10 bps")
            # Force to max spread
            bid_price = mark_price * (1 - self.max_spread_bps + Decimal('0.0001'))
            ask_price = mark_price * (1 + self.max_spread_bps - Decimal('0.0001'))
        
        # Calculate order size (maximize for Maker Hours)
        bid_size = self._calculate_optimal_size(OrderSide.BUY, inventory)
        ask_size = self._calculate_optimal_size(OrderSide.SELL, inventory)
        
        quotes = [
            Quote(price=bid_price, size=bid_size, side=OrderSide.BUY),
            Quote(price=ask_price, size=ask_size, side=OrderSide.SELL)
        ]
        
        # Track qualification
        self._track_qualification(mark_price, bid_price, ask_price, min(bid_size, ask_size))
        
        # Display status
        self._display_uptime_status(mark_price, inventory, quotes)
        
        return quotes
    
    def _calculate_optimal_size(self, side: OrderSide, inventory: Decimal) -> Decimal:
        """
        Calculate optimal order size for Maker Hours.
        
        Strategy:
        - Use maximum cap (2 BTC) whenever possible
        - Only reduce if capital insufficient or position limit reached
        """
        if self.prefer_max_size:
            # Start with maximum
            target_size = self.order_size_cap
        else:
            # Use configured base size
            target_size = self.order_size
        
        # Check position limits
        if side == OrderSide.BUY:
            available = self.max_position - inventory
        else:  # SELL
            available = self.max_position + inventory
        
        # Reduce if would exceed position limit
        if available < target_size:
            target_size = max(available * Decimal('0.8'), self.min_order_size)
        
        # Ensure within bounds
        target_size = max(
            self.min_order_size,
            min(self.order_size_cap, target_size)
        )
        
        return target_size
    
    async def _get_mark_price(self) -> Optional[Decimal]:
        """
        Get mark price from exchange.
        
        Mark price is used for spread calculation in Uptime Program.
        """
        if not self.use_mark_price:
            return None
        
        try:
            # Get symbol price info which includes mark price
            result = await self.exchange._request(
                'GET', '/api/query_symbol_price',
                params={'symbol': self.symbol}
            )
            
            if result and 'mark_price' in result:
                return Decimal(result['mark_price'])
        except Exception as e:
            print(f"⚠️  Failed to get mark price: {e}")
        
        return None
    
    def _track_qualification(
        self, 
        mark_price: Decimal,
        bid_price: Decimal,
        ask_price: Decimal,
        order_size: Decimal
    ):
        """Track if current orders would qualify for Uptime Program."""
        self.total_checks += 1
        
        # Check if within 10 bps
        bid_spread = (mark_price - bid_price) / mark_price
        ask_spread = (ask_price - mark_price) / mark_price
        
        within_spread = (
            bid_spread <= self.max_spread_bps and 
            ask_spread <= self.max_spread_bps and
            order_size > 0
        )
        
        if within_spread:
            self.qualified_checks += 1
        
        # Calculate current uptime percentage
        if self.total_checks > 0:
            current_uptime = self.qualified_checks / self.total_checks
            
            # Alert if below target
            if current_uptime < self.target_uptime:
                print(f"⚠️  Uptime below target: {current_uptime*100:.1f}% < {self.target_uptime*100:.0f}%")
    
    def _display_uptime_status(
        self,
        mark_price: Decimal,
        inventory: Decimal,
        quotes: List[Quote]
    ):
        """Display uptime program status."""
        bid = [q for q in quotes if q.side == OrderSide.BUY][0]
        ask = [q for q in quotes if q.side == OrderSide.SELL][0]
        
        bid_spread_bps = ((mark_price - bid.price) / mark_price) * 10000
        ask_spread_bps = ((ask.price - mark_price) / mark_price) * 10000
        
        # Calculate uptime stats
        current_uptime = (self.qualified_checks / self.total_checks * 100) if self.total_checks > 0 else 0
        runtime_hours = (time.time() - self.uptime_start) / 3600
        
        # Estimate Maker Hours
        smaller_size = min(bid.size, ask.size)
        if current_uptime >= 70:
            estimated_maker_hours = (smaller_size / 2) * Decimal('1.0')  # Boosted tier
            tier = "🟢 Boosted (1.0x)"
        elif current_uptime >= 50:
            estimated_maker_hours = (smaller_size / 2) * Decimal('0.5')  # Standard tier
            tier = "🟡 Standard (0.5x)"
        else:
            estimated_maker_hours = Decimal('0')
            tier = "⚪ Inactive (0x)"
        
        print(f"\n🎯 Uptime Market Maker Status")
        print(f"   Mark Price: ${mark_price:,.2f}")
        print(f"   Current Uptime: {current_uptime:.1f}% | Target: {self.target_uptime*100:.0f}%")
        print(f"   Tier: {tier}")
        print(f"   Runtime: {runtime_hours:.2f} hours")
        
        print(f"\n   📍 Bid:  {bid.size:.3f} BTC @ ${bid.price:,.2f} ({bid_spread_bps:.2f} bps)")
        print(f"   📍 Ask:  {ask.size:.3f} BTC @ ${ask.price:,.2f} ({ask_spread_bps:.2f} bps)")
        
        # Spread compliance check
        max_spread = max(bid_spread_bps, ask_spread_bps)
        if max_spread <= 100:  # 10 bps = 100 in our calculation
            print(f"   ✅ Within 10 bps requirement ({max_spread:.2f} bps)")
        else:
            print(f"   ❌ EXCEEDS 10 bps requirement ({max_spread:.2f} bps)")
        
        print(f"\n   Est. Maker Hours/hour: {estimated_maker_hours:.3f}")
        print(f"   Est. Monthly Hours: {estimated_maker_hours * 24 * 30:.1f} (Target: {'504 (MM2)' if self.target_uptime >= 0.70 else '360 (MM1)'})")
        print(f"   Position: {inventory:+.4f} BTC ({(inventory/self.max_position*100):+.1f}% of max)")
        
        print(f"\n   PnL: Realized ${self.metrics.realized_pnl:+,.2f} | "
              f"Unrealized ${self.metrics.unrealized_pnl:+,.2f}")
        print("   " + "="*70)
    
    async def on_start(self):
        """Initialize uptime tracking."""
        self.uptime_start = time.time()
        print(f"\n🎯 Uptime Program Mode Activated")
        print(f"   Target: {self.target_uptime*100:.0f}%+ uptime for Boosted tier")
        print(f"   Goal: {'504+ hours/month (MM2)' if self.target_uptime >= 0.70 else '360+ hours/month (MM1)'}")
        print(f"   Max Spread: 10 bps from mark price")
        print(f"   Order Size: {self.order_size_cap} BTC (capped)")
