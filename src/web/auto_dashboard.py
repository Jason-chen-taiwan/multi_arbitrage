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

# 全局變量
monitor: Optional[MultiExchangeMonitor] = None
executor: Optional[ArbitrageExecutor] = None
adapters: Dict[str, BasePerpAdapter] = {}
connected_clients: List[WebSocket] = []
system_status = {
    'running': False,
    'auto_execute': False,
    'dry_run': True,
    'started_at': None
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

    # 符號配置
    symbols_config = {
        'cex': ['BTC/USDT:USDT', 'ETH/USDT:USDT'],
        'dex': ['BTC-USD', 'ETH-USD']
    }

    adapters = {}
    symbols = set()

    # 加載 DEX
    for exchange_name, config in configs['dex'].items():
        try:
            adapter_config = {
                'exchange_name': exchange_name,
                'testnet': config.get('testnet', False)
            }
            adapter = create_adapter(adapter_config)
            adapters[exchange_name.upper()] = adapter
            symbols.update(symbols_config['dex'])
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
            adapters[exchange_name.upper()] = adapter
            symbols.update(symbols_config['cex'])
            logger.info(f"  ✅ {exchange_name.upper()} - 已連接")
        except Exception as e:
            logger.warning(f"  ⚠️  {exchange_name.upper()} - 跳過: {str(e)[:50]}")

    symbols = list(symbols)

    if len(adapters) == 0:
        logger.warning("⚠️  沒有已配置的交易所")
        return

    # 創建監控器
    monitor = MultiExchangeMonitor(
        adapters=adapters,
        symbols=symbols,
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

    if exchange_key in adapters:
        del adapters[exchange_key]

    if exchange_key in monitor.adapters:
        del monitor.adapters[exchange_key]

    logger.info(f"✅ {exchange_key} 已從監控系統移除")


async def broadcast_data():
    """廣播數據到所有連接的客戶端"""
    while True:
        try:
            if monitor and len(connected_clients) > 0:
                # 準備數據
                data = {
                    'timestamp': datetime.now().isoformat(),
                    'system_status': system_status,
                    'market_data': {},
                    'opportunities': [],
                    'stats': monitor.stats if monitor else {},
                    'executor_stats': executor.get_stats() if executor else {}
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

                # 廣播
                disconnected = []
                for client in connected_clients:
                    try:
                        await client.send_json(data)
                    except:
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


@app.get("/", response_class=HTMLResponse)
async def root():
    """首頁"""
    return """
    <!DOCTYPE html>
    <html lang="zh-TW">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>自動化套利控制台</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: #0f1419;
                color: #e4e6eb;
                padding: 20px;
            }
            .container { max-width: 1400px; margin: 0 auto; }
            .header {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                padding: 30px;
                border-radius: 12px;
                margin-bottom: 20px;
                text-align: center;
            }
            .header h1 { font-size: 32px; margin-bottom: 10px; }
            .header p { opacity: 0.9; font-size: 16px; }

            .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin-bottom: 20px; }
            .card {
                background: #1a1f2e;
                border: 1px solid #2a3347;
                border-radius: 12px;
                padding: 20px;
            }
            .card h2 { font-size: 18px; margin-bottom: 15px; color: #667eea; }
            .stat { display: flex; justify-content: space-between; margin-bottom: 10px; padding: 10px; background: #0f1419; border-radius: 8px; }
            .stat-label { color: #9ca3af; }
            .stat-value { font-weight: 600; color: #10b981; }

            .section { background: #1a1f2e; border: 1px solid #2a3347; border-radius: 12px; padding: 20px; margin-bottom: 20px; }
            .section h2 { font-size: 20px; margin-bottom: 15px; }

            table { width: 100%; border-collapse: collapse; }
            th, td { padding: 12px; text-align: left; border-bottom: 1px solid #2a3347; }
            th { color: #9ca3af; font-weight: 600; }

            .status-badge {
                display: inline-block;
                padding: 4px 12px;
                border-radius: 12px;
                font-size: 12px;
                font-weight: 600;
            }
            .status-online { background: #10b981; color: #fff; }
            .status-offline { background: #ef4444; color: #fff; }

            .opportunity-card {
                background: linear-gradient(135deg, #10b981 0%, #059669 100%);
                padding: 20px;
                border-radius: 12px;
                margin-bottom: 15px;
                color: white;
            }
            .opportunity-card h3 { margin-bottom: 10px; }
            .opportunity-details { display: flex; justify-content: space-between; align-items: center; }
            .profit { font-size: 24px; font-weight: 700; }

            .btn {
                padding: 10px 20px;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.3s;
            }
            .btn-primary {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
            }
            .btn-primary:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4); }

            .control-panel {
                display: flex;
                gap: 15px;
                flex-wrap: wrap;
                margin-bottom: 20px;
            }

            .toggle-switch {
                position: relative;
                display: inline-block;
                width: 50px;
                height: 24px;
            }
            .toggle-switch input { opacity: 0; width: 0; height: 0; }
            .slider {
                position: absolute;
                cursor: pointer;
                top: 0; left: 0; right: 0; bottom: 0;
                background-color: #ccc;
                transition: .4s;
                border-radius: 24px;
            }
            .slider:before {
                position: absolute;
                content: "";
                height: 16px;
                width: 16px;
                left: 4px;
                bottom: 4px;
                background-color: white;
                transition: .4s;
                border-radius: 50%;
            }
            input:checked + .slider { background-color: #10b981; }
            input:checked + .slider:before { transform: translateX(26px); }

            .config-form {
                display: grid;
                gap: 15px;
                margin-top: 20px;
            }
            .form-group { display: flex; flex-direction: column; }
            .form-group label { margin-bottom: 5px; color: #9ca3af; font-size: 14px; }
            .form-group input, .form-group select {
                padding: 10px;
                background: #0f1419;
                border: 1px solid #2a3347;
                border-radius: 8px;
                color: #e4e6eb;
                font-size: 14px;
            }
            .form-group input:focus, .form-group select:focus {
                outline: none;
                border-color: #667eea;
            }

            .exchange-card {
                background: #0f1419;
                border: 1px solid #2a3347;
                border-radius: 8px;
                padding: 15px;
                margin-bottom: 15px;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            .exchange-card:hover {
                border-color: #667eea;
            }
            .exchange-info {
                display: flex;
                align-items: center;
                gap: 15px;
            }
            .exchange-name {
                font-size: 18px;
                font-weight: 600;
                color: #e4e6eb;
            }
            .exchange-type {
                display: inline-block;
                padding: 4px 8px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: 600;
            }
            .exchange-type.dex {
                background: #10b981;
                color: white;
            }
            .exchange-type.cex {
                background: #3b82f6;
                color: white;
            }
            .exchange-details {
                font-size: 12px;
                color: #9ca3af;
                margin-top: 5px;
            }
            .btn-delete {
                background: #ef4444;
                color: white;
                padding: 8px 16px;
                border: none;
                border-radius: 6px;
                cursor: pointer;
                font-size: 14px;
                font-weight: 600;
                transition: all 0.3s;
            }
            .btn-delete:hover {
                background: #dc2626;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🤖 自動化套利控制台</h1>
                <p>啟動即監控 · 配置即生效</p>
            </div>

            <div class="control-panel">
                <div class="card" style="flex: 1;">
                    <h2>系統控制</h2>
                    <div style="display: flex; align-items: center; gap: 15px; margin-bottom: 15px;">
                        <label>自動執行</label>
                        <label class="toggle-switch">
                            <input type="checkbox" id="autoExecuteToggle" onchange="toggleAutoExecute()">
                            <span class="slider"></span>
                        </label>
                        <span id="autoExecuteStatus">關閉</span>
                    </div>
                    <div style="display: flex; align-items: center; gap: 15px;">
                        <label>實際交易</label>
                        <label class="toggle-switch">
                            <input type="checkbox" id="liveTradeToggle" onchange="toggleLiveTrade()">
                            <span class="slider"></span>
                        </label>
                        <span id="liveTradeStatus">模擬模式</span>
                    </div>
                </div>
            </div>

            <div class="grid">
                <div class="card">
                    <h2>系統狀態</h2>
                    <div class="stat">
                        <span class="stat-label">運行狀態</span>
                        <span class="stat-value" id="systemStatus">啟動中...</span>
                    </div>
                    <div class="stat">
                        <span class="stat-label">交易所數量</span>
                        <span class="stat-value" id="exchangeCount">0</span>
                    </div>
                    <div class="stat">
                        <span class="stat-label">運行時間</span>
                        <span class="stat-value" id="uptime">-</span>
                    </div>
                </div>

                <div class="card">
                    <h2>監控統計</h2>
                    <div class="stat">
                        <span class="stat-label">更新次數</span>
                        <span class="stat-value" id="totalUpdates">0</span>
                    </div>
                    <div class="stat">
                        <span class="stat-label">套利機會</span>
                        <span class="stat-value" id="totalOpportunities">0</span>
                    </div>
                    <div class="stat">
                        <span class="stat-label">當前機會</span>
                        <span class="stat-value" id="currentOpportunities">0</span>
                    </div>
                </div>

                <div class="card">
                    <h2>執行統計</h2>
                    <div class="stat">
                        <span class="stat-label">執行次數</span>
                        <span class="stat-value" id="totalAttempts">0</span>
                    </div>
                    <div class="stat">
                        <span class="stat-label">成功率</span>
                        <span class="stat-value" id="successRate">0%</span>
                    </div>
                    <div class="stat">
                        <span class="stat-label">總利潤</span>
                        <span class="stat-value" id="totalProfit">$0.00</span>
                    </div>
                </div>
            </div>

            <div class="section">
                <h2>💰 實時套利機會</h2>
                <div id="opportunitiesContainer">
                    <p style="color: #9ca3af; text-align: center; padding: 40px;">等待套利機會...</p>
                </div>
            </div>

            <div class="section">
                <h2>🏦 交易所價格</h2>
                <table id="pricesTable">
                    <thead>
                        <tr>
                            <th>交易所</th>
                            <th>BTC 買價</th>
                            <th>BTC 賣價</th>
                            <th>ETH 買價</th>
                            <th>ETH 賣價</th>
                            <th>狀態</th>
                        </tr>
                    </thead>
                    <tbody id="pricesTableBody">
                        <tr>
                            <td colspan="6" style="text-align: center; color: #9ca3af;">載入中...</td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <div class="section">
                <h2>📋 已配置交易所</h2>
                <p style="color: #9ca3af; margin-bottom: 15px;">當前系統中已配置的交易所</p>
                <div id="configuredExchanges">
                    <p style="color: #9ca3af; text-align: center; padding: 20px;">載入中...</p>
                </div>
            </div>

            <div class="section">
                <h2>⚙️ 添加新交易所</h2>
                <p style="color: #9ca3af; margin-bottom: 15px;">添加交易所後自動開始監控</p>

                <div class="config-form">
                    <div class="form-group">
                        <label>交易所類型</label>
                        <select id="exchangeType" onchange="updateExchangeOptions()">
                            <option value="cex">CEX (中心化交易所)</option>
                            <option value="dex">DEX (去中心化交易所)</option>
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

                    <div id="cexFields">
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
                            <input type="password" id="passphrase" placeholder="輸入 Passphrase (OKX/Bitget)">
                        </div>
                    </div>

                    <div id="dexFields" style="display: none;">
                        <div class="form-group">
                            <label>Private Key</label>
                            <input type="password" id="privateKey" placeholder="輸入錢包私鑰">
                        </div>
                        <div class="form-group">
                            <label>Wallet Address</label>
                            <input type="text" id="walletAddress" placeholder="輸入錢包地址">
                        </div>
                    </div>

                    <button class="btn btn-primary" onclick="saveConfig()">保存並開始監控</button>
                </div>
            </div>
        </div>

        <script>
            let ws = null;
            let systemStartTime = null;

            function connect() {
                ws = new WebSocket('ws://localhost:8888/ws');

                ws.onopen = () => {
                    console.log('WebSocket 已連接');
                };

                ws.onmessage = (event) => {
                    const data = JSON.parse(event.data);
                    updateUI(data);
                };

                ws.onerror = (error) => {
                    console.error('WebSocket error:', error);
                };

                ws.onclose = () => {
                    console.log('WebSocket 已斷開，3秒後重連...');
                    setTimeout(connect, 3000);
                };
            }

            function updateUI(data) {
                // 系統狀態
                document.getElementById('systemStatus').textContent = data.system_status.running ? '運行中' : '已停止';
                document.getElementById('exchangeCount').textContent = Object.keys(data.market_data).length;

                if (data.system_status.started_at && !systemStartTime) {
                    systemStartTime = new Date(data.system_status.started_at);
                }

                if (systemStartTime) {
                    const uptime = Math.floor((new Date() - systemStartTime) / 1000);
                    const hours = Math.floor(uptime / 3600);
                    const minutes = Math.floor((uptime % 3600) / 60);
                    const seconds = uptime % 60;
                    document.getElementById('uptime').textContent = `${hours}h ${minutes}m ${seconds}s`;
                }

                // 監控統計
                document.getElementById('totalUpdates').textContent = data.stats.total_updates || 0;
                document.getElementById('totalOpportunities').textContent = data.stats.total_opportunities || 0;
                document.getElementById('currentOpportunities').textContent = data.opportunities.length;

                // 執行統計
                const execStats = data.executor_stats;
                document.getElementById('totalAttempts').textContent = execStats.total_attempts || 0;

                const successRate = execStats.total_attempts > 0
                    ? ((execStats.successful_executions / execStats.total_attempts) * 100).toFixed(1)
                    : 0;
                document.getElementById('successRate').textContent = successRate + '%';

                const profit = execStats.total_profit - (execStats.total_loss || 0);
                document.getElementById('totalProfit').textContent = '$' + profit.toFixed(2);

                // 套利機會
                updateOpportunities(data.opportunities);

                // 價格表
                updatePrices(data.market_data);
            }

            function updateOpportunities(opportunities) {
                const container = document.getElementById('opportunitiesContainer');

                if (opportunities.length === 0) {
                    container.innerHTML = '<p style="color: #9ca3af; text-align: center; padding: 40px;">等待套利機會...</p>';
                    return;
                }

                container.innerHTML = opportunities.map(opp => `
                    <div class="opportunity-card">
                        <h3>🔥 ${opp.symbol}</h3>
                        <div class="opportunity-details">
                            <div>
                                <div>買入: ${opp.buy_exchange} @ $${opp.buy_price.toFixed(2)}</div>
                                <div>賣出: ${opp.sell_exchange} @ $${opp.sell_price.toFixed(2)}</div>
                                <div>數量: ${opp.max_quantity.toFixed(4)}</div>
                            </div>
                            <div class="profit">
                                +$${opp.profit.toFixed(2)}<br>
                                <span style="font-size: 16px;">(${opp.profit_pct.toFixed(2)}%)</span>
                            </div>
                        </div>
                    </div>
                `).join('');
            }

            function updatePrices(marketData) {
                const tbody = document.getElementById('pricesTableBody');
                const exchanges = Object.keys(marketData);

                if (exchanges.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: #9ca3af;">無數據</td></tr>';
                    return;
                }

                tbody.innerHTML = exchanges.map(exchange => {
                    const data = marketData[exchange];
                    const btc = data['BTC/USDT:USDT'] || data['BTC-USD'] || {};
                    const eth = data['ETH/USDT:USDT'] || data['ETH-USD'] || {};

                    return `
                        <tr>
                            <td>${exchange}</td>
                            <td>${btc.best_bid ? '$' + btc.best_bid.toFixed(2) : '-'}</td>
                            <td>${btc.best_ask ? '$' + btc.best_ask.toFixed(2) : '-'}</td>
                            <td>${eth.best_bid ? '$' + eth.best_bid.toFixed(2) : '-'}</td>
                            <td>${eth.best_ask ? '$' + eth.best_ask.toFixed(2) : '-'}</td>
                            <td><span class="status-badge status-online">在線</span></td>
                        </tr>
                    `;
                }).join('');
            }

            function updateExchangeOptions() {
                const type = document.getElementById('exchangeType').value;
                const nameSelect = document.getElementById('exchangeName');
                const cexFields = document.getElementById('cexFields');
                const dexFields = document.getElementById('dexFields');
                const passphraseField = document.getElementById('passphraseField');

                if (type === 'cex') {
                    cexFields.style.display = 'block';
                    dexFields.style.display = 'none';
                    nameSelect.innerHTML = `
                        <option value="binance">Binance</option>
                        <option value="okx">OKX</option>
                        <option value="bitget">Bitget</option>
                        <option value="bybit">Bybit</option>
                    `;
                } else {
                    cexFields.style.display = 'none';
                    dexFields.style.display = 'block';
                    nameSelect.innerHTML = `
                        <option value="standx">StandX</option>
                        <option value="grvt">GRVT</option>
                    `;
                }

                // 更新 passphrase 顯示
                nameSelect.onchange = () => {
                    const name = nameSelect.value;
                    passphraseField.style.display = (name === 'okx' || name === 'bitget') ? 'block' : 'none';
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
                    if (name === 'okx' || name === 'bitget') {
                        config.passphrase = document.getElementById('passphrase').value;
                    }
                } else {
                    config.private_key = document.getElementById('privateKey').value;
                    config.address = document.getElementById('walletAddress').value;
                }

                try {
                    const response = await fetch('/api/config/save', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            exchange_name: name,
                            exchange_type: type,
                            config: config
                        })
                    });

                    const result = await response.json();
                    if (result.success) {
                        alert('✅ 配置已保存並開始監控！');
                        // 清空表單
                        document.getElementById('apiKey').value = '';
                        document.getElementById('apiSecret').value = '';
                        document.getElementById('passphrase').value = '';
                        document.getElementById('privateKey').value = '';
                        document.getElementById('walletAddress').value = '';
                        // 刷新配置列表
                        loadConfiguredExchanges();
                    } else {
                        alert('❌ 保存失敗: ' + result.error);
                    }
                } catch (error) {
                    alert('❌ 保存失敗: ' + error.message);
                }
            }

            async function toggleAutoExecute() {
                const enabled = document.getElementById('autoExecuteToggle').checked;
                try {
                    const response = await fetch('/api/control/auto-execute', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ enabled })
                    });
                    const result = await response.json();
                    document.getElementById('autoExecuteStatus').textContent = enabled ? '開啟' : '關閉';
                } catch (error) {
                    console.error(error);
                }
            }

            async function toggleLiveTrade() {
                const enabled = document.getElementById('liveTradeToggle').checked;
                if (enabled) {
                    if (!confirm('⚠️ 警告：您即將啟用實際交易模式！這將使用真實資金。確定繼續嗎？')) {
                        document.getElementById('liveTradeToggle').checked = false;
                        return;
                    }
                }
                try {
                    const response = await fetch('/api/control/live-trade', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ enabled })
                    });
                    const result = await response.json();
                    document.getElementById('liveTradeStatus').textContent = enabled ? '實際交易' : '模擬模式';
                } catch (error) {
                    console.error(error);
                }
            }

            async function loadConfiguredExchanges() {
                try {
                    const response = await fetch('/api/config/list');
                    const data = await response.json();
                    displayConfiguredExchanges(data);
                } catch (error) {
                    console.error('載入配置失敗:', error);
                }
            }

            function displayConfiguredExchanges(configs) {
                const container = document.getElementById('configuredExchanges');

                const allExchanges = [];

                // DEX
                for (const [key, config] of Object.entries(configs.dex || {})) {
                    allExchanges.push({
                        name: key,
                        displayName: config.name,
                        type: 'dex',
                        testnet: config.testnet,
                        details: config.private_key_masked || config.api_key_masked
                    });
                }

                // CEX
                for (const [key, config] of Object.entries(configs.cex || {})) {
                    allExchanges.push({
                        name: key,
                        displayName: config.name,
                        type: 'cex',
                        testnet: config.testnet,
                        details: config.api_key_masked
                    });
                }

                if (allExchanges.length === 0) {
                    container.innerHTML = `
                        <p style="color: #9ca3af; text-align: center; padding: 20px;">
                            尚未配置任何交易所<br>
                            <span style="font-size: 14px;">請在下方添加交易所</span>
                        </p>
                    `;
                    return;
                }

                container.innerHTML = allExchanges.map(ex => `
                    <div class="exchange-card">
                        <div class="exchange-info">
                            <div>
                                <div style="display: flex; align-items: center; gap: 10px;">
                                    <span class="exchange-name">${ex.displayName}</span>
                                    <span class="exchange-type ${ex.type}">${ex.type.toUpperCase()}</span>
                                    ${ex.testnet ? '<span class="status-badge" style="background: #f59e0b;">測試網</span>' : ''}
                                </div>
                                <div class="exchange-details">
                                    Key: ${ex.details}
                                </div>
                            </div>
                        </div>
                        <button class="btn-delete" onclick="deleteExchange('${ex.name}', '${ex.type}')">移除</button>
                    </div>
                `).join('');
            }

            async function deleteExchange(name, type) {
                if (!confirm(`確定要移除 ${name.toUpperCase()} 嗎？`)) {
                    return;
                }

                try {
                    const response = await fetch('/api/config/delete', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            exchange_name: name,
                            exchange_type: type
                        })
                    });

                    const result = await response.json();
                    if (result.success) {
                        alert('✅ 已移除！');
                        loadConfiguredExchanges();
                    } else {
                        alert('❌ 移除失敗: ' + result.error);
                    }
                } catch (error) {
                    alert('❌ 移除失敗: ' + error.message);
                }
            }

            // 初始化
            connect();
            updateExchangeOptions();
            loadConfiguredExchanges();

            // 定期刷新配置列表
            setInterval(loadConfiguredExchanges, 10000);
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


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8888, log_level="info")
