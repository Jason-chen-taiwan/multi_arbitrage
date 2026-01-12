#!/usr/bin/env python3
"""
跨交易所套利監控 Web Dashboard
Cross-Exchange Arbitrage Monitoring Web Dashboard

實時顯示多個交易所的價格、訂單簿深度和套利機會
"""
import asyncio
import json
import os
from datetime import datetime
from typing import Dict, List, Optional
from decimal import Decimal
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager
import uvicorn
from pathlib import Path
from dotenv import load_dotenv

# Import modules
import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
from src.adapters.factory import create_adapter
from src.monitor.multi_exchange_monitor import MultiExchangeMonitor

# Global variables
monitor: Optional[MultiExchangeMonitor] = None
connected_clients: List[WebSocket] = []


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>跨交易所套利監控 - Arbitrage Dashboard</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f1419;
            color: #e4e6eb;
            padding: 20px;
        }

        .container {
            max-width: 1800px;
            margin: 0 auto;
        }

        .header {
            background: linear-gradient(135deg, #1e3a8a 0%, #7c3aed 100%);
            padding: 30px;
            border-radius: 15px;
            box-shadow: 0 8px 16px rgba(0,0,0,0.3);
            margin-bottom: 20px;
            text-align: center;
        }

        h1 {
            font-size: 36px;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.5);
        }

        .subtitle {
            font-size: 16px;
            opacity: 0.9;
            margin-bottom: 15px;
        }

        .status-bar {
            display: flex;
            justify-content: center;
            gap: 30px;
            font-size: 14px;
            flex-wrap: wrap;
        }

        .status-item {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .status-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-weight: 600;
            font-size: 12px;
        }

        .badge-connected {
            background: #10b981;
        }

        .badge-disconnected {
            background: #ef4444;
        }

        .badge-info {
            background: #3b82f6;
        }

        /* Statistics Cards */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }

        .stat-card {
            background: #1a1f2e;
            padding: 20px;
            border-radius: 12px;
            border: 1px solid #2a3347;
            box-shadow: 0 4px 8px rgba(0,0,0,0.2);
        }

        .stat-label {
            font-size: 12px;
            color: #9ca3af;
            margin-bottom: 8px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .stat-value {
            font-size: 28px;
            font-weight: 700;
            color: #ffffff;
        }

        .stat-value.positive {
            color: #10b981;
        }

        .stat-value.negative {
            color: #ef4444;
        }

        /* Exchange Prices */
        .exchanges-container {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }

        .exchange-card {
            background: #1a1f2e;
            border-radius: 12px;
            border: 1px solid #2a3347;
            overflow: hidden;
        }

        .exchange-header {
            background: linear-gradient(135deg, #374151 0%, #1f2937 100%);
            padding: 15px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .exchange-name {
            font-size: 18px;
            font-weight: 700;
            color: #ffffff;
        }

        .exchange-status {
            font-size: 12px;
            padding: 4px 10px;
            border-radius: 10px;
            background: #10b981;
            color: white;
        }

        .exchange-status.error {
            background: #ef4444;
        }

        .exchange-body {
            padding: 20px;
        }

        .price-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
            border-bottom: 1px solid #2a3347;
        }

        .price-row:last-child {
            border-bottom: none;
        }

        .price-label {
            font-size: 13px;
            color: #9ca3af;
        }

        .price-value {
            font-size: 18px;
            font-weight: 600;
        }

        .price-bid {
            color: #10b981;
        }

        .price-ask {
            color: #ef4444;
        }

        .price-spread {
            color: #60a5fa;
        }

        /* Arbitrage Opportunities */
        .opportunities-section {
            margin-bottom: 20px;
        }

        .section-header {
            background: #1a1f2e;
            padding: 15px 20px;
            border-radius: 12px 12px 0 0;
            border: 1px solid #2a3347;
            border-bottom: none;
        }

        .section-title {
            font-size: 20px;
            font-weight: 700;
            color: #ffffff;
        }

        .opportunities-list {
            background: #1a1f2e;
            border: 1px solid #2a3347;
            border-radius: 0 0 12px 12px;
            padding: 10px;
        }

        .opportunity-card {
            background: linear-gradient(135deg, #1e3a8a 0%, #7c3aed 100%);
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 10px;
            box-shadow: 0 4px 8px rgba(0,0,0,0.3);
        }

        .opportunity-card:last-child {
            margin-bottom: 0;
        }

        .opportunity-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }

        .opportunity-symbol {
            font-size: 20px;
            font-weight: 700;
        }

        .opportunity-profit {
            font-size: 24px;
            font-weight: 700;
            color: #10b981;
        }

        .opportunity-body {
            display: grid;
            grid-template-columns: 1fr auto 1fr;
            gap: 20px;
            align-items: center;
        }

        .trade-side {
            padding: 15px;
            background: rgba(255,255,255,0.1);
            border-radius: 8px;
        }

        .trade-label {
            font-size: 12px;
            color: #9ca3af;
            margin-bottom: 5px;
        }

        .trade-exchange {
            font-size: 16px;
            font-weight: 700;
            margin-bottom: 5px;
        }

        .trade-price {
            font-size: 20px;
            font-weight: 700;
        }

        .trade-size {
            font-size: 13px;
            color: #d1d5db;
            margin-top: 5px;
        }

        .trade-buy {
            border-left: 4px solid #10b981;
        }

        .trade-sell {
            border-left: 4px solid #ef4444;
        }

        .arrow-icon {
            font-size: 36px;
            color: #fbbf24;
        }

        .no-opportunities {
            text-align: center;
            padding: 40px;
            color: #6b7280;
            font-size: 16px;
        }

        /* Loading */
        .loading {
            text-align: center;
            padding: 40px;
            color: #6b7280;
        }

        .spinner {
            border: 4px solid #2a3347;
            border-top: 4px solid #3b82f6;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 0 auto;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <h1>🔥 跨交易所套利監控系統</h1>
            <div class="subtitle">Cross-Exchange Arbitrage Monitoring Dashboard</div>
            <div class="status-bar">
                <div class="status-item">
                    <span id="connection-status" class="status-badge badge-disconnected">🔴 連接中...</span>
                </div>
                <div class="status-item">
                    <span class="status-badge badge-info">交易所: <span id="exchange-count">0</span></span>
                </div>
                <div class="status-item">
                    <span class="status-badge badge-info">交易對: <span id="symbol-count">0</span></span>
                </div>
                <div class="status-item">
                    <span style="color: #9ca3af;">最後更新: <span id="last-update">-</span></span>
                </div>
            </div>
        </div>

        <!-- Statistics -->
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-label">🎯 總更新次數</div>
                <div class="stat-value" id="total-updates">0</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">💰 套利機會</div>
                <div class="stat-value positive" id="total-opportunities">0</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">📊 監控運行時間</div>
                <div class="stat-value" id="runtime">00:00:00</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">⚡ 更新頻率</div>
                <div class="stat-value" id="update-rate">0/s</div>
            </div>
        </div>

        <!-- Current Arbitrage Opportunities -->
        <div class="opportunities-section">
            <div class="section-header">
                <div class="section-title">🔥 當前套利機會</div>
            </div>
            <div class="opportunities-list" id="opportunities-list">
                <div class="loading">
                    <div class="spinner"></div>
                    <div style="margin-top: 15px;">載入中...</div>
                </div>
            </div>
        </div>

        <!-- Exchange Prices -->
        <div class="exchanges-container" id="exchanges-container">
            <div class="loading">
                <div class="spinner"></div>
                <div style="margin-top: 15px;">載入交易所數據...</div>
            </div>
        </div>
    </div>

    <script>
        let ws = null;
        let startTime = Date.now();
        let lastUpdateTime = Date.now();
        let updateCount = 0;

        function connectWebSocket() {
            const wsUrl = `ws://${window.location.host}/ws`;
            ws = new WebSocket(wsUrl);

            ws.onopen = () => {
                console.log('✅ WebSocket connected');
                document.getElementById('connection-status').className = 'status-badge badge-connected';
                document.getElementById('connection-status').textContent = '✅ 已連接';
            };

            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                updateDashboard(data);
            };

            ws.onclose = () => {
                console.log('❌ WebSocket disconnected');
                document.getElementById('connection-status').className = 'status-badge badge-disconnected';
                document.getElementById('connection-status').textContent = '🔴 已斷線';
                setTimeout(connectWebSocket, 3000);
            };

            ws.onerror = (error) => {
                console.error('WebSocket error:', error);
            };
        }

        function updateDashboard(data) {
            updateCount++;
            const now = Date.now();
            const updateRate = updateCount / ((now - startTime) / 1000);

            // Update stats
            document.getElementById('exchange-count').textContent = data.exchanges?.length || 0;
            document.getElementById('symbol-count').textContent = data.symbols?.length || 0;
            document.getElementById('last-update').textContent = new Date(data.timestamp).toLocaleTimeString();
            document.getElementById('total-updates').textContent = updateCount.toLocaleString();
            document.getElementById('total-opportunities').textContent = data.total_opportunities || 0;
            document.getElementById('update-rate').textContent = updateRate.toFixed(1) + '/s';

            // Update runtime
            const runtime = Math.floor((now - startTime) / 1000);
            const hours = Math.floor(runtime / 3600).toString().padStart(2, '0');
            const minutes = Math.floor((runtime % 3600) / 60).toString().padStart(2, '0');
            const seconds = (runtime % 60).toString().padStart(2, '0');
            document.getElementById('runtime').textContent = `${hours}:${minutes}:${seconds}`;

            // Update opportunities
            updateOpportunities(data.opportunities || []);

            // Update exchange prices
            updateExchangePrices(data.market_data || {});
        }

        function updateOpportunities(opportunities) {
            const container = document.getElementById('opportunities-list');

            if (opportunities.length === 0) {
                container.innerHTML = '<div class="no-opportunities">暫無套利機會</div>';
                return;
            }

            container.innerHTML = opportunities.map(opp => `
                <div class="opportunity-card">
                    <div class="opportunity-header">
                        <div class="opportunity-symbol">${opp.symbol}</div>
                        <div class="opportunity-profit">+$${opp.profit.toFixed(2)} (${opp.profit_pct.toFixed(2)}%)</div>
                    </div>
                    <div class="opportunity-body">
                        <div class="trade-side trade-buy">
                            <div class="trade-label">買入 BUY</div>
                            <div class="trade-exchange">${opp.buy_exchange}</div>
                            <div class="trade-price price-bid">$${opp.buy_price.toFixed(2)}</div>
                            <div class="trade-size">可用量: ${opp.buy_size.toFixed(4)}</div>
                        </div>
                        <div class="arrow-icon">→</div>
                        <div class="trade-side trade-sell">
                            <div class="trade-label">賣出 SELL</div>
                            <div class="trade-exchange">${opp.sell_exchange}</div>
                            <div class="trade-price price-ask">$${opp.sell_price.toFixed(2)}</div>
                            <div class="trade-size">可用量: ${opp.sell_size.toFixed(4)}</div>
                        </div>
                    </div>
                </div>
            `).join('');
        }

        function updateExchangePrices(marketData) {
            const container = document.getElementById('exchanges-container');
            const exchanges = Object.keys(marketData);

            if (exchanges.length === 0) {
                container.innerHTML = '<div class="loading">暫無交易所數據</div>';
                return;
            }

            container.innerHTML = exchanges.map(exchange => {
                const symbols = Object.keys(marketData[exchange] || {});

                return symbols.map(symbol => {
                    const data = marketData[exchange][symbol];
                    if (!data) return '';

                    return `
                        <div class="exchange-card">
                            <div class="exchange-header">
                                <div class="exchange-name">${exchange}</div>
                                <div class="exchange-status">${data.error ? 'ERROR' : 'ACTIVE'}</div>
                            </div>
                            <div class="exchange-body">
                                <div style="font-size: 14px; color: #9ca3af; margin-bottom: 15px;">${symbol}</div>
                                ${data.error ? `
                                    <div style="color: #ef4444; font-size: 14px;">${data.error}</div>
                                ` : `
                                    <div class="price-row">
                                        <span class="price-label">最佳買價 Best Bid</span>
                                        <span class="price-value price-bid">$${data.best_bid?.toFixed(2) || 'N/A'}</span>
                                    </div>
                                    <div class="price-row">
                                        <span class="price-label">最佳賣價 Best Ask</span>
                                        <span class="price-value price-ask">$${data.best_ask?.toFixed(2) || 'N/A'}</span>
                                    </div>
                                    <div class="price-row">
                                        <span class="price-label">買賣價差 Spread</span>
                                        <span class="price-value price-spread">${data.spread_pct?.toFixed(4) || 'N/A'}%</span>
                                    </div>
                                    <div class="price-row">
                                        <span class="price-label">買盤深度 Bid Size</span>
                                        <span class="price-value">${data.bid_size?.toFixed(4) || 'N/A'}</span>
                                    </div>
                                    <div class="price-row">
                                        <span class="price-label">賣盤深度 Ask Size</span>
                                        <span class="price-value">${data.ask_size?.toFixed(4) || 'N/A'}</span>
                                    </div>
                                `}
                            </div>
                        </div>
                    `;
                }).join('');
            }).join('');
        }

        // Initialize
        connectWebSocket();

        // Update runtime every second
        setInterval(() => {
            const now = Date.now();
            const runtime = Math.floor((now - startTime) / 1000);
            const hours = Math.floor(runtime / 3600).toString().padStart(2, '0');
            const minutes = Math.floor((runtime % 3600) / 60).toString().padStart(2, '0');
            const seconds = (runtime % 60).toString().padStart(2, '0');
            document.getElementById('runtime').textContent = `${hours}:${minutes}:${seconds}`;
        }, 1000);
    </script>
</body>
</html>
"""


async def get_dashboard():
    """返回儀表板 HTML"""
    return HTML_TEMPLATE


async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 連接處理"""
    await websocket.accept()
    connected_clients.append(websocket)
    print(f"✅ Client connected. Total clients: {len(connected_clients)}")

    try:
        while True:
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        connected_clients.remove(websocket)
        print(f"❌ Client disconnected. Total clients: {len(connected_clients)}")


async def broadcast_data():
    """定期廣播套利數據到所有連接的客戶端"""
    while True:
        try:
            if monitor is None or len(connected_clients) == 0:
                await asyncio.sleep(1)
                continue

            # 收集當前市場數據
            market_data = {}
            for exchange_name, data_dict in monitor.latest_data.items():
                market_data[exchange_name] = {}
                for symbol, market_data_obj in data_dict.items():
                    market_data[exchange_name][symbol] = {
                        "best_bid": float(market_data_obj.best_bid) if market_data_obj.best_bid else None,
                        "best_ask": float(market_data_obj.best_ask) if market_data_obj.best_ask else None,
                        "bid_size": float(market_data_obj.bid_size) if market_data_obj.bid_size else None,
                        "ask_size": float(market_data_obj.ask_size) if market_data_obj.ask_size else None,
                        "spread": float(market_data_obj.spread) if market_data_obj.spread else None,
                        "spread_pct": float(market_data_obj.spread_pct) if market_data_obj.spread_pct else None,
                    }

            # 收集套利機會
            opportunities = []
            for opp in monitor.opportunities:
                opportunities.append({
                    "symbol": opp["symbol"],
                    "buy_exchange": opp["buy_exchange"],
                    "sell_exchange": opp["sell_exchange"],
                    "buy_price": float(opp["buy_price"]),
                    "sell_price": float(opp["sell_price"]),
                    "buy_size": float(opp["buy_size"]),
                    "sell_size": float(opp["sell_size"]),
                    "profit": float(opp["profit"]),
                    "profit_pct": float(opp["profit_pct"]),
                })

            # 構建廣播數據
            data = {
                "timestamp": datetime.now().isoformat(),
                "exchanges": list(monitor.adapters.keys()),
                "symbols": monitor.symbols,
                "market_data": market_data,
                "opportunities": opportunities,
                "total_opportunities": monitor.total_opportunities_found,
            }

            # 廣播給所有客戶端
            disconnected = []
            for client in connected_clients:
                try:
                    await client.send_json(data)
                except Exception:
                    disconnected.append(client)

            # 移除斷線客戶端
            for client in disconnected:
                if client in connected_clients:
                    connected_clients.remove(client)

            await asyncio.sleep(1)  # 每秒更新一次

        except Exception as e:
            print(f"❌ Broadcast error: {e}")
            await asyncio.sleep(2)


async def initialize_monitor():
    """初始化監控系統"""
    global monitor

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

    print("🔌 連接交易所...")

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
            print(f"  ⚠️  {exchange.upper()} - 跳過: {e}")

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
            print(f"  ⚠️  {exchange.upper()} - 跳過: {e}")

    if not adapters:
        raise Exception("沒有可用的交易所，請先配置 API")

    # 去重 symbols
    symbols = list(set(symbols))

    print(f"\n📊 監控配置:")
    print(f"  交易所數量: {len(adapters)}")
    print(f"  交易對數量: {len(symbols)}")
    print(f"  更新間隔: 2 秒")
    print(f"  最小利潤: 0.1%\n")

    # 創建監控器
    monitor = MultiExchangeMonitor(
        adapters=adapters,
        symbols=symbols,
        update_interval=2.0,
        min_profit_pct=0.1
    )

    # 在背景啟動監控
    asyncio.create_task(monitor.start())


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """管理應用程序生命週期"""
    # Startup
    await initialize_monitor()
    task = asyncio.create_task(broadcast_data())
    print("🚀 Arbitrage Dashboard started")

    yield

    # Shutdown
    task.cancel()
    if monitor:
        await monitor.stop()
    print("👋 Arbitrage Dashboard stopped")


# Create app
app = FastAPI(title="Arbitrage Monitoring Dashboard", lifespan=lifespan)

# Register routes
app.get("/", response_class=HTMLResponse)(get_dashboard)
app.websocket("/ws")(websocket_endpoint)


def run_dashboard(host: str = "127.0.0.1", port: int = 8002):
    """啟動套利監控儀表板"""
    print(f"\n{'='*60}")
    print(f"🔥 Starting Arbitrage Monitoring Dashboard")
    print(f"{'='*60}")
    print(f"📡 Server: http://{host}:{port}")
    print(f"🌐 Open your browser and visit the URL above")
    print(f"{'='*60}\n")

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_dashboard()
