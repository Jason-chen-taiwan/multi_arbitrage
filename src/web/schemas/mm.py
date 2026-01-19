"""
Schemas for market maker API endpoints.

Covers:
- POST /api/mm/start
- POST /api/mm/stop
- GET /api/mm/status
- GET /api/mm/positions
- GET /api/mm/config
- POST /api/mm/config
- POST /api/mm/config/reload
"""

from typing import Optional, Any
from pydantic import BaseModel, Field


class MMStartRequest(BaseModel):
    """Request body for POST /api/mm/start."""
    dry_run: bool = Field(default=True, description="Whether to run in dry-run mode (no real orders)")
    order_size: Optional[float] = Field(default=None, description="Order size in BTC (uses config default if not set)")
    order_distance: Optional[int] = Field(default=None, description="Order distance in basis points (uses config default if not set)")


class QuoteConfig(BaseModel):
    """Quote-related configuration."""
    order_distance_bps: int = Field(default=8, description="Distance from mid price in basis points")
    cancel_distance_bps: int = Field(default=3, description="Cancel threshold distance in basis points")
    rebalance_distance_bps: int = Field(default=12, description="Rebalance threshold distance in basis points")
    queue_position_limit: Optional[int] = Field(default=None, description="Maximum queue position limit")


class PositionConfig(BaseModel):
    """Position-related configuration."""
    order_size_btc: float = Field(default=0.001, description="Order size in BTC")
    max_position_btc: float = Field(default=0.01, description="Maximum position in BTC")


class VolatilityConfig(BaseModel):
    """Volatility-related configuration."""
    window_sec: int = Field(default=2, description="Volatility calculation window in seconds")
    threshold_bps: float = Field(default=5.0, description="Volatility threshold to pause quoting in basis points")
    resume_threshold_bps: float = Field(default=4.0, description="Volatility threshold to resume quoting in basis points")
    stable_seconds: float = Field(default=2.0, description="Seconds of stability required before resuming")


class ExecutionConfig(BaseModel):
    """Execution-related configuration."""
    dry_run: bool = Field(default=True, description="Whether to run in dry-run mode")


class MMConfigResponse(BaseModel):
    """Response for GET /api/mm/config."""
    quote: QuoteConfig = Field(default_factory=QuoteConfig, description="Quote configuration")
    position: PositionConfig = Field(default_factory=PositionConfig, description="Position configuration")
    volatility: VolatilityConfig = Field(default_factory=VolatilityConfig, description="Volatility configuration")
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig, description="Execution configuration")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "quote": {
                        "order_distance_bps": 8,
                        "cancel_distance_bps": 3,
                        "rebalance_distance_bps": 12,
                        "queue_position_limit": None
                    },
                    "position": {
                        "order_size_btc": 0.001,
                        "max_position_btc": 0.01
                    },
                    "volatility": {
                        "window_sec": 2,
                        "threshold_bps": 5.0,
                        "resume_threshold_bps": 4.0,
                        "stable_seconds": 2.0
                    },
                    "execution": {
                        "dry_run": True
                    }
                }
            ]
        }
    }


class MMConfigUpdateRequest(BaseModel):
    """Request body for POST /api/mm/config."""
    quote: Optional[QuoteConfig] = Field(default=None, description="Quote configuration updates")
    position: Optional[PositionConfig] = Field(default=None, description="Position configuration updates")
    volatility: Optional[VolatilityConfig] = Field(default=None, description="Volatility configuration updates")
    execution: Optional[ExecutionConfig] = Field(default=None, description="Execution configuration updates")


class MMStatusResponse(BaseModel):
    """Response for GET /api/mm/status."""
    running: bool = Field(..., description="Whether market maker is running")
    status: str = Field(default="stopped", description="Current status: running, stopped, etc.")
    dry_run: bool = Field(default=True, description="Whether running in dry-run mode")
    order_size_btc: float = Field(default=0.0, description="Current order size in BTC")
    order_distance_bps: int = Field(default=0, description="Current order distance in basis points")
    cancel_distance_bps: int = Field(default=0, description="Current cancel distance in basis points")
    rebalance_distance_bps: int = Field(default=0, description="Current rebalance distance in basis points")
    max_position_btc: float = Field(default=0.0, description="Maximum position in BTC")
    executor: Optional[dict[str, Any]] = Field(default=None, description="Full executor state dictionary")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "running": True,
                    "status": "running",
                    "dry_run": False,
                    "order_size_btc": 0.001,
                    "order_distance_bps": 8,
                    "cancel_distance_bps": 3,
                    "rebalance_distance_bps": 12,
                    "max_position_btc": 0.01,
                    "executor": None
                }
            ]
        }
    }


class ExchangePosition(BaseModel):
    """Position for a single exchange."""
    btc: float = Field(..., description="BTC position")


class MMPositionResponse(BaseModel):
    """Response for GET /api/mm/positions."""
    status: str = Field(..., description="Connection status: connected or disconnected")
    message: Optional[str] = Field(default=None, description="Status message")
    standx: Optional[ExchangePosition] = Field(default=None, description="StandX position")
    grvt: Optional[ExchangePosition] = Field(default=None, description="GRVT position")
    net_btc: Optional[float] = Field(default=None, description="Net BTC position across exchanges")
    is_hedged: Optional[bool] = Field(default=None, description="Whether position is hedged")
    last_sync: Optional[float] = Field(default=None, description="Last position sync timestamp")
    seconds_ago: Optional[float] = Field(default=None, description="Seconds since last sync")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "status": "connected",
                    "message": None,
                    "standx": {"btc": 0.001},
                    "grvt": {"btc": -0.001},
                    "net_btc": 0.0,
                    "is_hedged": True,
                    "last_sync": 1705656000.0,
                    "seconds_ago": 1.5
                }
            ]
        }
    }
