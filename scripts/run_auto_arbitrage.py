#!/usr/bin/env python3
"""
自動套利交易系統
Automated Arbitrage Trading System

實時監控 + 自動執行套利交易
"""
import sys
import os
import asyncio
import argparse
from pathlib import Path
from decimal import Decimal

# 添加項目根目錄到路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from src.adapters.factory import create_adapter
from src.monitor.multi_exchange_monitor import MultiExchangeMonitor
from src.strategy.arbitrage_executor import ArbitrageExecutor


def print_banner():
    """顯示歡迎橫幅"""
    print("\n" + "="*80)
    print("🤖 自動套利交易系統")
    print("   Automated Arbitrage Trading System")
    print("="*80 + "\n")


def parse_args():
    """解析命令行參數"""
    parser = argparse.ArgumentParser(
        description="自動套利交易系統",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 僅監控模式（不執行交易）
  python scripts/run_auto_arbitrage.py --dry-run

  # 自動執行套利（模擬模式）
  python scripts/run_auto_arbitrage.py --auto --dry-run

  # 實際交易（危險！）
  python scripts/run_auto_arbitrage.py --auto --no-dry-run

  # 自定義參數
  python scripts/run_auto_arbitrage.py --auto --max-position 0.05 --min-profit 10
        """
    )

    parser.add_argument(
        '--auto',
        action='store_true',
        help='啟用自動執行套利'
    )

    parser.add_argument(
        '--dry-run',
        dest='dry_run',
        action='store_true',
        default=True,
        help='模擬模式（不實際下單，默認開啟）'
    )

    parser.add_argument(
        '--no-dry-run',
        dest='dry_run',
        action='store_false',
        help='關閉模擬模式（實際下單，危險！）'
    )

    parser.add_argument(
        '--max-position',
        type=float,
        default=0.1,
        help='單次最大交易量（默認: 0.1）'
    )

    parser.add_argument(
        '--min-profit',
        type=float,
        default=5.0,
        help='最小利潤閾值 USD（默認: 5.0）'
    )

    parser.add_argument(
        '--min-profit-pct',
        type=float,
        default=0.1,
        help='最小套利利潤百分比（默認: 0.1%%）'
    )

    parser.add_argument(
        '--update-interval',
        type=float,
        default=2.0,
        help='市場數據更新間隔（秒，默認: 2.0）'
    )

    return parser.parse_args()


def setup_exchanges():
    """設置交易所連接"""
    print("🔌 正在連接交易所...\n")

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

    adapters = {}
    symbols = []

    # 嘗試連接 DEX
    for exchange in dex_exchanges:
        try:
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

    # 去重 symbols
    symbols = list(set(symbols))

    if len(adapters) < 2:
        print(f"\n❌ 錯誤：至少需要 2 個交易所才能進行套利")
        print(f"   當前已連接: {len(adapters)} 個")
        print(f"   請在 .env 中配置更多交易所\n")
        sys.exit(1)

    print(f"\n✅ 成功連接 {len(adapters)} 個交易所")
    print(f"   交易所: {', '.join(adapters.keys())}")
    print(f"   交易對: {', '.join(symbols)}\n")

    return adapters, symbols


async def main():
    """主函數"""
    args = parse_args()
    print_banner()

    # 設置交易所
    adapters, symbols = setup_exchanges()

    # 顯示配置
    print("="*80)
    print("⚙️  系統配置")
    print("="*80)
    print(f"  自動執行: {'✅ 啟用' if args.auto else '❌ 禁用（僅監控）'}")
    print(f"  模擬模式: {'✅ 開啟（安全）' if args.dry_run else '❌ 關閉（實際交易！）'}")
    print(f"  最大倉位: {args.max_position}")
    print(f"  最小利潤: ${args.min_profit}")
    print(f"  利潤閾值: {args.min_profit_pct}%")
    print(f"  更新間隔: {args.update_interval}秒")
    print("="*80 + "\n")

    # 安全確認
    if args.auto and not args.dry_run:
        print("⚠️  警告：您即將啟用實際交易模式！")
        print("   這將使用真實資金進行交易，可能導致損失。")
        response = input("   確定繼續嗎？(輸入 'YES' 確認): ")
        if response != 'YES':
            print("\n❌ 已取消\n")
            return

    # 創建監控器
    monitor = MultiExchangeMonitor(
        adapters=adapters,
        symbols=symbols,
        update_interval=args.update_interval,
        min_profit_pct=args.min_profit_pct
    )

    # 創建執行器
    executor = ArbitrageExecutor(
        monitor=monitor,
        adapters=adapters,
        max_position_size=Decimal(str(args.max_position)),
        min_profit_usd=Decimal(str(args.min_profit)),
        execution_timeout=5.0,
        enable_auto_execute=args.auto,
        dry_run=args.dry_run
    )

    # 啟動系統
    try:
        await monitor.start()
        await executor.start()

        print("\n✅ 系統已啟動")
        print("   按 Ctrl+C 停止\n")

        # 保持運行
        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        print("\n\n🛑 收到停止信號...")

    finally:
        # 停止系統
        await executor.stop()
        await monitor.stop()
        print("\n👋 系統已停止\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 再見！\n")
