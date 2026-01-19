"""
邀請碼 API 路由

包含:
- GET /api/referral/info - 獲取邀請碼信息
- GET /api/referral/status - 檢查用戶邀請狀態
- POST /api/referral/apply - 應用邀請碼
- POST /api/referral/skip - 跳過（不再詢問）
"""

import aiohttp
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.utils.referral import (
    REFERRAL_CODE,
    get_referral_info,
    is_referral_checked,
    mark_referral_checked,
    check_referral_status,
    apply_referral_code,
)


router = APIRouter(prefix="/api/referral", tags=["referral"])


def register_referral_routes(app, dependencies):
    """
    註冊邀請碼相關路由

    Args:
        app: FastAPI 應用實例
        dependencies: 依賴項字典
    """
    adapters_getter = dependencies['adapters_getter']
    logger = dependencies.get('logger')

    @router.get("/info")
    async def get_info():
        """獲取邀請碼信息"""
        return JSONResponse(get_referral_info())

    @router.get("/status")
    async def get_status():
        """
        檢查用戶邀請狀態

        Returns:
            {
                "needs_prompt": bool,  # 是否需要彈窗詢問
                "already_referred": bool,  # 是否已被邀請
                "refer_at": str or null  # 被邀請時間
            }
        """
        # 如果已經處理過，不再詢問
        if is_referral_checked():
            return JSONResponse({
                "needs_prompt": False,
                "already_referred": None,  # 未知
                "refer_at": None
            })

        # 嘗試檢查 StandX 邀請狀態
        adapters = adapters_getter()
        standx = adapters.get('STANDX')

        if not standx:
            return JSONResponse({
                "needs_prompt": False,
                "already_referred": None,
                "refer_at": None,
                "error": "StandX not connected"
            })

        try:
            # 使用 StandX adapter 的 session 和認證
            auth_headers = standx.auth.get_auth_headers()
            refer_at = await check_referral_status(standx.session, auth_headers)

            if refer_at:
                # 已被邀請，標記並不再詢問
                mark_referral_checked()
                return JSONResponse({
                    "needs_prompt": False,
                    "already_referred": True,
                    "refer_at": refer_at
                })
            else:
                # 尚未被邀請，需要彈窗詢問
                return JSONResponse({
                    "needs_prompt": True,
                    "already_referred": False,
                    "refer_at": None
                })
        except Exception as e:
            if logger:
                logger.warning(f"[Referral] Status check error: {e}")
            return JSONResponse({
                "needs_prompt": False,
                "already_referred": None,
                "refer_at": None,
                "error": str(e)
            })

    @router.post("/apply")
    async def apply_code(request: Request):
        """
        應用邀請碼

        Request body (optional):
            {"code": "custom_code"}  # 默認使用 Jasoncrypto
        """
        adapters = adapters_getter()
        standx = adapters.get('STANDX')

        if not standx:
            return JSONResponse({
                "success": False,
                "error": "StandX not connected"
            })

        try:
            # 可選的自定義邀請碼
            data = await request.json() if request.headers.get('content-type') == 'application/json' else {}
            code = data.get('code', REFERRAL_CODE)

            auth_headers = standx.auth.get_auth_headers()
            success = await apply_referral_code(standx.session, auth_headers, code)

            # 無論成功失敗，都標記已處理
            mark_referral_checked()

            if success:
                return JSONResponse({
                    "success": True,
                    "message": f"已成功應用邀請碼 {code}，您將獲得 5% 積分加成！"
                })
            else:
                return JSONResponse({
                    "success": False,
                    "error": "應用邀請碼失敗，可能已被其他人邀請"
                })
        except Exception as e:
            if logger:
                logger.error(f"[Referral] Apply error: {e}")
            return JSONResponse({
                "success": False,
                "error": str(e)
            })

    @router.post("/skip")
    async def skip_referral():
        """跳過邀請碼（不再詢問）"""
        mark_referral_checked()
        return JSONResponse({
            "success": True,
            "message": "已跳過，之後不會再詢問"
        })

    # 註冊路由
    app.include_router(router)
