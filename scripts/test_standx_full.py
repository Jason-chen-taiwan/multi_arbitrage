"""
完整測試 StandX 適配器功能

測試從認證到下單的完整流程
"""
import asyncio
import os
import sys
from pathlib import Path
from decimal import Decimal

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from src.adapters import create_adapter

load_dotenv()

async def test_full_workflow():
    """測試完整的交易流程"""
    
    print("=" * 80)
    print("StandX 適配器完整功能測試")
    print("=" * 80)
    
    # 1. 創建適配器
    config = {
        "exchange_name": "standx",
        "private_key": os.getenv("WALLET_PRIVATE_KEY"),
        "chain": os.getenv("CHAIN", "bsc"),
        "base_url": os.getenv("STANDX_BASE_URL", "https://api.standx.com"),
        "perps_url": os.getenv("STANDX_PERPS_URL", "https://perps.standx.com"),
    }
    
    print("\n📦 創建適配器...")
    adapter = create_adapter(config)
    print(f"✅ {adapter}")
    
    # 2. 連接認證
    print("\n🔐 連接並認證...")
    success = await adapter.connect()
    
    if not success:
        print("❌ 認證失敗")
        return
    
    print("✅ 認證成功")
    
    # 3. 查詢餘額
    print("\n" + "=" * 80)
    print("💰 查詢賬戶餘額")
    print("=" * 80)
    try:
        balance = await adapter.get_balance()
        print(f"""
賬戶資訊:
  總餘額:       ${balance.total_balance:>12,.2f}
  可用餘額:     ${balance.available_balance:>12,.2f}
  已用保證金:   ${balance.used_margin:>12,.2f}
  未實現盈虧:   ${balance.unrealized_pnl:>+12,.2f}
  淨值:         ${balance.equity:>12,.2f}
        """)
    except Exception as e:
        print(f"❌ 查詢餘額失敗: {e}")
    
    # 4. 查詢持倉
    print("=" * 80)
    print("📊 查詢持倉")
    print("=" * 80)
    try:
        positions = await adapter.get_positions()
        if positions:
            print(f"\n當前持倉數量: {len(positions)}\n")
            for i, pos in enumerate(positions, 1):
                print(f"{i}. {pos.symbol} - {pos.side.upper()}")
                print(f"   數量:       {pos.size}")
                print(f"   入場價格:   ${pos.entry_price:,.2f}")
                print(f"   標記價格:   ${pos.mark_price:,.2f}")
                print(f"   未實現盈虧: ${pos.unrealized_pnl:+,.2f}")
                if pos.leverage:
                    print(f"   槓桿:       {pos.leverage}x")
                print()
        else:
            print("ℹ️  當前無持倉\n")
    except Exception as e:
        print(f"❌ 查詢持倉失敗: {e}")
    
    # 5. 查詢訂單簿
    print("=" * 80)
    print("📖 查詢 BTC-USD 訂單簿")
    print("=" * 80)
    try:
        orderbook = await adapter.get_orderbook("BTC-USD", depth=5)
        
        print("\n賣單 (Asks) - 從低到高:")
        for price, qty in reversed(orderbook['asks'][-5:]):
            total = price * qty
            print(f"  ${price:>10,.2f}  │  {qty:>8.4f} BTC  │  ${total:>12,.2f}")
        
        best_bid = orderbook['bids'][0][0]
        best_ask = orderbook['asks'][0][0]
        spread = best_ask - best_bid
        spread_bps = (spread / best_bid) * 10000
        mid_price = (best_bid + best_ask) / 2
        
        print(f"\n{'─' * 60}")
        print(f"  中間價: ${mid_price:,.2f}  │  價差: ${spread:.2f} ({spread_bps:.1f} bps)")
        print(f"{'─' * 60}\n")
        
        print("買單 (Bids) - 從高到低:")
        for price, qty in orderbook['bids'][:5]:
            total = price * qty
            print(f"  ${price:>10,.2f}  │  {qty:>8.4f} BTC  │  ${total:>12,.2f}")
        
        print()
    except Exception as e:
        print(f"❌ 查詢訂單簿失敗: {e}")
    
    # 6. 查詢未成交訂單
    print("=" * 80)
    print("📋 查詢未成交訂單")
    print("=" * 80)
    try:
        orders = await adapter.get_open_orders("BTC-USD")
        if orders:
            print(f"\n未成交訂單數量: {len(orders)}\n")
            for i, order in enumerate(orders[:10], 1):  # 顯示前10個
                print(f"{i}. {order.symbol} - {order.side.upper()} {order.order_type.upper()}")
                print(f"   訂單ID:     {order.order_id}")
                if order.client_order_id:
                    print(f"   客戶端ID:   {order.client_order_id}")
                if order.price:
                    print(f"   價格:       ${order.price:,.2f}")
                print(f"   數量:       {order.qty}")
                print(f"   已成交:     {order.filled_qty}")
                print(f"   狀態:       {order.status}")
                print()
        else:
            print("ℹ️  當前無未成交訂單\n")
    except Exception as e:
        print(f"❌ 查詢未成交訂單失敗: {e}")
    
    # 7. 測試下單（小額測試單）
    print("=" * 80)
    print("🎯 測試下限價單（僅測試，不實際成交）")
    print("=" * 80)
    
    test_order = input("\n是否要測試下單? (y/N): ").strip().lower()
    
    if test_order == 'y':
        try:
            # 獲取當前價格
            orderbook = await adapter.get_orderbook("BTC-USD", depth=1)
            best_bid = orderbook['bids'][0][0]
            
            # 設置一個遠離市場的價格（不會成交）
            test_price = best_bid * Decimal("0.5")  # 50% 的買價
            test_qty = Decimal("0.001")  # 最小數量
            
            print(f"\n下測試單:")
            print(f"  交易對: BTC-USD")
            print(f"  方向:   BUY")
            print(f"  類型:   LIMIT")
            print(f"  價格:   ${test_price:,.2f}")
            print(f"  數量:   {test_qty} BTC")
            print(f"  當前市價: ${best_bid:,.2f}")
            print(f"  (此訂單不會成交，僅用於測試)")
            
            confirm = input("\n確認下單? (y/N): ").strip().lower()
            
            if confirm == 'y':
                order = await adapter.place_limit_order(
                    symbol="BTC-USD",
                    side="buy",
                    quantity=test_qty,
                    price=test_price,
                    time_in_force="gtc"
                )
                
                print(f"\n✅ 訂單已提交")
                print(f"   客戶端訂單ID: {order.client_order_id}")
                print(f"   狀態: {order.status}")
                
                # 可選：取消測試訂單
                cancel = input("\n是否取消測試訂單? (y/N): ").strip().lower()
                if cancel == 'y' and order.client_order_id:
                    success = await adapter.cancel_order(
                        symbol="BTC-USD",
                        client_order_id=order.client_order_id
                    )
                    if success:
                        print("✅ 訂單已取消")
                    else:
                        print("❌ 取消訂單失敗")
            else:
                print("⏭️  跳過下單")
        except Exception as e:
            print(f"❌ 下單失敗: {e}")
    else:
        print("⏭️  跳過下單測試")
    
    # 8. 斷開連接
    print("\n" + "=" * 80)
    print("🔌 斷開連接...")
    await adapter.disconnect()
    print("✅ 測試完成！")
    print("=" * 80 + "\n")


async def main():
    """主函數"""
    try:
        await test_full_workflow()
    except KeyboardInterrupt:
        print("\n\n⚠️  測試中斷")
    except Exception as e:
        print(f"\n\n❌ 測試失敗: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
