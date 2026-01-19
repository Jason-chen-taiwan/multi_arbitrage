"""
StandX Referral Code Manager

首次使用時提示用戶是否使用邀請碼，雙方都可獲得 5% 積分加成。
"""

import os
import asyncio
import logging
from pathlib import Path
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# 邀請碼
REFERRAL_CODE = "Jasoncrypto"
REFERRAL_URL = f"https://standx.com/referral?code={REFERRAL_CODE}"

# 標記文件路徑（記錄是否已處理過邀請碼）
REFERRAL_MARKER_FILE = Path(__file__).parent.parent.parent / ".referral_checked"


async def check_referral_status(session: aiohttp.ClientSession, auth_headers: dict) -> Optional[str]:
    """
    檢查用戶是否已被邀請

    Returns:
        - None: 尚未被邀請
        - str: 已被邀請的時間 (refer_at)
    """
    try:
        url = "https://api.standx.com/v1/offchain/perps-campaign/points"
        async with session.get(url, headers=auth_headers, timeout=10) as resp:
            if resp.status == 200:
                data = await resp.json()
                refer_at = data.get("refer_at")
                if refer_at:
                    logger.info(f"[Referral] Already referred at: {refer_at}")
                    return refer_at
                return None
            else:
                logger.warning(f"[Referral] Check status failed: {resp.status}")
                return None
    except Exception as e:
        logger.warning(f"[Referral] Check status error: {e}")
        return None


async def apply_referral_code(
    session: aiohttp.ClientSession,
    auth_headers: dict,
    code: str = REFERRAL_CODE
) -> bool:
    """
    應用邀請碼

    Returns:
        True if successful, False otherwise
    """
    try:
        url = "https://api.standx.com/v1/offchain/referral"
        payload = {"code": code}

        async with session.post(url, json=payload, headers=auth_headers, timeout=10) as resp:
            if resp.status == 200:
                logger.info(f"[Referral] Successfully applied code: {code}")
                return True
            else:
                text = await resp.text()
                logger.warning(f"[Referral] Apply failed: {resp.status} - {text}")
                return False
    except Exception as e:
        logger.error(f"[Referral] Apply error: {e}")
        return False


def is_referral_checked() -> bool:
    """檢查是否已處理過邀請碼（不再詢問）"""
    return REFERRAL_MARKER_FILE.exists()


def mark_referral_checked():
    """標記已處理過邀請碼"""
    try:
        REFERRAL_MARKER_FILE.touch()
        logger.info("[Referral] Marked as checked")
    except Exception as e:
        logger.warning(f"[Referral] Failed to mark: {e}")


def get_referral_info() -> dict:
    """
    獲取邀請碼相關信息（供 API 使用）

    Returns:
        {
            "code": "Jasoncrypto",
            "url": "https://standx.com/referral?code=Jasoncrypto",
            "checked": bool,
            "benefit": "雙方都可獲得 5% 積分加成"
        }
    """
    return {
        "code": REFERRAL_CODE,
        "url": REFERRAL_URL,
        "checked": is_referral_checked(),
        "benefit": "雙方都可獲得 5% 積分加成"
    }
