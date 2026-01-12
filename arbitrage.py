#!/usr/bin/env python3
"""
多交易所套利系統 - 統一啟動介面
Multi-Exchange Arbitrage System - Unified Launcher

整合所有功能：
- 配置管理面板
- 實時套利監控
- 做市商策略
- 多交易所測試
"""
import sys
import os
import argparse
import asyncio
from pathlib import Path

# 添加項目根目錄到 Python 路徑
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def print_banner():
    """顯示歡迎橫幅"""
    print("\n" + "=" * 80)
    print("🚀 多交易所永續合約套利系統")
    print("   Multi-Exchange Perpetual Futures Arbitrage System")
    print("=" * 80 + "\n")


def print_menu():
    """顯示主選單"""
    print("📋 可用功能：\n")
    print("  1. 🎯 統一 Dashboard   - 整合所有功能的 Web UI (強烈推薦)")
    print("  2. 🔧 配置管理面板     - Web UI 管理交易所 API 配置")
    print("  3. 🔍 實時套利監控     - 終端監控多交易所價格和套利機會")
    print("  4. 🔥 套利 Dashboard   - Web UI 實時監控跨所套利")
    print("  5. 🤖 做市商策略       - 運行自動做市商策略")
    print("  6. 🧪 測試交易所連接   - 測試所有已配置的交易所")
    print("  7. 📊 單交易所面板     - Web Dashboard (單交易所)")
    print("\n" + "-" * 80 + "\n")


def run_unified_dashboard():
    """啟動統一 Dashboard"""
    print("\n🎯 啟動統一 Dashboard...\n")
    print("💡 整合所有功能：配置管理、套利監控、交易所狀態")
    from src.web.unified_dashboard import app
    import uvicorn

    print("📍 訪問地址：http://localhost:8888")
    print("⚠️  按 Ctrl+C 停止服務\n")

    try:
        uvicorn.run(app, host="127.0.0.1", port=8888, log_level="info")
    except KeyboardInterrupt:
        print("\n\n👋 統一 Dashboard 已停止")


def run_config_dashboard():
    """啟動配置管理面板"""
    print("\n🔧 啟動配置管理面板...\n")
    from src.web.config_dashboard import app, config_manager
    import uvicorn

    # 顯示當前配置狀態
    configs = config_manager.get_all_configs()
    dex_count = len(configs['dex'])
    cex_count = len(configs['cex'])

    print(f"📊 當前配置狀態：")
    print(f"  DEX 交易所: {dex_count} 個已配置")
    print(f"  CEX 交易所: {cex_count} 個已配置")

    if dex_count + cex_count == 0:
        print("\n💡 提示：尚未配置任何交易所，請在 Web 面板中添加配置")

    print("\n📍 訪問地址：http://localhost:8001")
    print("⚠️  按 Ctrl+C 停止服務\n")

    try:
        uvicorn.run(app, host="127.0.0.1", port=8001, log_level="info")
    except KeyboardInterrupt:
        print("\n\n👋 配置面板已停止")


def run_arbitrage_dashboard():
    """啟動套利 Web Dashboard"""
    print("\n🔥 啟動套利 Web Dashboard...\n")
    from src.web.arbitrage_dashboard import app
    import uvicorn

    print("📍 訪問地址：http://localhost:8002")
    print("⚠️  按 Ctrl+C 停止服務\n")

    try:
        uvicorn.run(app, host="127.0.0.1", port=8002, log_level="info")
    except KeyboardInterrupt:
        print("\n\n👋 套利 Dashboard 已停止")


def run_arbitrage_monitor():
    """啟動套利監控系統（終端版）"""
    print("\n🔍 啟動實時套利監控系統（終端版）...\n")

    from dotenv import load_dotenv
    from src.adapters.factory import create_adapter
    from src.monitor.multi_exchange_monitor import MultiExchangeMonitor

    # 載入環境變數
    load_dotenv()

    # 配置要監控的交易對
    symbols_config = {
        'cex': ['BTC/USDT:USDT', 'ETH/USDT:USDT'],
        'dex': ['BTC-USD', 'ETH-USD']
    }

    # 支援的交易所列表
    dex_exchanges = ['standx', 'grvt']
    cex_exchanges = ['binance', 'okx', 'bitget', 'bybit']

    # 創建交易所適配器
    adapters = {}
    symbols = []

    print("🔌 連接交易所...\n")

    # 嘗試連接 DEX
    for exchange in dex_exchanges:
        try:
            # 檢查是否有配置
            if exchange == 'standx':
                if not os.getenv('WALLET_PRIVATE_KEY'):
                    continue
            elif exchange == 'grvt':
                if not os.getenv('GRVT_API_KEY'):
                    continue

            config = {
                'exchange_name': exchange,
                'testnet': os.getenv(f'{exchange.upper()}_TESTNET', 'false').lower() == 'true'
            }

            adapter = create_adapter(config)
            adapters[exchange.upper()] = adapter
            symbols.extend(symbols_config['dex'])
            print(f"  ✅ {exchange.upper()} - 已連接")
        except Exception as e:
            print(f"  ⚠️  {exchange.upper()} - 跳過 ({str(e)[:50]}...)")

    # 嘗試連接 CEX
    for exchange in cex_exchanges:
        try:
            api_key = os.getenv(f'{exchange.upper()}_API_KEY')
            if not api_key:
                continue

            config = {
                'exchange_name': exchange,
                'api_key': api_key,
                'api_secret': os.getenv(f'{exchange.upper()}_API_SECRET'),
                'testnet': os.getenv(f'{exchange.upper()}_TESTNET', 'false').lower() == 'true'
            }

            # OKX 和 Bitget 需要 passphrase
            if exchange in ['okx', 'bitget']:
                passphrase = os.getenv(f'{exchange.upper()}_PASSPHRASE')
                if passphrase:
                    config['passphrase'] = passphrase

            adapter = create_adapter(config)
            adapters[exchange.upper()] = adapter
            if symbols_config['cex'] not in symbols:
                symbols.extend(symbols_config['cex'])
            print(f"  ✅ {exchange.upper()} - 已連接")
        except Exception as e:
            print(f"  ⚠️  {exchange.upper()} - 跳過 ({str(e)[:50]}...)")

    if not adapters:
        print("\n❌ 錯誤：沒有可用的交易所")
        print("   請先使用「配置管理面板」添加交易所配置\n")
        return

    # 去重 symbols
    symbols = list(set(symbols))

    print(f"\n📊 監控配置：")
    print(f"  交易所數量: {len(adapters)}")
    print(f"  交易對數量: {len(symbols)}")
    print(f"  更新間隔: 2 秒")
    print(f"  最小利潤: 0.1%")
    print("\n⚠️  按 Ctrl+C 停止監控\n")

    # 創建並運行監控器
    async def run_monitor():
        monitor = MultiExchangeMonitor(
            adapters=adapters,
            symbols=symbols,
            update_interval=2.0,
            min_profit_pct=0.1
        )

        try:
            await monitor.start()
        except KeyboardInterrupt:
            print("\n\n👋 監控已停止")
            await monitor.stop()

    try:
        asyncio.run(run_monitor())
    except KeyboardInterrupt:
        print("\n\n👋 監控已停止")


def run_market_maker():
    """啟動做市商策略"""
    print("\n🤖 啟動做市商策略...\n")
    print("💡 功能開發中，敬請期待！")
    print("   計劃功能：")
    print("   - 自動雙邊掛單")
    print("   - 動態價差調整")
    print("   - 庫存管理")
    print("   - StandX Uptime Program 優化\n")


def run_test_exchanges():
    """測試所有交易所連接"""
    print("\n🧪 測試交易所連接...\n")

    from dotenv import load_dotenv
    from src.adapters.factory import create_adapter

    load_dotenv()

    exchanges = {
        'DEX': {
            'standx': {'required': ['WALLET_PRIVATE_KEY', 'WALLET_ADDRESS']},
            'grvt': {'required': ['GRVT_API_KEY', 'GRVT_API_SECRET']}
        },
        'CEX': {
            'binance': {'required': ['BINANCE_API_KEY', 'BINANCE_API_SECRET']},
            'okx': {'required': ['OKX_API_KEY', 'OKX_API_SECRET', 'OKX_PASSPHRASE']},
            'bitget': {'required': ['BITGET_API_KEY', 'BITGET_API_SECRET', 'BITGET_PASSPHRASE']},
            'bybit': {'required': ['BYBIT_API_KEY', 'BYBIT_API_SECRET']}
        }
    }

    async def test_exchange(exchange_name, exchange_type):
        """測試單個交易所"""
        try:
            config = {'exchange_name': exchange_name}

            if exchange_type == 'CEX':
                config['api_key'] = os.getenv(f'{exchange_name.upper()}_API_KEY')
                config['api_secret'] = os.getenv(f'{exchange_name.upper()}_API_SECRET')

                if exchange_name in ['okx', 'bitget']:
                    config['passphrase'] = os.getenv(f'{exchange_name.upper()}_PASSPHRASE')

            adapter = create_adapter(config)

            # 測試獲取訂單簿
            symbol = 'BTC-USD' if exchange_type == 'DEX' else 'BTC/USDT:USDT'
            orderbook = await adapter.get_orderbook(symbol, limit=5)

            print(f"  ✅ {exchange_name.upper():15} - 連接成功 (Best Bid: ${orderbook.bids[0][0]:,.2f})")
            return True
        except Exception as e:
            print(f"  ❌ {exchange_name.upper():15} - 失敗: {str(e)[:60]}")
            return False

    async def run_tests():
        for exchange_type, exchange_list in exchanges.items():
            print(f"\n📡 測試 {exchange_type} 交易所：\n")

            for exchange_name, info in exchange_list.items():
                # 檢查必需的環境變數
                required_vars = info['required']
                has_config = all(os.getenv(var) for var in required_vars)

                if not has_config:
                    print(f"  ⚠️  {exchange_name.upper():15} - 未配置 (需要: {', '.join(required_vars)})")
                    continue

                await test_exchange(exchange_name, exchange_type)

    print("開始測試所有已配置的交易所...\n")
    try:
        asyncio.run(run_tests())
    except KeyboardInterrupt:
        print("\n\n👋 測試已中斷")

    print("\n✅ 測試完成\n")


def run_multi_dashboard():
    """啟動多交易所主控面板"""
    print("\n📊 啟動多交易所主控面板...\n")
    from src.web.adapter_dashboard import app
    import uvicorn

    print("📍 訪問地址：http://localhost:8000")
    print("⚠️  按 Ctrl+C 停止服務\n")

    try:
        uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
    except KeyboardInterrupt:
        print("\n\n👋 主控面板已停止")




def main():
    """主函數"""
    parser = argparse.ArgumentParser(
        description='多交易所永續合約套利系統',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        'command',
        nargs='?',
        choices=['unified', 'config', 'monitor', 'arb', 'mm', 'test', 'dashboard'],
        help='要執行的功能'
    )

    args = parser.parse_args()

    print_banner()

    # 如果沒有指定命令，顯示選單
    if not args.command:
        print_menu()

        try:
            choice = input("請選擇功能 (1-7) 或按 Ctrl+C 退出: ").strip()
        except KeyboardInterrupt:
            print("\n\n👋 再見！\n")
            return

        command_map = {
            '1': 'unified',
            '2': 'config',
            '3': 'monitor',
            '4': 'arb',
            '5': 'mm',
            '6': 'test',
            '7': 'dashboard'
        }

        args.command = command_map.get(choice)

        if not args.command:
            print("\n❌ 無效的選擇\n")
            return

    # 執行對應功能
    function_map = {
        'unified': run_unified_dashboard,
        'config': run_config_dashboard,
        'monitor': run_arbitrage_monitor,
        'arb': run_arbitrage_dashboard,
        'mm': run_market_maker,
        'test': run_test_exchanges,
        'dashboard': run_multi_dashboard
    }

    try:
        function_map[args.command]()
    except Exception as e:
        print(f"\n❌ 錯誤：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
