"""
Schemas for simulation API endpoints.

Covers:
- GET/POST/PUT/DELETE /api/simulation/param-sets
- POST /api/simulation/start
- POST /api/simulation/stop
- POST /api/simulation/force-stop
- GET /api/simulation/status
- GET /api/simulation/comparison
- GET /api/simulation/runs
- GET /api/simulation/runs/{run_id}
- GET /api/simulation/runs/{run_id}/comparison
- DELETE /api/simulation/runs/{run_id}
"""

from typing import Optional, Any
from pydantic import BaseModel, Field


class ParamSetOverrides(BaseModel):
    """Parameter overrides for a simulation parameter set."""
    quote: Optional[dict[str, Any]] = Field(default=None, description="Quote config overrides")
    position: Optional[dict[str, Any]] = Field(default=None, description="Position config overrides")
    volatility: Optional[dict[str, Any]] = Field(default=None, description="Volatility config overrides")


class ParamSetItem(BaseModel):
    """A single parameter set item."""
    id: str = Field(..., description="Unique parameter set ID")
    name: str = Field(..., description="Display name")
    description: Optional[str] = Field(default=None, description="Description of this parameter set")
    overrides: Optional[ParamSetOverrides] = Field(default=None, description="Configuration overrides")


class ParamSetResponse(BaseModel):
    """Response for GET /api/simulation/param-sets."""
    param_sets: list[ParamSetItem] = Field(default_factory=list, description="List of parameter sets")


class ParamSetCreateRequest(BaseModel):
    """Request body for POST /api/simulation/param-sets."""
    id: Optional[str] = Field(default=None, description="Optional ID (auto-generated if not provided)")
    name: str = Field(..., description="Display name")
    description: Optional[str] = Field(default=None, description="Description")
    overrides: Optional[ParamSetOverrides] = Field(default=None, description="Configuration overrides")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "Conservative",
                    "description": "Lower risk settings",
                    "overrides": {
                        "quote": {
                            "order_distance_bps": 12
                        }
                    }
                }
            ]
        }
    }


class ParamSetUpdateRequest(ParamSetCreateRequest):
    """Request body for PUT /api/simulation/param-sets/{id}."""
    pass


class ParamSetCreateResponse(BaseModel):
    """Response for POST /api/simulation/param-sets."""
    success: bool = Field(..., description="Whether creation succeeded")
    param_set: Optional[ParamSetItem] = Field(default=None, description="Created parameter set")
    error: Optional[str] = Field(default=None, description="Error message if failed")


class SimulationStartRequest(BaseModel):
    """Request body for POST /api/simulation/start."""
    param_set_ids: list[str] = Field(..., description="List of parameter set IDs to simulate")
    duration_minutes: int = Field(default=60, description="Simulation duration in minutes")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "param_set_ids": ["conservative", "aggressive"],
                    "duration_minutes": 30
                }
            ]
        }
    }


class SimulationStartResponse(BaseModel):
    """Response for POST /api/simulation/start."""
    success: bool = Field(..., description="Whether simulation started successfully")
    run_id: Optional[str] = Field(default=None, description="Unique run ID")
    param_set_ids: Optional[list[str]] = Field(default=None, description="Parameter sets being simulated")
    duration_minutes: Optional[int] = Field(default=None, description="Simulation duration")
    error: Optional[str] = Field(default=None, description="Error message if failed")


class ExecutorStatus(BaseModel):
    """Status of a single parameter set executor during simulation."""
    param_set_id: str = Field(..., description="Parameter set ID")
    param_set_name: str = Field(..., description="Parameter set name")
    total_pnl: float = Field(default=0.0, description="Total PnL in USD")
    uptime_percentage: float = Field(default=0.0, description="Uptime percentage")
    fill_count: int = Field(default=0, description="Number of fills")
    effective_points: float = Field(default=0.0, description="Effective uptime points")


class SimulationStatusResponse(BaseModel):
    """Response for GET /api/simulation/status."""
    running: bool = Field(..., description="Whether simulation is running")
    run_id: Optional[str] = Field(default=None, description="Current run ID")
    elapsed_seconds: Optional[float] = Field(default=None, description="Elapsed time in seconds")
    remaining_seconds: Optional[float] = Field(default=None, description="Remaining time in seconds")
    executors: Optional[list[ExecutorStatus]] = Field(default=None, description="Status of each executor")
    message: Optional[str] = Field(default=None, description="Status message")
    timeout: Optional[bool] = Field(default=None, description="Whether status fetch timed out")
    error: Optional[str] = Field(default=None, description="Error message if any")


class ComparisonItem(BaseModel):
    """A single comparison table row."""
    param_set_id: str = Field(..., description="Parameter set ID")
    param_set_name: str = Field(..., description="Parameter set name")
    total_pnl: float = Field(default=0.0, description="Total PnL in USD")
    uptime_percentage: float = Field(default=0.0, description="Uptime percentage")
    fill_count: int = Field(default=0, description="Number of fills")
    effective_points: float = Field(default=0.0, description="Effective uptime points")
    tier_breakdown: Optional[dict[str, float]] = Field(default=None, description="Time by tier")


class SimulationComparisonResponse(BaseModel):
    """Response for GET /api/simulation/comparison."""
    comparison: list[ComparisonItem] = Field(default_factory=list, description="Comparison data")


class SimulationRunSummary(BaseModel):
    """Summary of a simulation run."""
    run_id: str = Field(..., description="Run ID")
    started_at: str = Field(..., description="Start time ISO format")
    ended_at: Optional[str] = Field(default=None, description="End time ISO format")
    duration_seconds: Optional[float] = Field(default=None, description="Duration in seconds")
    param_set_count: int = Field(default=0, description="Number of parameter sets tested")


class SimulationRunListResponse(BaseModel):
    """Response for GET /api/simulation/runs."""
    runs: list[SimulationRunSummary] = Field(default_factory=list, description="List of simulation runs")


class SimulationRunDetailResponse(BaseModel):
    """Response for GET /api/simulation/runs/{run_id}."""
    run_id: str = Field(..., description="Run ID")
    started_at: str = Field(..., description="Start time")
    ended_at: Optional[str] = Field(default=None, description="End time")
    duration_seconds: Optional[float] = Field(default=None, description="Duration")
    results: list[dict[str, Any]] = Field(default_factory=list, description="Results per parameter set")


class Recommendation(BaseModel):
    """Recommended parameter set."""
    param_set_id: str = Field(..., description="Recommended parameter set ID")
    param_set_name: str = Field(..., description="Parameter set name")
    reason: str = Field(..., description="Reason for recommendation")
    score: float = Field(..., description="Recommendation score")


class ComparisonTableResponse(BaseModel):
    """Response for GET /api/simulation/runs/{run_id}/comparison."""
    comparison_table: list[ComparisonItem] = Field(default_factory=list, description="Comparison table")
    recommendation: Optional[Recommendation] = Field(default=None, description="Recommended parameter set")
