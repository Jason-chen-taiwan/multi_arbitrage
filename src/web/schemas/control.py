"""
Schemas for system control API endpoints.

Covers:
- POST /api/system/reinit
- POST /api/control/auto-execute
- POST /api/control/live-trade
"""

from typing import Optional, Any
from pydantic import BaseModel, Field


class AutoExecuteRequest(BaseModel):
    """Request body for POST /api/control/auto-execute."""
    enabled: bool = Field(..., description="Whether to enable auto-execution")


class LiveTradeRequest(BaseModel):
    """Request body for POST /api/control/live-trade."""
    enabled: bool = Field(..., description="Whether to enable live trading (disables dry-run)")


class ReinitResponse(BaseModel):
    """Response for POST /api/system/reinit."""
    success: bool = Field(..., description="Whether reinitialization succeeded")
    message: Optional[str] = Field(default=None, description="Status message")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    connected: Optional[list[str]] = Field(default=None, description="Successfully connected exchanges")
    failed: Optional[list[str]] = Field(default=None, description="Failed to connect exchanges")
    ready_for_trading: bool = Field(default=False, description="Whether system is ready for trading")
    hedging_available: bool = Field(default=False, description="Whether hedging is available")
    details: Optional[dict[str, Any]] = Field(default=None, description="Detailed connection results")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "message": "已連接 2 個交易所: STANDX, GRVT",
                    "error": None,
                    "connected": ["STANDX", "GRVT"],
                    "failed": [],
                    "ready_for_trading": True,
                    "hedging_available": True,
                    "details": {
                        "STANDX": {"success": True, "error": None},
                        "GRVT": {"success": True, "error": None}
                    }
                }
            ]
        }
    }
