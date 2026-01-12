"""
Simple Market Making Strategy

A basic market making strategy that places orders at fixed spreads
around the mid price.
"""

from typing import List
from decimal import Decimal

from .base import BaseStrategy, Quote
from ..exchange import OrderSide, OrderBook


class SimpleMarketMaker(BaseStrategy):
    """
    Simple Market Making Strategy.
    
    Places buy and sell orders at fixed spreads around the market mid price.
    Adjusts quotes based on current inventory to maintain position neutrality.
    """
    
    def __init__(self, exchange, config):
        """
        Initialize simple market maker.
        
        Additional config parameters:
            - num_levels: Number of price levels per side (default: 1)
            - level_spacing: Price spacing between levels (default: 0.0005)
            - inventory_skew_factor: Position adjustment coefficient (default: 0.5)
        """
        super().__init__(exchange, config)
        
        self.num_levels = config.get('num_levels', 1)
        self.level_spacing = Decimal(str(config.get('level_spacing', 0.0005)))
        self.inventory_skew_factor = Decimal(str(config.get('inventory_skew_factor', 0.5)))
        
        print(f"📊 Simple Market Maker Configuration:")
        print(f"   Symbol: {self.symbol}")
        print(f"   Base Spread: {self.base_spread * 100:.3f}%")
        print(f"   Order Size: {self.order_size}")
        print(f"   Max Position: {self.max_position}")
        print(f"   Levels: {self.num_levels}")
    
    async def calculate_quotes(self) -> List[Quote]:
        """
        Calculate buy and sell quotes.
        
        Strategy:
        1. Get current market mid price
        2. Calculate base bid/ask prices with spread
        3. Apply inventory skew adjustment
        4. Generate multiple levels if configured
        
        Returns:
            List of Quote objects for both sides
        """
        # Get order book
        orderbook = await self.exchange.get_orderbook(self.symbol)
        
        if not orderbook.mid_price:
            print("⚠️  No mid price available")
            return []
        
        mid_price = orderbook.mid_price
        
        # Calculate inventory skew
        inventory = self.get_current_inventory()
        inventory_ratio = inventory / self.max_position if self.max_position > 0 else Decimal('0')
        
        # Inventory adjustment: push prices away when position is large
        # If long (positive inventory), lower both bid and ask to encourage selling
        # If short (negative inventory), raise both bid and ask to encourage buying
        inventory_adjustment = inventory_ratio * self.inventory_skew_factor * mid_price
        
        # Base prices
        half_spread = self.base_spread / 2
        base_bid = mid_price * (1 - half_spread) - inventory_adjustment
        base_ask = mid_price * (1 + half_spread) - inventory_adjustment
        
        quotes = []
        
        # Generate multiple levels
        for level in range(self.num_levels):
            level_offset = self.level_spacing * level * mid_price
            
            # Buy quotes (bids)
            bid_price = base_bid - level_offset
            bid_size = self.calculate_order_size(OrderSide.BUY, level)
            
            quotes.append(Quote(
                price=bid_price,
                size=bid_size,
                side=OrderSide.BUY
            ))
            
            # Sell quotes (asks)
            ask_price = base_ask + level_offset
            ask_size = self.calculate_order_size(OrderSide.SELL, level)
            
            quotes.append(Quote(
                price=ask_price,
                size=ask_size,
                side=OrderSide.SELL
            ))
        
        # Display strategy info
        self._display_quotes_info(mid_price, inventory, quotes)
        
        return quotes
    
    def calculate_order_size(self, side: OrderSide, level: int) -> Decimal:
        """
        Calculate order size for a given level.
        
        Can be overridden to implement size skewing based on inventory.
        """
        # Base size
        size = self.order_size
        
        # Optionally reduce size for further levels
        if level > 0:
            size = size * Decimal('0.8') ** level
        
        # Inventory-based size adjustment
        inventory = self.get_current_inventory()
        inventory_ratio = inventory / self.max_position if self.max_position > 0 else Decimal('0')
        
        # If long, increase sell size and decrease buy size
        # If short, increase buy size and decrease sell size
        if side == OrderSide.BUY:
            # Reduce buy size if already long
            size_multiplier = 1 - (inventory_ratio * Decimal('0.5'))
        else:  # SELL
            # Reduce sell size if already short
            size_multiplier = 1 + (inventory_ratio * Decimal('0.5'))
        
        size = size * max(size_multiplier, Decimal('0.1'))  # Minimum 10% of base size
        
        return size
    
    def _display_quotes_info(self, mid_price: Decimal, inventory: Decimal, quotes: List[Quote]):
        """Display current quotes information."""
        print(f"\n📈 Market Making Status")
        print(f"   Mid Price: ${mid_price:,.2f}")
        print(f"   Position: {inventory:+.4f} ({(inventory/self.max_position*100):+.1f}% of max)")
        
        # Display quotes
        buys = [q for q in quotes if q.side == OrderSide.BUY]
        sells = [q for q in quotes if q.side == OrderSide.SELL]
        
        print(f"\n   Buy Orders:")
        for i, quote in enumerate(sorted(buys, key=lambda q: q.price, reverse=True)):
            spread_bps = ((mid_price - quote.price) / mid_price) * 10000
            print(f"      L{i+1}: {quote.size:.4f} @ ${quote.price:,.2f} (-{spread_bps:.1f} bps)")
        
        print(f"\n   Sell Orders:")
        for i, quote in enumerate(sorted(sells, key=lambda q: q.price)):
            spread_bps = ((quote.price - mid_price) / mid_price) * 10000
            print(f"      L{i+1}: {quote.size:.4f} @ ${quote.price:,.2f} (+{spread_bps:.1f} bps)")
        
        print(f"\n   PnL: Realized ${self.metrics.realized_pnl:+,.2f} | "
              f"Unrealized ${self.metrics.unrealized_pnl:+,.2f}")
        print("   " + "="*60)
    
    async def on_start(self):
        """Initialize strategy."""
        # Get symbol info for precision
        symbol_info = await self.exchange.get_symbol_info(self.symbol)
        print(f"✅ Symbol Info: {symbol_info.get('symbol')}")
        print(f"   Min Order: {symbol_info.get('min_order_qty')}")
        print(f"   Max Order: {symbol_info.get('max_order_qty')}")
        print(f"   Maker Fee: {symbol_info.get('maker_fee')}")
