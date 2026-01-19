"""
Pydantic schemas for API request/response validation.

This module provides type-safe schemas for all API endpoints,
enabling OpenAPI documentation and TypeScript type generation.
"""

from .base import APIResponse, ErrorResponse, SuccessResponse
from .config import (
    ExchangeConfig,
    ExchangeListResponse,
    SaveConfigRequest,
    DeleteConfigRequest,
    HealthCheckResponse,
    ExchangeHealthResponse,
    ReconnectResponse,
)
from .control import (
    AutoExecuteRequest,
    LiveTradeRequest,
    ReinitResponse,
)
from .mm import (
    MMStartRequest,
    MMStatusResponse,
    MMPositionResponse,
    MMConfigResponse,
    MMConfigUpdateRequest,
)
from .simulation import (
    ParamSetResponse,
    ParamSetCreateRequest,
    ParamSetUpdateRequest,
    SimulationStartRequest,
    SimulationStartResponse,
    SimulationStatusResponse,
    SimulationComparisonResponse,
    SimulationRunListResponse,
    SimulationRunDetailResponse,
    ComparisonTableResponse,
)
from .referral import (
    ReferralInfoResponse,
    ReferralStatusResponse,
    ReferralApplyRequest,
    ReferralApplyResponse,
)
from .websocket import (
    WebSocketMessage,
    MarketData,
    OrderBookData,
    MMExecutorData,
    PositionData,
    FillHistoryItem,
)

__all__ = [
    # Base
    "APIResponse",
    "ErrorResponse",
    "SuccessResponse",
    # Config
    "ExchangeConfig",
    "ExchangeListResponse",
    "SaveConfigRequest",
    "DeleteConfigRequest",
    "HealthCheckResponse",
    "ExchangeHealthResponse",
    "ReconnectResponse",
    # Control
    "AutoExecuteRequest",
    "LiveTradeRequest",
    "ReinitResponse",
    # MM
    "MMStartRequest",
    "MMStatusResponse",
    "MMPositionResponse",
    "MMConfigResponse",
    "MMConfigUpdateRequest",
    # Simulation
    "ParamSetResponse",
    "ParamSetCreateRequest",
    "ParamSetUpdateRequest",
    "SimulationStartRequest",
    "SimulationStartResponse",
    "SimulationStatusResponse",
    "SimulationComparisonResponse",
    "SimulationRunListResponse",
    "SimulationRunDetailResponse",
    "ComparisonTableResponse",
    # Referral
    "ReferralInfoResponse",
    "ReferralStatusResponse",
    "ReferralApplyRequest",
    "ReferralApplyResponse",
    # WebSocket
    "WebSocketMessage",
    "MarketData",
    "OrderBookData",
    "MMExecutorData",
    "PositionData",
    "FillHistoryItem",
]
