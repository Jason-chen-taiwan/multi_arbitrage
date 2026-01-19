"""
Schemas for configuration API endpoints.

Covers:
- GET /api/config/list
- POST /api/config/save
- POST /api/config/delete
- GET /api/config/health
- GET /api/config/health/{exchange}
- POST /api/config/reconnect
"""

from typing import Optional, Any
from pydantic import BaseModel, Field


class ExchangeCredentials(BaseModel):
    """Exchange API credentials."""
    api_key: Optional[str] = Field(default=None, description="API key")
    api_secret: Optional[str] = Field(default=None, description="API secret")
    passphrase: Optional[str] = Field(default=None, description="API passphrase (for some exchanges)")
    private_key: Optional[str] = Field(default=None, description="Private key (for DEX)")
    address: Optional[str] = Field(default=None, description="Wallet address (for DEX)")


class ExchangeConfig(BaseModel):
    """Single exchange configuration."""
    exchange_name: str = Field(..., description="Exchange identifier (e.g., STANDX, GRVT)")
    exchange_type: str = Field(..., description="Exchange type: cex or dex")
    config: ExchangeCredentials = Field(..., description="Exchange credentials")


class ExchangeListResponse(BaseModel):
    """Response for GET /api/config/list."""
    cex: dict[str, dict[str, Any]] = Field(default_factory=dict, description="CEX configurations")
    dex: dict[str, dict[str, Any]] = Field(default_factory=dict, description="DEX configurations")


class SaveConfigRequest(BaseModel):
    """Request body for POST /api/config/save."""
    exchange_name: str = Field(..., description="Exchange identifier")
    exchange_type: str = Field(..., description="Exchange type: cex or dex")
    config: dict[str, Any] = Field(..., description="Exchange configuration dict")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "exchange_name": "STANDX",
                    "exchange_type": "dex",
                    "config": {
                        "api_key": "your_api_key",
                        "private_key": "your_private_key"
                    }
                }
            ]
        }
    }


class DeleteConfigRequest(BaseModel):
    """Request body for POST /api/config/delete."""
    exchange_name: str = Field(..., description="Exchange identifier to delete")
    exchange_type: str = Field(..., description="Exchange type: cex or dex")


class ExchangeHealthDetail(BaseModel):
    """Health check details for a single exchange."""
    healthy: bool = Field(..., description="Whether the exchange connection is healthy")
    latency_ms: float = Field(default=0, description="Connection latency in milliseconds")
    error: Optional[str] = Field(default=None, description="Error message if unhealthy")
    details: dict[str, Any] = Field(default_factory=dict, description="Additional health details")


class HealthCheckResponse(BaseModel):
    """Response for GET /api/config/health."""
    all_healthy: bool = Field(..., description="Whether all exchanges are healthy")
    ready_for_trading: bool = Field(..., description="Whether system is ready for trading")
    hedging_available: bool = Field(..., description="Whether hedging exchange (GRVT) is available")
    exchanges: dict[str, ExchangeHealthDetail] = Field(
        default_factory=dict,
        description="Health status per exchange"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "all_healthy": True,
                    "ready_for_trading": True,
                    "hedging_available": True,
                    "exchanges": {
                        "STANDX": {
                            "healthy": True,
                            "latency_ms": 45.2,
                            "error": None,
                            "details": {}
                        },
                        "GRVT": {
                            "healthy": True,
                            "latency_ms": 32.1,
                            "error": None,
                            "details": {}
                        }
                    }
                }
            ]
        }
    }


class ExchangeHealthResponse(ExchangeHealthDetail):
    """Response for GET /api/config/health/{exchange}."""
    pass


class ReconnectResult(BaseModel):
    """Result of reconnecting a single exchange."""
    success: bool = Field(..., description="Whether reconnection succeeded")
    error: Optional[str] = Field(default=None, description="Error message if failed")


class ReconnectResponse(BaseModel):
    """Response for POST /api/config/reconnect."""
    success: bool = Field(..., description="Whether all reconnections succeeded")
    results: dict[str, ReconnectResult] = Field(
        default_factory=dict,
        description="Reconnection results per exchange"
    )
    ready_for_trading: bool = Field(default=False, description="Whether system is ready for trading")
    hedging_available: bool = Field(default=False, description="Whether hedging is available")
