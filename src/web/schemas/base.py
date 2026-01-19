"""
Base schemas for API responses.

Provides a consistent response format across all endpoints.
"""

from datetime import datetime
from typing import TypeVar, Generic, Optional, Any
from pydantic import BaseModel, Field

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    """
    Standard API response wrapper.

    All API endpoints should return this format for consistency.
    """
    success: bool = Field(..., description="Whether the operation succeeded")
    data: Optional[T] = Field(default=None, description="Response data if successful")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    timestamp: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="Response timestamp in ISO format"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "data": {"key": "value"},
                    "error": None,
                    "timestamp": "2026-01-19T10:30:00.000000"
                }
            ]
        }
    }


class SuccessResponse(BaseModel):
    """Simple success response without data."""
    success: bool = Field(default=True, description="Always true for success")
    message: Optional[str] = Field(default=None, description="Optional success message")


class ErrorResponse(BaseModel):
    """Error response schema."""
    success: bool = Field(default=False, description="Always false for errors")
    error: str = Field(..., description="Error message describing what went wrong")
    details: Optional[dict[str, Any]] = Field(default=None, description="Additional error details")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": False,
                    "error": "StandX 未連接",
                    "details": None
                }
            ]
        }
    }
