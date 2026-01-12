"""
測試多交易所適配器

這個腳本演示如何使用統一的適配器接口來連接不同的交易所。
"""
import asyncio
import os
import sys
from pathlib import Path

# 添加項目根目錄到 Python 路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

# 加載環境變量
load_dotenv()

async def test_standx_adapter():
    """測試 StandX 適配器"""
    from src.adapters import create_adapter, get_available_exchanges
    
    print("=" * 60)
    print("測試多交易所適配器系統")
    print("=" * 60)
    
    # 顯示可用的交易所
    exchanges = get_available_exchanges()
    print(f"\n✅ 可用的交易所: {', '.join(exchanges)}")
    
    # 配置 StandX
    config = {
        "exchange_name": "standx",
        "private_key": os.getenv("WALLET_PRIVATE_KEY"),
        "chain": os.getenv("CHAIN", "bsc"),
        "base_url": os.getenv("STANDX_BASE_URL", "https://api.standx.com"),
        "perps_url": os.getenv("STANDX_PERPS_URL", "https://perps.standx.com"),
    }
    
    print(f"\n🔧 創建 {config['exchange_name']} 適配器...")
    adapter = create_adapter(config)
    print(f"✅ 適配器創建成功: {adapter}")
    
    # 連接
    print(f"\n🔌 連接到 {config['exchange_name']}...")
    success = await adapter.connect()
    
    if not success:
        print("❌ 連接失敗")
        return
    
    print("\n✅ 連接成功！測試基本功能...\n")
    
    # 測試餘額查詢
    print("1️⃣ 查詢賬戶餘額...")
    try:
        balance = await adapter.get_balance()
        print(f"   💰 總餘額: ${balance.total_balance:,.2f}")
        print(f"   💵 可用餘額: ${balance.available_balance:,.2f}")
        print(f"   📊 未實現盈虧: ${balance.unrealized_pnl:+,.2f}")
        print(f"   💼 淨值: ${balance.equity:,.2f}")
    except Exception as e:
        print(f"   ❌ 錯誤: {e}")
    
    # 測試持倉查詢
    print("\n2️⃣ 查詢持倉...")
    try:
        positions = await adapter.get_positions()
        if positions:
            for pos in positions:
                print(f"   📈 {pos.symbol}: {pos.side.upper()} {pos.size} @ ${pos.entry_price}")
                print(f"      未實現盈虧: ${pos.unrealized_pnl:+,.2f}")
        else:
            print("   ℹ️  當前無持倉")
    except Exception as e:
        print(f"   ❌ 錯誤: {e}")
    
    # 測試訂單簿查詢
    print("\n3️⃣ 查詢 BTC-USD 訂單簿...")
    try:
        orderbook = await adapter.get_orderbook("BTC-USD", depth=5)
        
        print("   📕 賣單 (Asks):")
        for price, qty in reversed(orderbook['asks'][-5:]):
            print(f"      ${price:>10,.2f} | {qty:>8.4f} BTC")
        
        spread = orderbook['asks'][0][0] - orderbook['bids'][0][0]
        spread_bps = (spread / orderbook['bids'][0][0]) * 10000
        print(f"   💹 價差: ${spread:.2f} ({spread_bps:.1f} bps)")
        
        print("   📗 買單 (Bids):")
        for price, qty in orderbook['bids'][:5]:
            print(f"      ${price:>10,.2f} | {qty:>8.4f} BTC")
            
    except Exception as e:
        print(f"   ❌ 錯誤: {e}")
    
    # 測試未成交訂單查詢
    print("\n4️⃣ 查詢未成交訂單...")
    try:
        orders = await adapter.get_open_orders("BTC-USD")
        if orders:
            for order in orders[:5]:  # 顯示前5個
                print(f"   📝 {order.side.upper()} {order.qty} @ ${order.price} ({order.status})")
        else:
            print("   ℹ️  當前無未成交訂單")
    except Exception as e:
        print(f"   ❌ 錯誤: {e}")
    
    # 斷開連接
    print("\n🔌 斷開連接...")
    await adapter.disconnect()
    print("✅ 測試完成！\n")


async def main():
    """主函數"""
    try:
        await test_standx_adapter()
    except KeyboardInterrupt:
        print("\n⚠️  測試中斷")
    except Exception as e:
        print(f"\n❌ 測試失敗: {e}")


if __name__ == "__main__":
    asyncio.run(main())
