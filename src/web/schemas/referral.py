"""
Schemas for referral API endpoints.

Covers:
- GET /api/referral/info
- GET /api/referral/status
- POST /api/referral/apply
- POST /api/referral/skip
"""

from typing import Optional
from pydantic import BaseModel, Field


class ReferralInfoResponse(BaseModel):
    """Response for GET /api/referral/info."""
    code: str = Field(..., description="Referral code")
    bonus_percentage: float = Field(default=5.0, description="Bonus percentage for using referral")
    description: Optional[str] = Field(default=None, description="Description of the referral program")


class ReferralStatusResponse(BaseModel):
    """Response for GET /api/referral/status."""
    needs_prompt: bool = Field(..., description="Whether to show referral prompt to user")
    already_referred: Optional[bool] = Field(default=None, description="Whether user is already referred")
    refer_at: Optional[str] = Field(default=None, description="When user was referred (ISO timestamp)")
    error: Optional[str] = Field(default=None, description="Error message if status check failed")


class ReferralApplyRequest(BaseModel):
    """Request body for POST /api/referral/apply."""
    code: Optional[str] = Field(default=None, description="Custom referral code (uses default if not provided)")


class ReferralApplyResponse(BaseModel):
    """Response for POST /api/referral/apply."""
    success: bool = Field(..., description="Whether referral was applied successfully")
    message: Optional[str] = Field(default=None, description="Success message")
    error: Optional[str] = Field(default=None, description="Error message if failed")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "message": "已成功應用邀請碼 Jasoncrypto，您將獲得 5% 積分加成！",
                    "error": None
                }
            ]
        }
    }


class ReferralSkipResponse(BaseModel):
    """Response for POST /api/referral/skip."""
    success: bool = Field(default=True, description="Always true")
    message: str = Field(default="已跳過，之後不會再詢問", description="Confirmation message")
