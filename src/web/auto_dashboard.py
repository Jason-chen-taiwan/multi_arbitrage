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
import uvicorn

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
from src.simulation import (
    ParamSetManager, SimulationRunner, ResultLogger, ComparisonEngine,
    get_param_set_manager
)

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
    'order_distance_bps': 9,  # 默認值與 mm_config.yaml 同步
}

# Simulation comparison globals
simulation_runner: Optional[SimulationRunner] = None
result_logger: Optional[ResultLogger] = None
comparison_engine: Optional[ComparisonEngine] = None

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
        # 使用 quote_mode='never' 避免添加引號
        if exchange_type == 'dex':
            if exchange_name == 'standx':
                set_key(self.env_file, 'WALLET_PRIVATE_KEY', config.get('private_key', ''), quote_mode='never')
                set_key(self.env_file, 'WALLET_ADDRESS', config.get('address', ''), quote_mode='never')
                set_key(self.env_file, 'STANDX_TESTNET', str(testnet).lower(), quote_mode='never')
            elif exchange_name == 'grvt':
                set_key(self.env_file, 'GRVT_API_KEY', config.get('api_key', ''), quote_mode='never')
                set_key(self.env_file, 'GRVT_API_SECRET', config.get('api_secret', ''), quote_mode='never')
                set_key(self.env_file, 'GRVT_TESTNET', str(testnet).lower(), quote_mode='never')
        else:
            prefix = exchange_name.upper()
            set_key(self.env_file, f'{prefix}_API_KEY', config.get('api_key', ''), quote_mode='never')
            set_key(self.env_file, f'{prefix}_API_SECRET', config.get('api_secret', ''), quote_mode='never')
            set_key(self.env_file, f'{prefix}_TESTNET', str(testnet).lower(), quote_mode='never')

            if exchange_name in ['okx', 'bitget']:
                passphrase = config.get('passphrase', '')
                if passphrase:
                    set_key(self.env_file, f'{prefix}_PASSPHRASE', passphrase, quote_mode='never')

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
    global simulation_runner
    # 啟動
    await init_system()
    asyncio.create_task(broadcast_data())
    yield
    # 關閉 - 確保所有組件正確停止
    logger.info("Shutting down application...")

    # Stop simulation runner first
    if simulation_runner and simulation_runner.is_running():
        logger.info("Stopping simulation runner...")
        try:
            await asyncio.wait_for(simulation_runner.stop(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Simulation runner stop timed out during shutdown")
            simulation_runner._running = False
        except Exception as e:
            logger.error(f"Error stopping simulation runner: {e}")

    if monitor:
        await monitor.stop()
    if executor:
        await executor.stop()

    logger.info("Application shutdown complete")


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
                <button class="nav-tab" onclick="switchPage('comparison')">參數比較</button>
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
                        <div class="card-title">模擬掛單 (需在 mark ± 30 bps 內)</div>
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
                            載入配置中...
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
                    <div class="settings-title" style="display: flex; justify-content: space-between; align-items: center;">
                        <span>已配置交易所</span>
                        <button class="btn btn-primary" onclick="reinitSystem()" id="reinitBtn">🔄 重新連接</button>
                    </div>
                    <div id="reinitStatus" style="color: #9ca3af; margin-bottom: 10px; display: none;"></div>
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

            <!-- ==================== 參數比較頁面 ==================== -->
            <div id="page-comparison" class="page">
                <div style="margin-bottom: 20px;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <h2 style="font-size: 24px; font-weight: 700; color: #667eea;">參數比較模擬</h2>
                        <div style="display: flex; gap: 10px; align-items: center;">
                            <span id="simStatusBadge" class="badge" style="background: #2a3347; padding: 6px 12px;">未運行</span>
                            <button id="simStartBtn" class="btn btn-primary" onclick="startSimulation()">開始比較</button>
                            <button id="simStopBtn" class="btn btn-danger" onclick="stopSimulation()" style="display:none;">停止</button>
                        </div>
                    </div>
                    <p style="color: #9ca3af; margin-top: 8px; font-size: 13px;">
                        同時運行多組參數，比較 Uptime、成交次數、PnL 等指標，找出最佳參數組合
                    </p>
                </div>

                <div class="grid-2" style="gap: 20px;">
                    <!-- 左側：參數組選擇 -->
                    <div class="card">
                        <div class="card-title" style="display: flex; justify-content: space-between; align-items: center;">
                            <span>選擇參數組</span>
                            <button class="btn" style="padding: 4px 10px; font-size: 11px;" onclick="openParamSetEditor()">+ 新增</button>
                        </div>
                        <div id="paramSetList" style="display: flex; flex-direction: column; gap: 8px; max-height: 400px; overflow-y: auto;">
                            <p style="color: #9ca3af; text-align: center;">載入中...</p>
                        </div>
                        <div style="margin-top: 15px; padding-top: 15px; border-top: 1px solid #2a3347;">
                            <div style="display: flex; align-items: center; gap: 15px;">
                                <label style="font-size: 12px; color: #9ca3af;">持續時間</label>
                                <select id="simDuration" style="padding: 6px 12px; background: #0f1419; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                                    <option value="5">5 分鐘</option>
                                    <option value="15">15 分鐘</option>
                                    <option value="30">30 分鐘</option>
                                    <option value="60" selected>1 小時</option>
                                    <option value="120">2 小時</option>
                                    <option value="240">4 小時</option>
                                </select>
                            </div>
                        </div>
                    </div>

                    <!-- 右側：即時比較結果 -->
                    <div class="card">
                        <div class="card-title">即時比較 <span id="simProgress" style="color: #9ca3af; font-size: 11px; margin-left: 10px;"></span></div>
                        <div style="font-size: 10px; color: #6b7280; margin-bottom: 8px;">
                            積分規則：<span style="color: #10b981;">0-10bps=100%</span> |
                            <span style="color: #f59e0b;">10-30bps=50%</span> |
                            <span style="color: #9ca3af;">30-100bps=10%</span>
                        </div>
                        <div id="liveComparison" style="overflow-x: auto;">
                            <table class="price-table" style="font-size: 11px;">
                                <thead>
                                    <tr>
                                        <th>參數組</th>
                                        <th style="color: #667eea;">有效積分</th>
                                        <th style="color: #10b981;">100%檔</th>
                                        <th style="color: #f59e0b;">50%檔</th>
                                        <th style="color: #9ca3af;">10%檔</th>
                                        <th>成交</th>
                                        <th>PnL</th>
                                        <th>撤單</th>
                                    </tr>
                                </thead>
                                <tbody id="liveComparisonBody">
                                    <tr><td colspan="8" style="text-align: center; color: #9ca3af; padding: 20px;">選擇參數組後點擊「開始比較」</td></tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>

                <!-- 歷史運行記錄 -->
                <div class="card" style="margin-top: 20px;">
                    <div class="card-title" style="display: flex; justify-content: space-between; align-items: center;">
                        <span>歷史比較記錄</span>
                        <button class="btn" style="padding: 4px 10px; font-size: 11px;" onclick="loadSimulationRuns()">刷新</button>
                    </div>
                    <div id="simRunsList" style="overflow-x: auto;">
                        <table class="price-table" style="font-size: 12px;">
                            <thead>
                                <tr>
                                    <th>運行ID</th>
                                    <th>開始時間</th>
                                    <th>持續時間</th>
                                    <th>參數組數</th>
                                    <th>推薦</th>
                                    <th>操作</th>
                                </tr>
                            </thead>
                            <tbody id="simRunsBody">
                                <tr><td colspan="6" style="text-align: center; color: #9ca3af; padding: 20px;">無歷史記錄</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <!-- 模擬操作歷史 -->
                <div id="simOperationHistoryCard" class="card" style="margin-top: 20px; display: none;">
                    <div class="card-title" style="display: flex; justify-content: space-between; align-items: center;">
                        <span>操作歷史 <span style="font-size: 10px; color: #9ca3af;">(最近 50 筆)</span></span>
                        <select id="simHistoryParamSetSelect" onchange="updateSimOperationHistory()" style="padding: 4px 8px; background: #0f1419; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 11px;">
                            <option value="">載入中...</option>
                        </select>
                    </div>
                    <div id="simOperationHistoryList" style="max-height: 350px; overflow-y: auto; font-size: 11px;">
                        <div style="color: #9ca3af; text-align: center; padding: 20px;">載入操作歷史中...</div>
                    </div>
                </div>

                <!-- 詳細結果展開區 -->
                <div id="simResultDetail" class="card" style="margin-top: 20px; display: none;">
                    <div class="card-title" style="display: flex; justify-content: space-between; align-items: center;">
                        <span>比較結果詳情</span>
                        <button class="btn" style="padding: 4px 10px; font-size: 11px;" onclick="closeResultDetail()">關閉</button>
                    </div>
                    <div id="simResultContent"></div>
                </div>

                <!-- 參數組編輯彈窗 -->
                <div id="paramSetModal" style="display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); z-index: 2000; align-items: center; justify-content: center;">
                    <div style="background: #1a1f2e; border: 1px solid #2a3347; border-radius: 8px; padding: 20px; width: 450px; max-width: 90%;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                            <h3 id="paramSetModalTitle" style="font-size: 16px; color: #667eea;">編輯參數組</h3>
                            <button onclick="closeParamSetEditor()" style="background: none; border: none; color: #9ca3af; font-size: 20px; cursor: pointer;">&times;</button>
                        </div>
                        <div style="display: flex; flex-direction: column; gap: 12px;">
                            <input type="hidden" id="psEditId">
                            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
                                <div>
                                    <label style="font-size: 11px; color: #9ca3af; display: block; margin-bottom: 4px;">ID (唯一標識)</label>
                                    <input type="text" id="psEditIdInput" placeholder="例: my_strategy" style="width: 100%; padding: 8px; background: #0f1419; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                                </div>
                                <div>
                                    <label style="font-size: 11px; color: #9ca3af; display: block; margin-bottom: 4px;">名稱</label>
                                    <input type="text" id="psEditName" placeholder="例: 我的策略" style="width: 100%; padding: 8px; background: #0f1419; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                                </div>
                            </div>
                            <div>
                                <label style="font-size: 11px; color: #9ca3af; display: block; margin-bottom: 4px;">描述</label>
                                <input type="text" id="psEditDesc" placeholder="策略描述" style="width: 100%; padding: 8px; background: #0f1419; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                            </div>
                            <div style="background: #0f1419; padding: 12px; border-radius: 6px;">
                                <div style="font-size: 11px; color: #6b7280; margin-bottom: 10px;">報價參數</div>
                                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
                                    <div>
                                        <label style="font-size: 10px; color: #9ca3af;">掛單距離 (bps)</label>
                                        <input type="number" id="psEditOrderDist" min="1" max="20" step="1" style="width: 100%; padding: 6px; background: #1a1f2e; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                                    </div>
                                    <div>
                                        <label style="font-size: 10px; color: #9ca3af;">撤單距離 (bps)</label>
                                        <input type="number" id="psEditCancelDist" min="1" max="10" step="1" style="width: 100%; padding: 6px; background: #1a1f2e; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                                    </div>
                                    <div>
                                        <label style="font-size: 10px; color: #9ca3af;">重掛距離 (bps)</label>
                                        <input type="number" id="psEditRebalDist" min="8" max="30" step="1" style="width: 100%; padding: 6px; background: #1a1f2e; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                                    </div>
                                    <div>
                                        <label style="font-size: 10px; color: #9ca3af;">隊列風控 (檔)</label>
                                        <input type="number" id="psEditQueueLimit" min="1" max="10" step="1" style="width: 100%; padding: 6px; background: #1a1f2e; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                                    </div>
                                </div>
                            </div>
                            <div style="display: flex; gap: 10px; margin-top: 10px;">
                                <button onclick="saveParamSet()" class="btn btn-primary" style="flex: 1;">保存</button>
                                <button onclick="closeParamSetEditor()" class="btn" style="flex: 1;">取消</button>
                            </div>
                            <div id="psEditDeleteBtn" style="display: none; margin-top: 5px;">
                                <button onclick="deleteParamSet()" class="btn btn-danger" style="width: 100%;">刪除此參數組</button>
                            </div>
                        </div>
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

                let html = '<table style="width: 100%; border-collapse: collapse; font-size: 10px;">';
                html += '<thead><tr style="color: #9ca3af; border-bottom: 1px solid #2a3347;">';
                html += '<th style="text-align: left; padding: 3px;">時間</th>';
                html += '<th style="text-align: left; padding: 3px;">操作</th>';
                html += '<th style="text-align: center; padding: 3px;">排位</th>';
                html += '<th style="text-align: right; padding: 3px;">訂單價</th>';
                html += '<th style="text-align: right; padding: 3px;">Best Bid</th>';
                html += '<th style="text-align: right; padding: 3px;">Best Ask</th>';
                html += '<th style="text-align: left; padding: 3px;">原因</th>';
                html += '</tr></thead><tbody>';

                mmSim.history.forEach((h, i) => {
                    const bgColor = i % 2 === 0 ? '#0f1419' : 'transparent';
                    const actionColor = actionColors[h.action] || '#9ca3af';
                    const orderPrice = h.oldPrice || h.newPrice;

                    // 隊列位置顏色：1-3檔紅色警告
                    const queueColor = h.queuePos && h.queuePos <= 3 ? '#ef4444' : '#9ca3af';
                    const queueText = h.queuePos ? '第' + h.queuePos + '檔' : '-';

                    html += '<tr style="background: ' + bgColor + ';">';
                    html += '<td style="padding: 3px; color: #6b7280;">' + h.time + '</td>';
                    html += '<td style="padding: 3px;"><span style="color: ' + actionColor + ';">' + sideNames[h.side] + actionNames[h.action] + '</span></td>';
                    html += '<td style="padding: 3px; text-align: center; color: ' + queueColor + '; font-weight: ' + (h.queuePos <= 3 ? '700' : '400') + ';">' + queueText + '</td>';
                    html += '<td style="padding: 3px; text-align: right; color: #e5e7eb;">' + (orderPrice ? '$' + orderPrice.toLocaleString(undefined, {minimumFractionDigits: 2}) : '-') + '</td>';
                    html += '<td style="padding: 3px; text-align: right; color: #10b981;">' + (h.bestBid ? '$' + h.bestBid.toLocaleString(undefined, {minimumFractionDigits: 2}) : '-') + '</td>';
                    html += '<td style="padding: 3px; text-align: right; color: #ef4444;">' + (h.bestAsk ? '$' + h.bestAsk.toLocaleString(undefined, {minimumFractionDigits: 2}) : '-') + '</td>';
                    html += '<td style="padding: 3px; color: #9ca3af;">' + h.reason + '</td>';
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
                    document.getElementById('mmQueuePositionLimit').value = mmConfig.quote.queue_position_limit;
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
                        '撤單: ' + q.cancel_distance_bps + ' bps | 隊列: 前' + q.queue_position_limit + '檔 | 重掛: ' + q.rebalance_distance_bps + ' bps';
                }
            }

            // ===== 做市商模擬狀態 =====
            const mmSim = {
                // 配置 (從 API 加載，不設默認值)
                orderDistanceBps: null,
                cancelDistanceBps: null,
                rebalanceDistanceBps: null,
                uptimeMaxDistanceBps: null,
                queuePositionLimit: null,

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
                addHistory(action, side, oldPrice, newPrice, midPrice, distBps, reason, extra = {}) {
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
                        reason,      // 原因說明
                        queuePos: extra.queuePos || null,      // 隊列位置
                        bestBid: extra.bestBid || null,        // 最佳買價
                        bestAsk: extra.bestAsk || null,        // 最佳賣價
                    });
                    if (this.history.length > this.maxHistorySize) {
                        this.history.pop();
                    }
                },

                // 下單
                placeOrder(side, midPrice, reason = '初始下單', ob = null) {
                    const price = side === 'bid'
                        ? Math.floor(midPrice * (1 - this.orderDistanceBps / 10000) * 100) / 100
                        : Math.ceil(midPrice * (1 + this.orderDistanceBps / 10000) * 100) / 100;

                    const order = { price, placedAt: Date.now(), placedMid: midPrice };
                    if (side === 'bid') this.bidOrder = order;
                    else this.askOrder = order;

                    // 計算新訂單的隊列位置
                    const queuePos = this.getQueuePosition(side, price, ob);
                    const extra = {
                        queuePos,
                        bestBid: ob?.bids?.[0]?.[0] || null,
                        bestAsk: ob?.asks?.[0]?.[0] || null,
                    };

                    this.addHistory('place', side, null, price, midPrice, this.orderDistanceBps, reason, extra);
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

                // 檢查配置是否已載入
                isConfigLoaded() {
                    return this.orderDistanceBps !== null;
                },

                // 檢查並處理訂單 (基於時間的 Uptime 計算)
                tick(midPrice, ob) {
                    // 配置未載入時不執行
                    if (!this.isConfigLoaded()) return { bidStatus: 'waiting', askStatus: 'waiting' };

                    const now = Date.now();
                    let bidStatus = 'none';
                    let askStatus = 'none';

                    // 計算自上次 tick 以來的時間間隔
                    const deltaMs = this.lastTickTime ? (now - this.lastTickTime) : 0;
                    this.lastTickTime = now;
                    this.totalTimeMs += deltaMs;

                    // 取得最佳買賣價
                    const bestBid = ob?.bids?.[0]?.[0] || null;
                    const bestAsk = ob?.asks?.[0]?.[0] || null;

                    // 處理買單
                    if (this.bidOrder) {
                        const distBps = (midPrice - this.bidOrder.price) / midPrice * 10000;
                        const queuePos = this.getQueuePosition('bid', this.bidOrder.price, ob);
                        const extra = { queuePos, bestBid, bestAsk };

                        // 優先檢查隊列位置風控
                        if (queuePos && queuePos <= this.queuePositionLimit) {
                            const oldPrice = this.bidOrder.price;
                            bidStatus = 'queue_cancel';
                            this.bidOrder = null;
                            this.bidQueueCancels++;
                            this.addHistory('cancel', 'bid', oldPrice, null, midPrice, distBps.toFixed(2),
                                '隊列風控 (第' + queuePos + '檔)', extra);
                        } else if (distBps < this.cancelDistanceBps) {
                            const oldPrice = this.bidOrder.price;
                            bidStatus = 'cancel';
                            this.bidOrder = null;
                            this.bidCancels++;
                            this.addHistory('cancel', 'bid', oldPrice, null, midPrice, distBps.toFixed(2),
                                'bps太近 (' + distBps.toFixed(2) + ' < ' + this.cancelDistanceBps + ')', extra);
                        } else if (distBps > this.rebalanceDistanceBps) {
                            const oldPrice = this.bidOrder.price;
                            bidStatus = 'rebalance';
                            this.bidOrder = null;
                            this.bidRebalances++;
                            this.addHistory('rebalance', 'bid', oldPrice, null, midPrice, distBps.toFixed(2),
                                'bps太遠 (' + distBps.toFixed(2) + ' > ' + this.rebalanceDistanceBps + ')', extra);
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
                        const extra = { queuePos, bestBid, bestAsk };

                        // 優先檢查隊列位置風控
                        if (queuePos && queuePos <= this.queuePositionLimit) {
                            const oldPrice = this.askOrder.price;
                            askStatus = 'queue_cancel';
                            this.askOrder = null;
                            this.askQueueCancels++;
                            this.addHistory('cancel', 'ask', oldPrice, null, midPrice, distBps.toFixed(2),
                                '隊列風控 (第' + queuePos + '檔)', extra);
                        } else if (distBps < this.cancelDistanceBps) {
                            const oldPrice = this.askOrder.price;
                            askStatus = 'cancel';
                            this.askOrder = null;
                            this.askCancels++;
                            this.addHistory('cancel', 'ask', oldPrice, null, midPrice, distBps.toFixed(2),
                                'bps太近 (' + distBps.toFixed(2) + ' < ' + this.cancelDistanceBps + ')', extra);
                        } else if (distBps > this.rebalanceDistanceBps) {
                            const oldPrice = this.askOrder.price;
                            askStatus = 'rebalance';
                            this.askOrder = null;
                            this.askRebalances++;
                            this.addHistory('rebalance', 'ask', oldPrice, null, midPrice, distBps.toFixed(2),
                                'bps太遠 (' + distBps.toFixed(2) + ' > ' + this.rebalanceDistanceBps + ')', extra);
                        } else if (distBps <= this.uptimeMaxDistanceBps) {
                            askStatus = 'qualified';
                        } else {
                            askStatus = 'out_of_range';
                        }
                    }

                    // 沒有訂單則下單，並立即檢查是否合格
                    if (!this.bidOrder) {
                        const reason = (bidStatus === 'cancel' || bidStatus === 'queue_cancel') ? '撤單後重掛' : (bidStatus === 'rebalance' ? '重平衡重掛' : '初始下單');
                        this.placeOrder('bid', midPrice, reason, ob);
                        if (this.orderDistanceBps <= this.uptimeMaxDistanceBps) {
                            bidStatus = 'qualified';
                        }
                    }
                    if (!this.askOrder) {
                        const reason = (askStatus === 'cancel' || askStatus === 'queue_cancel') ? '撤單後重掛' : (askStatus === 'rebalance' ? '重平衡重掛' : '初始下單');
                        this.placeOrder('ask', midPrice, reason, ob);
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
                        this.queuePositionLimit = config.quote.queue_position_limit;
                    }
                    if (config.uptime) {
                        this.uptimeMaxDistanceBps = config.uptime.max_distance_bps;
                    }
                    console.log('mmSim config loaded:', {
                        orderDistanceBps: this.orderDistanceBps,
                        cancelDistanceBps: this.cancelDistanceBps,
                        rebalanceDistanceBps: this.rebalanceDistanceBps,
                        queuePositionLimit: this.queuePositionLimit,
                        uptimeMaxDistanceBps: this.uptimeMaxDistanceBps
                    });
                }
            };

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
                const maxDistBps = mmSim.uptimeMaxDistanceBps || 30;
                if (bidOrder) {
                    const bidInRange = bidDistBps <= maxDistBps;
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
                        bidStatusText = '⚠️ 超出' + maxDistBps + 'bps (' + bidDistBps.toFixed(1) + ')';
                    }
                    document.getElementById('mmBidStatus').textContent = bidStatusText;
                } else {
                    document.getElementById('mmSuggestedBid').innerHTML = '<span style="color: #9ca3af">下單中...</span>';
                    document.getElementById('mmBidStatus').textContent = '新掛單';
                }

                if (askOrder) {
                    const askInRange = askDistBps <= maxDistBps;
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
                        askStatusText = '⚠️ 超出' + maxDistBps + 'bps (' + askDistBps.toFixed(1) + ')';
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

            async function reinitSystem() {
                const btn = document.getElementById('reinitBtn');
                const status = document.getElementById('reinitStatus');
                btn.disabled = true;
                btn.textContent = '🔄 連接中...';
                status.style.display = 'block';
                status.textContent = '正在重新初始化系統...';
                status.style.color = '#f59e0b';

                try {
                    const res = await fetch('/api/system/reinit', { method: 'POST' });
                    const result = await res.json();
                    if (result.success) {
                        status.textContent = '✅ ' + result.message;
                        status.style.color = '#10b981';
                        loadConfiguredExchanges();
                    } else {
                        status.textContent = '❌ ' + result.error;
                        status.style.color = '#ef4444';
                    }
                } catch (e) {
                    status.textContent = '❌ 連接失敗: ' + e.message;
                    status.style.color = '#ef4444';
                }
                btn.disabled = false;
                btn.textContent = '🔄 重新連接';
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

            // ===== 參數比較模擬功能 =====
            let simPollingInterval = null;
            let selectedParamSets = new Set();

            let paramSetsData = {};  // Store loaded param sets for editing

            async function loadParamSets() {
                try {
                    const res = await fetch('/api/simulation/param-sets');
                    const data = await res.json();

                    const container = document.getElementById('paramSetList');
                    if (!data.param_sets || data.param_sets.length === 0) {
                        container.innerHTML = '<p style="color: #9ca3af; text-align: center;">無可用參數組</p>';
                        return;
                    }

                    // Store for editing
                    paramSetsData = {};
                    data.param_sets.forEach(ps => { paramSetsData[ps.id] = ps; });

                    // Clear and rebuild selection - default select 100% tier (boosted) strategies
                    selectedParamSets.clear();
                    const defaultIds = ['boosted_safe', 'boosted_balanced', 'boosted_risky'];

                    container.innerHTML = data.param_sets.map(ps => {
                        const isDefault = defaultIds.includes(ps.id);
                        if (isDefault) selectedParamSets.add(ps.id);
                        const quote = ps.config && ps.config.quote ? ps.config.quote : {};
                        return `
                            <div class="param-set-item" style="display: flex; align-items: center; gap: 10px; padding: 10px; background: #0f1419; border-radius: 6px;">
                                <input type="checkbox" id="ps_${ps.id}" value="${ps.id}" ${isDefault ? 'checked' : ''}
                                    onchange="toggleParamSet('${ps.id}')"
                                    style="width: 16px; height: 16px; accent-color: #667eea; cursor: pointer;">
                                <div style="flex: 1; cursor: pointer;" onclick="document.getElementById('ps_${ps.id}').click()">
                                    <div style="font-weight: 600; color: #e4e6eb;">${ps.name}</div>
                                    <div style="font-size: 11px; color: #6b7280;">${ps.description || ''}</div>
                                    <div style="font-size: 10px; color: #4b5563; margin-top: 4px;">
                                        掛單 <span style="color: #667eea;">${quote.order_distance_bps || '-'}</span> bps |
                                        撤單 <span style="color: #ef4444;">${quote.cancel_distance_bps || '-'}</span> bps |
                                        重掛 <span style="color: #f59e0b;">${quote.rebalance_distance_bps || '-'}</span> bps |
                                        隊列 <span style="color: #10b981;">${quote.queue_position_limit || '-'}</span> 檔
                                    </div>
                                </div>
                                <button onclick="openParamSetEditor('${ps.id}')" class="btn" style="padding: 4px 8px; font-size: 10px;">編輯</button>
                            </div>
                        `;
                    }).join('');

                    console.log('Loaded param sets, default selected:', Array.from(selectedParamSets));
                } catch (e) {
                    console.error('Failed to load param sets:', e);
                    document.getElementById('paramSetList').innerHTML = '<p style="color: #ef4444;">載入失敗</p>';
                }
            }

            function toggleParamSet(id) {
                const checkbox = document.getElementById('ps_' + id);
                if (checkbox && checkbox.checked) {
                    selectedParamSets.add(id);
                } else {
                    selectedParamSets.delete(id);
                }
                console.log('toggleParamSet:', id, 'selected:', Array.from(selectedParamSets));
            }

            // ===== 參數組編輯功能 =====
            let currentEditingId = null;

            function openParamSetEditor(id = null) {
                const modal = document.getElementById('paramSetModal');
                modal.style.display = 'flex';

                if (id && paramSetsData[id]) {
                    // Edit existing
                    const ps = paramSetsData[id];
                    const quote = ps.config && ps.config.quote ? ps.config.quote : {};
                    currentEditingId = id;
                    document.getElementById('paramSetModalTitle').textContent = '編輯參數組';
                    document.getElementById('psEditId').value = id;
                    document.getElementById('psEditIdInput').value = id;
                    document.getElementById('psEditIdInput').disabled = true;  // Can't change ID when editing
                    document.getElementById('psEditName').value = ps.name || '';
                    document.getElementById('psEditDesc').value = ps.description || '';
                    document.getElementById('psEditOrderDist').value = quote.order_distance_bps || 8;
                    document.getElementById('psEditCancelDist').value = quote.cancel_distance_bps || 4;
                    document.getElementById('psEditRebalDist').value = quote.rebalance_distance_bps || 12;
                    document.getElementById('psEditQueueLimit').value = quote.queue_position_limit || 3;
                    document.getElementById('psEditDeleteBtn').style.display = 'block';
                } else {
                    // Create new
                    currentEditingId = null;
                    document.getElementById('paramSetModalTitle').textContent = '新增參數組';
                    document.getElementById('psEditId').value = '';
                    document.getElementById('psEditIdInput').value = '';
                    document.getElementById('psEditIdInput').disabled = false;
                    document.getElementById('psEditName').value = '';
                    document.getElementById('psEditDesc').value = '';
                    document.getElementById('psEditOrderDist').value = 8;
                    document.getElementById('psEditCancelDist').value = 4;
                    document.getElementById('psEditRebalDist').value = 12;
                    document.getElementById('psEditQueueLimit').value = 3;
                    document.getElementById('psEditDeleteBtn').style.display = 'none';
                }
            }

            function closeParamSetEditor() {
                document.getElementById('paramSetModal').style.display = 'none';
                currentEditingId = null;
            }

            async function saveParamSet() {
                const id = currentEditingId || document.getElementById('psEditIdInput').value.trim();
                const name = document.getElementById('psEditName').value.trim();

                if (!id) {
                    alert('請輸入參數組 ID');
                    return;
                }
                if (!name) {
                    alert('請輸入參數組名稱');
                    return;
                }

                const psData = {
                    id: id,
                    name: name,
                    description: document.getElementById('psEditDesc').value.trim(),
                    overrides: {
                        quote: {
                            order_distance_bps: parseInt(document.getElementById('psEditOrderDist').value),
                            cancel_distance_bps: parseInt(document.getElementById('psEditCancelDist').value),
                            rebalance_distance_bps: parseInt(document.getElementById('psEditRebalDist').value),
                            queue_position_limit: parseInt(document.getElementById('psEditQueueLimit').value)
                        }
                    }
                };

                try {
                    const url = currentEditingId
                        ? '/api/simulation/param-sets/' + currentEditingId
                        : '/api/simulation/param-sets';
                    const method = currentEditingId ? 'PUT' : 'POST';

                    const res = await fetch(url, {
                        method: method,
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(psData)
                    });
                    const result = await res.json();

                    if (result.success) {
                        closeParamSetEditor();
                        loadParamSets();
                    } else {
                        alert('保存失敗: ' + result.error);
                    }
                } catch (e) {
                    console.error('Failed to save param set:', e);
                    alert('保存失敗: ' + e.message);
                }
            }

            async function deleteParamSet() {
                if (!currentEditingId) return;
                if (!confirm('確定刪除此參數組？此操作無法撤銷。')) return;

                try {
                    const res = await fetch('/api/simulation/param-sets/' + currentEditingId, {
                        method: 'DELETE'
                    });
                    const result = await res.json();

                    if (result.success) {
                        closeParamSetEditor();
                        selectedParamSets.delete(currentEditingId);
                        loadParamSets();
                    } else {
                        alert('刪除失敗: ' + result.error);
                    }
                } catch (e) {
                    console.error('Failed to delete param set:', e);
                    alert('刪除失敗: ' + e.message);
                }
            }

            async function startSimulation() {
                console.log('startSimulation() called');
                console.log('selectedParamSets:', Array.from(selectedParamSets));

                if (selectedParamSets.size === 0) {
                    console.log('No param sets selected');
                    alert('請至少選擇一個參數組');
                    return;
                }

                const duration = parseInt(document.getElementById('simDuration').value);
                const paramSetIds = Array.from(selectedParamSets);
                console.log('Starting simulation with:', { paramSetIds, duration });

                try {
                    document.getElementById('simStartBtn').disabled = true;
                    document.getElementById('simStartBtn').textContent = '啟動中...';

                    console.log('Sending start request...');
                    const res = await fetch('/api/simulation/start', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            param_set_ids: paramSetIds,
                            duration_minutes: duration
                        })
                    });

                    console.log('Response status:', res.status);
                    const result = await res.json();
                    console.log('Response data:', result);

                    if (result.success) {
                        console.log('Simulation started successfully');
                        document.getElementById('simStartBtn').style.display = 'none';
                        document.getElementById('simStopBtn').style.display = 'inline-block';
                        document.getElementById('simStatusBadge').textContent = '運行中';
                        document.getElementById('simStatusBadge').style.background = '#10b981';

                        // 開始定時更新
                        startSimPolling();
                    } else {
                        console.error('Start failed:', result.error);
                        alert('啟動失敗: ' + result.error);
                    }
                } catch (e) {
                    console.error('Failed to start simulation:', e);
                    alert('啟動失敗: ' + e.message);
                } finally {
                    document.getElementById('simStartBtn').disabled = false;
                    document.getElementById('simStartBtn').textContent = '開始比較';
                }
            }

            async function stopSimulation() {
                console.log('stopSimulation() called');

                // Stop polling immediately to prevent race conditions
                stopSimPolling();

                const stopBtn = document.getElementById('simStopBtn');
                if (stopBtn) {
                    stopBtn.disabled = true;
                    stopBtn.textContent = '停止中...';
                }

                // Helper to reset UI
                function resetUI(status, color) {
                    document.getElementById('simStartBtn').style.display = 'inline-block';
                    document.getElementById('simStopBtn').style.display = 'none';
                    document.getElementById('simStatusBadge').textContent = status;
                    document.getElementById('simStatusBadge').style.background = color;
                    document.getElementById('simOperationHistoryCard').style.display = 'none';
                    liveSimStatus = null;
                    if (stopBtn) {
                        stopBtn.disabled = false;
                        stopBtn.textContent = '停止';
                    }
                }

                try {
                    console.log('Sending stop request with timeout...');

                    // Use AbortController for fetch timeout
                    const controller = new AbortController();
                    const timeoutId = setTimeout(() => controller.abort(), 15000);

                    let res;
                    try {
                        res = await fetch('/api/simulation/stop', {
                            method: 'POST',
                            signal: controller.signal
                        });
                        clearTimeout(timeoutId);
                    } catch (fetchError) {
                        clearTimeout(timeoutId);
                        if (fetchError.name === 'AbortError') {
                            console.log('Stop request timed out, trying force-stop...');
                            // Try force-stop
                            const forceRes = await fetch('/api/simulation/force-stop', { method: 'POST' });
                            const forceResult = await forceRes.json();
                            console.log('Force stop result:', forceResult);
                            resetUI('已強制停止', '#f59e0b');
                            loadSimulationRuns();
                            return;
                        }
                        throw fetchError;
                    }

                    console.log('Response status:', res.status);
                    const result = await res.json();
                    console.log('Stop result:', result);

                    resetUI('已停止', '#f59e0b');
                    loadSimulationRuns();

                    if (!result.success) {
                        console.error('Stop failed:', result.error);
                        alert('停止失敗: ' + (result.error || '未知錯誤'));
                    }
                } catch (e) {
                    console.error('Failed to stop simulation:', e);

                    // Try force-stop as last resort
                    try {
                        console.log('Trying force-stop as fallback...');
                        await fetch('/api/simulation/force-stop', { method: 'POST' });
                        resetUI('已強制停止', '#f59e0b');
                    } catch (forceError) {
                        console.error('Force stop also failed:', forceError);
                        resetUI('錯誤', '#ef4444');
                        alert('停止請求失敗，請重新整理頁面');
                    }
                }
            }

            function startSimPolling() {
                console.log('startSimPolling() called');
                updateLiveComparison();  // 立即更新一次
                simPollingInterval = setInterval(updateLiveComparison, 1000);  // 每秒更新
            }

            function stopSimPolling() {
                if (simPollingInterval) {
                    clearInterval(simPollingInterval);
                    simPollingInterval = null;
                }
            }

            // Store live status with executors for operation history
            let liveSimStatus = null;

            async function updateLiveComparison() {
                try {
                    console.log('updateLiveComparison() called');
                    // 獲取狀態
                    const statusRes = await fetch('/api/simulation/status');
                    const status = await statusRes.json();
                    console.log('Status response:', status);

                    if (!status.running) {
                        console.log('Simulation not running, resetting UI');
                        stopSimPolling();
                        document.getElementById('simStartBtn').style.display = 'inline-block';
                        document.getElementById('simStopBtn').style.display = 'none';
                        document.getElementById('simStatusBadge').textContent = '已完成';
                        document.getElementById('simStatusBadge').style.background = '#667eea';
                        document.getElementById('simOperationHistoryCard').style.display = 'none';
                        liveSimStatus = null;
                        loadSimulationRuns();
                        return;
                    }

                    // Store status for operation history
                    liveSimStatus = status;

                    // 更新進度
                    const progress = status.progress_pct || 0;
                    const elapsed = Math.floor(status.elapsed_seconds || 0);
                    document.getElementById('simProgress').textContent =
                        `${progress.toFixed(1)}% (${Math.floor(elapsed/60)}分${elapsed%60}秒)`;

                    // 獲取即時比較數據
                    const compRes = await fetch('/api/simulation/comparison');
                    const comparison = await compRes.json();

                    updateComparisonTable(comparison);

                    // 更新操作歷史選擇器
                    updateSimHistoryParamSetSelect(status.executors);

                    // 顯示操作歷史卡片
                    document.getElementById('simOperationHistoryCard').style.display = 'block';

                    // 更新當前選中的操作歷史
                    updateSimOperationHistory();
                } catch (e) {
                    console.error('Failed to update live comparison:', e);
                }
            }

            function updateSimHistoryParamSetSelect(executors) {
                const select = document.getElementById('simHistoryParamSetSelect');
                const currentValue = select.value;

                const executorIds = Object.keys(executors || {});
                console.log('updateSimHistoryParamSetSelect, executorIds:', executorIds);

                if (executorIds.length === 0) {
                    select.innerHTML = '<option value="">無可用參數組</option>';
                    return;
                }

                // Always rebuild options to keep in sync
                let html = '';
                executorIds.forEach(id => {
                    const executor = executors[id];
                    const name = executor.param_set_name || id;
                    html += `<option value="${id}">${name}</option>`;
                });
                select.innerHTML = html;

                // Restore selection or default to first
                if (currentValue && executorIds.includes(currentValue)) {
                    select.value = currentValue;
                } else {
                    select.value = executorIds[0];
                }
                console.log('Selected param set:', select.value);
            }

            function updateSimOperationHistory() {
                const select = document.getElementById('simHistoryParamSetSelect');
                const container = document.getElementById('simOperationHistoryList');
                let selectedId = select.value;

                // Debug logging
                console.log('updateSimOperationHistory called');
                console.log('  selectedId:', selectedId);
                console.log('  liveSimStatus:', liveSimStatus);
                console.log('  liveSimStatus.executors:', liveSimStatus?.executors);

                if (!liveSimStatus || !liveSimStatus.executors) {
                    container.innerHTML = '<div style="color: #9ca3af; text-align: center; padding: 20px;">等待模擬數據...</div>';
                    return;
                }

                // Auto-select first executor if none selected
                const executorIds = Object.keys(liveSimStatus.executors);
                if (!selectedId && executorIds.length > 0) {
                    selectedId = executorIds[0];
                    select.value = selectedId;
                    console.log('  Auto-selected:', selectedId);
                }

                if (!selectedId) {
                    container.innerHTML = '<div style="color: #9ca3af; text-align: center; padding: 20px;">無可用參數組</div>';
                    return;
                }

                const executor = liveSimStatus.executors[selectedId];
                console.log('  executor:', executor);
                console.log('  executor.state:', executor?.state);
                console.log('  operation_history:', executor?.state?.operation_history);

                if (!executor || !executor.state) {
                    container.innerHTML = '<div style="color: #9ca3af; text-align: center; padding: 20px;">執行器狀態不可用</div>';
                    return;
                }

                const history = executor.state.operation_history;
                if (!history) {
                    container.innerHTML = '<div style="color: #9ca3af; text-align: center; padding: 20px;">無操作歷史數據</div>';
                    return;
                }

                if (history.length === 0) {
                    container.innerHTML = '<div style="color: #9ca3af; text-align: center; padding: 20px;">等待操作...</div>';
                    return;
                }

                // Build table
                const actionColors = {
                    'cancel': '#ef4444',
                    'rebalance': '#f59e0b',
                    'place': '#10b981',
                    'fill': '#667eea'
                };

                const actionLabels = {
                    'cancel': '撤單',
                    'rebalance': '重掛',
                    'place': '下單',
                    'fill': '成交'
                };

                let html = '<table class="price-table" style="font-size: 10px; width: 100%;">';
                html += '<thead><tr>';
                html += '<th style="padding: 4px; text-align: left;">時間</th>';
                html += '<th style="padding: 4px; text-align: center;">操作</th>';
                html += '<th style="padding: 4px; text-align: right;">訂單價</th>';
                html += '<th style="padding: 4px; text-align: right;">Best Bid</th>';
                html += '<th style="padding: 4px; text-align: right;">Best Ask</th>';
                html += '<th style="padding: 4px; text-align: left;">原因</th>';
                html += '</tr></thead><tbody>';

                history.forEach((h, i) => {
                    const bgColor = i % 2 === 0 ? '#0f1419' : 'transparent';
                    const actionColor = actionColors[h.action] || '#9ca3af';
                    const sideLabel = h.side === 'buy' ? '買' : '賣';
                    const actionLabel = actionLabels[h.action] || h.action;

                    html += `<tr style="background: ${bgColor};">`;
                    html += `<td style="padding: 4px; font-family: monospace;">${h.time}</td>`;
                    html += `<td style="padding: 4px; text-align: center; color: ${actionColor}; font-weight: 600;">${sideLabel}${actionLabel}</td>`;
                    html += `<td style="padding: 4px; text-align: right; font-family: monospace;">$${h.order_price?.toFixed(2) || '-'}</td>`;
                    html += `<td style="padding: 4px; text-align: right; font-family: monospace; color: #10b981;">$${h.best_bid?.toFixed(2) || '-'}</td>`;
                    html += `<td style="padding: 4px; text-align: right; font-family: monospace; color: #ef4444;">$${h.best_ask?.toFixed(2) || '-'}</td>`;
                    html += `<td style="padding: 4px; color: #9ca3af; font-size: 9px;">${h.reason || ''}</td>`;
                    html += '</tr>';
                });

                html += '</tbody></table>';
                container.innerHTML = html;
            }

            function updateComparisonTable(data) {
                const tbody = document.getElementById('liveComparisonBody');

                if (!data || data.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: #9ca3af; padding: 20px;">等待數據...</td></tr>';
                    return;
                }

                // 按有效積分排序 (已由後端排序)
                tbody.innerHTML = data.map((row, idx) => {
                    const effectivePts = row.effective_points_pct || 0;
                    const boosted = row.boosted_time_pct || 0;
                    const standard = row.standard_time_pct || 0;
                    const basic = row.basic_time_pct || 0;
                    const isTop = idx === 0;
                    const totalCancels = (row.price_cancel_count || 0) + (row.queue_cancel_count || 0);

                    return `
                        <tr style="${isTop ? 'background: #10b98120;' : ''}">
                            <td style="${isTop ? 'font-weight: 700;' : ''}">${row.param_set_name || row.param_set_id}${isTop ? ' ⭐' : ''}</td>
                            <td style="color: #667eea; font-weight: 700;">${effectivePts.toFixed(1)}%</td>
                            <td style="color: #10b981;">${boosted.toFixed(1)}%</td>
                            <td style="color: #f59e0b;">${standard.toFixed(1)}%</td>
                            <td style="color: #9ca3af;">${basic.toFixed(1)}%</td>
                            <td>${row.simulated_fills || 0}</td>
                            <td style="color: ${(row.simulated_pnl_usd || 0) >= 0 ? '#10b981' : '#ef4444'};">
                                $${(row.simulated_pnl_usd || 0).toFixed(2)}
                            </td>
                            <td style="color: #6b7280;">${totalCancels}</td>
                        </tr>
                    `;
                }).join('');
            }

            async function loadSimulationRuns() {
                try {
                    const res = await fetch('/api/simulation/runs');
                    const data = await res.json();

                    const tbody = document.getElementById('simRunsBody');

                    if (!data.runs || data.runs.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: #9ca3af; padding: 20px;">無歷史記錄</td></tr>';
                        return;
                    }

                    tbody.innerHTML = data.runs.map(run => {
                        const startTime = run.started_at ? new Date(run.started_at).toLocaleString('zh-TW') : '-';
                        const duration = run.duration_seconds ? Math.floor(run.duration_seconds / 60) + ' 分鐘' : '-';

                        return `
                            <tr>
                                <td style="font-family: monospace; font-size: 11px;">${run.run_id}</td>
                                <td>${startTime}</td>
                                <td>${duration}</td>
                                <td>${run.param_set_count || '-'}</td>
                                <td style="color: #10b981;">${run.recommendation || '-'}</td>
                                <td>
                                    <button class="btn" style="padding: 3px 8px; font-size: 10px; margin-right: 4px;"
                                        onclick="viewRunDetail('${run.run_id}')">查看</button>
                                    <button class="btn btn-danger" style="padding: 3px 8px; font-size: 10px;"
                                        onclick="deleteRun('${run.run_id}')">刪除</button>
                                </td>
                            </tr>
                        `;
                    }).join('');
                } catch (e) {
                    console.error('Failed to load simulation runs:', e);
                }
            }

            async function viewRunDetail(runId) {
                try {
                    const res = await fetch('/api/simulation/runs/' + runId + '/comparison');
                    const data = await res.json();

                    const container = document.getElementById('simResultContent');
                    const detailDiv = document.getElementById('simResultDetail');

                    let html = '<div style="margin-bottom: 15px;">';

                    // 推薦參數組
                    if (data.recommendation) {
                        html += `
                            <div style="background: #10b98120; border: 1px solid #10b981; border-radius: 6px; padding: 12px; margin-bottom: 15px;">
                                <div style="font-weight: 700; color: #10b981; margin-bottom: 5px;">⭐ 推薦: ${data.recommendation.param_set_name}</div>
                                <div style="font-size: 12px; color: #9ca3af;">${data.recommendation.reason}</div>
                            </div>
                        `;
                    }

                    // 比較表格
                    html += `
                        <table class="price-table" style="font-size: 12px;">
                            <thead>
                                <tr>
                                    <th>排名</th>
                                    <th>參數組</th>
                                    <th>Uptime %</th>
                                    <th>Boosted %</th>
                                    <th>模擬成交</th>
                                    <th>PnL (USD)</th>
                                </tr>
                            </thead>
                            <tbody>
                    `;

                    if (data.comparison_table) {
                        data.comparison_table.forEach((row, idx) => {
                            const uptime = row.uptime_percentage || 0;
                            const uptimeColor = uptime >= 70 ? '#10b981' : (uptime >= 50 ? '#f59e0b' : '#ef4444');

                            html += `
                                <tr>
                                    <td style="font-weight: 600;">#${idx + 1}</td>
                                    <td>${row.param_set_name || row.param_set_id}</td>
                                    <td style="color: ${uptimeColor};">${uptime.toFixed(1)}%</td>
                                    <td>${(row.boosted_time_pct || 0).toFixed(1)}%</td>
                                    <td>${row.simulated_fills || 0}</td>
                                    <td style="color: ${(row.simulated_pnl_usd || 0) >= 0 ? '#10b981' : '#ef4444'};">
                                        $${(row.simulated_pnl_usd || 0).toFixed(2)}
                                    </td>
                                </tr>
                            `;
                        });
                    }

                    html += '</tbody></table></div>';

                    container.innerHTML = html;
                    detailDiv.style.display = 'block';
                } catch (e) {
                    console.error('Failed to view run detail:', e);
                    alert('載入失敗: ' + e.message);
                }
            }

            function closeResultDetail() {
                document.getElementById('simResultDetail').style.display = 'none';
            }

            async function deleteRun(runId) {
                if (!confirm('確定刪除此運行記錄？')) return;

                try {
                    const res = await fetch('/api/simulation/runs/' + runId, { method: 'DELETE' });
                    const result = await res.json();

                    if (result.success) {
                        loadSimulationRuns();
                    } else {
                        alert('刪除失敗: ' + result.error);
                    }
                } catch (e) {
                    console.error('Failed to delete run:', e);
                }
            }

            // ===== 頁面切換增強 =====
            function switchPage(page) {
                document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
                document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
                document.getElementById('page-' + page).classList.add('active');
                event.target.classList.add('active');

                // 切換到比較頁面時載入數據
                if (page === 'comparison') {
                    loadParamSets();
                    loadSimulationRuns();
                }
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


@app.post("/api/system/reinit")
async def reinit_system_api():
    """重新初始化系統 - 重新連接所有已配置的交易所"""
    global monitor, executor, adapters, system_status

    try:
        logger.info("🔄 重新初始化系統...")

        # 停止現有監控
        if monitor:
            await monitor.stop()
        if executor:
            await executor.stop()

        # 斷開所有現有連接
        for name, adapter in list(adapters.items()):
            if hasattr(adapter, 'disconnect'):
                try:
                    await adapter.disconnect()
                except:
                    pass

        # 重新初始化
        await init_system()

        connected_count = len(adapters)
        if connected_count > 0:
            return JSONResponse({
                'success': True,
                'message': f'已連接 {connected_count} 個交易所: {", ".join(adapters.keys())}'
            })
        else:
            return JSONResponse({
                'success': False,
                'error': '沒有可連接的交易所，請先配置交易所'
            })

    except Exception as e:
        logger.error(f"重新初始化失敗: {e}")
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


# ==================== Simulation Comparison API ====================

@app.get("/api/simulation/param-sets")
async def get_simulation_param_sets():
    """獲取所有參數組"""
    try:
        manager = get_param_set_manager()
        return JSONResponse(manager.to_dict())
    except Exception as e:
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


@app.post("/api/simulation/param-sets")
async def create_simulation_param_set(request: Request):
    """創建新參數組"""
    try:
        data = await request.json()
        manager = get_param_set_manager()
        param_set = manager.add_param_set(data, save=True)
        return JSONResponse({
            'success': True,
            'param_set': {
                'id': param_set.id,
                'name': param_set.name,
                'description': param_set.description
            }
        })
    except Exception as e:
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


@app.put("/api/simulation/param-sets/{param_set_id}")
async def update_simulation_param_set(param_set_id: str, request: Request):
    """更新參數組"""
    try:
        data = await request.json()
        manager = get_param_set_manager()

        # Remove old and add new with same ID
        manager.remove_param_set(param_set_id, save=False)
        data['id'] = param_set_id  # Ensure ID stays the same
        param_set = manager.add_param_set(data, save=True)

        return JSONResponse({
            'success': True,
            'param_set': {
                'id': param_set.id,
                'name': param_set.name,
                'description': param_set.description
            }
        })
    except Exception as e:
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


@app.delete("/api/simulation/param-sets/{param_set_id}")
async def delete_simulation_param_set(param_set_id: str):
    """刪除參數組"""
    try:
        manager = get_param_set_manager()
        success = manager.remove_param_set(param_set_id, save=True)

        if success:
            return JSONResponse({'success': True})
        else:
            return JSONResponse({'success': False, 'error': '參數組不存在'}, status_code=404)
    except Exception as e:
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


@app.post("/api/simulation/start")
async def start_simulation(request: Request):
    """開始多參數模擬"""
    global simulation_runner, result_logger, comparison_engine

    logger.info("=== /api/simulation/start called ===")

    try:
        data = await request.json()
        param_set_ids = data.get('param_set_ids', [])
        duration_minutes = data.get('duration_minutes', 60)
        logger.info(f"Request data: param_set_ids={param_set_ids}, duration={duration_minutes}")

        if not param_set_ids:
            logger.warning("No param_set_ids provided")
            return JSONResponse({'success': False, 'error': '請選擇至少一個參數組'})

        # Check if StandX adapter is available
        standx_adapter = adapters.get('STANDX')
        logger.info(f"StandX adapter available: {standx_adapter is not None}")
        if not standx_adapter:
            logger.warning("StandX adapter not connected")
            return JSONResponse({'success': False, 'error': 'StandX 未連接，請先連接交易所'})

        # Initialize components if needed
        if result_logger is None:
            result_logger = ResultLogger()
        if comparison_engine is None:
            comparison_engine = ComparisonEngine(result_logger)

        # Create simulation runner
        param_set_manager = get_param_set_manager()
        simulation_runner = SimulationRunner(
            adapter=standx_adapter,
            param_set_manager=param_set_manager,
            result_logger=result_logger,
            symbol="BTC-USD",
            tick_interval_ms=100
        )

        # Start simulation
        run_id = await simulation_runner.start(
            param_set_ids=param_set_ids,
            duration_minutes=duration_minutes
        )

        return JSONResponse({
            'success': True,
            'run_id': run_id,
            'param_set_ids': param_set_ids,
            'duration_minutes': duration_minutes
        })

    except Exception as e:
        logger.error(f"Failed to start simulation: {e}")
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


@app.post("/api/simulation/stop")
async def stop_simulation():
    """停止模擬"""
    global simulation_runner

    logger.info("Stop simulation API called")

    try:
        if simulation_runner is None:
            logger.info("simulation_runner is None")
            return JSONResponse({'success': False, 'error': '沒有模擬運行器'})

        if not simulation_runner.is_running():
            logger.info("simulation_runner is not running")
            return JSONResponse({'success': False, 'error': '沒有正在運行的模擬'})

        logger.info("Calling simulation_runner.stop() with timeout...")

        # Add timeout to prevent hanging the web service
        try:
            results = await asyncio.wait_for(simulation_runner.stop(), timeout=10.0)
            logger.info(f"Stop completed normally: {results}")
        except asyncio.TimeoutError:
            logger.warning("Simulation stop timed out, forcing cleanup")
            # Force cleanup
            simulation_runner._running = False
            simulation_runner._executors = {}
            simulation_runner._market_feed = None
            simulation_runner._current_run_id = None
            simulation_runner._auto_stop_task = None
            results = {'timeout': True, 'message': '停止超時，已強制清理'}
        except asyncio.CancelledError:
            logger.warning("Simulation stop was cancelled")
            simulation_runner._running = False
            results = {'cancelled': True}

        return JSONResponse({
            'success': True,
            'results': results
        })

    except Exception as e:
        logger.error(f"Failed to stop simulation: {e}", exc_info=True)
        # Force cleanup on error
        if simulation_runner:
            simulation_runner._running = False
            simulation_runner._executors = {}
            simulation_runner._market_feed = None
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


@app.post("/api/simulation/force-stop")
async def force_stop_simulation():
    """強制停止模擬 - 不等待任何操作"""
    global simulation_runner

    logger.info("Force stop simulation API called")

    if simulation_runner is None:
        return JSONResponse({'success': True, 'message': '沒有模擬運行器'})

    # Forcibly clear all state without waiting
    simulation_runner._running = False

    # Cancel auto-stop task if exists
    if simulation_runner._auto_stop_task:
        simulation_runner._auto_stop_task.cancel()
        simulation_runner._auto_stop_task = None

    # Clear executors and market feed references
    simulation_runner._executors = {}
    simulation_runner._market_feed = None
    simulation_runner._current_run_id = None
    simulation_runner._started_at = None

    logger.info("Force stop completed")
    return JSONResponse({
        'success': True,
        'message': '已強制停止模擬'
    })


@app.get("/api/simulation/status")
async def get_simulation_status():
    """獲取模擬狀態"""
    global simulation_runner

    if simulation_runner is None:
        return JSONResponse({
            'running': False,
            'message': 'No simulation runner initialized'
        })

    # Run in thread pool to avoid blocking event loop (state uses locks)
    try:
        status = await asyncio.wait_for(
            asyncio.to_thread(simulation_runner.get_live_status),
            timeout=2.0
        )
        return JSONResponse(status)
    except asyncio.TimeoutError:
        logger.warning("get_live_status timed out")
        return JSONResponse({
            'running': True,
            'timeout': True,
            'message': 'Status fetch timed out - simulation may be busy'
        })
    except Exception as e:
        logger.error(f"get_live_status error: {e}")
        return JSONResponse({
            'running': True,
            'error': str(e)
        })


@app.get("/api/simulation/comparison")
async def get_live_simulation_comparison():
    """獲取即時比較數據"""
    global simulation_runner

    if simulation_runner is None or not simulation_runner.is_running():
        return JSONResponse([])

    # Run in thread pool to avoid blocking event loop (state uses locks)
    try:
        comparison = await asyncio.wait_for(
            asyncio.to_thread(simulation_runner.get_live_comparison),
            timeout=2.0
        )
        return JSONResponse(comparison)
    except asyncio.TimeoutError:
        logger.warning("get_live_comparison timed out")
        return JSONResponse([])
    except Exception as e:
        logger.error(f"get_live_comparison error: {e}")
        return JSONResponse([])


@app.get("/api/simulation/runs")
async def list_simulation_runs():
    """列出所有歷史運行"""
    global comparison_engine, result_logger

    try:
        if result_logger is None:
            result_logger = ResultLogger()
        if comparison_engine is None:
            comparison_engine = ComparisonEngine(result_logger)

        runs = comparison_engine.get_all_runs()
        return JSONResponse({'runs': runs})

    except Exception as e:
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


@app.get("/api/simulation/runs/{run_id}")
async def get_simulation_run_details(run_id: str):
    """獲取特定運行的詳細結果"""
    global comparison_engine, result_logger

    try:
        if result_logger is None:
            result_logger = ResultLogger()
        if comparison_engine is None:
            comparison_engine = ComparisonEngine(result_logger)

        results = comparison_engine.get_run_details(run_id)
        if results is None:
            return JSONResponse({'success': False, 'error': '運行記錄不存在'}, status_code=404)

        return JSONResponse(results)

    except Exception as e:
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


@app.get("/api/simulation/runs/{run_id}/comparison")
async def get_simulation_run_comparison(run_id: str, sort_by: str = "uptime_percentage"):
    """獲取運行比較表"""
    global comparison_engine, result_logger

    try:
        if result_logger is None:
            result_logger = ResultLogger()
        if comparison_engine is None:
            comparison_engine = ComparisonEngine(result_logger)

        table = comparison_engine.get_comparison_table(run_id, sort_by=sort_by)
        recommendation = comparison_engine.get_recommendation(run_id)

        return JSONResponse({
            'comparison_table': table,
            'recommendation': {
                'param_set_id': recommendation.param_set_id,
                'param_set_name': recommendation.param_set_name,
                'reason': recommendation.reason,
                'score': recommendation.score
            } if recommendation else None
        })

    except Exception as e:
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


@app.delete("/api/simulation/runs/{run_id}")
async def delete_simulation_run(run_id: str):
    """刪除運行記錄"""
    global result_logger

    try:
        if result_logger is None:
            result_logger = ResultLogger()

        success = result_logger.delete_run(run_id)
        if success:
            return JSONResponse({'success': True})
        else:
            return JSONResponse({'success': False, 'error': '運行記錄不存在'}, status_code=404)

    except Exception as e:
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8888, log_level="info")
