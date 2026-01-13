#!/usr/bin/env python3
"""
自動化套利控制台
Automated Arbitrage Control Panel

一鍵啟動，自動監控所有已配置交易所
動態添加交易所後自動開始監控
"""
import asyncio
import json
import os
from datetime import datetime
from typing import Dict, List, Optional
from decimal import Decimal
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv, set_key, unset_key
import logging

# Import modules
import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
from src.adapters.factory import create_adapter
from src.adapters.base_adapter import BasePerpAdapter
from src.monitor.multi_exchange_monitor import MultiExchangeMonitor
from src.strategy.arbitrage_executor import ArbitrageExecutor
from src.strategy.market_maker_executor import MarketMakerExecutor, MMConfig, ExecutorStatus
from src.strategy.hedge_engine import HedgeEngine, HedgeConfig
from src.strategy.mm_state import MMState, FillEvent
from src.utils.mm_config_manager import get_mm_config, MMConfigManager

# 全局變量
monitor: Optional[MultiExchangeMonitor] = None
executor: Optional[ArbitrageExecutor] = None
mm_executor: Optional[MarketMakerExecutor] = None
adapters: Dict[str, BasePerpAdapter] = {}
connected_clients: List[WebSocket] = []
system_status = {
    'running': False,
    'auto_execute': False,
    'dry_run': True,
    'started_at': None
}
mm_status = {
    'running': False,
    'status': 'stopped',
    'dry_run': True,
    'order_size_btc': 0.001,
    'order_distance_bps': 8,
}

env_file = Path(__file__).parent.parent.parent / ".env"

# 日誌設置
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ConfigManager:
    """配置管理器"""

    def __init__(self, env_file: Path):
        self.env_file = env_file
        if not env_file.exists():
            env_file.touch()
        load_dotenv(env_file)

    def get_all_configs(self) -> Dict:
        """獲取所有配置"""
        load_dotenv(self.env_file, override=True)

        configs = {'dex': {}, 'cex': {}}

        # DEX 配置
        if os.getenv('WALLET_PRIVATE_KEY'):
            configs['dex']['standx'] = {
                'name': 'StandX',
                'configured': True,
                'private_key_masked': self._mask_key(os.getenv('WALLET_PRIVATE_KEY', '')),
                'address': os.getenv('WALLET_ADDRESS', ''),
                'testnet': os.getenv('STANDX_TESTNET', 'false').lower() == 'true'
            }

        if os.getenv('GRVT_API_KEY'):
            configs['dex']['grvt'] = {
                'name': 'GRVT',
                'configured': True,
                'api_key_masked': self._mask_key(os.getenv('GRVT_API_KEY', '')),
                'testnet': os.getenv('GRVT_TESTNET', 'false').lower() == 'true'
            }

        # CEX 配置
        for exchange in ['binance', 'okx', 'bitget', 'bybit']:
            api_key = os.getenv(f'{exchange.upper()}_API_KEY')
            if api_key:
                config = {
                    'name': exchange.title(),
                    'configured': True,
                    'api_key_masked': self._mask_key(api_key),
                    'testnet': os.getenv(f'{exchange.upper()}_TESTNET', 'false').lower() == 'true'
                }
                if exchange in ['okx', 'bitget']:
                    passphrase = os.getenv(f'{exchange.upper()}_PASSPHRASE')
                    if passphrase:
                        config['passphrase_masked'] = self._mask_key(passphrase)
                configs['cex'][exchange] = config

        return configs

    def save_config(self, exchange_name: str, exchange_type: str, config: dict, testnet: bool = False):
        """保存配置並立即啟動監控"""
        if exchange_type == 'dex':
            if exchange_name == 'standx':
                set_key(self.env_file, 'WALLET_PRIVATE_KEY', config.get('private_key', ''))
                set_key(self.env_file, 'WALLET_ADDRESS', config.get('address', ''))
                set_key(self.env_file, 'STANDX_TESTNET', str(testnet).lower())
            elif exchange_name == 'grvt':
                set_key(self.env_file, 'GRVT_API_KEY', config.get('api_key', ''))
                set_key(self.env_file, 'GRVT_API_SECRET', config.get('api_secret', ''))
                set_key(self.env_file, 'GRVT_TESTNET', str(testnet).lower())
        else:
            prefix = exchange_name.upper()
            set_key(self.env_file, f'{prefix}_API_KEY', config.get('api_key', ''))
            set_key(self.env_file, f'{prefix}_API_SECRET', config.get('api_secret', ''))
            set_key(self.env_file, f'{prefix}_TESTNET', str(testnet).lower())

            if exchange_name in ['okx', 'bitget']:
                passphrase = config.get('passphrase', '')
                if passphrase:
                    set_key(self.env_file, f'{prefix}_PASSPHRASE', passphrase)

        load_dotenv(self.env_file, override=True)

    def delete_config(self, exchange_name: str, exchange_type: str):
        """刪除配置"""
        if exchange_type == 'dex':
            if exchange_name == 'standx':
                keys = ['WALLET_PRIVATE_KEY', 'WALLET_ADDRESS', 'STANDX_TESTNET']
            else:  # grvt
                keys = ['GRVT_API_KEY', 'GRVT_API_SECRET', 'GRVT_TESTNET']
        else:
            prefix = exchange_name.upper()
            keys = [f'{prefix}_API_KEY', f'{prefix}_API_SECRET', f'{prefix}_TESTNET']
            if exchange_name in ['okx', 'bitget']:
                keys.append(f'{prefix}_PASSPHRASE')

        for key in keys:
            unset_key(self.env_file, key)
            # 同時從環境變量中刪除
            if key in os.environ:
                del os.environ[key]

        load_dotenv(self.env_file, override=True)

    @staticmethod
    def _mask_key(key: str) -> str:
        """遮罩敏感信息"""
        if len(key) <= 8:
            return '*' * len(key)
        return key[:4] + '*' * (len(key) - 8) + key[-4:]


config_manager = ConfigManager(env_file)


async def init_system():
    """初始化系統 - 自動加載所有已配置的交易所"""
    global monitor, executor, adapters, system_status

    logger.info("🚀 正在初始化系統...")

    # 加載配置
    configs = config_manager.get_all_configs()

    # 統一符號格式 - Adapter 會自動轉換為各交易所的格式
    # BTC-USD -> Binance: BTC/USDT:USDT, StandX: BTC-USD
    unified_symbols = ['BTC-USD', 'ETH-USD']

    adapters = {}

    # 加載 DEX
    for exchange_name, config in configs['dex'].items():
        try:
            adapter_config = {
                'exchange_name': exchange_name,
                'testnet': config.get('testnet', False)
            }

            # 添加特定交易所的配置
            if exchange_name == 'standx':
                private_key = os.getenv('WALLET_PRIVATE_KEY')
                address = os.getenv('WALLET_ADDRESS')
                if private_key:
                    adapter_config['private_key'] = private_key
                if address:
                    adapter_config['wallet_address'] = address
            elif exchange_name == 'grvt':
                api_key = os.getenv('GRVT_API_KEY')
                api_secret = os.getenv('GRVT_API_SECRET')
                if api_key:
                    adapter_config['api_key'] = api_key
                if api_secret:
                    adapter_config['api_secret'] = api_secret

            adapter = create_adapter(adapter_config)

            # 連接到交易所
            if hasattr(adapter, 'connect'):
                connected = await adapter.connect()
                if not connected:
                    logger.warning(f"  ⚠️  {exchange_name.upper()} - 連接失敗")
                    continue

            adapters[exchange_name.upper()] = adapter
            logger.info(f"  ✅ {exchange_name.upper()} - 已連接")
        except Exception as e:
            logger.warning(f"  ⚠️  {exchange_name.upper()} - 跳過: {str(e)[:50]}")

    # 加載 CEX
    for exchange_name, config in configs['cex'].items():
        try:
            adapter_config = {
                'exchange_name': exchange_name,
                'api_key': os.getenv(f'{exchange_name.upper()}_API_KEY'),
                'api_secret': os.getenv(f'{exchange_name.upper()}_API_SECRET'),
                'testnet': config.get('testnet', False)
            }

            if exchange_name in ['okx', 'bitget']:
                passphrase = os.getenv(f'{exchange_name.upper()}_PASSPHRASE')
                if passphrase:
                    adapter_config['passphrase'] = passphrase

            adapter = create_adapter(adapter_config)

            # 連接到交易所
            if hasattr(adapter, 'connect'):
                connected = await adapter.connect()
                if not connected:
                    logger.warning(f"  ⚠️  {exchange_name.upper()} - 連接失敗")
                    continue

            adapters[exchange_name.upper()] = adapter
            logger.info(f"  ✅ {exchange_name.upper()} - 已連接")
        except Exception as e:
            logger.warning(f"  ⚠️  {exchange_name.upper()} - 跳過: {str(e)[:50]}")

    if len(adapters) == 0:
        logger.warning("⚠️  沒有已配置的交易所")
        return

    # 創建監控器 - 使用統一的 symbol 格式
    monitor = MultiExchangeMonitor(
        adapters=adapters,
        symbols=unified_symbols,
        update_interval=2.0,
        min_profit_pct=0.1
    )

    # 創建執行器（默認僅監控）
    executor = ArbitrageExecutor(
        monitor=monitor,
        adapters=adapters,
        max_position_size=Decimal("0.1"),
        min_profit_usd=Decimal("5.0"),
        enable_auto_execute=False,  # 默認不自動執行
        dry_run=True
    )

    # 啟動監控
    await monitor.start()
    await executor.start()

    system_status['running'] = True
    system_status['started_at'] = datetime.now().isoformat()

    logger.info(f"✅ 系統已啟動 - 監控 {len(adapters)} 個交易所")


async def add_exchange(exchange_name: str, exchange_type: str):
    """動態添加交易所到監控系統"""
    global monitor, adapters

    if not monitor:
        return

    try:
        # 創建適配器
        if exchange_type == 'dex':
            adapter_config = {
                'exchange_name': exchange_name,
                'testnet': os.getenv(f'{exchange_name.upper()}_TESTNET', 'false').lower() == 'true'
            }

            # 添加 DEX 特定配置
            if exchange_name == 'standx':
                private_key = os.getenv('WALLET_PRIVATE_KEY')
                address = os.getenv('WALLET_ADDRESS')
                if private_key:
                    adapter_config['private_key'] = private_key
                if address:
                    adapter_config['wallet_address'] = address
            elif exchange_name == 'grvt':
                api_key = os.getenv('GRVT_API_KEY')
                api_secret = os.getenv('GRVT_API_SECRET')
                if api_key:
                    adapter_config['api_key'] = api_key
                if api_secret:
                    adapter_config['api_secret'] = api_secret
        else:
            adapter_config = {
                'exchange_name': exchange_name,
                'api_key': os.getenv(f'{exchange_name.upper()}_API_KEY'),
                'api_secret': os.getenv(f'{exchange_name.upper()}_API_SECRET'),
                'testnet': os.getenv(f'{exchange_name.upper()}_TESTNET', 'false').lower() == 'true'
            }

            if exchange_name in ['okx', 'bitget']:
                passphrase = os.getenv(f'{exchange_name.upper()}_PASSPHRASE')
                if passphrase:
                    adapter_config['passphrase'] = passphrase

        adapter = create_adapter(adapter_config)

        # 連接到交易所
        if hasattr(adapter, 'connect'):
            connected = await adapter.connect()
            if not connected:
                logger.error(f"❌ {exchange_name.upper()} 連接失敗")
                return False

        adapters[exchange_name.upper()] = adapter

        # 更新監控器
        monitor.adapters[exchange_name.upper()] = adapter

        logger.info(f"✅ {exchange_name.upper()} 已添加到監控系統")
        return True

    except Exception as e:
        logger.error(f"❌ 添加 {exchange_name.upper()} 失敗: {e}")
        return False


async def remove_exchange(exchange_name: str):
    """從監控系統移除交易所"""
    global monitor, adapters

    if not monitor:
        return

    exchange_key = exchange_name.upper()

    # 斷開連接
    if exchange_key in adapters:
        adapter = adapters[exchange_key]
        if hasattr(adapter, 'disconnect'):
            try:
                await adapter.disconnect()
            except Exception as e:
                logger.warning(f"⚠️  斷開 {exchange_key} 連接時出錯: {e}")
        del adapters[exchange_key]

    if exchange_key in monitor.adapters:
        del monitor.adapters[exchange_key]

    logger.info(f"✅ {exchange_key} 已從監控系統移除")


def serialize_for_json(obj):
    """將 Decimal 和其他不能序列化的類型轉換為可序列化的類型"""
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {k: serialize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [serialize_for_json(item) for item in obj]
    elif isinstance(obj, (int, float, str, bool, type(None))):
        return obj
    else:
        return str(obj)


async def broadcast_data():
    """廣播數據到所有連接的客戶端"""
    logger.info("📡 廣播任務已啟動")
    while True:
        try:
            client_count = len(connected_clients)
            if monitor and client_count > 0:
                # 準備數據
                data = {
                    'timestamp': datetime.now().isoformat(),
                    'system_status': system_status,
                    'market_data': {},
                    'orderbooks': {},
                    'opportunities': [],
                    'stats': serialize_for_json(dict(monitor.stats)) if monitor else {},
                    'executor_stats': serialize_for_json(executor.get_stats()) if executor else {}
                }

                # 市場數據
                for exchange_name, symbols_data in monitor.market_data.items():
                    data['market_data'][exchange_name] = {}
                    for symbol, market in symbols_data.items():
                        data['market_data'][exchange_name][symbol] = {
                            'best_bid': float(market.best_bid),
                            'best_ask': float(market.best_ask),
                            'bid_size': float(market.bid_size),
                            'ask_size': float(market.ask_size),
                            'spread_pct': float(market.spread_pct)
                        }

                # 獲取 StandX 訂單簿深度
                if 'STANDX' in adapters:
                    try:
                        standx = adapters['STANDX']
                        ob = await standx.get_orderbook('BTC-USD')
                        # ob 是 Orderbook dataclass，用屬性而非字典訪問
                        if ob and ob.bids and ob.asks:
                            bids = [[float(b[0]), float(b[1])] for b in ob.bids[:10]]
                            asks = [[float(a[0]), float(a[1])] for a in ob.asks[:10]]
                            data['orderbooks']['STANDX'] = {
                                'BTC-USD': {
                                    'bids': bids,
                                    'asks': asks
                                }
                            }
                    except Exception as e:
                        logger.warning(f"獲取 StandX 訂單簿失敗: {e}")

                # Debug: 打印發送的數據
                if data['market_data']:
                    logger.debug(f"Broadcasting market data: {list(data['market_data'].keys())}")

                # 套利機會
                for opp in monitor.arbitrage_opportunities:
                    data['opportunities'].append({
                        'buy_exchange': opp.buy_exchange,
                        'sell_exchange': opp.sell_exchange,
                        'symbol': opp.symbol,
                        'buy_price': float(opp.buy_price),
                        'sell_price': float(opp.sell_price),
                        'profit': float(opp.profit),
                        'profit_pct': float(opp.profit_pct),
                        'max_quantity': float(opp.max_quantity)
                    })

                # 做市商狀態
                data['mm_status'] = mm_status.copy()
                if mm_executor:
                    data['mm_executor'] = serialize_for_json(mm_executor.to_dict())

                # 做市商實時倉位
                positions = {
                    'standx': {'btc': 0, 'equity': 0},
                    'binance': {'btc': 0, 'usdt': 0},
                }
                if 'STANDX' in adapters:
                    try:
                        standx = adapters['STANDX']
                        standx_positions = await standx.get_positions('BTC-USD')
                        for pos in standx_positions:
                            if 'BTC' in pos.symbol:
                                qty = float(pos.size)
                                if pos.side == 'short':
                                    qty = -qty
                                positions['standx']['btc'] = qty
                        balance = await standx.get_balance()
                        positions['standx']['equity'] = float(balance.equity)
                    except:
                        pass
                if 'BINANCE' in adapters:
                    try:
                        binance = adapters['BINANCE']
                        binance_positions = await binance.get_positions('BTC/USDT:USDT')
                        for pos in binance_positions:
                            if 'BTC' in pos.symbol:
                                qty = float(pos.size)
                                if pos.side == 'short':
                                    qty = -qty
                                positions['binance']['btc'] = qty
                        balance = await binance.get_balance()
                        positions['binance']['usdt'] = float(balance.available_balance)
                    except:
                        pass
                positions['net_btc'] = positions['standx']['btc'] + positions['binance']['btc']
                positions['is_hedged'] = abs(positions['net_btc']) < 0.0001
                data['mm_positions'] = positions

                # 廣播
                disconnected = []
                for client in connected_clients:
                    try:
                        await client.send_json(data)
                    except Exception as e:
                        logger.debug(f"發送失敗: {e}")
                        disconnected.append(client)

                # 移除斷開的客戶端
                for client in disconnected:
                    connected_clients.remove(client)

            await asyncio.sleep(1)  # 1秒更新一次

        except Exception as e:
            logger.error(f"Broadcast error: {e}")
            await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用生命週期管理"""
    # 啟動
    await init_system()
    asyncio.create_task(broadcast_data())
    yield
    # 關閉
    if monitor:
        await monitor.stop()
    if executor:
        await executor.stop()


# FastAPI app
app = FastAPI(lifespan=lifespan)

# 註冊模組路由
from src.web.modules.orderbook_monitor import register_routes as register_orderbook_routes
from src.web.modules.strategy_analyzer import register_routes as register_strategy_routes
register_orderbook_routes(app, lambda: adapters)
register_strategy_routes(app, lambda: adapters)


@app.get("/", response_class=HTMLResponse)
async def root():
    """首頁 - 帶分頁切換"""
    return """
    <!DOCTYPE html>
    <html lang="zh-TW">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>交易控制台</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: 'SF Mono', -apple-system, BlinkMacSystemFont, monospace;
                background: #0a0e14;
                color: #e4e6eb;
                min-height: 100vh;
            }

            /* ===== 頂部導航 ===== */
            .top-nav {
                background: #1a1f2e;
                border-bottom: 1px solid #2a3347;
                padding: 0 20px;
                display: flex;
                align-items: center;
                height: 50px;
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                z-index: 1000;
            }
            .nav-logo {
                font-size: 18px;
                font-weight: 700;
                color: #667eea;
                margin-right: 40px;
            }
            .nav-tabs {
                display: flex;
                gap: 5px;
            }
            .nav-tab {
                padding: 12px 24px;
                background: transparent;
                border: none;
                color: #9ca3af;
                font-size: 14px;
                font-weight: 600;
                cursor: pointer;
                border-bottom: 2px solid transparent;
                transition: all 0.2s;
            }
            .nav-tab:hover {
                color: #e4e6eb;
                background: #2a3347;
            }
            .nav-tab.active {
                color: #667eea;
                border-bottom-color: #667eea;
            }
            .nav-status {
                margin-left: auto;
                display: flex;
                align-items: center;
                gap: 15px;
                font-size: 12px;
            }
            .status-dot {
                width: 8px;
                height: 8px;
                border-radius: 50%;
                background: #10b981;
            }
            .status-dot.offline { background: #ef4444; }

            /* ===== 主內容區 ===== */
            .main-content {
                margin-top: 50px;
                padding: 20px;
            }
            .page { display: none; }
            .page.active { display: block; }

            /* ===== 通用樣式 ===== */
            .card {
                background: #1a1f2e;
                border: 1px solid #2a3347;
                border-radius: 8px;
                padding: 15px;
            }
            .card-title {
                font-size: 13px;
                color: #667eea;
                margin-bottom: 12px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }
            .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
            .grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 15px; }
            .grid-4 { display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 15px; }
            .stat-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #2a334755; }
            .stat-row:last-child { border-bottom: none; }
            .stat-label { color: #9ca3af; font-size: 12px; }
            .stat-value { font-weight: 600; font-size: 13px; }
            .text-green { color: #10b981; }
            .text-red { color: #ef4444; }
            .text-yellow { color: #f59e0b; }

            /* ===== 套利頁面 ===== */
            .arb-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 20px;
            }
            .arb-title { font-size: 24px; font-weight: 700; }
            .arb-controls { display: flex; gap: 15px; align-items: center; }
            .toggle-group { display: flex; align-items: center; gap: 8px; font-size: 13px; }
            .toggle {
                width: 44px; height: 22px;
                background: #2a3347;
                border-radius: 11px;
                position: relative;
                cursor: pointer;
                transition: background 0.2s;
            }
            .toggle.active { background: #10b981; }
            .toggle::after {
                content: '';
                position: absolute;
                width: 18px; height: 18px;
                background: white;
                border-radius: 50%;
                top: 2px; left: 2px;
                transition: transform 0.2s;
            }
            .toggle.active::after { transform: translateX(22px); }

            .opportunity-card {
                background: linear-gradient(135deg, #10b981 0%, #059669 100%);
                padding: 15px;
                border-radius: 8px;
                margin-bottom: 10px;
                color: white;
            }
            .opp-header { display: flex; justify-content: space-between; margin-bottom: 10px; }
            .opp-symbol { font-size: 16px; font-weight: 700; }
            .opp-profit { font-size: 20px; font-weight: 700; }
            .opp-details { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; font-size: 12px; }

            .price-table { width: 100%; border-collapse: collapse; font-size: 13px; }
            .price-table th { color: #9ca3af; font-weight: 600; text-align: left; padding: 10px; border-bottom: 1px solid #2a3347; }
            .price-table td { padding: 10px; border-bottom: 1px solid #2a334755; }
            .badge { padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
            .badge-online { background: #10b98133; color: #10b981; }
            .badge-dex { background: #10b981; color: white; }
            .badge-cex { background: #3b82f6; color: white; }

            /* ===== 做市商頁面 ===== */
            .mm-grid {
                display: grid;
                grid-template-columns: 1fr 1fr 1fr;
                grid-template-rows: auto auto;
                gap: 15px;
            }
            .mm-header-bar {
                grid-column: 1 / -1;
                background: linear-gradient(135deg, #1a1f2e 0%, #0f1419 100%);
                border: 1px solid #2a3347;
                border-radius: 8px;
                padding: 15px 20px;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            .mm-title { font-size: 20px; font-weight: 700; color: #667eea; }
            .mm-stats { display: flex; gap: 40px; }
            .mm-stat { text-align: center; }
            .mm-stat-value { font-size: 22px; font-weight: 700; }
            .mm-stat-label { font-size: 11px; color: #9ca3af; text-transform: uppercase; }

            /* 訂單簿 */
            .orderbook { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
            .ob-side { font-size: 12px; }
            .ob-header { display: grid; grid-template-columns: 1fr 1fr; padding: 5px; color: #9ca3af; font-size: 10px; border-bottom: 1px solid #2a3347; }
            .ob-row { display: grid; grid-template-columns: 1fr 1fr; padding: 3px 5px; position: relative; }
            .ob-row .bg { position: absolute; top: 0; bottom: 0; opacity: 0.15; }
            .ob-row.bid .bg { background: #10b981; right: 0; }
            .ob-row.ask .bg { background: #ef4444; left: 0; }
            .ob-price-bid { color: #10b981; }
            .ob-price-ask { color: #ef4444; }
            .ob-size { text-align: right; color: #9ca3af; }
            .spread-bar { background: #0f1419; padding: 8px; border-radius: 4px; text-align: center; margin-top: 8px; font-size: 13px; }

            /* Uptime 圓圈 */
            .uptime-circle {
                width: 100px; height: 100px;
                border-radius: 50%;
                border: 6px solid #2a3347;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                margin: 0 auto 15px;
            }
            .uptime-circle.boosted { border-color: #10b981; }
            .uptime-circle.standard { border-color: #f59e0b; }
            .uptime-pct { font-size: 24px; font-weight: 700; }
            .uptime-tier { font-size: 10px; text-transform: uppercase; }
            .tier-boosted { color: #10b981; }
            .tier-standard { color: #f59e0b; }
            .tier-inactive { color: #ef4444; }

            /* 建議報價 */
            .quote-box { background: #0f1419; border-radius: 6px; padding: 12px; margin-bottom: 8px; }
            .quote-label { font-size: 10px; color: #9ca3af; text-transform: uppercase; }
            .quote-price { font-size: 16px; font-weight: 600; }
            .quote-bid { color: #10b981; }
            .quote-ask { color: #ef4444; }

            /* 深度條 */
            .depth-bar { display: flex; height: 24px; border-radius: 4px; overflow: hidden; margin: 10px 0; }
            .depth-bid { background: #10b981; display: flex; align-items: center; justify-content: flex-end; padding-right: 6px; font-size: 10px; font-weight: 600; }
            .depth-ask { background: #ef4444; display: flex; align-items: center; padding-left: 6px; font-size: 10px; font-weight: 600; }

            /* 風險標籤 */
            .risk-row { display: flex; justify-content: space-between; padding: 8px; background: #0f1419; border-radius: 4px; margin-bottom: 6px; font-size: 12px; }
            .risk-badge { padding: 3px 8px; border-radius: 4px; font-size: 10px; font-weight: 600; text-transform: uppercase; }
            .risk-low { background: #10b98133; color: #10b981; }
            .risk-medium { background: #f59e0b33; color: #f59e0b; }
            .risk-high { background: #ef444433; color: #ef4444; }

            /* 模擬統計 */
            .sim-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
            .sim-stat { background: #0f1419; border-radius: 6px; padding: 10px; text-align: center; }
            .sim-value { font-size: 18px; font-weight: 700; }
            .sim-label { font-size: 9px; color: #9ca3af; text-transform: uppercase; margin-top: 2px; }

            /* 進度條 */
            .progress-bar { background: #0f1419; border-radius: 4px; height: 20px; position: relative; overflow: hidden; margin-bottom: 8px; }
            .progress-fill { height: 100%; border-radius: 4px; transition: width 0.3s; }
            .progress-fill.mm1 { background: linear-gradient(90deg, #667eea, #764ba2); }
            .progress-fill.mm2 { background: linear-gradient(90deg, #10b981, #059669); }
            .progress-text { position: absolute; right: 8px; top: 50%; transform: translateY(-50%); font-size: 10px; font-weight: 600; }
            .progress-label { font-size: 10px; color: #9ca3af; margin-bottom: 4px; }

            /* ===== 設定頁面 ===== */
            .settings-section { margin-bottom: 30px; }
            .settings-title { font-size: 18px; margin-bottom: 15px; }
            .exchange-card {
                background: #0f1419;
                border: 1px solid #2a3347;
                border-radius: 8px;
                padding: 15px;
                margin-bottom: 10px;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            .exchange-info { display: flex; align-items: center; gap: 12px; }
            .exchange-name { font-size: 16px; font-weight: 600; }
            .exchange-details { font-size: 11px; color: #9ca3af; margin-top: 3px; }
            .btn { padding: 8px 16px; border: none; border-radius: 6px; font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.2s; }
            .btn-primary { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; }
            .btn-danger { background: #ef4444; color: white; }
            .btn:hover { transform: translateY(-1px); }

            .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
            .form-group { display: flex; flex-direction: column; }
            .form-group label { font-size: 12px; color: #9ca3af; margin-bottom: 5px; }
            .form-group input, .form-group select {
                padding: 10px;
                background: #0f1419;
                border: 1px solid #2a3347;
                border-radius: 6px;
                color: #e4e6eb;
                font-size: 13px;
            }
            .form-group input:focus, .form-group select:focus { outline: none; border-color: #667eea; }
        </style>
    </head>
    <body>
        <!-- 頂部導航 -->
        <nav class="top-nav">
            <div class="nav-logo">Trading Console</div>
            <div class="nav-tabs">
                <button class="nav-tab active" onclick="switchPage('arbitrage')">套利監控</button>
                <button class="nav-tab" onclick="switchPage('marketmaker')">做市商</button>
                <button class="nav-tab" onclick="switchPage('settings')">設定</button>
            </div>
            <div class="nav-status">
                <span class="status-dot" id="statusDot"></span>
                <span id="statusText">連接中...</span>
                <span style="color: #9ca3af;">|</span>
                <span id="uptimeDisplay">0h 0m</span>
            </div>
        </nav>

        <div class="main-content">
            <!-- ==================== 套利頁面 ==================== -->
            <div id="page-arbitrage" class="page active">
                <div class="arb-header">
                    <div class="arb-title">套利監控</div>
                    <div class="arb-controls">
                        <div class="toggle-group">
                            <span>自動執行</span>
                            <div class="toggle" id="autoExecToggle" onclick="toggleAutoExec()"></div>
                        </div>
                        <div class="toggle-group">
                            <span>實盤模式</span>
                            <div class="toggle" id="liveToggle" onclick="toggleLive()"></div>
                        </div>
                    </div>
                </div>

                <div class="grid-3" style="margin-bottom: 20px;">
                    <div class="card">
                        <div class="card-title">系統狀態</div>
                        <div class="stat-row"><span class="stat-label">運行狀態</span><span class="stat-value text-green" id="arbStatus">運行中</span></div>
                        <div class="stat-row"><span class="stat-label">交易所數量</span><span class="stat-value" id="arbExchangeCount">0</span></div>
                        <div class="stat-row"><span class="stat-label">更新次數</span><span class="stat-value" id="arbUpdates">0</span></div>
                    </div>
                    <div class="card">
                        <div class="card-title">套利統計</div>
                        <div class="stat-row"><span class="stat-label">發現機會</span><span class="stat-value" id="arbOppsFound">0</span></div>
                        <div class="stat-row"><span class="stat-label">當前機會</span><span class="stat-value text-green" id="arbCurrentOpps">0</span></div>
                        <div class="stat-row"><span class="stat-label">執行次數</span><span class="stat-value" id="arbExecCount">0</span></div>
                    </div>
                    <div class="card">
                        <div class="card-title">收益統計</div>
                        <div class="stat-row"><span class="stat-label">成功率</span><span class="stat-value" id="arbSuccessRate">0%</span></div>
                        <div class="stat-row"><span class="stat-label">總利潤</span><span class="stat-value text-green" id="arbProfit">$0.00</span></div>
                        <div class="stat-row"><span class="stat-label">模式</span><span class="stat-value" id="arbMode">模擬</span></div>
                    </div>
                </div>

                <div class="grid-2" style="gap: 20px;">
                    <div class="card">
                        <div class="card-title">實時套利機會</div>
                        <div id="arbOpportunities">
                            <p style="color: #9ca3af; text-align: center; padding: 30px;">等待套利機會...</p>
                        </div>
                    </div>
                    <div class="card">
                        <div class="card-title">交易所價格</div>
                        <table class="price-table">
                            <thead>
                                <tr><th>交易所</th><th>BTC Bid</th><th>BTC Ask</th><th>狀態</th></tr>
                            </thead>
                            <tbody id="arbPriceTable">
                                <tr><td colspan="4" style="text-align: center; color: #9ca3af;">載入中...</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- ==================== 做市商頁面 ==================== -->
            <div id="page-marketmaker" class="page">
                <div class="mm-grid">
                    <div class="mm-header-bar">
                        <div class="mm-title">StandX 做市商</div>
                        <div class="mm-stats">
                            <div class="mm-stat">
                                <div class="mm-stat-value" id="mmMidPrice">-</div>
                                <div class="mm-stat-label">BTC-USD 中間價</div>
                            </div>
                            <div class="mm-stat">
                                <div class="mm-stat-value text-green" id="mmSpread">-</div>
                                <div class="mm-stat-label">價差 (bps)</div>
                            </div>
                            <div class="mm-stat">
                                <div class="mm-stat-value" id="mmRuntime">0m</div>
                                <div class="mm-stat-label">運行時間</div>
                            </div>
                        </div>
                        <div class="mm-controls" style="display: flex; gap: 10px; align-items: center;">
                            <span id="mmStatusBadge" class="badge" style="background: #2a3347; padding: 6px 12px;">停止</span>
                            <button id="mmStartBtn" class="btn btn-primary" onclick="startMM()">啟動</button>
                            <button id="mmStopBtn" class="btn btn-danger" onclick="stopMM()" style="display:none;">停止</button>
                        </div>
                    </div>

                    <!-- 控制面板 -->
                    <div class="card" style="grid-column: 1 / -1;">
                        <div class="card-title">策略配置 <span id="mmConfigStatus" style="font-size: 10px; color: #9ca3af; margin-left: 10px;"></span></div>
                        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 15px;">
                            <!-- 報價參數 -->
                            <div style="background: #0f1419; padding: 12px; border-radius: 6px;">
                                <div style="font-size: 11px; color: #6b7280; margin-bottom: 8px;">報價參數</div>
                                <div style="display: flex; flex-direction: column; gap: 8px;">
                                    <div style="display: flex; align-items: center; justify-content: space-between;">
                                        <label style="font-size: 11px; color: #9ca3af;">掛單距離</label>
                                        <div style="display: flex; align-items: center; gap: 4px;">
                                            <input type="number" id="mmOrderDistance" value="8" step="1" min="1" max="20" style="width: 50px; padding: 4px; background: #1a1f2e; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                                            <span style="font-size: 10px; color: #6b7280;">bps</span>
                                        </div>
                                    </div>
                                    <div style="display: flex; align-items: center; justify-content: space-between;">
                                        <label style="font-size: 11px; color: #9ca3af;">撤單距離</label>
                                        <div style="display: flex; align-items: center; gap: 4px;">
                                            <input type="number" id="mmCancelDistance" value="3" step="1" min="1" max="10" style="width: 50px; padding: 4px; background: #1a1f2e; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                                            <span style="font-size: 10px; color: #6b7280;">bps</span>
                                        </div>
                                    </div>
                                    <div style="display: flex; align-items: center; justify-content: space-between;">
                                        <label style="font-size: 11px; color: #9ca3af;">重掛距離</label>
                                        <div style="display: flex; align-items: center; gap: 4px;">
                                            <input type="number" id="mmRebalanceDistance" value="12" step="1" min="10" max="30" style="width: 50px; padding: 4px; background: #1a1f2e; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                                            <span style="font-size: 10px; color: #6b7280;">bps</span>
                                        </div>
                                    </div>
                                    <div style="display: flex; align-items: center; justify-content: space-between;">
                                        <label style="font-size: 11px; color: #9ca3af;">隊列風控</label>
                                        <div style="display: flex; align-items: center; gap: 4px;">
                                            <input type="number" id="mmQueuePositionLimit" value="3" step="1" min="1" max="10" style="width: 50px; padding: 4px; background: #1a1f2e; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                                            <span style="font-size: 10px; color: #6b7280;">檔</span>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <!-- 倉位參數 -->
                            <div style="background: #0f1419; padding: 12px; border-radius: 6px;">
                                <div style="font-size: 11px; color: #6b7280; margin-bottom: 8px;">倉位參數</div>
                                <div style="display: flex; flex-direction: column; gap: 8px;">
                                    <div style="display: flex; align-items: center; justify-content: space-between;">
                                        <label style="font-size: 11px; color: #9ca3af;">訂單大小</label>
                                        <div style="display: flex; align-items: center; gap: 4px;">
                                            <input type="number" id="mmOrderSize" value="0.001" step="0.001" min="0.001" max="0.1" style="width: 60px; padding: 4px; background: #1a1f2e; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                                            <span style="font-size: 10px; color: #6b7280;">BTC</span>
                                        </div>
                                    </div>
                                    <div style="display: flex; align-items: center; justify-content: space-between;">
                                        <label style="font-size: 11px; color: #9ca3af;">最大持倉</label>
                                        <div style="display: flex; align-items: center; gap: 4px;">
                                            <input type="number" id="mmMaxPosition" value="0.01" step="0.001" min="0.001" max="1" style="width: 60px; padding: 4px; background: #1a1f2e; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                                            <span style="font-size: 10px; color: #6b7280;">BTC</span>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <!-- 波動率控制 -->
                            <div style="background: #0f1419; padding: 12px; border-radius: 6px;">
                                <div style="font-size: 11px; color: #6b7280; margin-bottom: 8px;">波動率控制</div>
                                <div style="display: flex; flex-direction: column; gap: 8px;">
                                    <div style="display: flex; align-items: center; justify-content: space-between;">
                                        <label style="font-size: 11px; color: #9ca3af;">觀察窗口</label>
                                        <div style="display: flex; align-items: center; gap: 4px;">
                                            <input type="number" id="mmVolatilityWindow" value="5" step="1" min="1" max="60" style="width: 50px; padding: 4px; background: #1a1f2e; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                                            <span style="font-size: 10px; color: #6b7280;">秒</span>
                                        </div>
                                    </div>
                                    <div style="display: flex; align-items: center; justify-content: space-between;">
                                        <label style="font-size: 11px; color: #9ca3af;">閾值</label>
                                        <div style="display: flex; align-items: center; gap: 4px;">
                                            <input type="number" id="mmVolatilityThreshold" value="5" step="0.5" min="1" max="20" style="width: 50px; padding: 4px; background: #1a1f2e; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                                            <span style="font-size: 10px; color: #6b7280;">bps</span>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <!-- 執行控制 -->
                            <div style="background: #0f1419; padding: 12px; border-radius: 6px;">
                                <div style="font-size: 11px; color: #6b7280; margin-bottom: 8px;">執行控制</div>
                                <div style="display: flex; flex-direction: column; gap: 8px;">
                                    <div style="display: flex; align-items: center; justify-content: space-between;">
                                        <label style="font-size: 11px; color: #9ca3af;">模擬模式</label>
                                        <div class="toggle active" id="mmDryRunToggle" onclick="toggleMMDryRun()" style="transform: scale(0.8);"></div>
                                    </div>
                                    <div style="display: flex; gap: 8px; margin-top: 4px;">
                                        <button class="btn btn-primary" onclick="saveMMConfig()" style="flex: 1; font-size: 11px; padding: 6px;">保存配置</button>
                                        <button class="btn" onclick="loadMMConfig()" style="flex: 1; font-size: 11px; padding: 6px; background: #2a3347;">重載</button>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <!-- 倉位狀態 -->
                        <div style="display: flex; gap: 15px; font-size: 11px; color: #9ca3af; padding-top: 10px; border-top: 1px solid #2a3347;">
                            <span>StandX: <span id="mmStandxPos" style="color: #e4e6eb;">0</span> BTC</span>
                            <span>Binance: <span id="mmBinancePos" style="color: #e4e6eb;">0</span> BTC</span>
                            <span>淨敞口: <span id="mmNetPos" style="color: #10b981;">0</span></span>
                            <span>StandX 權益: $<span id="mmStandxEquity" style="color: #e4e6eb;">0</span></span>
                            <span>Binance USDT: $<span id="mmBinanceUsdt" style="color: #e4e6eb;">0</span></span>
                        </div>
                    </div>

                    <!-- 訂單簿 -->
                    <div class="card">
                        <div class="card-title">訂單簿深度</div>
                        <div class="orderbook">
                            <div class="ob-side">
                                <div class="ob-header"><span>買價</span><span style="text-align:right">數量</span></div>
                                <div id="mmBidRows"></div>
                            </div>
                            <div class="ob-side">
                                <div class="ob-header"><span>賣價</span><span style="text-align:right">數量</span></div>
                                <div id="mmAskRows"></div>
                            </div>
                        </div>
                        <div class="spread-bar">Spread: <span id="mmSpreadDisplay" class="text-green">- bps</span></div>
                    </div>

                    <!-- Uptime -->
                    <div class="card">
                        <div class="card-title">Uptime Program 狀態</div>
                        <div class="uptime-circle" id="mmUptimeCircle">
                            <div class="uptime-pct" id="mmUptimePct">0%</div>
                            <div class="uptime-tier tier-inactive" id="mmUptimeTier">INACTIVE</div>
                        </div>
                        <div class="stat-row"><span class="stat-label">Boosted (≥70%)</span><span class="stat-value">1.0x</span></div>
                        <div class="stat-row"><span class="stat-label">Standard (≥50%)</span><span class="stat-value">0.5x</span></div>
                        <div class="stat-row"><span class="stat-label">當前乘數</span><span class="stat-value" id="mmMultiplier">0x</span></div>
                    </div>

                    <!-- 模擬掛單 -->
                    <div class="card">
                        <div class="card-title">模擬掛單 (需在 mark ± 10 bps 內)</div>
                        <div class="quote-box">
                            <div class="quote-label">買單價格</div>
                            <div class="quote-price quote-bid" id="mmSuggestedBid">-</div>
                            <div class="quote-status" id="mmBidStatus" style="font-size: 10px; margin-top: 4px;">-</div>
                        </div>
                        <div class="quote-box">
                            <div class="quote-label">賣單價格</div>
                            <div class="quote-price quote-ask" id="mmSuggestedAsk">-</div>
                            <div class="quote-status" id="mmAskStatus" style="font-size: 10px; margin-top: 4px;">-</div>
                        </div>
                        <p style="font-size: 10px; color: #9ca3af; text-align: center; margin-top: 8px;" id="mmStrategyDesc">
                            策略：mid * (1 ± 8/10000)<br/>
                            撤單: 3 bps | 隊列: 前3檔 | 重掛: 12 bps
                        </p>
                    </div>

                    <!-- 深度分析 -->
                    <div class="card">
                        <div class="card-title">深度分析</div>
                        <div class="depth-bar">
                            <div class="depth-bid" id="mmDepthBid" style="width:50%">0 BTC</div>
                            <div class="depth-ask" id="mmDepthAsk" style="width:50%">0 BTC</div>
                        </div>
                        <div style="display: flex; justify-content: space-between; font-size: 10px; color: #9ca3af; margin-bottom: 15px;">
                            <span>買方深度</span><span id="mmImbalance">平衡: 0%</span><span>賣方深度</span>
                        </div>
                        <div class="card-title" style="margin-top: 10px;">報價排隊位置</div>
                        <div class="risk-row"><span>買單位置</span><span id="mmBidPosition" style="font-weight:600">-</span></div>
                        <div class="risk-row"><span>賣單位置</span><span id="mmAskPosition" style="font-weight:600">-</span></div>
                    </div>

                    <!-- 模擬統計 -->
                    <div class="card">
                        <div class="card-title">訂單模擬</div>
                        <div class="sim-grid">
                            <div class="sim-stat"><div class="sim-value" id="mmTotalQuotes">0秒</div><div class="sim-label">運行時間</div></div>
                            <div class="sim-stat"><div class="sim-value" id="mmQualifiedRate">0%</div><div class="sim-label">符合率</div></div>
                            <div class="sim-stat"><div class="sim-value" id="mmBidFillRate">0/0/0</div><div class="sim-label">買撤/隊列/重掛</div></div>
                            <div class="sim-stat"><div class="sim-value" id="mmAskFillRate">0/0/0</div><div class="sim-label">賣撤/隊列/重掛</div></div>
                        </div>
                        <p style="font-size: 9px; color: #9ca3af; text-align: center; margin-top: 10px;">撤=bps太近 / 隊列=排前3檔 / 重掛=bps太遠</p>
                    </div>

                    <!-- 訂單操作歷史 -->
                    <div class="card">
                        <div class="card-title">操作歷史 <span style="font-size: 10px; color: #9ca3af;">(最近 50 筆)</span></div>
                        <div id="mmHistoryList" style="max-height: 300px; overflow-y: auto; font-size: 11px;">
                            <div style="color: #9ca3af; text-align: center; padding: 20px;">等待訂單操作...</div>
                        </div>
                    </div>

                    <!-- Maker Hours -->
                    <div class="card">
                        <div class="card-title">Maker Hours 預估</div>
                        <div class="progress-label">MM1 目標 (360h/月)</div>
                        <div class="progress-bar">
                            <div class="progress-fill mm1" id="mmMM1Progress" style="width:0%"></div>
                            <span class="progress-text" id="mmMM1Text">0%</span>
                        </div>
                        <div class="progress-label">MM2 目標 (504h/月)</div>
                        <div class="progress-bar">
                            <div class="progress-fill mm2" id="mmMM2Progress" style="width:0%"></div>
                            <span class="progress-text" id="mmMM2Text">0%</span>
                        </div>
                        <div class="stat-row" style="margin-top: 10px;"><span class="stat-label">每小時</span><span class="stat-value" id="mmHoursPerHour">0</span></div>
                        <div class="stat-row"><span class="stat-label">每月預估</span><span class="stat-value" id="mmHoursPerMonth">0</span></div>
                    </div>
                </div>
            </div>

            <!-- ==================== 設定頁面 ==================== -->
            <div id="page-settings" class="page">
                <div class="settings-section">
                    <div class="settings-title">已配置交易所</div>
                    <div id="configuredExchanges">
                        <p style="color: #9ca3af;">載入中...</p>
                    </div>
                </div>

                <div class="settings-section">
                    <div class="settings-title">添加新交易所</div>
                    <div class="card" style="padding: 20px;">
                        <div class="form-grid">
                            <div class="form-group">
                                <label>交易所類型</label>
                                <select id="exchangeType" onchange="updateExchangeOptions()">
                                    <option value="cex">CEX (中心化)</option>
                                    <option value="dex">DEX (去中心化)</option>
                                </select>
                            </div>
                            <div class="form-group">
                                <label>選擇交易所</label>
                                <select id="exchangeName">
                                    <option value="binance">Binance</option>
                                    <option value="okx">OKX</option>
                                    <option value="bitget">Bitget</option>
                                    <option value="bybit">Bybit</option>
                                </select>
                            </div>
                        </div>
                        <div id="cexFields" class="form-grid" style="margin-top: 15px;">
                            <div class="form-group">
                                <label>API Key</label>
                                <input type="text" id="apiKey" placeholder="輸入 API Key">
                            </div>
                            <div class="form-group">
                                <label>API Secret</label>
                                <input type="password" id="apiSecret" placeholder="輸入 API Secret">
                            </div>
                            <div class="form-group" id="passphraseField" style="display: none;">
                                <label>Passphrase</label>
                                <input type="password" id="passphrase" placeholder="OKX/Bitget 需要">
                            </div>
                        </div>
                        <div id="dexFields" class="form-grid" style="margin-top: 15px; display: none;">
                            <div class="form-group">
                                <label>Private Key</label>
                                <input type="password" id="privateKey" placeholder="錢包私鑰">
                            </div>
                            <div class="form-group">
                                <label>Wallet Address</label>
                                <input type="text" id="walletAddress" placeholder="錢包地址">
                            </div>
                        </div>
                        <button class="btn btn-primary" style="margin-top: 20px;" onclick="saveConfig()">保存並開始監控</button>
                    </div>
                </div>
            </div>
        </div>

        <script>
            let ws = null;
            let systemStartTime = null;

            // ===== 做市商配置 (從 API 加載) =====
            let mmConfig = null;

            async function loadMMConfig() {
                try {
                    document.getElementById('mmConfigStatus').textContent = '加載中...';
                    const res = await fetch('/api/mm/config');
                    mmConfig = await res.json();
                    console.log('Loaded MM config:', mmConfig);

                    // 更新 mmSim 配置
                    mmSim.updateConfig(mmConfig);

                    // 更新 UI 輸入框
                    updateMMConfigDisplay();

                    document.getElementById('mmConfigStatus').textContent = '已加載';
                    setTimeout(() => {
                        document.getElementById('mmConfigStatus').textContent = '';
                    }, 2000);
                } catch (e) {
                    console.error('Failed to load MM config:', e);
                    document.getElementById('mmConfigStatus').textContent = '加載失敗';
                }
            }

            async function saveMMConfig() {
                try {
                    document.getElementById('mmConfigStatus').textContent = '保存中...';

                    // 從輸入框收集配置
                    const config = {
                        quote: {
                            order_distance_bps: parseInt(document.getElementById('mmOrderDistance').value),
                            cancel_distance_bps: parseInt(document.getElementById('mmCancelDistance').value),
                            rebalance_distance_bps: parseInt(document.getElementById('mmRebalanceDistance').value),
                            queue_position_limit: parseInt(document.getElementById('mmQueuePositionLimit').value),
                        },
                        position: {
                            order_size_btc: parseFloat(document.getElementById('mmOrderSize').value),
                            max_position_btc: parseFloat(document.getElementById('mmMaxPosition').value),
                        },
                        volatility: {
                            window_sec: parseInt(document.getElementById('mmVolatilityWindow').value),
                            threshold_bps: parseFloat(document.getElementById('mmVolatilityThreshold').value),
                        },
                        execution: {
                            dry_run: mmDryRun,
                        }
                    };

                    const res = await fetch('/api/mm/config', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(config)
                    });

                    const result = await res.json();
                    if (result.success) {
                        mmConfig = result.config;
                        mmSim.updateConfig(mmConfig);
                        document.getElementById('mmConfigStatus').textContent = '已保存';
                        document.getElementById('mmConfigStatus').style.color = '#10b981';
                    } else {
                        document.getElementById('mmConfigStatus').textContent = '保存失敗: ' + result.error;
                        document.getElementById('mmConfigStatus').style.color = '#ef4444';
                    }

                    setTimeout(() => {
                        document.getElementById('mmConfigStatus').textContent = '';
                        document.getElementById('mmConfigStatus').style.color = '#9ca3af';
                    }, 3000);
                } catch (e) {
                    console.error('Failed to save MM config:', e);
                    document.getElementById('mmConfigStatus').textContent = '保存失敗';
                    document.getElementById('mmConfigStatus').style.color = '#ef4444';
                }
            }

            // 更新歷史記錄顯示
            function updateHistoryDisplay() {
                const container = document.getElementById('mmHistoryList');
                if (!container || mmSim.history.length === 0) return;

                const actionColors = {
                    'cancel': '#ef4444',     // 紅色 - 撤單
                    'rebalance': '#f59e0b',  // 黃色 - 重掛
                    'place': '#10b981'       // 綠色 - 下單
                };

                const actionNames = {
                    'cancel': '撤單',
                    'rebalance': '重掛',
                    'place': '下單'
                };

                const sideNames = {
                    'bid': '買',
                    'ask': '賣'
                };

                let html = '<table style="width: 100%; border-collapse: collapse;">';
                html += '<thead><tr style="color: #9ca3af; font-size: 10px; border-bottom: 1px solid #2a3347;">';
                html += '<th style="text-align: left; padding: 4px;">時間</th>';
                html += '<th style="text-align: left; padding: 4px;">操作</th>';
                html += '<th style="text-align: right; padding: 4px;">舊價</th>';
                html += '<th style="text-align: right; padding: 4px;">新價</th>';
                html += '<th style="text-align: right; padding: 4px;">Mid</th>';
                html += '<th style="text-align: left; padding: 4px;">原因</th>';
                html += '</tr></thead><tbody>';

                mmSim.history.forEach((h, i) => {
                    const bgColor = i % 2 === 0 ? '#0f1419' : 'transparent';
                    const actionColor = actionColors[h.action] || '#9ca3af';
                    html += '<tr style="background: ' + bgColor + ';">';
                    html += '<td style="padding: 4px; color: #9ca3af;">' + h.time + '</td>';
                    html += '<td style="padding: 4px;"><span style="color: ' + actionColor + ';">' + sideNames[h.side] + actionNames[h.action] + '</span></td>';
                    html += '<td style="padding: 4px; text-align: right; color: #9ca3af;">' + (h.oldPrice ? '$' + h.oldPrice.toLocaleString() : '-') + '</td>';
                    html += '<td style="padding: 4px; text-align: right; color: #e5e7eb;">' + (h.newPrice ? '$' + h.newPrice.toLocaleString() : '-') + '</td>';
                    html += '<td style="padding: 4px; text-align: right; color: #9ca3af;">$' + h.midPrice.toLocaleString() + '</td>';
                    html += '<td style="padding: 4px; color: #9ca3af; font-size: 10px;">' + h.reason + '</td>';
                    html += '</tr>';
                });

                html += '</tbody></table>';
                container.innerHTML = html;
            }

            function updateMMConfigDisplay() {
                if (!mmConfig) return;

                // 報價參數
                if (mmConfig.quote) {
                    document.getElementById('mmOrderDistance').value = mmConfig.quote.order_distance_bps;
                    document.getElementById('mmCancelDistance').value = mmConfig.quote.cancel_distance_bps;
                    document.getElementById('mmRebalanceDistance').value = mmConfig.quote.rebalance_distance_bps;
                    document.getElementById('mmQueuePositionLimit').value = mmConfig.quote.queue_position_limit || 3;
                }

                // 倉位參數
                if (mmConfig.position) {
                    document.getElementById('mmOrderSize').value = mmConfig.position.order_size_btc;
                    document.getElementById('mmMaxPosition').value = mmConfig.position.max_position_btc;
                }

                // 波動率參數
                if (mmConfig.volatility) {
                    document.getElementById('mmVolatilityWindow').value = mmConfig.volatility.window_sec;
                    document.getElementById('mmVolatilityThreshold').value = mmConfig.volatility.threshold_bps;
                }

                // 執行參數
                if (mmConfig.execution) {
                    mmDryRun = mmConfig.execution.dry_run;
                    const toggle = document.getElementById('mmDryRunToggle');
                    if (mmDryRun) {
                        toggle.classList.add('active');
                    } else {
                        toggle.classList.remove('active');
                    }
                }

                // 更新策略說明
                if (mmConfig.quote) {
                    const q = mmConfig.quote;
                    document.getElementById('mmStrategyDesc').innerHTML =
                        '策略：mid * (1 ± ' + q.order_distance_bps + '/10000)<br/>' +
                        '撤單: ' + q.cancel_distance_bps + ' bps | 隊列: 前' + (q.queue_position_limit || 3) + '檔 | 重掛: ' + q.rebalance_distance_bps + ' bps';
                }
            }

            // ===== 做市商模擬狀態 =====
            const mmSim = {
                // 配置 (從 API 加載後更新)
                orderDistanceBps: 8,
                cancelDistanceBps: 3,
                rebalanceDistanceBps: 12,
                uptimeMaxDistanceBps: 10,

                // 隊列位置風控：排在前 N 檔時撤單
                queuePositionLimit: 3,  // 排在前3檔時撤單（成交風險高）

                // 模擬掛單 (null = 無單)
                bidOrder: null,
                askOrder: null,

                // 時間統計 (毫秒)
                startTime: Date.now(),
                lastTickTime: null,
                qualifiedTimeMs: 0,   // 雙邊都合格的總時間
                totalTimeMs: 0,       // 總運行時間

                // 訂單操作統計
                bidCancels: 0,
                askCancels: 0,
                bidRebalances: 0,
                askRebalances: 0,
                bidQueueCancels: 0,   // 因隊列位置撤單
                askQueueCancels: 0,

                // 歷史記錄 (最多保留 50 條)
                history: [],
                maxHistorySize: 50,

                // 添加歷史記錄
                addHistory(action, side, oldPrice, newPrice, midPrice, distBps, reason) {
                    const now = new Date();
                    const timeStr = now.toLocaleTimeString('zh-TW', { hour12: false });
                    this.history.unshift({
                        time: timeStr,
                        action,      // 'cancel' | 'rebalance' | 'place'
                        side,        // 'bid' | 'ask'
                        oldPrice,    // 舊訂單價格 (撤單時)
                        newPrice,    // 新訂單價格
                        midPrice,    // 當時的中間價
                        distBps,     // 觸發時的距離
                        reason       // 原因說明
                    });
                    if (this.history.length > this.maxHistorySize) {
                        this.history.pop();
                    }
                },

                // 下單
                placeOrder(side, midPrice, reason = '初始下單') {
                    const price = side === 'bid'
                        ? Math.floor(midPrice * (1 - this.orderDistanceBps / 10000) * 100) / 100
                        : Math.ceil(midPrice * (1 + this.orderDistanceBps / 10000) * 100) / 100;

                    const order = { price, placedAt: Date.now(), placedMid: midPrice };
                    if (side === 'bid') this.bidOrder = order;
                    else this.askOrder = order;

                    this.addHistory('place', side, null, price, midPrice, this.orderDistanceBps, reason);
                    return order;
                },

                // 計算訂單在 orderbook 中的隊列位置
                getQueuePosition(side, orderPrice, ob) {
                    if (!ob || !orderPrice) return null;

                    if (side === 'bid') {
                        // 買單：找第一個價格 < orderPrice 的位置
                        const pos = ob.bids.findIndex(b => b[0] < orderPrice);
                        return pos === -1 ? ob.bids.length + 1 : pos + 1;
                    } else {
                        // 賣單：找第一個價格 > orderPrice 的位置
                        const pos = ob.asks.findIndex(a => a[0] > orderPrice);
                        return pos === -1 ? ob.asks.length + 1 : pos + 1;
                    }
                },

                // 檢查並處理訂單 (基於時間的 Uptime 計算)
                tick(midPrice, ob) {
                    const now = Date.now();
                    let bidStatus = 'none';
                    let askStatus = 'none';

                    // 計算自上次 tick 以來的時間間隔
                    const deltaMs = this.lastTickTime ? (now - this.lastTickTime) : 0;
                    this.lastTickTime = now;
                    this.totalTimeMs += deltaMs;

                    // 處理買單
                    if (this.bidOrder) {
                        const distBps = (midPrice - this.bidOrder.price) / midPrice * 10000;
                        const queuePos = this.getQueuePosition('bid', this.bidOrder.price, ob);

                        // 優先檢查隊列位置風控
                        if (queuePos && queuePos <= this.queuePositionLimit) {
                            const oldPrice = this.bidOrder.price;
                            bidStatus = 'queue_cancel';
                            this.bidOrder = null;
                            this.bidQueueCancels++;
                            this.addHistory('cancel', 'bid', oldPrice, null, midPrice, distBps.toFixed(2),
                                '隊列風控 (第' + queuePos + '檔，距離 ' + distBps.toFixed(2) + ' bps)');
                        } else if (distBps < this.cancelDistanceBps) {
                            const oldPrice = this.bidOrder.price;
                            bidStatus = 'cancel';
                            this.bidOrder = null;
                            this.bidCancels++;
                            this.addHistory('cancel', 'bid', oldPrice, null, midPrice, distBps.toFixed(2),
                                '價格靠近 (' + distBps.toFixed(2) + ' < ' + this.cancelDistanceBps + ' bps)');
                        } else if (distBps > this.rebalanceDistanceBps) {
                            const oldPrice = this.bidOrder.price;
                            bidStatus = 'rebalance';
                            this.bidOrder = null;
                            this.bidRebalances++;
                            this.addHistory('rebalance', 'bid', oldPrice, null, midPrice, distBps.toFixed(2),
                                '價格遠離 (' + distBps.toFixed(2) + ' > ' + this.rebalanceDistanceBps + ' bps)');
                        } else if (distBps <= this.uptimeMaxDistanceBps) {
                            bidStatus = 'qualified';
                        } else {
                            bidStatus = 'out_of_range';
                        }
                    }

                    // 處理賣單
                    if (this.askOrder) {
                        const distBps = (this.askOrder.price - midPrice) / midPrice * 10000;
                        const queuePos = this.getQueuePosition('ask', this.askOrder.price, ob);

                        // 優先檢查隊列位置風控
                        if (queuePos && queuePos <= this.queuePositionLimit) {
                            const oldPrice = this.askOrder.price;
                            askStatus = 'queue_cancel';
                            this.askOrder = null;
                            this.askQueueCancels++;
                            this.addHistory('cancel', 'ask', oldPrice, null, midPrice, distBps.toFixed(2),
                                '隊列風控 (第' + queuePos + '檔，距離 ' + distBps.toFixed(2) + ' bps)');
                        } else if (distBps < this.cancelDistanceBps) {
                            const oldPrice = this.askOrder.price;
                            askStatus = 'cancel';
                            this.askOrder = null;
                            this.askCancels++;
                            this.addHistory('cancel', 'ask', oldPrice, null, midPrice, distBps.toFixed(2),
                                '價格靠近 (' + distBps.toFixed(2) + ' < ' + this.cancelDistanceBps + ' bps)');
                        } else if (distBps > this.rebalanceDistanceBps) {
                            const oldPrice = this.askOrder.price;
                            askStatus = 'rebalance';
                            this.askOrder = null;
                            this.askRebalances++;
                            this.addHistory('rebalance', 'ask', oldPrice, null, midPrice, distBps.toFixed(2),
                                '價格遠離 (' + distBps.toFixed(2) + ' > ' + this.rebalanceDistanceBps + ' bps)');
                        } else if (distBps <= this.uptimeMaxDistanceBps) {
                            askStatus = 'qualified';
                        } else {
                            askStatus = 'out_of_range';
                        }
                    }

                    // 沒有訂單則下單，並立即檢查是否合格
                    if (!this.bidOrder) {
                        const reason = (bidStatus === 'cancel' || bidStatus === 'queue_cancel') ? '撤單後重掛' : (bidStatus === 'rebalance' ? '重平衡重掛' : '初始下單');
                        this.placeOrder('bid', midPrice, reason);
                        if (this.orderDistanceBps <= this.uptimeMaxDistanceBps) {
                            bidStatus = 'qualified';
                        }
                    }
                    if (!this.askOrder) {
                        const reason = (askStatus === 'cancel' || askStatus === 'queue_cancel') ? '撤單後重掛' : (askStatus === 'rebalance' ? '重平衡重掛' : '初始下單');
                        this.placeOrder('ask', midPrice, reason);
                        if (this.orderDistanceBps <= this.uptimeMaxDistanceBps) {
                            askStatus = 'qualified';
                        }
                    }

                    // 累計合格時間 (雙邊都符合才計入)
                    if (bidStatus === 'qualified' && askStatus === 'qualified') {
                        this.qualifiedTimeMs += deltaMs;
                    }

                    return { bidStatus, askStatus };
                },

                // 計算距離
                getDistance(side, midPrice) {
                    const order = side === 'bid' ? this.bidOrder : this.askOrder;
                    if (!order) return null;
                    return side === 'bid'
                        ? (midPrice - order.price) / midPrice * 10000
                        : (order.price - midPrice) / midPrice * 10000;
                },

                // 重置
                reset() {
                    this.bidOrder = null;
                    this.askOrder = null;
                    this.startTime = Date.now();
                    this.lastTickTime = null;
                    this.qualifiedTimeMs = 0;
                    this.totalTimeMs = 0;
                    this.bidCancels = 0;
                    this.askCancels = 0;
                    this.bidRebalances = 0;
                    this.askRebalances = 0;
                    this.bidQueueCancels = 0;
                    this.askQueueCancels = 0;
                    this.history = [];
                },

                // 獲取 Uptime 百分比
                getUptimePct() {
                    return this.totalTimeMs > 0 ? (this.qualifiedTimeMs / this.totalTimeMs * 100) : 0;
                },

                // 獲取運行時間 (秒)
                getRunningTimeSec() {
                    return this.totalTimeMs / 1000;
                },

                // 更新配置
                updateConfig(config) {
                    if (config.quote) {
                        this.orderDistanceBps = config.quote.order_distance_bps;
                        this.cancelDistanceBps = config.quote.cancel_distance_bps;
                        this.rebalanceDistanceBps = config.quote.rebalance_distance_bps;
                        this.queuePositionLimit = config.quote.queue_position_limit || 3;
                    }
                    if (config.uptime) {
                        this.uptimeMaxDistanceBps = config.uptime.max_distance_bps;
                    }
                }
            };

            // ===== 分頁切換 =====
            function switchPage(page) {
                document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
                document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
                document.getElementById('page-' + page).classList.add('active');
                event.target.classList.add('active');
            }

            // ===== WebSocket 連接 =====
            function connect() {
                ws = new WebSocket('ws://localhost:8888/ws');
                ws.onopen = () => {
                    document.getElementById('statusDot').classList.remove('offline');
                    document.getElementById('statusText').textContent = '已連接';
                };
                ws.onclose = () => {
                    document.getElementById('statusDot').classList.add('offline');
                    document.getElementById('statusText').textContent = '已斷開';
                    setTimeout(connect, 3000);
                };
                ws.onmessage = (event) => {
                    const data = JSON.parse(event.data);
                    updateArbitragePage(data);
                    updateMarketMakerPage(data);
                };
            }

            // ===== 套利頁面更新 =====
            function updateArbitragePage(data) {
                if (data.system_status.started_at && !systemStartTime) {
                    systemStartTime = new Date(data.system_status.started_at);
                }
                if (systemStartTime) {
                    const uptime = Math.floor((Date.now() - systemStartTime) / 1000);
                    const h = Math.floor(uptime / 3600);
                    const m = Math.floor((uptime % 3600) / 60);
                    document.getElementById('uptimeDisplay').textContent = h + 'h ' + m + 'm';
                }

                document.getElementById('arbStatus').textContent = data.system_status.running ? '運行中' : '已停止';
                document.getElementById('arbExchangeCount').textContent = Object.keys(data.market_data).length;
                document.getElementById('arbUpdates').textContent = data.stats.total_updates || 0;
                document.getElementById('arbOppsFound').textContent = data.stats.total_opportunities || 0;
                document.getElementById('arbCurrentOpps').textContent = data.opportunities.length;
                document.getElementById('arbExecCount').textContent = data.executor_stats.total_attempts || 0;

                const rate = data.executor_stats.total_attempts > 0
                    ? ((data.executor_stats.successful_executions / data.executor_stats.total_attempts) * 100).toFixed(1)
                    : 0;
                document.getElementById('arbSuccessRate').textContent = rate + '%';
                document.getElementById('arbProfit').textContent = '$' + (data.executor_stats.total_profit || 0).toFixed(2);
                document.getElementById('arbMode').textContent = data.system_status.dry_run ? '模擬' : '實盤';

                // 套利機會
                const oppContainer = document.getElementById('arbOpportunities');
                if (data.opportunities.length === 0) {
                    oppContainer.innerHTML = '<p style="color: #9ca3af; text-align: center; padding: 30px;">等待套利機會...</p>';
                } else {
                    oppContainer.innerHTML = data.opportunities.map(o => `
                        <div class="opportunity-card">
                            <div class="opp-header">
                                <span class="opp-symbol">${o.symbol}</span>
                                <span class="opp-profit">+$${o.profit.toFixed(2)} (${o.profit_pct.toFixed(2)}%)</span>
                            </div>
                            <div class="opp-details">
                                <div>買: ${o.buy_exchange} @ $${o.buy_price.toFixed(2)}</div>
                                <div>賣: ${o.sell_exchange} @ $${o.sell_price.toFixed(2)}</div>
                                <div>數量: ${o.max_quantity.toFixed(4)}</div>
                            </div>
                        </div>
                    `).join('');
                }

                // 價格表
                const tbody = document.getElementById('arbPriceTable');
                const exchanges = Object.keys(data.market_data);
                if (exchanges.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="4" style="color: #9ca3af;">無數據</td></tr>';
                } else {
                    tbody.innerHTML = exchanges.map(ex => {
                        const d = data.market_data[ex];
                        const btc = d['BTC/USDT:USDT'] || d['BTC-USD'] || {};
                        return `<tr>
                            <td>${ex}</td>
                            <td>${btc.best_bid ? '$' + btc.best_bid.toFixed(2) : '-'}</td>
                            <td>${btc.best_ask ? '$' + btc.best_ask.toFixed(2) : '-'}</td>
                            <td><span class="badge badge-online">在線</span></td>
                        </tr>`;
                    }).join('');
                }
            }

            // ===== 做市商頁面更新 =====
            function updateMarketMakerPage(data) {
                // 從 StandX 數據更新
                const standx = data.market_data['STANDX'];
                if (!standx) return;

                const btc = standx['BTC-USD'];
                if (!btc) return;

                const midPrice = (btc.best_bid + btc.best_ask) / 2;
                const spreadBps = ((btc.best_ask - btc.best_bid) / midPrice * 10000);

                // Header
                document.getElementById('mmMidPrice').textContent = '$' + midPrice.toLocaleString(undefined, {maximumFractionDigits: 2});
                const spreadEl = document.getElementById('mmSpread');
                spreadEl.textContent = spreadBps.toFixed(1);
                spreadEl.className = 'mm-stat-value ' + (spreadBps <= 10 ? 'text-green' : (spreadBps <= 15 ? 'text-yellow' : 'text-red'));

                const runtime = Math.floor((Date.now() - mmSim.startTime) / 60000);
                document.getElementById('mmRuntime').textContent = runtime + 'm';

                // 取得 orderbook 用於隊列位置風控
                const ob = data.orderbooks?.STANDX?.['BTC-USD'];

                // ===== 使用 mmSim 模擬訂單生命週期 =====
                const simResult = mmSim.tick(midPrice, ob);

                // 顯示實際掛單價格（不是理論價格）
                const bidOrder = mmSim.bidOrder;
                const askOrder = mmSim.askOrder;

                // 計算當前距離
                const bidDistBps = mmSim.getDistance('bid', midPrice);
                const askDistBps = mmSim.getDistance('ask', midPrice);

                // 顯示報價和狀態
                if (bidOrder) {
                    const bidInRange = bidDistBps <= 10;
                    const bidStyle = bidInRange ? 'color: #10b981' : 'color: #ef4444';
                    document.getElementById('mmSuggestedBid').innerHTML = '<span style="' + bidStyle + '">$' + bidOrder.price.toLocaleString(undefined, {maximumFractionDigits: 2}) + '</span>';

                    // 狀態指示
                    let bidStatusText = '';
                    if (simResult.bidStatus === 'cancel') {
                        bidStatusText = '⚡ 撤單 (bps太近)';
                    } else if (simResult.bidStatus === 'queue_cancel') {
                        bidStatusText = '🚨 撤單 (隊列風控)';
                    } else if (simResult.bidStatus === 'rebalance') {
                        bidStatusText = '🔄 重掛 (太遠)';
                    } else if (bidInRange) {
                        bidStatusText = '✓ ' + bidDistBps.toFixed(1) + ' bps';
                    } else {
                        bidStatusText = '⚠️ 超出10bps (' + bidDistBps.toFixed(1) + ')';
                    }
                    document.getElementById('mmBidStatus').textContent = bidStatusText;
                } else {
                    document.getElementById('mmSuggestedBid').innerHTML = '<span style="color: #9ca3af">下單中...</span>';
                    document.getElementById('mmBidStatus').textContent = '新掛單';
                }

                if (askOrder) {
                    const askInRange = askDistBps <= 10;
                    const askStyle = askInRange ? 'color: #10b981' : 'color: #ef4444';
                    document.getElementById('mmSuggestedAsk').innerHTML = '<span style="' + askStyle + '">$' + askOrder.price.toLocaleString(undefined, {maximumFractionDigits: 2}) + '</span>';

                    let askStatusText = '';
                    if (simResult.askStatus === 'cancel') {
                        askStatusText = '⚡ 撤單 (bps太近)';
                    } else if (simResult.askStatus === 'queue_cancel') {
                        askStatusText = '🚨 撤單 (隊列風控)';
                    } else if (simResult.askStatus === 'rebalance') {
                        askStatusText = '🔄 重掛 (太遠)';
                    } else if (askInRange) {
                        askStatusText = '✓ ' + askDistBps.toFixed(1) + ' bps';
                    } else {
                        askStatusText = '⚠️ 超出10bps (' + askDistBps.toFixed(1) + ')';
                    }
                    document.getElementById('mmAskStatus').textContent = askStatusText;
                } else {
                    document.getElementById('mmSuggestedAsk').innerHTML = '<span style="color: #9ca3af">下單中...</span>';
                    document.getElementById('mmAskStatus').textContent = '新掛單';
                }

                // Spread display
                const spreadDisplay = document.getElementById('mmSpreadDisplay');
                spreadDisplay.textContent = spreadBps.toFixed(1) + ' bps';
                spreadDisplay.className = spreadBps <= 10 ? 'text-green' : (spreadBps <= 15 ? 'text-yellow' : 'text-red');

                // ===== 訂單簿顯示 =====
                // ob 已在上方取得 (用於隊列位置風控)
                // 使用 mmSim 的實際掛單價格
                const simBidPrice = bidOrder ? bidOrder.price : null;
                const simAskPrice = askOrder ? askOrder.price : null;

                if (ob && ob.bids && ob.asks) {
                    const maxSize = Math.max(...ob.bids.map(b => b[1]), ...ob.asks.map(a => a[1]));

                    document.getElementById('mmBidRows').innerHTML = ob.bids.slice(0, 8).map(b => {
                        const pct = (b[1] / maxSize * 100).toFixed(0);
                        return '<div class="ob-row bid"><div class="bg" style="width:' + pct + '%"></div><span class="ob-price-bid">' + b[0].toLocaleString(undefined, {minimumFractionDigits: 2}) + '</span><span class="ob-size">' + b[1].toFixed(4) + '</span></div>';
                    }).join('');

                    document.getElementById('mmAskRows').innerHTML = ob.asks.slice(0, 8).map(a => {
                        const pct = (a[1] / maxSize * 100).toFixed(0);
                        return '<div class="ob-row ask"><div class="bg" style="width:' + pct + '%"></div><span class="ob-price-ask">' + a[0].toLocaleString(undefined, {minimumFractionDigits: 2}) + '</span><span class="ob-size">' + a[1].toFixed(4) + '</span></div>';
                    }).join('');

                    // 計算模擬掛單會排在第幾檔
                    if (simBidPrice) {
                        let bidPos = ob.bids.findIndex(b => b[0] < simBidPrice);
                        bidPos = bidPos === -1 ? ob.bids.length + 1 : bidPos + 1;
                        const bidPosText = bidPos === 1 ? '最佳價 (第1檔)' : '第 ' + bidPos + ' 檔';
                        document.getElementById('mmBidPosition').textContent = bidPosText;
                        document.getElementById('mmBidPosition').style.color = bidPos <= 2 ? '#10b981' : '#9ca3af';
                    } else {
                        document.getElementById('mmBidPosition').textContent = '-';
                    }

                    if (simAskPrice) {
                        let askPos = ob.asks.findIndex(a => a[0] > simAskPrice);
                        askPos = askPos === -1 ? ob.asks.length + 1 : askPos + 1;
                        const askPosText = askPos === 1 ? '最佳價 (第1檔)' : '第 ' + askPos + ' 檔';
                        document.getElementById('mmAskPosition').textContent = askPosText;
                        document.getElementById('mmAskPosition').style.color = askPos <= 2 ? '#10b981' : '#9ca3af';
                    } else {
                        document.getElementById('mmAskPosition').textContent = '-';
                    }

                    // 計算實際深度
                    var bidDepth = ob.bids.slice(0, 5).reduce((sum, b) => sum + b[1], 0);
                    var askDepth = ob.asks.slice(0, 5).reduce((sum, a) => sum + a[1], 0);
                } else {
                    var bidDepth = btc.bid_size || 0;
                    var askDepth = btc.ask_size || 0;
                    document.getElementById('mmBidPosition').textContent = '-';
                    document.getElementById('mmAskPosition').textContent = '-';
                }

                // Uptime - 使用時間計算
                const uptimePct = mmSim.getUptimePct();
                document.getElementById('mmUptimePct').textContent = uptimePct.toFixed(1) + '%';

                const tier = uptimePct >= 70 ? 'boosted' : (uptimePct >= 50 ? 'standard' : 'inactive');
                const multiplier = uptimePct >= 70 ? 1.0 : (uptimePct >= 50 ? 0.5 : 0);
                document.getElementById('mmUptimeCircle').className = 'uptime-circle ' + tier;
                document.getElementById('mmUptimeTier').textContent = tier.toUpperCase();
                document.getElementById('mmUptimeTier').className = 'uptime-tier tier-' + tier;
                document.getElementById('mmMultiplier').textContent = multiplier + 'x';

                // 模擬統計顯示 - 運行時間和訂單操作
                const runningTimeSec = mmSim.getRunningTimeSec();
                const runningTimeStr = runningTimeSec >= 60
                    ? Math.floor(runningTimeSec / 60) + '分' + Math.floor(runningTimeSec % 60) + '秒'
                    : runningTimeSec.toFixed(0) + '秒';
                document.getElementById('mmTotalQuotes').textContent = runningTimeStr;
                document.getElementById('mmQualifiedRate').textContent = uptimePct.toFixed(1) + '%';
                // 撤單次數和重掛次數
                document.getElementById('mmBidFillRate').textContent = mmSim.bidCancels + '/' + mmSim.bidQueueCancels + '/' + mmSim.bidRebalances;
                document.getElementById('mmAskFillRate').textContent = mmSim.askCancels + '/' + mmSim.askQueueCancels + '/' + mmSim.askRebalances;

                // 更新歷史記錄顯示
                updateHistoryDisplay();

                // Maker Hours - 使用配置中的訂單大小
                // StandX 規則：Maker Hours = min(bid_size, ask_size, 2) / 2 * multiplier
                const configOrderSize = mmConfig?.position?.order_size_btc || 0.001;
                const effectiveOrderSize = Math.min(configOrderSize, 2.0);  // 單邊最多 2 BTC
                const makerHoursPerHour = (effectiveOrderSize / 2) * multiplier;
                const makerHoursPerMonth = makerHoursPerHour * 720;  // 30 天 * 24 小時
                const mm1Progress = Math.min((makerHoursPerMonth / 360) * 100, 100);  // MM1 需要 360 hours
                const mm2Progress = Math.min((makerHoursPerMonth / 504) * 100, 100);  // MM2 需要 504 hours

                document.getElementById('mmMM1Progress').style.width = mm1Progress + '%';
                document.getElementById('mmMM1Text').textContent = mm1Progress.toFixed(0) + '%';
                document.getElementById('mmMM2Progress').style.width = mm2Progress + '%';
                document.getElementById('mmMM2Text').textContent = mm2Progress.toFixed(0) + '%';
                document.getElementById('mmHoursPerHour').textContent = makerHoursPerHour.toFixed(4);
                document.getElementById('mmHoursPerMonth').textContent = makerHoursPerMonth.toFixed(2);

                // 深度顯示
                const totalDepth = bidDepth + askDepth || 1;
                const bidPct = (bidDepth / totalDepth * 100);
                document.getElementById('mmDepthBid').style.width = bidPct + '%';
                document.getElementById('mmDepthBid').textContent = bidDepth.toFixed(2) + ' BTC';
                document.getElementById('mmDepthAsk').style.width = (100 - bidPct) + '%';
                document.getElementById('mmDepthAsk').textContent = askDepth.toFixed(2) + ' BTC';
                const imbalance = ((bidDepth - askDepth) / totalDepth * 100);
                document.getElementById('mmImbalance').textContent = '偏移: ' + (imbalance > 0 ? '+' : '') + imbalance.toFixed(1) + '%';

                // 更新實時倉位 (從 WebSocket)
                if (data.mm_positions) {
                    const pos = data.mm_positions;
                    document.getElementById('mmStandxPos').textContent = (pos.standx?.btc || 0).toFixed(4);
                    document.getElementById('mmBinancePos').textContent = (pos.binance?.btc || 0).toFixed(4);
                    document.getElementById('mmStandxEquity').textContent = (pos.standx?.equity || 0).toFixed(2);
                    document.getElementById('mmBinanceUsdt').textContent = (pos.binance?.usdt || 0).toFixed(2);

                    const netPos = pos.net_btc || 0;
                    const netEl = document.getElementById('mmNetPos');
                    netEl.textContent = netPos.toFixed(4);
                    netEl.style.color = Math.abs(netPos) < 0.0001 ? '#10b981' : '#ef4444';
                }

                // 更新做市商執行器統計 (實盤運行時使用後端數據)
                // 注意：目前主要使用前端模擬 (mmSim)，後端數據暫不覆蓋
                // if (data.mm_executor && data.mm_executor.stats) {
                //     document.getElementById('mmTotalQuotes').textContent = data.mm_executor.stats.total_quotes || 0;
                // }

                // 更新 UI 按鈕狀態
                if (data.mm_status) {
                    const running = data.mm_status.running;
                    document.getElementById('mmStartBtn').style.display = running ? 'none' : 'block';
                    document.getElementById('mmStopBtn').style.display = running ? 'block' : 'none';

                    const badge = document.getElementById('mmStatusBadge');
                    if (running) {
                        badge.textContent = data.mm_status.dry_run ? '模擬中' : '運行中';
                        badge.style.background = data.mm_status.dry_run ? '#f59e0b' : '#10b981';
                    } else {
                        badge.textContent = '停止';
                        badge.style.background = '#2a3347';
                    }
                }
            }

            // ===== 控制開關 =====
            async function toggleAutoExec() {
                const toggle = document.getElementById('autoExecToggle');
                toggle.classList.toggle('active');
                const enabled = toggle.classList.contains('active');
                await fetch('/api/control/auto-execute', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enabled })
                });
            }

            async function toggleLive() {
                const toggle = document.getElementById('liveToggle');
                if (!toggle.classList.contains('active')) {
                    if (!confirm('⚠️ 確定啟用實盤模式？將使用真實資金！')) return;
                }
                toggle.classList.toggle('active');
                const enabled = toggle.classList.contains('active');
                await fetch('/api/control/live-trade', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enabled })
                });
            }

            // ===== 設定頁面 =====
            function updateExchangeOptions() {
                const type = document.getElementById('exchangeType').value;
                const nameSelect = document.getElementById('exchangeName');
                const cexFields = document.getElementById('cexFields');
                const dexFields = document.getElementById('dexFields');

                if (type === 'cex') {
                    cexFields.style.display = 'grid';
                    dexFields.style.display = 'none';
                    nameSelect.innerHTML = '<option value="binance">Binance</option><option value="okx">OKX</option><option value="bitget">Bitget</option><option value="bybit">Bybit</option>';
                } else {
                    cexFields.style.display = 'none';
                    dexFields.style.display = 'grid';
                    nameSelect.innerHTML = '<option value="standx">StandX</option><option value="grvt">GRVT</option>';
                }
                nameSelect.onchange = () => {
                    const name = nameSelect.value;
                    document.getElementById('passphraseField').style.display = (name === 'okx' || name === 'bitget') ? 'block' : 'none';
                };
                nameSelect.onchange();
            }

            async function saveConfig() {
                const type = document.getElementById('exchangeType').value;
                const name = document.getElementById('exchangeName').value;
                const config = {};

                if (type === 'cex') {
                    config.api_key = document.getElementById('apiKey').value;
                    config.api_secret = document.getElementById('apiSecret').value;
                    if (name === 'okx' || name === 'bitget') config.passphrase = document.getElementById('passphrase').value;
                } else {
                    config.private_key = document.getElementById('privateKey').value;
                    config.address = document.getElementById('walletAddress').value;
                }

                const res = await fetch('/api/config/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ exchange_name: name, exchange_type: type, config })
                });
                const result = await res.json();
                if (result.success) {
                    alert('✅ 已保存！');
                    document.querySelectorAll('#cexFields input, #dexFields input').forEach(i => i.value = '');
                    loadConfiguredExchanges();
                } else {
                    alert('❌ 失敗: ' + result.error);
                }
            }

            async function loadConfiguredExchanges() {
                const res = await fetch('/api/config/list');
                const configs = await res.json();
                const container = document.getElementById('configuredExchanges');

                const all = [];
                for (const [k, v] of Object.entries(configs.dex || {})) {
                    all.push({ name: k, display: v.name, type: 'dex', key: v.private_key_masked || v.api_key_masked });
                }
                for (const [k, v] of Object.entries(configs.cex || {})) {
                    all.push({ name: k, display: v.name, type: 'cex', key: v.api_key_masked });
                }

                if (all.length === 0) {
                    container.innerHTML = '<p style="color: #9ca3af;">尚未配置交易所</p>';
                    return;
                }

                container.innerHTML = all.map(ex => `
                    <div class="exchange-card">
                        <div class="exchange-info">
                            <div>
                                <div style="display: flex; gap: 8px; align-items: center;">
                                    <span class="exchange-name">${ex.display}</span>
                                    <span class="badge badge-${ex.type}">${ex.type.toUpperCase()}</span>
                                </div>
                                <div class="exchange-details">Key: ${ex.key}</div>
                            </div>
                        </div>
                        <button class="btn btn-danger" onclick="deleteExchange('${ex.name}', '${ex.type}')">移除</button>
                    </div>
                `).join('');
            }

            async function deleteExchange(name, type) {
                if (!confirm('確定移除 ' + name.toUpperCase() + '？')) return;
                const res = await fetch('/api/config/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ exchange_name: name, exchange_type: type })
                });
                if ((await res.json()).success) {
                    alert('✅ 已移除');
                    loadConfiguredExchanges();
                }
            }

            // ===== 做市商控制 =====
            let mmDryRun = true;

            async function startMM() {
                const orderSize = document.getElementById('mmOrderSize').value;
                const orderDistance = document.getElementById('mmOrderDistance').value;

                if (!mmDryRun && !confirm('⚠️ 確定啟用實盤模式？將使用真實資金進行交易！')) {
                    return;
                }

                const res = await fetch('/api/mm/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        order_size: parseFloat(orderSize),
                        order_distance: parseInt(orderDistance),
                        dry_run: mmDryRun
                    })
                });
                const result = await res.json();
                if (result.success) {
                    document.getElementById('mmStartBtn').style.display = 'none';
                    document.getElementById('mmStopBtn').style.display = 'block';
                    document.getElementById('mmStatusBadge').textContent = mmDryRun ? '模擬中' : '運行中';
                    document.getElementById('mmStatusBadge').style.background = mmDryRun ? '#f59e0b' : '#10b981';
                    mmSim.reset();  // 重置模擬統計
                } else {
                    alert('啟動失敗: ' + result.error);
                }
            }

            async function stopMM() {
                const res = await fetch('/api/mm/stop', { method: 'POST' });
                const result = await res.json();
                if (result.success) {
                    document.getElementById('mmStartBtn').style.display = 'block';
                    document.getElementById('mmStopBtn').style.display = 'none';
                    document.getElementById('mmStatusBadge').textContent = '停止';
                    document.getElementById('mmStatusBadge').style.background = '#2a3347';
                }
            }

            function toggleMMDryRun() {
                const toggle = document.getElementById('mmDryRunToggle');
                toggle.classList.toggle('active');
                mmDryRun = toggle.classList.contains('active');
            }

            // 初始化
            connect();
            updateExchangeOptions();
            loadConfiguredExchanges();
            loadMMConfig();  // 加載做市商配置
        </script>
    </body>
    </html>
    """


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 連接"""
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_clients.remove(websocket)


@app.get("/api/config/list")
async def list_configs():
    """獲取所有配置"""
    try:
        configs = config_manager.get_all_configs()
        return JSONResponse(configs)
    except Exception as e:
        return JSONResponse({'error': str(e)})


@app.post("/api/config/save")
async def save_config(request: Request):
    """保存配置並動態添加到監控"""
    try:
        data = await request.json()
        exchange_name = data['exchange_name']
        exchange_type = data['exchange_type']
        config = data['config']

        # 保存配置
        config_manager.save_config(exchange_name, exchange_type, config)

        # 動態添加到監控
        await add_exchange(exchange_name, exchange_type)

        return JSONResponse({'success': True})
    except Exception as e:
        return JSONResponse({'success': False, 'error': str(e)})


@app.post("/api/config/delete")
async def delete_config(request: Request):
    """刪除配置並從監控移除"""
    try:
        data = await request.json()
        exchange_name = data['exchange_name']
        exchange_type = data['exchange_type']

        # 從監控移除
        await remove_exchange(exchange_name)

        # 刪除配置
        config_manager.delete_config(exchange_name, exchange_type)

        return JSONResponse({'success': True})
    except Exception as e:
        return JSONResponse({'success': False, 'error': str(e)})


@app.post("/api/control/auto-execute")
async def control_auto_execute(request: Request):
    """控制自動執行"""
    try:
        data = await request.json()
        enabled = data['enabled']

        if executor:
            executor.enable_auto_execute = enabled
            system_status['auto_execute'] = enabled

        return JSONResponse({'success': True})
    except Exception as e:
        return JSONResponse({'success': False, 'error': str(e)})


@app.post("/api/control/live-trade")
async def control_live_trade(request: Request):
    """控制實際交易"""
    try:
        data = await request.json()
        enabled = data['enabled']

        if executor:
            executor.dry_run = not enabled
            system_status['dry_run'] = not enabled

        return JSONResponse({'success': True})
    except Exception as e:
        return JSONResponse({'success': False, 'error': str(e)})


# ==================== 做市商 API ====================

@app.post("/api/mm/start")
async def start_market_maker(request: Request):
    """啟動做市商"""
    global mm_executor, mm_status

    try:
        data = await request.json()
        order_size = Decimal(str(data.get('order_size', '0.001')))
        order_distance = int(data.get('order_distance', 8))
        dry_run = data.get('dry_run', True)

        # 檢查是否有 StandX 和 Binance
        if 'STANDX' not in adapters:
            return JSONResponse({'success': False, 'error': 'StandX 未連接'})
        if 'BINANCE' not in adapters:
            return JSONResponse({'success': False, 'error': 'Binance 未連接'})

        standx = adapters['STANDX']
        binance = adapters['BINANCE']

        # 創建配置
        config = MMConfig(
            standx_symbol="BTC-USD",
            binance_symbol="BTC/USDT:USDT",
            order_size_btc=order_size,
            order_distance_bps=order_distance,
            dry_run=dry_run,
        )

        # 創建對沖引擎
        hedge_engine = HedgeEngine(
            binance_adapter=binance,
            standx_adapter=standx,
        )

        # 創建執行器
        mm_executor = MarketMakerExecutor(
            standx_adapter=standx,
            binance_adapter=binance,
            hedge_engine=hedge_engine,
            config=config,
        )

        # 設置回調
        async def on_status_change(status: ExecutorStatus):
            mm_status['status'] = status.value

        mm_executor.on_status_change(on_status_change)

        # 啟動
        await mm_executor.start()

        mm_status['running'] = True
        mm_status['status'] = 'running'
        mm_status['dry_run'] = dry_run
        mm_status['order_size_btc'] = float(order_size)
        mm_status['order_distance_bps'] = order_distance

        logger.info(f"做市商已啟動 (dry_run={dry_run})")
        return JSONResponse({'success': True})

    except Exception as e:
        logger.error(f"啟動做市商失敗: {e}")
        return JSONResponse({'success': False, 'error': str(e)})


@app.post("/api/mm/stop")
async def stop_market_maker():
    """停止做市商"""
    global mm_executor, mm_status

    try:
        if mm_executor:
            await mm_executor.stop()
            mm_executor = None

        mm_status['running'] = False
        mm_status['status'] = 'stopped'

        logger.info("做市商已停止")
        return JSONResponse({'success': True})

    except Exception as e:
        logger.error(f"停止做市商失敗: {e}")
        return JSONResponse({'success': False, 'error': str(e)})


@app.get("/api/mm/status")
async def get_mm_status():
    """獲取做市商狀態"""
    try:
        result = mm_status.copy()
        if mm_executor:
            result['executor'] = serialize_for_json(mm_executor.to_dict())
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({'error': str(e)})


@app.get("/api/mm/positions")
async def get_mm_positions():
    """獲取做市商實時倉位"""
    try:
        positions = {
            'standx': {'btc': 0, 'equity': 0},
            'binance': {'btc': 0, 'usdt': 0},
        }

        # 查詢 StandX 倉位
        if 'STANDX' in adapters:
            try:
                standx = adapters['STANDX']
                standx_positions = await standx.get_positions('BTC-USD')
                for pos in standx_positions:
                    if 'BTC' in pos.symbol:
                        qty = float(pos.size)
                        if pos.side == 'short':
                            qty = -qty
                        positions['standx']['btc'] = qty

                # 查詢餘額
                balance = await standx.get_balance()
                positions['standx']['equity'] = float(balance.equity)
            except Exception as e:
                logger.warning(f"查詢 StandX 倉位失敗: {e}")

        # 查詢 Binance 倉位
        if 'BINANCE' in adapters:
            try:
                binance = adapters['BINANCE']
                binance_positions = await binance.get_positions('BTC/USDT:USDT')
                for pos in binance_positions:
                    if 'BTC' in pos.symbol:
                        qty = float(pos.size)
                        if pos.side == 'short':
                            qty = -qty
                        positions['binance']['btc'] = qty

                # 查詢 USDT 餘額
                balance = await binance.get_balance()
                positions['binance']['usdt'] = float(balance.available_balance)
            except Exception as e:
                logger.warning(f"查詢 Binance 倉位失敗: {e}")

        # 計算淨敞口
        positions['net_btc'] = positions['standx']['btc'] + positions['binance']['btc']
        positions['is_hedged'] = abs(positions['net_btc']) < 0.0001

        return JSONResponse(serialize_for_json(positions))
    except Exception as e:
        return JSONResponse({'error': str(e)})


@app.get("/api/mm/config")
async def get_mm_config_api():
    """獲取做市商配置"""
    try:
        config_manager = get_mm_config()
        return JSONResponse(config_manager.get_dict())
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=500)


@app.post("/api/mm/config")
async def update_mm_config_api(request: Request):
    """更新做市商配置"""
    try:
        data = await request.json()
        config_manager = get_mm_config()
        config_manager.update(data, save=True)
        return JSONResponse({'success': True, 'config': config_manager.get_dict()})
    except Exception as e:
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


@app.post("/api/mm/config/reload")
async def reload_mm_config_api():
    """重新加載做市商配置"""
    try:
        config_manager = get_mm_config()
        config_manager.reload()
        return JSONResponse({'success': True, 'config': config_manager.get_dict()})
    except Exception as e:
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8888, log_level="info")
