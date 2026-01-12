"""
Real-time Web Dashboard for Multi-Exchange Adapters
顯示實時交易數據的Web儀表板
"""

import asyncio
import json
import os
from datetime import datetime
from typing import Dict, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import uvicorn
from pathlib import Path
from dotenv import load_dotenv

# Import adapter factory
import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
from src.adapters.factory import create_adapter
from src.adapters.base_adapter import OrderSide, OrderType, TimeInForce

# Global adapter instance
adapter = None
connected_clients: List[WebSocket] = []


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>多交易所儀表板 - Multi-Exchange Dashboard</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #333;
            padding: 20px;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        
        .header {
            background: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }
        
        h1 {
            color: #667eea;
            margin-bottom: 10px;
        }
        
        .connection-status {
            display: inline-block;
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 14px;
            font-weight: 600;
        }
        
        .status-connected {
            background: #10b981;
            color: white;
        }
        
        .status-disconnected {
            background: #ef4444;
            color: white;
        }
        
        .dashboard-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        
        .card {
            background: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        
        .card h2 {
            color: #667eea;
            font-size: 18px;
            margin-bottom: 15px;
            border-bottom: 2px solid #667eea;
            padding-bottom: 10px;
        }
        
        .metric {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0;
            border-bottom: 1px solid #eee;
        }
        
        .metric:last-child {
            border-bottom: none;
        }
        
        .metric-label {
            color: #666;
            font-size: 14px;
        }
        
        .metric-value {
            font-weight: 700;
            font-size: 16px;
            color: #333;
        }
        
        .positive {
            color: #10b981;
        }
        
        .negative {
            color: #ef4444;
        }
        
        .table-container {
            overflow-x: auto;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
        }
        
        th {
            background: #f3f4f6;
            padding: 10px;
            text-align: left;
            font-size: 12px;
            color: #666;
            border-bottom: 2px solid #667eea;
        }
        
        td {
            padding: 10px;
            border-bottom: 1px solid #eee;
            font-size: 14px;
        }
        
        tr:hover {
            background: #f9fafb;
        }
        
        .order-buy {
            color: #10b981;
            font-weight: 600;
        }
        
        .order-sell {
            color: #ef4444;
            font-weight: 600;
        }
        
        .loading {
            text-align: center;
            padding: 20px;
            color: #666;
        }
        
        .error {
            background: #fee2e2;
            color: #991b1b;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 多交易所永續合約儀表板</h1>
            <p style="color: #666; margin: 10px 0;">Multi-Exchange Perpetual Trading Dashboard</p>
            <div id="connection-status" class="connection-status status-disconnected">
                ⚠️ 連接中... Connecting...
            </div>
            <div style="margin-top: 10px; color: #666; font-size: 14px;">
                <span id="exchange-name">Exchange: -</span> | 
                <span id="last-update">Last Update: -</span>
            </div>
        </div>
        
        <div id="error-message" class="error" style="display: none;"></div>
        
        <!-- Account Overview -->
        <div class="dashboard-grid">
            <div class="card">
                <h2>💰 帳戶餘額 Balance</h2>
                <div id="balance-content" class="loading">Loading...</div>
            </div>
            
            <div class="card">
                <h2>📊 持倉概覽 Positions</h2>
                <div id="positions-summary" class="loading">Loading...</div>
            </div>
            
            <div class="card">
                <h2>📈 市場數據 Market</h2>
                <div id="market-data" class="loading">Loading...</div>
            </div>
        </div>
        
        <!-- Detailed Tables -->
        <div class="card" style="margin-bottom: 20px;">
            <h2>📍 當前持倉 Active Positions</h2>
            <div class="table-container">
                <table id="positions-table">
                    <thead>
                        <tr>
                            <th>Symbol</th>
                            <th>Side</th>
                            <th>Size</th>
                            <th>Entry Price</th>
                            <th>Mark Price</th>
                            <th>PnL</th>
                            <th>ROE %</th>
                        </tr>
                    </thead>
                    <tbody id="positions-tbody">
                        <tr><td colspan="7" style="text-align: center; color: #666;">No positions</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
        
        <div class="card">
            <h2>📋 未成交訂單 Open Orders</h2>
            <div class="table-container">
                <table id="orders-table">
                    <thead>
                        <tr>
                            <th>Order ID</th>
                            <th>Symbol</th>
                            <th>Side</th>
                            <th>Type</th>
                            <th>Price</th>
                            <th>Quantity</th>
                            <th>Filled</th>
                            <th>Status</th>
                            <th>Time</th>
                        </tr>
                    </thead>
                    <tbody id="orders-tbody">
                        <tr><td colspan="9" style="text-align: center; color: #666;">No open orders</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    
    <script>
        let ws = null;
        let reconnectAttempts = 0;
        const maxReconnectAttempts = 5;
        
        function connectWebSocket() {
            const wsUrl = `ws://${window.location.host}/ws`;
            ws = new WebSocket(wsUrl);
            
            ws.onopen = () => {
                console.log('✅ WebSocket connected');
                reconnectAttempts = 0;
                document.getElementById('connection-status').className = 'connection-status status-connected';
                document.getElementById('connection-status').textContent = '✅ 已連接 Connected';
            };
            
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                updateDashboard(data);
            };
            
            ws.onclose = () => {
                console.log('❌ WebSocket disconnected');
                document.getElementById('connection-status').className = 'connection-status status-disconnected';
                document.getElementById('connection-status').textContent = '❌ 已斷線 Disconnected';
                
                if (reconnectAttempts < maxReconnectAttempts) {
                    reconnectAttempts++;
                    console.log(`Reconnecting... Attempt ${reconnectAttempts}`);
                    setTimeout(connectWebSocket, 3000);
                }
            };
            
            ws.onerror = (error) => {
                console.error('WebSocket error:', error);
            };
        }
        
        function updateDashboard(data) {
            document.getElementById('last-update').textContent = `Last Update: ${new Date(data.timestamp).toLocaleTimeString()}`;
            document.getElementById('exchange-name').textContent = `Exchange: ${data.exchange || 'Unknown'}`;
            
            // Update balance
            if (data.balance) {
                const balanceHtml = `
                    <div class="metric">
                        <span class="metric-label">Total Equity</span>
                        <span class="metric-value">$${data.balance.total_equity.toFixed(2)}</span>
                    </div>
                    <div class="metric">
                        <span class="metric-label">Available</span>
                        <span class="metric-value">$${data.balance.available.toFixed(2)}</span>
                    </div>
                    <div class="metric">
                        <span class="metric-label">Used Margin</span>
                        <span class="metric-value">$${data.balance.used_margin.toFixed(2)}</span>
                    </div>
                `;
                document.getElementById('balance-content').innerHTML = balanceHtml;
            }
            
            // Update positions summary
            if (data.positions) {
                const totalPnL = data.positions.reduce((sum, p) => sum + p.unrealized_pnl, 0);
                const positionsHtml = `
                    <div class="metric">
                        <span class="metric-label">Open Positions</span>
                        <span class="metric-value">${data.positions.length}</span>
                    </div>
                    <div class="metric">
                        <span class="metric-label">Total PnL</span>
                        <span class="metric-value ${totalPnL >= 0 ? 'positive' : 'negative'}">
                            ${totalPnL >= 0 ? '+' : ''}$${totalPnL.toFixed(2)}
                        </span>
                    </div>
                `;
                document.getElementById('positions-summary').innerHTML = positionsHtml;
                
                // Update positions table
                updatePositionsTable(data.positions);
            }
            
            // Update market data
            if (data.orderbook) {
                const ob = data.orderbook;
                const spread = ob.asks[0] && ob.bids[0] ? ob.asks[0][0] - ob.bids[0][0] : 0;
                const mid = ob.asks[0] && ob.bids[0] ? (ob.asks[0][0] + ob.bids[0][0]) / 2 : 0;
                
                const marketHtml = `
                    <div class="metric">
                        <span class="metric-label">Symbol</span>
                        <span class="metric-value">${data.symbol || 'N/A'}</span>
                    </div>
                    <div class="metric">
                        <span class="metric-label">Best Bid</span>
                        <span class="metric-value positive">$${ob.bids[0] ? ob.bids[0][0].toFixed(2) : 'N/A'}</span>
                    </div>
                    <div class="metric">
                        <span class="metric-label">Best Ask</span>
                        <span class="metric-value negative">$${ob.asks[0] ? ob.asks[0][0].toFixed(2) : 'N/A'}</span>
                    </div>
                    <div class="metric">
                        <span class="metric-label">Spread</span>
                        <span class="metric-value">$${spread.toFixed(2)}</span>
                    </div>
                `;
                document.getElementById('market-data').innerHTML = marketHtml;
            }
            
            // Update orders table
            if (data.orders) {
                updateOrdersTable(data.orders);
            }
            
            // Show errors
            if (data.error) {
                const errorDiv = document.getElementById('error-message');
                errorDiv.textContent = `⚠️ ${data.error}`;
                errorDiv.style.display = 'block';
            }
        }
        
        function updatePositionsTable(positions) {
            const tbody = document.getElementById('positions-tbody');
            if (positions.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: #666;">No positions</td></tr>';
                return;
            }
            
            tbody.innerHTML = positions.map(p => {
                const pnlClass = p.unrealized_pnl >= 0 ? 'positive' : 'negative';
                const sideClass = p.side === 'LONG' ? 'order-buy' : 'order-sell';
                const roe = ((p.unrealized_pnl / (p.entry_price * p.size)) * 100).toFixed(2);
                
                return `
                    <tr>
                        <td>${p.symbol}</td>
                        <td class="${sideClass}">${p.side}</td>
                        <td>${p.size}</td>
                        <td>$${p.entry_price.toFixed(2)}</td>
                        <td>$${p.mark_price.toFixed(2)}</td>
                        <td class="${pnlClass}">${p.unrealized_pnl >= 0 ? '+' : ''}$${p.unrealized_pnl.toFixed(2)}</td>
                        <td class="${pnlClass}">${roe >= 0 ? '+' : ''}${roe}%</td>
                    </tr>
                `;
            }).join('');
        }
        
        function updateOrdersTable(orders) {
            const tbody = document.getElementById('orders-tbody');
            if (orders.length === 0) {
                tbody.innerHTML = '<tr><td colspan="9" style="text-align: center; color: #666;">No open orders</td></tr>';
                return;
            }
            
            tbody.innerHTML = orders.map(o => {
                const sideClass = o.side === 'BUY' ? 'order-buy' : 'order-sell';
                const timestamp = new Date(o.timestamp).toLocaleString();
                
                return `
                    <tr>
                        <td style="font-family: monospace; font-size: 12px;">${o.order_id.substring(0, 16)}...</td>
                        <td>${o.symbol}</td>
                        <td class="${sideClass}">${o.side}</td>
                        <td>${o.order_type}</td>
                        <td>$${o.price.toFixed(2)}</td>
                        <td>${o.quantity}</td>
                        <td>${o.filled_quantity}</td>
                        <td>${o.status}</td>
                        <td>${timestamp}</td>
                    </tr>
                `;
            }).join('');
        }
        
        // Initialize
        connectWebSocket();
    </script>
</body>
</html>
"""


async def get_dashboard():
    """返回儀表板 HTML"""
    return HTML_TEMPLATE


async def get_status():
    """獲取適配器狀態"""
    if adapter is None:
        return {"connected": False, "error": "Adapter not initialized"}
    return {
        "connected": hasattr(adapter, '_connected') and adapter._connected,
        "exchange": adapter.__class__.__name__.replace('Adapter', '')
    }


async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 連接處理"""
    await websocket.accept()
    connected_clients.append(websocket)
    print(f"✅ Client connected. Total clients: {len(connected_clients)}")
    
    try:
        while True:
            # Keep connection alive
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        connected_clients.remove(websocket)
        print(f"❌ Client disconnected. Total clients: {len(connected_clients)}")


async def broadcast_data():
    """定期廣播交易數據到所有連接的客戶端"""
    while True:
        try:
            if adapter is None or len(connected_clients) == 0:
                await asyncio.sleep(2)
                continue
            
            # Gather data from adapter
            data = {
                "timestamp": datetime.now().isoformat(),
                "exchange": adapter.__class__.__name__.replace('Adapter', ''),
            }
            
            try:
                # Get balance
                balance = await adapter.get_balance()
                data["balance"] = {
                    "total_equity": balance.total_equity,
                    "available": balance.available_balance,
                    "used_margin": balance.used_margin
                }
            except Exception as e:
                data["balance_error"] = str(e)
            
            try:
                # Get positions
                positions = await adapter.get_positions()
                data["positions"] = [
                    {
                        "symbol": p.symbol,
                        "side": p.side,
                        "size": p.size,
                        "entry_price": p.entry_price,
                        "mark_price": p.mark_price,
                        "unrealized_pnl": p.unrealized_pnl,
                        "leverage": p.leverage
                    }
                    for p in positions
                ]
            except Exception as e:
                data["positions"] = []
                data["positions_error"] = str(e)
            
            try:
                # Get orderbook (default BTC-USD)
                orderbook = await adapter.get_orderbook("BTC-USD", limit=5)
                data["orderbook"] = {
                    "bids": orderbook.bids[:5],
                    "asks": orderbook.asks[:5]
                }
                data["symbol"] = "BTC-USD"
            except Exception as e:
                data["orderbook_error"] = str(e)
            
            try:
                # Get open orders
                orders = await adapter.get_open_orders()
                data["orders"] = [
                    {
                        "order_id": o.order_id,
                        "symbol": o.symbol,
                        "side": o.side,
                        "order_type": o.order_type,
                        "price": o.price,
                        "quantity": o.quantity,
                        "filled_quantity": o.filled_quantity,
                        "status": o.status,
                        "timestamp": o.timestamp.isoformat() if o.timestamp else None
                    }
                    for o in orders
                ]
            except Exception as e:
                data["orders"] = []
                data["orders_error"] = str(e)
            
            # Broadcast to all clients
            disconnected = []
            for client in connected_clients:
                try:
                    await client.send_json(data)
                except Exception:
                    disconnected.append(client)
            
            # Remove disconnected clients
            for client in disconnected:
                if client in connected_clients:
                    connected_clients.remove(client)
            
            await asyncio.sleep(2)  # Update every 2 seconds
            
        except Exception as e:
            print(f"❌ Broadcast error: {e}")
            await asyncio.sleep(5)


async def initialize_adapter():
    """初始化適配器"""
    global adapter

    # Load environment variables
    load_dotenv()

    # Get credentials from environment
    private_key = os.getenv("WALLET_PRIVATE_KEY")
    if not private_key:
        raise ValueError("WALLET_PRIVATE_KEY not found in environment variables")

    # Create StandX adapter with correct config format
    config = {
        "exchange_name": "standx",
        "private_key": private_key,
        "chain": os.getenv("CHAIN", "bsc"),
        "base_url": os.getenv("STANDX_BASE_URL", "https://api.standx.com"),
        "perps_url": os.getenv("STANDX_PERPS_URL", "https://perps.standx.com")
    }
    adapter = create_adapter(config)

    # Connect to exchange
    print("🔌 Connecting to StandX...")
    await adapter.connect()
    print("✅ Adapter initialized and connected")


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """管理應用程序生命週期"""
    # Startup
    await initialize_adapter()
    task = asyncio.create_task(broadcast_data())
    print("🚀 Dashboard server started")
    
    yield
    
    # Shutdown
    task.cancel()
    print("👋 Dashboard server stopped")

# Create app with lifespan
app = FastAPI(title="Multi-Exchange Dashboard", lifespan=lifespan)

# Register routes
app.get("/", response_class=HTMLResponse)(get_dashboard)
app.get("/api/status")(get_status)
app.websocket("/ws")(websocket_endpoint)

# Mount static files
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


def run_dashboard(host: str = "127.0.0.1", port: int = 8000):
    """啟動儀表板服務器"""
    print(f"\n{'='*60}")
    print(f"🚀 Starting Multi-Exchange Dashboard")
    print(f"{'='*60}")
    print(f"📡 Server: http://{host}:{port}")
    print(f"🌐 Open your browser and visit the URL above")
    print(f"{'='*60}\n")
    
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_dashboard()
