"""
實時套利監控腳本
Real-time Arbitrage Monitoring Script

監控多個交易所的 BTC 和 ETH 永續合約價格並實時檢測套利機會
"""
import asyncio
import os
import signal
from dotenv import load_dotenv

from src.adapters.factory import create_adapter
from src.monitor.multi_exchange_monitor import MultiExchangeMonitor


# 全局監控器實例
monitor = None


def signal_handler(signum, frame):
    """處理 Ctrl+C 信號"""
    print("\n\n⚠️  Received interrupt signal...")
    if monitor:
        asyncio.create_task(monitor.stop())


async def main():
    """主函數"""
    global monitor

    load_dotenv()

    print("\n" + "="*80)
    print("🔍 MULTI-EXCHANGE ARBITRAGE MONITOR")
    print("="*80)
    print("Monitoring BTC and ETH perpetual futures across multiple exchanges")
    print("Press Ctrl+C to stop\n")

    # 配置要監控的交易對
    # CEX 使用 CCXT 格式: BTC/USDT:USDT
    # DEX 使用原生格式: BTC-USD
    symbols_config = {
        'cex': ['BTC/USDT:USDT', 'ETH/USDT:USDT'],  # CEX 符號
        'dex': ['BTC-USD', 'ETH-USD']  # DEX 符號
    }

    # 配置交易所
    adapters = {}
    exchange_types = {}  # 記錄交易所類型

    # === DEX 配置 ===
    # StandX
    if os.getenv("WALLET_PRIVATE_KEY"):
        try:
            standx_config = {
                "exchange_name": "standx",
                "private_key": os.getenv("WALLET_PRIVATE_KEY"),
                "chain": os.getenv("CHAIN", "bsc"),
                "base_url": os.getenv("STANDX_BASE_URL"),
                "perps_url": os.getenv("STANDX_PERPS_URL")
            }
            adapters['standx'] = create_adapter(standx_config)
            exchange_types['standx'] = 'dex'
            print("✅ StandX adapter configured")
        except Exception as e:
            print(f"⚠️  StandX adapter failed: {e}")

    # GRVT
    if os.getenv("GRVT_API_KEY") and os.getenv("GRVT_API_SECRET"):
        try:
            grvt_config = {
                "exchange_name": "grvt",
                "api_key": os.getenv("GRVT_API_KEY"),
                "api_secret": os.getenv("GRVT_API_SECRET"),
                "testnet": os.getenv("GRVT_TESTNET", "false").lower() == "true"
            }
            adapters['grvt'] = create_adapter(grvt_config)
            exchange_types['grvt'] = 'dex'
            print("✅ GRVT adapter configured")
        except Exception as e:
            print(f"⚠️  GRVT adapter failed: {e}")

    # === CEX 配置 ===
    # Binance
    if os.getenv("BINANCE_API_KEY") and os.getenv("BINANCE_API_SECRET"):
        try:
            binance_config = {
                "exchange_name": "binance",
                "api_key": os.getenv("BINANCE_API_KEY"),
                "api_secret": os.getenv("BINANCE_API_SECRET"),
                "testnet": os.getenv("BINANCE_TESTNET", "false").lower() == "true"
            }
            adapters['binance'] = create_adapter(binance_config)
            exchange_types['binance'] = 'cex'
            print("✅ Binance adapter configured")
        except Exception as e:
            print(f"⚠️  Binance adapter failed: {e}")

    # OKX
    if os.getenv("OKX_API_KEY") and os.getenv("OKX_API_SECRET") and os.getenv("OKX_PASSPHRASE"):
        try:
            okx_config = {
                "exchange_name": "okx",
                "api_key": os.getenv("OKX_API_KEY"),
                "api_secret": os.getenv("OKX_API_SECRET"),
                "password": os.getenv("OKX_PASSPHRASE"),
                "testnet": os.getenv("OKX_TESTNET", "false").lower() == "true"
            }
            adapters['okx'] = create_adapter(okx_config)
            exchange_types['okx'] = 'cex'
            print("✅ OKX adapter configured")
        except Exception as e:
            print(f"⚠️  OKX adapter failed: {e}")

    # Bitget
    if os.getenv("BITGET_API_KEY") and os.getenv("BITGET_API_SECRET") and os.getenv("BITGET_PASSPHRASE"):
        try:
            bitget_config = {
                "exchange_name": "bitget",
                "api_key": os.getenv("BITGET_API_KEY"),
                "api_secret": os.getenv("BITGET_API_SECRET"),
                "password": os.getenv("BITGET_PASSPHRASE"),
                "testnet": os.getenv("BITGET_TESTNET", "false").lower() == "true"
            }
            adapters['bitget'] = create_adapter(bitget_config)
            exchange_types['bitget'] = 'cex'
            print("✅ Bitget adapter configured")
        except Exception as e:
            print(f"⚠️  Bitget adapter failed: {e}")

    # Bybit
    if os.getenv("BYBIT_API_KEY") and os.getenv("BYBIT_API_SECRET"):
        try:
            bybit_config = {
                "exchange_name": "bybit",
                "api_key": os.getenv("BYBIT_API_KEY"),
                "api_secret": os.getenv("BYBIT_API_SECRET"),
                "testnet": os.getenv("BYBIT_TESTNET", "false").lower() == "true"
            }
            adapters['bybit'] = create_adapter(bybit_config)
            exchange_types['bybit'] = 'cex'
            print("✅ Bybit adapter configured")
        except Exception as e:
            print(f"⚠️  Bybit adapter failed: {e}")

    if not adapters:
        print("\n❌ No exchanges configured!")
        print("\nPlease configure at least one exchange in .env:")
        print("  DEX: WALLET_PRIVATE_KEY (StandX)")
        print("  CEX: BINANCE_API_KEY, OKX_API_KEY, etc.")
        return

    print(f"\n✅ Total exchanges configured: {len(adapters)}")

    # 連接所有交易所
    print(f"\n{'='*80}")
    print("🔌 Connecting to exchanges...")
    print(f"{'='*80}")

    connect_tasks = []
    for name, adapter in adapters.items():
        connect_tasks.append(adapter.connect())

    results = await asyncio.gather(*connect_tasks, return_exceptions=True)

    # 檢查連接結果
    connected_adapters = {}
    for name, adapter, result in zip(adapters.keys(), adapters.values(), results):
        if isinstance(result, Exception):
            print(f"❌ {name.upper()} connection failed: {result}")
        elif result:
            connected_adapters[name] = adapter
            print(f"✅ {name.upper()} connected")
        else:
            print(f"❌ {name.upper()} connection failed")

    if not connected_adapters:
        print("\n❌ No exchanges connected successfully!")
        return

    # 為每個交易所準備正確的符號格式
    exchange_symbols = {}
    for exchange_name in connected_adapters.keys():
        ex_type = exchange_types[exchange_name]
        exchange_symbols[exchange_name] = symbols_config[ex_type]

    # 獲取所有唯一的符號（用於顯示）
    all_symbols = set()
    for symbols in exchange_symbols.values():
        all_symbols.update(symbols)

    print(f"\n{'='*80}")
    print(f"📊 Monitor Configuration:")
    print(f"{'='*80}")
    print(f"Exchanges: {len(connected_adapters)}")
    for exchange_name, symbols in exchange_symbols.items():
        print(f"  {exchange_name.upper():15s} - {', '.join(symbols)}")
    print(f"Update interval: 2 seconds")
    print(f"Min profit threshold: 0.1%")
    print(f"{'='*80}\n")

    # 創建監控器 - 使用每個交易所各自的符號列表
    # 我們需要為每個交易所創建單獨的監控器
    # 或者修改監控器以支持每個交易所不同的符號格式

    # 暫時使用 BTC 和 ETH 的統一邏輯
    # 創建符號映射
    symbol_mapping = {
        'BTC': {
            'cex': 'BTC/USDT:USDT',
            'dex': 'BTC-USD'
        },
        'ETH': {
            'cex': 'ETH/USDT:USDT',
            'dex': 'ETH-USD'
        }
    }

    # 為簡化，我們按類型分組監控
    # 先實現一個簡單版本：只監控相同類型的交易所
    cex_adapters = {k: v for k, v in connected_adapters.items() if exchange_types[k] == 'cex'}
    dex_adapters = {k: v for k, v in connected_adapters.items() if exchange_types[k] == 'dex'}

    monitors = []

    # CEX 監控器
    if cex_adapters:
        cex_monitor = MultiExchangeMonitor(
            adapters=cex_adapters,
            symbols=symbols_config['cex'],
            update_interval=2.0,
            min_profit_pct=0.1
        )
        await cex_monitor.start()
        monitors.append(cex_monitor)

    # DEX 監控器
    if dex_adapters:
        dex_monitor = MultiExchangeMonitor(
            adapters=dex_adapters,
            symbols=symbols_config['dex'],
            update_interval=2.0,
            min_profit_pct=0.1
        )
        await dex_monitor.start()
        monitors.append(dex_monitor)

    # 設置全局監控器（用於信號處理）
    monitor = monitors[0] if monitors else None

    # 註冊信號處理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # 保持運行
        print("\n✅ Monitor started! Press Ctrl+C to stop...\n")
        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        print("\n\n⚠️  Stopping monitor...")

    finally:
        # 停止所有監控器
        for mon in monitors:
            await mon.stop()

        # 導出數據
        for i, mon in enumerate(monitors):
            mon.export_data(f'market_data_{i}.json')

        # 斷開所有連接
        print("\n🔌 Disconnecting from exchanges...")
        disconnect_tasks = [adapter.disconnect() for adapter in connected_adapters.values()]
        await asyncio.gather(*disconnect_tasks, return_exceptions=True)

        print("\n✅ Monitor stopped successfully!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
