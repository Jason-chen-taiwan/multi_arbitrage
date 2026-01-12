"""
CEX 交易所測試腳本
Test script for Centralized Exchanges (CEX)

測試 Binance、OKX、Bitget 等中心化交易所的連接
"""
import asyncio
import os
from dotenv import load_dotenv
from src.adapters.factory import create_adapter, get_available_exchanges


async def test_cex_exchange(exchange_name: str, config: dict):
    """測試單個 CEX 交易所"""
    print(f"\n{'='*70}")
    print(f"🧪 Testing {exchange_name.upper()} Exchange (CEX)")
    print(f"{'='*70}")

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
            for pos in positions[:5]:  # 只顯示前 5 個
                print(f"    - {pos.symbol}: {pos.side} {pos.size} @ ${pos.entry_price}")
        except Exception as e:
            print(f"  ⚠️  Positions fetch failed: {e}")

        # 獲取訂單簿（BTC/USDT 永續合約）
        try:
            symbol = "BTC/USDT:USDT"
            print(f"\n📖 Fetching orderbook for {symbol}...")
            orderbook = await adapter.get_orderbook(symbol, limit=5)
            if orderbook.bids and orderbook.asks:
                best_bid = orderbook.bids[0][0]
                best_ask = orderbook.asks[0][0]
                spread = best_ask - best_bid
                spread_pct = (spread / best_bid * 100)
                print(f"  Best Bid: ${best_bid}")
                print(f"  Best Ask: ${best_ask}")
                print(f"  Spread: ${spread} ({spread_pct:.4f}%)")
            else:
                print(f"  ⚠️  No orderbook data available")
        except Exception as e:
            print(f"  ⚠️  Orderbook fetch failed: {e}")

        # 斷開連接
        await adapter.disconnect()
        print(f"\n✅ {exchange_name.upper()} test completed!")

        return {
            "exchange": exchange_name,
            "orderbook": orderbook if 'orderbook' in locals() else None
        }

    except Exception as e:
        print(f"\n❌ {exchange_name.upper()} test failed: {e}")
        import traceback
        traceback.print_exc()
        return None


async def main():
    """主函數"""
    print("\n" + "="*80)
    print("🚀 CEX EXCHANGES TEST")
    print("="*80)

    load_dotenv()

    # 顯示所有可用的交易所
    exchanges = get_available_exchanges()
    print(f"\n📋 Available Exchanges:")
    print(f"  DEX ({len(exchanges['dex'])}): {', '.join(exchanges['dex'])}")
    print(f"  CEX ({len(exchanges['cex'])}): {', '.join(exchanges['cex'])}")
    print(f"  Total: {len(exchanges['all'])} exchanges")

    # 配置要測試的 CEX
    cex_configs = {}

    # Binance
    if os.getenv("BINANCE_API_KEY") and os.getenv("BINANCE_API_SECRET"):
        cex_configs["binance"] = {
            "exchange_name": "binance",
            "api_key": os.getenv("BINANCE_API_KEY"),
            "api_secret": os.getenv("BINANCE_API_SECRET"),
            "testnet": os.getenv("BINANCE_TESTNET", "false").lower() == "true"
        }

    # OKX
    if os.getenv("OKX_API_KEY") and os.getenv("OKX_API_SECRET") and os.getenv("OKX_PASSPHRASE"):
        cex_configs["okx"] = {
            "exchange_name": "okx",
            "api_key": os.getenv("OKX_API_KEY"),
            "api_secret": os.getenv("OKX_API_SECRET"),
            "password": os.getenv("OKX_PASSPHRASE"),
            "testnet": os.getenv("OKX_TESTNET", "false").lower() == "true"
        }

    # Bitget
    if os.getenv("BITGET_API_KEY") and os.getenv("BITGET_API_SECRET") and os.getenv("BITGET_PASSPHRASE"):
        cex_configs["bitget"] = {
            "exchange_name": "bitget",
            "api_key": os.getenv("BITGET_API_KEY"),
            "api_secret": os.getenv("BITGET_API_SECRET"),
            "password": os.getenv("BITGET_PASSPHRASE"),
            "testnet": os.getenv("BITGET_TESTNET", "false").lower() == "true"
        }

    # Bybit
    if os.getenv("BYBIT_API_KEY") and os.getenv("BYBIT_API_SECRET"):
        cex_configs["bybit"] = {
            "exchange_name": "bybit",
            "api_key": os.getenv("BYBIT_API_KEY"),
            "api_secret": os.getenv("BYBIT_API_SECRET"),
            "testnet": os.getenv("BYBIT_TESTNET", "false").lower() == "true"
        }

    if not cex_configs:
        print("\n⚠️  No CEX credentials found in .env file")
        print("\nTo test CEX exchanges, please configure at least one:")
        print("  - Binance: BINANCE_API_KEY, BINANCE_API_SECRET")
        print("  - OKX: OKX_API_KEY, OKX_API_SECRET, OKX_PASSPHRASE")
        print("  - Bitget: BITGET_API_KEY, BITGET_API_SECRET, BITGET_PASSPHRASE")
        print("  - Bybit: BYBIT_API_KEY, BYBIT_API_SECRET")
        print("\nExample:")
        print("  EXCHANGE_NAME=binance")
        print("  BINANCE_API_KEY=your_api_key")
        print("  BINANCE_API_SECRET=your_api_secret")
        return

    print(f"\n✅ Found {len(cex_configs)} configured CEX exchange(s):")
    for name in cex_configs.keys():
        print(f"  - {name.upper()}")

    # 測試所有配置的 CEX
    print(f"\n🚀 Testing all CEX exchanges...")
    results = []
    for name, config in cex_configs.items():
        result = await test_cex_exchange(name, config)
        if result:
            results.append(result)

    # 價格比較
    if len(results) >= 2:
        print("\n" + "="*80)
        print("📊 PRICE COMPARISON (CEX)")
        print("="*80)

        symbol = "BTC/USDT:USDT"
        print(f"\nSymbol: {symbol}")
        print("-" * 80)
        print(f"{'Exchange':<15} {'Best Bid':>15} {'Best Ask':>15} {'Spread':>15} {'Spread %':>12}")
        print("-" * 80)

        prices = {}
        for result in results:
            if result.get('orderbook') and result['orderbook'].bids and result['orderbook'].asks:
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

    print("\n" + "="*80)
    print("✅ CEX TEST COMPLETED!")
    print("="*80)


if __name__ == "__main__":
    asyncio.run(main())
