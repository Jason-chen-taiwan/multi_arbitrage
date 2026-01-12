"""
多交易所測試腳本
Multi-Exchange Test Script

演示如何同時連接多個交易所並比較價格
"""
import asyncio
import os
from decimal import Decimal
from dotenv import load_dotenv
from src.adapters.factory import create_adapter, get_available_exchanges


async def test_single_exchange(exchange_name: str, config: dict):
    """測試單個交易所連接"""
    print(f"\n{'='*60}")
    print(f"🧪 Testing {exchange_name.upper()} Exchange")
    print(f"{'='*60}")

    try:
        # 創建適配器
        adapter = create_adapter(config)
        print(f"✅ Adapter created: {adapter.__class__.__name__}")

        # 連接
        print(f"🔌 Connecting to {exchange_name}...")
        connected = await adapter.connect()

        if not connected:
            print(f"❌ Failed to connect to {exchange_name}")
            return None

        print(f"✅ Connected to {exchange_name}")

        # 獲取餘額
        try:
            print(f"\n💰 Fetching balance...")
            balance = await adapter.get_balance()
            print(f"  Total Balance: ${balance.total_balance}")
            print(f"  Available: ${balance.available_balance}")
            print(f"  Used Margin: ${balance.used_margin}")
        except Exception as e:
            print(f"  ⚠️  Balance fetch failed: {e}")

        # 獲取持倉
        try:
            print(f"\n📊 Fetching positions...")
            positions = await adapter.get_positions()
            print(f"  Open Positions: {len(positions)}")
            for pos in positions:
                print(f"    - {pos.symbol}: {pos.side} {pos.size} @ ${pos.entry_price}")
        except Exception as e:
            print(f"  ⚠️  Positions fetch failed: {e}")

        # 獲取訂單簿
        try:
            print(f"\n📖 Fetching orderbook for BTC-USD...")
            orderbook = await adapter.get_orderbook("BTC-USD", limit=5)
            if orderbook.bids and orderbook.asks:
                best_bid = orderbook.bids[0][0]
                best_ask = orderbook.asks[0][0]
                spread = best_ask - best_bid
                print(f"  Best Bid: ${best_bid}")
                print(f"  Best Ask: ${best_ask}")
                print(f"  Spread: ${spread} ({(spread/best_bid*100):.4f}%)")
            else:
                print(f"  ⚠️  No orderbook data available")
        except Exception as e:
            print(f"  ⚠️  Orderbook fetch failed: {e}")

        # 斷開連接
        await adapter.disconnect()
        print(f"\n✅ {exchange_name.upper()} test completed!")

        return {
            "exchange": exchange_name,
            "adapter": adapter,
            "orderbook": orderbook if 'orderbook' in locals() else None
        }

    except Exception as e:
        print(f"\n❌ {exchange_name.upper()} test failed: {e}")
        import traceback
        traceback.print_exc()
        return None


async def test_price_comparison():
    """比較多個交易所的價格"""
    print("\n" + "="*80)
    print("📊 MULTI-EXCHANGE PRICE COMPARISON")
    print("="*80)

    load_dotenv()

    # 配置多個交易所
    exchanges_config = {}

    # StandX
    if os.getenv("WALLET_PRIVATE_KEY"):
        exchanges_config["standx"] = {
            "exchange_name": "standx",
            "private_key": os.getenv("WALLET_PRIVATE_KEY"),
            "chain": os.getenv("CHAIN", "bsc"),
            "base_url": os.getenv("STANDX_BASE_URL", "https://api.standx.com"),
            "perps_url": os.getenv("STANDX_PERPS_URL", "https://perps.standx.com")
        }

    # GRVT (如果配置了)
    if os.getenv("GRVT_API_KEY") and os.getenv("GRVT_API_SECRET"):
        exchanges_config["grvt"] = {
            "exchange_name": "grvt",
            "api_key": os.getenv("GRVT_API_KEY"),
            "api_secret": os.getenv("GRVT_API_SECRET"),
            "base_url": os.getenv("GRVT_BASE_URL", "https://api.grvt.io"),
            "testnet": os.getenv("GRVT_TESTNET", "false").lower() == "true"
        }

    if not exchanges_config:
        print("❌ No exchange credentials found in .env file")
        print("Please configure at least one exchange:")
        print("  - StandX: WALLET_PRIVATE_KEY, CHAIN")
        print("  - GRVT: GRVT_API_KEY, GRVT_API_SECRET")
        return

    print(f"\n✅ Found {len(exchanges_config)} configured exchange(s):")
    for name in exchanges_config.keys():
        print(f"  - {name.upper()}")

    # 並行測試所有交易所
    print(f"\n🚀 Testing all exchanges in parallel...")
    tasks = [
        test_single_exchange(name, config)
        for name, config in exchanges_config.items()
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 過濾成功的結果
    successful_results = [r for r in results if r is not None and not isinstance(r, Exception)]

    if len(successful_results) < 2:
        print("\n⚠️  Need at least 2 exchanges to compare prices")
        return

    # 比較價格
    print("\n" + "="*80)
    print("📊 PRICE COMPARISON SUMMARY")
    print("="*80)

    symbol = "BTC-USD"
    print(f"\nSymbol: {symbol}")
    print("-" * 80)
    print(f"{'Exchange':<15} {'Best Bid':>15} {'Best Ask':>15} {'Spread':>15} {'Spread %':>12}")
    print("-" * 80)

    prices = {}
    for result in successful_results:
        if result['orderbook'] and result['orderbook'].bids and result['orderbook'].asks:
            exchange = result['exchange']
            best_bid = result['orderbook'].bids[0][0]
            best_ask = result['orderbook'].asks[0][0]
            spread = best_ask - best_bid
            spread_pct = (spread / best_bid * 100)

            prices[exchange] = {
                'bid': best_bid,
                'ask': best_ask,
                'spread': spread,
                'spread_pct': spread_pct
            }

            print(f"{exchange.upper():<15} ${best_bid:>14.2f} ${best_ask:>14.2f} ${spread:>14.2f} {spread_pct:>11.4f}%")

    # 計算套利機會
    if len(prices) >= 2:
        print("\n" + "="*80)
        print("💰 ARBITRAGE OPPORTUNITIES")
        print("="*80)

        exchanges = list(prices.keys())
        for i, exchange1 in enumerate(exchanges):
            for exchange2 in exchanges[i+1:]:
                # 計算套利空間：在 exchange1 買入，在 exchange2 賣出
                profit1 = prices[exchange2]['bid'] - prices[exchange1]['ask']
                profit1_pct = (profit1 / prices[exchange1]['ask'] * 100)

                # 計算套利空間：在 exchange2 買入，在 exchange1 賣出
                profit2 = prices[exchange1]['bid'] - prices[exchange2]['ask']
                profit2_pct = (profit2 / prices[exchange2]['ask'] * 100)

                print(f"\n{exchange1.upper()} ↔ {exchange2.upper()}:")

                if profit1 > 0:
                    print(f"  ✅ Buy on {exchange1.upper()} @ ${prices[exchange1]['ask']:.2f}")
                    print(f"     Sell on {exchange2.upper()} @ ${prices[exchange2]['bid']:.2f}")
                    print(f"     Profit: ${profit1:.2f} ({profit1_pct:.4f}%)")
                elif profit2 > 0:
                    print(f"  ✅ Buy on {exchange2.upper()} @ ${prices[exchange2]['ask']:.2f}")
                    print(f"     Sell on {exchange1.upper()} @ ${prices[exchange1]['bid']:.2f}")
                    print(f"     Profit: ${profit2:.2f} ({profit2_pct:.4f}%)")
                else:
                    print(f"  ⚠️  No arbitrage opportunity (negative spread)")


async def list_available_exchanges():
    """列出所有可用的交易所"""
    print("\n" + "="*60)
    print("📋 AVAILABLE EXCHANGES")
    print("="*60)

    exchanges = get_available_exchanges()
    for i, exchange in enumerate(exchanges, 1):
        print(f"{i}. {exchange.upper()}")

    print(f"\nTotal: {len(exchanges)} exchange(s)")


async def main():
    """主函數"""
    print("\n" + "="*80)
    print("🚀 MULTI-EXCHANGE TRADING SYSTEM TEST")
    print("="*80)

    # 列出可用交易所
    await list_available_exchanges()

    # 測試價格比較
    await test_price_comparison()

    print("\n" + "="*80)
    print("✅ ALL TESTS COMPLETED!")
    print("="*80)


if __name__ == "__main__":
    asyncio.run(main())
