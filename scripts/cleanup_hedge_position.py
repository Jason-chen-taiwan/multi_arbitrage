#!/usr/bin/env python3
"""
清理對沖帳戶測試倉位

使用方式：
    python scripts/cleanup_hedge_position.py [--confirm]
"""

import argparse
import asyncio
import os
import sys
from decimal import Decimal
from pathlib import Path

# 添加項目根目錄到 path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("cleanup")


async def main(auto_confirm: bool = False):
    from src.adapters.factory import create_adapter

    hedge_token = os.getenv('STANDX_HEDGE_API_TOKEN')
    hedge_key = os.getenv('STANDX_HEDGE_ED25519_PRIVATE_KEY')

    if not hedge_token or not hedge_key:
        print("❌ 未配置對沖帳戶")
        return

    # 連接對沖帳戶
    config = {
        'exchange_name': 'standx',
        'api_token': hedge_token,
        'ed25519_private_key': hedge_key,
        'testnet': False,
    }
    adapter = create_adapter(config)
    await adapter.connect()
    print("✅ 對沖帳戶連接成功")

    # 查詢倉位
    symbol = "BTC-USD"
    positions = await adapter.get_positions(symbol)

    current_pos = Decimal("0")
    pos_side = None
    for pos in positions:
        if pos.symbol == symbol:
            current_pos = Decimal(str(pos.size))
            pos_side = pos.side
            if pos_side == "short":
                current_pos = -current_pos
            break

    if current_pos == 0:
        print("✅ 對沖帳戶無倉位，無需清理")
        return

    print(f"\n📊 當前對沖帳戶倉位: {current_pos} BTC ({pos_side})")

    # 平倉方向
    close_side = "buy" if current_pos < 0 else "sell"
    close_qty = abs(current_pos)

    print(f"   需要執行: {close_side} {close_qty} BTC 來平倉")

    if not auto_confirm:
        confirm = input("\n⚠️  確認執行平倉？(yes/no): ")
        if confirm.lower() != 'yes':
            print("已取消")
            return

    print("\n🚀 執行平倉...")
    order = await adapter.place_order(
        symbol=symbol,
        side=close_side,
        order_type="market",
        quantity=close_qty,
    )

    if order:
        print(f"✅ 平倉成功！訂單 ID: {getattr(order, 'order_id', 'N/A')}")
    else:
        print("❌ 平倉失敗")

    # 確認最終倉位
    await asyncio.sleep(1)
    positions = await adapter.get_positions(symbol)
    final_pos = Decimal("0")
    for pos in positions:
        if pos.symbol == symbol:
            final_pos = Decimal(str(pos.size))
            if pos.side == "short":
                final_pos = -final_pos
            break

    print(f"\n📊 最終對沖帳戶倉位: {final_pos} BTC")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="清理對沖帳戶測試倉位")
    parser.add_argument("--confirm", action="store_true", help="跳過確認提示")
    args = parser.parse_args()

    try:
        asyncio.run(main(auto_confirm=args.confirm))
    except KeyboardInterrupt:
        print("\n已中斷")
    except Exception as e:
        logger.exception(f"失敗: {e}")
