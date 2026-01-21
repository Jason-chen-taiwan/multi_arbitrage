#!/usr/bin/env python3
"""
StandX 對沖測試腳本

測試流程：
1. 連接主帳戶和對沖帳戶
2. 查詢兩邊初始倉位
3. 模擬主帳戶成交事件
4. 觸發對沖引擎執行對沖
5. 查詢兩邊最終倉位，驗證對沖是否成功

使用方式：
    python scripts/test_standx_hedge.py [--confirm]

    --confirm: 跳過確認提示，直接執行對沖

環境變數需求：
    - STANDX_API_TOKEN, STANDX_ED25519_PRIVATE_KEY (主帳戶)
    - STANDX_HEDGE_API_TOKEN, STANDX_HEDGE_ED25519_PRIVATE_KEY (對沖帳戶)
    - HEDGE_TARGET=standx_hedge
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

# 載入環境變數
load_dotenv(project_root / ".env")

import logging

# 設置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("test_hedge")


async def create_standx_adapter(api_token: str, ed25519_key: str, name: str = "STANDX"):
    """創建 StandX 適配器"""
    from src.adapters.factory import create_adapter

    config = {
        'exchange_name': 'standx',
        'api_token': api_token,
        'ed25519_private_key': ed25519_key,
        'testnet': False,
    }

    adapter = create_adapter(config)

    if hasattr(adapter, 'connect'):
        connected = await adapter.connect()
        if connected:
            logger.info(f"✅ {name} 連接成功")
        else:
            logger.error(f"❌ {name} 連接失敗")
            return None

    return adapter


async def get_position(adapter, symbol: str = "BTC-USD") -> Decimal:
    """查詢倉位"""
    try:
        positions = await adapter.get_positions(symbol)
        for pos in positions:
            if pos.symbol == symbol:
                size = Decimal(str(pos.size))
                if pos.side == "short":
                    size = -size
                return size
        return Decimal("0")
    except Exception as e:
        logger.error(f"查詢倉位失敗: {e}")
        return Decimal("0")


async def get_balance(adapter) -> dict:
    """查詢餘額"""
    try:
        balance = await adapter.get_balance()
        return balance
    except Exception as e:
        logger.error(f"查詢餘額失敗: {e}")
        return {}


async def main(auto_confirm: bool = False):
    """主測試流程"""
    print("\n" + "=" * 60)
    print("StandX 對沖測試")
    print("=" * 60 + "\n")

    # 1. 檢查環境變數
    main_token = os.getenv('STANDX_API_TOKEN')
    main_key = os.getenv('STANDX_ED25519_PRIVATE_KEY')
    hedge_token = os.getenv('STANDX_HEDGE_API_TOKEN')
    hedge_key = os.getenv('STANDX_HEDGE_ED25519_PRIVATE_KEY')
    hedge_target = os.getenv('HEDGE_TARGET', 'grvt')

    print("📋 環境變數檢查:")
    print(f"   HEDGE_TARGET = {hedge_target}")
    print(f"   主帳戶 Token: {'✅ 已配置' if main_token else '❌ 未配置'}")
    print(f"   主帳戶 Key:   {'✅ 已配置' if main_key else '❌ 未配置'}")
    print(f"   對沖帳戶 Token: {'✅ 已配置' if hedge_token else '❌ 未配置'}")
    print(f"   對沖帳戶 Key:   {'✅ 已配置' if hedge_key else '❌ 未配置'}")
    print()

    if not all([main_token, main_key, hedge_token, hedge_key]):
        print("❌ 缺少必要的環境變數，請檢查 .env 配置")
        return

    if hedge_target != 'standx_hedge':
        print(f"⚠️  HEDGE_TARGET={hedge_target}，建議設為 standx_hedge 進行測試")
        print("   繼續執行測試...")

    # 2. 連接兩個帳戶
    print("\n🔌 連接交易所...")

    main_adapter = await create_standx_adapter(main_token, main_key, "主帳戶")
    if not main_adapter:
        return

    hedge_adapter = await create_standx_adapter(hedge_token, hedge_key, "對沖帳戶")
    if not hedge_adapter:
        return

    # 3. 查詢初始倉位
    print("\n📊 查詢初始倉位...")
    symbol = "BTC-USD"

    main_pos_before = await get_position(main_adapter, symbol)
    hedge_pos_before = await get_position(hedge_adapter, symbol)

    print(f"   主帳戶倉位:   {main_pos_before} BTC")
    print(f"   對沖帳戶倉位: {hedge_pos_before} BTC")
    print(f"   淨倉位:       {main_pos_before + hedge_pos_before} BTC")

    # 4. 創建對沖引擎
    print("\n⚙️  創建對沖引擎...")
    from src.strategy.standx_hedge_engine import StandXHedgeEngine

    hedge_engine = StandXHedgeEngine(
        hedge_adapter=hedge_adapter,
        fallback_adapter=main_adapter,
    )
    logger.info("StandXHedgeEngine 已創建")

    # 5. 模擬成交並執行對沖
    print("\n🎯 模擬成交事件並執行對沖...")

    # 模擬參數
    fill_id = "test_fill_001"
    fill_side = "buy"  # 主帳戶買入 → 對沖帳戶賣出
    fill_qty = Decimal("0.001")  # 0.001 BTC
    fill_price = Decimal("105000")  # 假設價格

    print(f"   模擬成交: {fill_side} {fill_qty} BTC @ {fill_price}")
    print(f"   預期對沖: sell {fill_qty} BTC (市價單)")

    # 詢問用戶是否繼續
    print("\n" + "-" * 40)
    if auto_confirm:
        print("⚠️  使用 --confirm 參數，自動執行對沖")
    else:
        confirm = input("⚠️  這將在對沖帳戶執行真實的市價單！確認執行？(yes/no): ")
        if confirm.lower() != 'yes':
            print("已取消測試")
            return

    print("\n🚀 執行對沖...")

    result = await hedge_engine.execute_hedge(
        fill_id=fill_id,
        fill_side=fill_side,
        fill_qty=fill_qty,
        fill_price=fill_price,
        source_symbol=symbol,
    )

    # 6. 顯示對沖結果
    print("\n📝 對沖結果:")
    print(f"   成功: {'✅ 是' if result.success else '❌ 否'}")
    print(f"   狀態: {result.status.value}")
    print(f"   訂單 ID: {result.order_id}")
    print(f"   成交數量: {result.fill_qty}")
    print(f"   成交價格: {result.fill_price}")
    print(f"   滑點: {result.slippage_bps:.2f} bps" if result.slippage_bps else "   滑點: N/A")
    print(f"   延遲: {result.latency_ms:.0f} ms" if result.latency_ms else "   延遲: N/A")
    print(f"   嘗試次數: {result.attempts}")
    if result.error_message:
        print(f"   錯誤: {result.error_message}")

    # 7. 查詢最終倉位
    print("\n📊 查詢最終倉位...")
    await asyncio.sleep(1)  # 等待訂單處理

    main_pos_after = await get_position(main_adapter, symbol)
    hedge_pos_after = await get_position(hedge_adapter, symbol)

    print(f"   主帳戶倉位:   {main_pos_before} → {main_pos_after} BTC (變化: {main_pos_after - main_pos_before})")
    print(f"   對沖帳戶倉位: {hedge_pos_before} → {hedge_pos_after} BTC (變化: {hedge_pos_after - hedge_pos_before})")
    print(f"   淨倉位:       {main_pos_after + hedge_pos_after} BTC")

    # 8. 驗證結果
    print("\n" + "=" * 60)
    if result.success:
        hedge_change = hedge_pos_after - hedge_pos_before
        expected_change = -fill_qty if fill_side == "buy" else fill_qty

        if abs(hedge_change - expected_change) < Decimal("0.0001"):
            print("✅ 測試通過！對沖數量匹配")
        else:
            print(f"⚠️  對沖數量不完全匹配")
            print(f"   預期變化: {expected_change}")
            print(f"   實際變化: {hedge_change}")
    else:
        print("❌ 對沖失敗，請檢查日誌")

    print("=" * 60 + "\n")

    # 顯示對沖引擎統計
    stats = hedge_engine.get_stats()
    print("📈 對沖引擎統計:")
    print(f"   總嘗試: {stats['total_attempts']}")
    print(f"   成功: {stats['total_success']}")
    print(f"   失敗: {stats['total_failed']}")
    print(f"   Fallback: {stats['total_fallback']}")
    print(f"   成功率: {stats['success_rate']:.1%}")
    if stats['avg_latency_ms']:
        print(f"   平均延遲: {stats['avg_latency_ms']:.0f} ms")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="StandX 對沖測試腳本")
    parser.add_argument("--confirm", action="store_true", help="跳過確認提示，直接執行對沖")
    args = parser.parse_args()

    try:
        asyncio.run(main(auto_confirm=args.confirm))
    except KeyboardInterrupt:
        print("\n已中斷")
    except Exception as e:
        logger.exception(f"測試失敗: {e}")
