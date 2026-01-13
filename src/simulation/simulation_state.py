"""
Simulation State

Isolated state management for each parameter set simulation.
Tracks simulated orders, positions, and metrics without affecting real trading.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Deque
from decimal import Decimal
from datetime import datetime
from collections import deque
from threading import Lock


@dataclass
class SimulatedOrder:
    """A simulated order (not actually placed)."""
    order_id: str
    side: str  # "buy" or "sell"
    price: Decimal
    qty: Decimal
    created_at: datetime = field(default_factory=datetime.now)
    distance_bps: float = 0.0  # Distance from mid price


@dataclass
class SimulatedFill:
    """A simulated fill event."""
    order_id: str
    side: str
    fill_price: Decimal
    fill_qty: Decimal
    spread_captured_bps: float
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class SimulationMetrics:
    """
    Metrics collected during simulation.

    StandX Maker Points tiers (by order distance from mid):
    - Boosted (0-10 bps): 100% points
    - Standard (10-30 bps): 50% points
    - Basic (30-100 bps): 10% points
    - No points (>100 bps): 0% points
    """
    # Uptime tracking
    total_ticks: int = 0

    # Tier tracking by order distance (StandX rules)
    boosted_ticks: int = 0   # 0-10 bps: 100% points
    standard_ticks: int = 0  # 10-30 bps: 50% points
    basic_ticks: int = 0     # 30-100 bps: 10% points
    no_points_ticks: int = 0 # >100 bps: 0% points

    # Simulated trading
    simulated_fills: int = 0
    simulated_pnl_usd: Decimal = Decimal("0")
    total_spread_captured_bps: float = 0.0

    # Order behavior
    orders_placed: int = 0
    orders_cancelled: int = 0
    cancel_by_distance: int = 0
    cancel_by_queue: int = 0
    rebalance_count: int = 0
    volatility_pauses: int = 0

    @property
    def qualified_ticks(self) -> int:
        """Ticks earning any points (within 100 bps)."""
        return self.boosted_ticks + self.standard_ticks + self.basic_ticks

    @property
    def uptime_percentage(self) -> float:
        """Percentage of time earning any points."""
        if self.total_ticks == 0:
            return 0.0
        return (self.qualified_ticks / self.total_ticks) * 100

    @property
    def avg_spread_captured_bps(self) -> float:
        if self.simulated_fills == 0:
            return 0.0
        return self.total_spread_captured_bps / self.simulated_fills

    @property
    def boosted_time_pct(self) -> float:
        """Percentage at 0-10 bps (100% points)."""
        if self.total_ticks == 0:
            return 0.0
        return (self.boosted_ticks / self.total_ticks) * 100

    @property
    def standard_time_pct(self) -> float:
        """Percentage at 10-30 bps (50% points)."""
        if self.total_ticks == 0:
            return 0.0
        return (self.standard_ticks / self.total_ticks) * 100

    @property
    def basic_time_pct(self) -> float:
        """Percentage at 30-100 bps (10% points)."""
        if self.total_ticks == 0:
            return 0.0
        return (self.basic_ticks / self.total_ticks) * 100

    @property
    def effective_points_pct(self) -> float:
        """
        Weighted effective points percentage.
        Boosted=100%, Standard=50%, Basic=10%
        """
        if self.total_ticks == 0:
            return 0.0
        weighted = (
            self.boosted_ticks * 1.0 +
            self.standard_ticks * 0.5 +
            self.basic_ticks * 0.1
        )
        return (weighted / self.total_ticks) * 100

    def to_dict(self) -> Dict:
        return {
            'uptime_percentage': round(self.uptime_percentage, 2),
            'qualified_ticks': self.qualified_ticks,
            'total_ticks': self.total_ticks,
            'boosted_ticks': self.boosted_ticks,
            'standard_ticks': self.standard_ticks,
            'basic_ticks': self.basic_ticks,
            'boosted_time_pct': round(self.boosted_time_pct, 2),
            'standard_time_pct': round(self.standard_time_pct, 2),
            'basic_time_pct': round(self.basic_time_pct, 2),
            'effective_points_pct': round(self.effective_points_pct, 2),
            'simulated_fills': self.simulated_fills,
            'simulated_pnl_usd': float(self.simulated_pnl_usd),
            'avg_spread_captured_bps': round(self.avg_spread_captured_bps, 2),
            'orders_placed': self.orders_placed,
            'orders_cancelled': self.orders_cancelled,
            'cancel_by_distance': self.cancel_by_distance,
            'cancel_by_queue': self.cancel_by_queue,
            'rebalance_count': self.rebalance_count,
            'volatility_pauses': self.volatility_pauses,
        }


class SimulationState:
    """
    Isolated state for each parameter set simulation.
    Thread-safe and does NOT share state with real trading.
    """

    def __init__(self, param_set_id: str, volatility_window_sec: int = 5):
        self.param_set_id = param_set_id
        self.volatility_window_sec = volatility_window_sec

        # Simulated orders
        self._bid_order: Optional[SimulatedOrder] = None
        self._ask_order: Optional[SimulatedOrder] = None

        # Simulated position
        self._position: Decimal = Decimal("0")

        # Price history for volatility calculation
        self._price_history: Deque[tuple] = deque(maxlen=1000)  # (timestamp, price)

        # Fill history
        self._fills: List[SimulatedFill] = []

        # Metrics
        self.metrics = SimulationMetrics()

        # Thread safety
        self._lock = Lock()

        # Running uptime calculation (rolling window)
        self._uptime_window: Deque[bool] = deque(maxlen=100)

        # Timestamps
        self.started_at: Optional[datetime] = None
        self.last_tick_at: Optional[datetime] = None

    def start(self):
        """Start simulation timing."""
        with self._lock:
            self.started_at = datetime.now()
            self.last_tick_at = datetime.now()

    def update_price(self, price: Decimal, timestamp: datetime = None):
        """Update price history."""
        with self._lock:
            if timestamp is None:
                timestamp = datetime.now()
            self._price_history.append((timestamp, price))
            self.last_tick_at = timestamp

    def get_volatility_bps(self) -> float:
        """Calculate volatility over the window period."""
        with self._lock:
            if len(self._price_history) < 2:
                return 0.0

            now = datetime.now()
            window_prices = []

            for ts, price in self._price_history:
                age = (now - ts).total_seconds()
                if age <= self.volatility_window_sec:
                    window_prices.append(float(price))

            if len(window_prices) < 2:
                return 0.0

            min_p = min(window_prices)
            max_p = max(window_prices)
            avg_p = sum(window_prices) / len(window_prices)

            if avg_p == 0:
                return 0.0

            return ((max_p - min_p) / avg_p) * 10000

    def set_bid_order(self, order: SimulatedOrder):
        """Set simulated bid order."""
        with self._lock:
            self._bid_order = order
            self.metrics.orders_placed += 1

    def set_ask_order(self, order: SimulatedOrder):
        """Set simulated ask order."""
        with self._lock:
            self._ask_order = order
            self.metrics.orders_placed += 1

    def get_bid_order(self) -> Optional[SimulatedOrder]:
        """Get current simulated bid order."""
        with self._lock:
            return self._bid_order

    def get_ask_order(self) -> Optional[SimulatedOrder]:
        """Get current simulated ask order."""
        with self._lock:
            return self._ask_order

    def has_orders(self) -> bool:
        """Check if we have any simulated orders."""
        with self._lock:
            return self._bid_order is not None or self._ask_order is not None

    def cancel_bid_order(self, reason: str = ""):
        """Cancel simulated bid order."""
        with self._lock:
            if self._bid_order is not None:
                self._bid_order = None
                self.metrics.orders_cancelled += 1
                if reason == "distance":
                    self.metrics.cancel_by_distance += 1
                elif reason == "queue":
                    self.metrics.cancel_by_queue += 1

    def cancel_ask_order(self, reason: str = ""):
        """Cancel simulated ask order."""
        with self._lock:
            if self._ask_order is not None:
                self._ask_order = None
                self.metrics.orders_cancelled += 1
                if reason == "distance":
                    self.metrics.cancel_by_distance += 1
                elif reason == "queue":
                    self.metrics.cancel_by_queue += 1

    def cancel_all_orders(self, reason: str = ""):
        """Cancel all simulated orders."""
        self.cancel_bid_order(reason)
        self.cancel_ask_order(reason)

    def record_rebalance(self):
        """Record a rebalance event."""
        with self._lock:
            self.metrics.rebalance_count += 1

    def record_volatility_pause(self):
        """Record a volatility pause event."""
        with self._lock:
            self.metrics.volatility_pauses += 1

    def record_tick(self, order_distance_bps: float):
        """
        Record a simulation tick with order distance for tier tracking.

        StandX Maker Points tiers:
        - 0-10 bps: 100% points (Boosted)
        - 10-30 bps: 50% points (Standard)
        - 30-100 bps: 10% points (Basic)
        - >100 bps: 0% points

        Args:
            order_distance_bps: Distance of order from mid price in basis points.
                               Use -1 or None if no order is active.
        """
        with self._lock:
            self.metrics.total_ticks += 1

            # Determine tier based on order distance
            if order_distance_bps is None or order_distance_bps < 0:
                # No active order
                self.metrics.no_points_ticks += 1
                is_qualified = False
            elif order_distance_bps <= 10:
                self.metrics.boosted_ticks += 1
                is_qualified = True
            elif order_distance_bps <= 30:
                self.metrics.standard_ticks += 1
                is_qualified = True
            elif order_distance_bps <= 100:
                self.metrics.basic_ticks += 1
                is_qualified = True
            else:
                self.metrics.no_points_ticks += 1
                is_qualified = False

            # Update uptime window for rolling calculation
            self._uptime_window.append(is_qualified)

    def simulate_fill(
        self,
        side: str,
        fill_price: Decimal,
        fill_qty: Decimal,
        spread_bps: float
    ):
        """
        Record a simulated fill.

        Args:
            side: "buy" or "sell"
            fill_price: Price at which fill occurred
            fill_qty: Quantity filled
            spread_bps: Spread captured in basis points
        """
        with self._lock:
            fill = SimulatedFill(
                order_id=f"sim_{self.param_set_id}_{self.metrics.simulated_fills}",
                side=side,
                fill_price=fill_price,
                fill_qty=fill_qty,
                spread_captured_bps=spread_bps
            )
            self._fills.append(fill)

            self.metrics.simulated_fills += 1
            self.metrics.total_spread_captured_bps += spread_bps

            # Calculate PnL (spread capture)
            pnl = (Decimal(str(spread_bps)) / Decimal("10000")) * fill_price * fill_qty
            self.metrics.simulated_pnl_usd += pnl

            # Update position
            if side == "buy":
                self._position += fill_qty
            else:
                self._position -= fill_qty

    def get_position(self) -> Decimal:
        """Get current simulated position."""
        with self._lock:
            return self._position

    def get_rolling_uptime(self) -> float:
        """Get rolling uptime percentage from recent window."""
        with self._lock:
            if len(self._uptime_window) == 0:
                return 0.0
            qualified = sum(1 for q in self._uptime_window if q)
            return (qualified / len(self._uptime_window)) * 100

    def get_metrics(self) -> SimulationMetrics:
        """Get current simulation metrics."""
        with self._lock:
            return self.metrics

    def get_fills(self) -> List[SimulatedFill]:
        """Get all simulated fills."""
        with self._lock:
            return self._fills.copy()

    def get_runtime_seconds(self) -> float:
        """Get simulation runtime in seconds."""
        if self.started_at is None:
            return 0.0
        return (datetime.now() - self.started_at).total_seconds()

    def to_dict(self) -> Dict:
        """Export state as dict for API response."""
        with self._lock:
            return {
                'param_set_id': self.param_set_id,
                'runtime_seconds': self.get_runtime_seconds(),
                'position': float(self._position),
                'has_bid': self._bid_order is not None,
                'has_ask': self._ask_order is not None,
                'bid_price': float(self._bid_order.price) if self._bid_order else None,
                'ask_price': float(self._ask_order.price) if self._ask_order else None,
                'rolling_uptime': round(self.get_rolling_uptime(), 2),
                'metrics': self.metrics.to_dict()
            }
