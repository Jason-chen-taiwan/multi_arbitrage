"""
Schemas for WebSocket message types.

These schemas define the structure of real-time data
broadcast via WebSocket at /ws endpoint.
"""

from typing import Optional, Any
from pydantic import BaseModel, Field


class PriceData(BaseModel):
    """Price data for a single symbol on an exchange."""
    best_bid: float = Field(..., description="Best bid price")
    best_ask: float = Field(..., description="Best ask price")
    bid_size: Optional[float] = Field(default=None, description="Bid size")
    ask_size: Optional[float] = Field(default=None, description="Ask size")
    spread_pct: Optional[float] = Field(default=None, description="Spread percentage")


class MarketData(BaseModel):
    """Market data from all exchanges."""
    # Exchange name -> Symbol -> PriceData
    # e.g., {"STANDX": {"BTC-USD": {...}}, "GRVT": {"BTC_USDT_Perp": {...}}}
    data: dict[str, dict[str, PriceData]] = Field(
        default_factory=dict,
        description="Market data organized by exchange and symbol"
    )


class OrderBookLevel(BaseModel):
    """Single level in order book."""
    price: float = Field(..., description="Price level")
    size: float = Field(..., description="Size at this price")


class OrderBookSide(BaseModel):
    """One side of the order book."""
    bids: list[list[float]] = Field(default_factory=list, description="Bid levels [[price, size], ...]")
    asks: list[list[float]] = Field(default_factory=list, description="Ask levels [[price, size], ...]")


class OrderBookData(BaseModel):
    """Order book data from exchanges."""
    # Exchange -> Symbol -> OrderBookSide
    # e.g., {"STANDX": {"BTC-USD": {"bids": [...], "asks": [...]}}}
    data: dict[str, dict[str, OrderBookSide]] = Field(
        default_factory=dict,
        description="Order books organized by exchange and symbol"
    )


class ArbitrageOpportunity(BaseModel):
    """A detected arbitrage opportunity."""
    buy_exchange: str = Field(..., description="Exchange to buy on")
    sell_exchange: str = Field(..., description="Exchange to sell on")
    symbol: str = Field(..., description="Trading symbol")
    buy_price: float = Field(..., description="Buy price")
    sell_price: float = Field(..., description="Sell price")
    profit: float = Field(..., description="Profit in USD")
    profit_pct: float = Field(..., description="Profit percentage")
    max_quantity: float = Field(..., description="Maximum executable quantity")


class MonitorStats(BaseModel):
    """Statistics from the monitor."""
    total_updates: int = Field(default=0, description="Total market data updates")
    total_opportunities: int = Field(default=0, description="Total opportunities detected")


class ExecutorStats(BaseModel):
    """Statistics from the arbitrage executor."""
    total_attempts: int = Field(default=0, description="Total execution attempts")
    successful_executions: int = Field(default=0, description="Successful executions")
    total_profit: float = Field(default=0.0, description="Total profit in USD")


class MMStatus(BaseModel):
    """Market maker status."""
    running: bool = Field(default=False, description="Whether MM is running")
    status: str = Field(default="stopped", description="Status string")
    dry_run: bool = Field(default=True, description="Whether in dry-run mode")
    order_size_btc: float = Field(default=0.0, description="Order size")
    order_distance_bps: int = Field(default=0, description="Order distance in bps")


class MMExecutorData(BaseModel):
    """Full market maker executor state."""
    # This is a flexible dict since executor.to_dict() returns varying data
    data: dict[str, Any] = Field(default_factory=dict, description="Full executor state")


class PositionData(BaseModel):
    """Real-time position data."""
    status: str = Field(..., description="Connection status")
    standx: Optional[dict[str, float]] = Field(default=None, description="StandX positions")
    grvt: Optional[dict[str, float]] = Field(default=None, description="GRVT positions")
    net_btc: Optional[float] = Field(default=None, description="Net BTC position")
    is_hedged: Optional[bool] = Field(default=None, description="Whether hedged")
    seconds_ago: Optional[float] = Field(default=None, description="Seconds since last sync")


class FillHistoryItem(BaseModel):
    """A single fill event in history."""
    time: str = Field(..., description="Fill timestamp")
    side: str = Field(..., description="Fill side: buy or sell")
    price: float = Field(..., description="Fill price")
    qty: float = Field(..., description="Fill quantity")
    value: float = Field(..., description="Fill value in USD")


class SystemStatus(BaseModel):
    """System status information."""
    running: bool = Field(default=False, description="Whether system is running")
    dry_run: bool = Field(default=True, description="Whether in dry-run mode")
    started_at: Optional[str] = Field(default=None, description="Start time ISO format")


class WebSocketMessage(BaseModel):
    """
    Complete WebSocket broadcast message structure.

    This is the schema for messages sent every 1 second to connected clients.
    """
    timestamp: str = Field(..., description="Message timestamp ISO format")
    system_status: SystemStatus = Field(default_factory=SystemStatus, description="System status")
    market_data: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Market prices by exchange and symbol"
    )
    orderbooks: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Order books by exchange and symbol"
    )
    opportunities: list[ArbitrageOpportunity] = Field(
        default_factory=list,
        description="Current arbitrage opportunities"
    )
    stats: MonitorStats = Field(default_factory=MonitorStats, description="Monitor statistics")
    executor_stats: ExecutorStats = Field(default_factory=ExecutorStats, description="Executor statistics")
    mm_status: MMStatus = Field(default_factory=MMStatus, description="Market maker status")
    mm_executor: Optional[dict[str, Any]] = Field(default=None, description="Full MM executor state")
    mm_positions: Optional[PositionData] = Field(default=None, description="Real-time positions")
    fill_history: list[FillHistoryItem] = Field(default_factory=list, description="Recent fill history")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "timestamp": "2026-01-19T10:30:00.000000",
                    "system_status": {"running": True, "dry_run": False, "started_at": "2026-01-19T10:00:00"},
                    "market_data": {
                        "STANDX": {"BTC-USD": {"best_bid": 42000.5, "best_ask": 42001.0}}
                    },
                    "orderbooks": {},
                    "opportunities": [],
                    "stats": {"total_updates": 1000, "total_opportunities": 5},
                    "executor_stats": {"total_attempts": 3, "successful_executions": 2, "total_profit": 15.5},
                    "mm_status": {"running": True, "status": "running", "dry_run": False},
                    "mm_executor": None,
                    "mm_positions": {"status": "connected", "standx": {"btc": 0.001}, "grvt": {"btc": -0.001}},
                    "fill_history": []
                }
            ]
        }
    }
