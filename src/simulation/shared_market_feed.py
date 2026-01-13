"""
Shared Market Feed

Single market data source that broadcasts to all simulators.
Ensures all parameter sets receive identical data for fair comparison.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Awaitable, Any
from decimal import Decimal
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class MarketTick:
    """A single market data tick."""
    timestamp: datetime
    symbol: str
    mid_price: Decimal
    bid_price: Decimal
    ask_price: Decimal
    bid_qty: Decimal
    ask_qty: Decimal
    spread_bps: float
    # Optional orderbook depth for queue position simulation
    bid_depth: List[tuple] = field(default_factory=list)  # [(price, qty), ...]
    ask_depth: List[tuple] = field(default_factory=list)


@dataclass
class OrderbookSnapshot:
    """Orderbook snapshot for queue position analysis."""
    timestamp: datetime
    symbol: str
    bids: List[tuple]  # [(price, qty), ...]
    asks: List[tuple]
    mark_price: Optional[Decimal] = None


class SharedMarketFeed:
    """
    Single market data source that broadcasts to all simulators.
    Fetches data from exchange adapter and distributes to subscribers.
    """

    def __init__(
        self,
        adapter: Any,  # BasePerpAdapter
        symbol: str = "BTC-USD",
        tick_interval_ms: int = 100
    ):
        self.adapter = adapter
        self.symbol = symbol
        self.tick_interval_ms = tick_interval_ms

        # Subscribers (callback functions)
        self._subscribers: List[Callable[[MarketTick], Awaitable[None]]] = []

        # Current market state
        self._current_tick: Optional[MarketTick] = None
        self._current_orderbook: Optional[OrderbookSnapshot] = None

        # Control
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Statistics
        self._ticks_sent = 0
        self._errors = 0
        self._started_at: Optional[datetime] = None

    def subscribe(self, callback: Callable[[MarketTick], Awaitable[None]]):
        """
        Register a callback to receive market updates.

        Args:
            callback: Async function that takes MarketTick
        """
        self._subscribers.append(callback)
        logger.info(f"Subscriber added. Total: {len(self._subscribers)}")

    def unsubscribe(self, callback: Callable[[MarketTick], Awaitable[None]]):
        """Remove a subscriber."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)
            logger.info(f"Subscriber removed. Total: {len(self._subscribers)}")

    async def start(self):
        """Start the market feed."""
        if self._running:
            logger.warning("Market feed already running")
            return

        self._running = True
        self._started_at = datetime.now()
        self._task = asyncio.create_task(self._feed_loop())
        logger.info(f"Market feed started for {self.symbol}")

    async def stop(self):
        """Stop the market feed."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(f"Market feed stopped. Sent {self._ticks_sent} ticks, {self._errors} errors")

    async def _feed_loop(self):
        """Main feed loop - fetch and broadcast market data."""
        interval_sec = self.tick_interval_ms / 1000

        while self._running:
            try:
                # Fetch orderbook from adapter
                orderbook = await self.adapter.get_orderbook(self.symbol)

                if orderbook and orderbook.bids and orderbook.asks:
                    # Create market tick
                    best_bid = Decimal(str(orderbook.bids[0][0]))
                    best_ask = Decimal(str(orderbook.asks[0][0]))
                    bid_qty = Decimal(str(orderbook.bids[0][1]))
                    ask_qty = Decimal(str(orderbook.asks[0][1]))
                    mid_price = (best_bid + best_ask) / 2

                    # Calculate spread
                    spread_bps = float((best_ask - best_bid) / mid_price * 10000)

                    tick = MarketTick(
                        timestamp=datetime.now(),
                        symbol=self.symbol,
                        mid_price=mid_price,
                        bid_price=best_bid,
                        ask_price=best_ask,
                        bid_qty=bid_qty,
                        ask_qty=ask_qty,
                        spread_bps=spread_bps,
                        bid_depth=[(Decimal(str(p)), Decimal(str(q))) for p, q in orderbook.bids[:10]],
                        ask_depth=[(Decimal(str(p)), Decimal(str(q))) for p, q in orderbook.asks[:10]]
                    )

                    self._current_tick = tick

                    # Store orderbook snapshot
                    self._current_orderbook = OrderbookSnapshot(
                        timestamp=tick.timestamp,
                        symbol=self.symbol,
                        bids=orderbook.bids[:20],
                        asks=orderbook.asks[:20],
                        mark_price=mid_price
                    )

                    # Broadcast to all subscribers
                    await self._broadcast(tick)
                    self._ticks_sent += 1

            except Exception as e:
                self._errors += 1
                if self._errors % 10 == 1:  # Log every 10th error
                    logger.warning(f"Market feed error: {e}")

            await asyncio.sleep(interval_sec)

    async def _broadcast(self, tick: MarketTick):
        """Broadcast tick to all subscribers."""
        if not self._subscribers:
            return

        # Call all subscribers concurrently
        tasks = [callback(tick) for callback in self._subscribers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Log any errors
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(f"Subscriber {i} error: {result}")

    def get_current_tick(self) -> Optional[MarketTick]:
        """Get the most recent market tick."""
        return self._current_tick

    def get_current_orderbook(self) -> Optional[OrderbookSnapshot]:
        """Get the most recent orderbook snapshot."""
        return self._current_orderbook

    def get_queue_position(self, side: str, price: Decimal) -> int:
        """
        Estimate queue position for a price level.

        Args:
            side: "buy" or "sell"
            price: Order price

        Returns:
            Estimated queue position (1 = best, higher = further back)
        """
        if self._current_orderbook is None:
            return 0

        if side == "buy":
            depth = self._current_orderbook.bids
            # For bids, higher price = better position
            position = 1
            for level_price, _ in depth:
                if Decimal(str(level_price)) > price:
                    position += 1
                elif Decimal(str(level_price)) == price:
                    return position
            return position
        else:
            depth = self._current_orderbook.asks
            # For asks, lower price = better position
            position = 1
            for level_price, _ in depth:
                if Decimal(str(level_price)) < price:
                    position += 1
                elif Decimal(str(level_price)) == price:
                    return position
            return position

    def get_stats(self) -> Dict:
        """Get feed statistics."""
        runtime = 0
        if self._started_at:
            runtime = (datetime.now() - self._started_at).total_seconds()

        return {
            'running': self._running,
            'symbol': self.symbol,
            'subscribers': len(self._subscribers),
            'ticks_sent': self._ticks_sent,
            'errors': self._errors,
            'runtime_seconds': runtime,
            'ticks_per_second': self._ticks_sent / max(runtime, 1)
        }
