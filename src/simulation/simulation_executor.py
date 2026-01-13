"""
Simulation Executor

Simulated market maker executor for a single parameter set.
Processes market data and simulates order behavior without placing real orders.
"""

import asyncio
from dataclasses import dataclass
from typing import Dict, Optional, Any
from decimal import Decimal
from datetime import datetime
import logging

from .simulation_state import SimulationState, SimulatedOrder
from .shared_market_feed import MarketTick
from .param_set_manager import ParamSet

logger = logging.getLogger(__name__)


@dataclass
class SimulatorConfig:
    """Configuration extracted from ParamSet for simulation."""
    # Quote parameters
    order_distance_bps: int = 8
    cancel_distance_bps: int = 4
    rebalance_distance_bps: int = 12
    queue_position_limit: int = 3

    # Position parameters
    order_size_btc: Decimal = Decimal("0.001")
    max_position_btc: Decimal = Decimal("0.01")

    # Volatility parameters
    volatility_window_sec: int = 5
    volatility_threshold_bps: float = 5.0

    # Uptime parameters
    max_distance_bps: int = 10

    @classmethod
    def from_param_set(cls, param_set: ParamSet) -> 'SimulatorConfig':
        """Create config from ParamSet."""
        config = param_set.config
        quote = config.get('quote', {})
        position = config.get('position', {})
        volatility = config.get('volatility', {})
        uptime = config.get('uptime', {})

        return cls(
            order_distance_bps=quote.get('order_distance_bps', 8),
            cancel_distance_bps=quote.get('cancel_distance_bps', 4),
            rebalance_distance_bps=quote.get('rebalance_distance_bps', 12),
            queue_position_limit=quote.get('queue_position_limit', 3),
            order_size_btc=Decimal(str(position.get('order_size_btc', 0.001))),
            max_position_btc=Decimal(str(position.get('max_position_btc', 0.01))),
            volatility_window_sec=volatility.get('window_sec', 5),
            volatility_threshold_bps=volatility.get('threshold_bps', 5.0),
            max_distance_bps=uptime.get('max_distance_bps', 10),
        )


class SimulationExecutor:
    """
    Simulates market maker behavior for a single parameter set.

    Processes market ticks and tracks:
    - When orders would be placed/cancelled
    - Uptime qualification
    - Simulated fills (when price crosses order)
    - Queue position impact
    """

    def __init__(self, param_set: ParamSet):
        self.param_set = param_set
        self.config = SimulatorConfig.from_param_set(param_set)
        self.state = SimulationState(
            param_set_id=param_set.id,
            volatility_window_sec=self.config.volatility_window_sec
        )

        # Control
        self._running = False
        self._paused_for_volatility = False

        # Last known prices for order placement
        self._last_mid_price: Optional[Decimal] = None

    async def start(self):
        """Start the simulation."""
        self._running = True
        self.state.start()
        logger.info(f"Simulation started for param set: {self.param_set.id}")

    async def stop(self):
        """Stop the simulation."""
        self._running = False
        logger.info(f"Simulation stopped for param set: {self.param_set.id}")

    async def on_market_tick(self, tick: MarketTick):
        """
        Process a market tick.

        This is called by SharedMarketFeed for each tick.
        Simulates what the market maker would do with these parameters.
        """
        if not self._running:
            return

        mid_price = tick.mid_price
        self._last_mid_price = mid_price

        # Update price history for volatility calculation
        self.state.update_price(mid_price, tick.timestamp)

        # Check volatility
        volatility = self.state.get_volatility_bps()
        if volatility > self.config.volatility_threshold_bps:
            if not self._paused_for_volatility:
                self._paused_for_volatility = True
                self.state.record_volatility_pause()
                self.state.cancel_all_orders("volatility")
            # Record tick as not qualified
            self._record_tick(mid_price, is_qualified=False)
            return
        else:
            self._paused_for_volatility = False

        # Process existing orders
        await self._process_orders(tick)

        # Place new orders if needed
        await self._place_orders_if_needed(tick)

        # Record tick with qualification status
        is_qualified = self._check_uptime_qualified(mid_price)
        self._record_tick(mid_price, is_qualified)

    async def _process_orders(self, tick: MarketTick):
        """Process existing simulated orders - check for cancels, fills, rebalances."""
        mid_price = tick.mid_price

        bid_order = self.state.get_bid_order()
        ask_order = self.state.get_ask_order()

        # Check bid order
        if bid_order:
            bid_distance = self._calculate_distance_bps(bid_order.price, mid_price)

            # Check for simulated fill (price dropped to or below bid)
            if tick.ask_price <= bid_order.price:
                # Simulated fill!
                spread_captured = self.config.order_distance_bps  # Approximation
                self.state.simulate_fill(
                    side="buy",
                    fill_price=bid_order.price,
                    fill_qty=bid_order.qty,
                    spread_bps=spread_captured
                )
                self.state.cancel_bid_order()

            # Check for cancel by distance (price too close)
            elif bid_distance < self.config.cancel_distance_bps:
                self.state.cancel_bid_order("distance")

            # Check for rebalance (price moved away)
            elif bid_distance > self.config.rebalance_distance_bps:
                self.state.cancel_bid_order()
                self.state.record_rebalance()

        # Check ask order
        if ask_order:
            ask_distance = self._calculate_distance_bps(ask_order.price, mid_price)

            # Check for simulated fill (price rose to or above ask)
            if tick.bid_price >= ask_order.price:
                # Simulated fill!
                spread_captured = self.config.order_distance_bps
                self.state.simulate_fill(
                    side="sell",
                    fill_price=ask_order.price,
                    fill_qty=ask_order.qty,
                    spread_bps=spread_captured
                )
                self.state.cancel_ask_order()

            # Check for cancel by distance
            elif ask_distance < self.config.cancel_distance_bps:
                self.state.cancel_ask_order("distance")

            # Check for rebalance
            elif ask_distance > self.config.rebalance_distance_bps:
                self.state.cancel_ask_order()
                self.state.record_rebalance()

    async def _place_orders_if_needed(self, tick: MarketTick):
        """Place simulated orders if we don't have them."""
        mid_price = tick.mid_price
        position = self.state.get_position()

        # Check position limits
        if abs(position) >= self.config.max_position_btc:
            # At max position, only place reducing orders
            if position > 0 and self.state.get_ask_order() is None:
                # Have long position, place ask to reduce
                ask_price = self._calculate_ask_price(mid_price)
                self.state.set_ask_order(SimulatedOrder(
                    order_id=f"sim_ask_{self.param_set.id}_{tick.timestamp.timestamp()}",
                    side="sell",
                    price=ask_price,
                    qty=self.config.order_size_btc,
                    distance_bps=self.config.order_distance_bps
                ))
            elif position < 0 and self.state.get_bid_order() is None:
                # Have short position, place bid to reduce
                bid_price = self._calculate_bid_price(mid_price)
                self.state.set_bid_order(SimulatedOrder(
                    order_id=f"sim_bid_{self.param_set.id}_{tick.timestamp.timestamp()}",
                    side="buy",
                    price=bid_price,
                    qty=self.config.order_size_btc,
                    distance_bps=self.config.order_distance_bps
                ))
            return

        # Normal operation - place both sides
        if self.state.get_bid_order() is None:
            bid_price = self._calculate_bid_price(mid_price)
            self.state.set_bid_order(SimulatedOrder(
                order_id=f"sim_bid_{self.param_set.id}_{tick.timestamp.timestamp()}",
                side="buy",
                price=bid_price,
                qty=self.config.order_size_btc,
                distance_bps=self.config.order_distance_bps
            ))

        if self.state.get_ask_order() is None:
            ask_price = self._calculate_ask_price(mid_price)
            self.state.set_ask_order(SimulatedOrder(
                order_id=f"sim_ask_{self.param_set.id}_{tick.timestamp.timestamp()}",
                side="sell",
                price=ask_price,
                qty=self.config.order_size_btc,
                distance_bps=self.config.order_distance_bps
            ))

    def _calculate_bid_price(self, mid_price: Decimal) -> Decimal:
        """Calculate bid price based on order_distance_bps."""
        distance = Decimal(str(self.config.order_distance_bps)) / Decimal("10000")
        return mid_price * (1 - distance)

    def _calculate_ask_price(self, mid_price: Decimal) -> Decimal:
        """Calculate ask price based on order_distance_bps."""
        distance = Decimal(str(self.config.order_distance_bps)) / Decimal("10000")
        return mid_price * (1 + distance)

    def _calculate_distance_bps(self, order_price: Decimal, mid_price: Decimal) -> float:
        """Calculate distance in basis points between order and mid price."""
        if mid_price == 0:
            return 0.0
        return abs(float((order_price - mid_price) / mid_price * 10000))

    def _check_uptime_qualified(self, mid_price: Decimal) -> bool:
        """
        Check if current orders qualify for uptime tracking.
        Orders must be within max_distance_bps of mid price.
        """
        bid_order = self.state.get_bid_order()
        ask_order = self.state.get_ask_order()

        # Need at least one order to qualify
        if bid_order is None and ask_order is None:
            return False

        # Check bid order qualification
        bid_qualified = False
        if bid_order:
            bid_distance = self._calculate_distance_bps(bid_order.price, mid_price)
            bid_qualified = bid_distance <= self.config.max_distance_bps

        # Check ask order qualification
        ask_qualified = False
        if ask_order:
            ask_distance = self._calculate_distance_bps(ask_order.price, mid_price)
            ask_qualified = ask_distance <= self.config.max_distance_bps

        # Qualify if at least one order is within range
        return bid_qualified or ask_qualified

    def _record_tick(self, mid_price: Decimal, is_qualified: bool):
        """Record tick for metrics."""
        current_uptime = self.state.get_rolling_uptime()
        self.state.record_tick(is_qualified, current_uptime)

    def get_state(self) -> SimulationState:
        """Get current simulation state."""
        return self.state

    def get_metrics(self) -> Dict:
        """Get current metrics as dict."""
        return self.state.metrics.to_dict()

    def get_status(self) -> Dict:
        """Get full status for API response."""
        return {
            'param_set_id': self.param_set.id,
            'param_set_name': self.param_set.name,
            'running': self._running,
            'paused_for_volatility': self._paused_for_volatility,
            'config': {
                'order_distance_bps': self.config.order_distance_bps,
                'cancel_distance_bps': self.config.cancel_distance_bps,
                'rebalance_distance_bps': self.config.rebalance_distance_bps,
                'queue_position_limit': self.config.queue_position_limit,
            },
            'state': self.state.to_dict()
        }
