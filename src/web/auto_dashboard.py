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
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv, set_key, unset_key
import logging
import uvicorn

# 載入 .env 文件（必須在讀取環境變數之前）
load_dotenv()

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
from src.web.api import register_all_routes
from src.web.config_manager import ConfigManager
from src.web.system_manager import SystemManager

# 全局變量
mm_executor: Optional[MarketMakerExecutor] = None
connected_clients: List[WebSocket] = []

# Orderbook 緩存 (避免 rate limiting)
_orderbook_cache: Dict[str, dict] = {}  # {exchange_symbol: {'data': ..., 'timestamp': ...}}
_orderbook_cache_ttl = 2.0  # 緩存 2 秒

mm_status = {
    'running': False,
    'status': 'stopped',
    'hedge_target': os.getenv('HEDGE_TARGET', 'none'),  # 從環境變數讀取對沖目標
    'order_size_btc': 0.001,
    'order_distance_bps': 9,  # 默認值與 mm_config.yaml 同步
    'cancel_distance_bps': 3,
    'rebalance_distance_bps': 12,
    'max_position_btc': 0.01,
}

# Simulation comparison globals
simulation_runner: Optional[SimulationRunner] = None
result_logger: Optional[ResultLogger] = None
comparison_engine: Optional[ComparisonEngine] = None

env_file = Path(__file__).parent.parent.parent / ".env"

# 日誌設置
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 配置管理器和系統管理器實例
config_manager = ConfigManager(env_file)
system_manager = SystemManager(config_manager)

# 便捷訪問器 (保持向後兼容)
def get_adapters():
    return system_manager.adapters

def get_monitor():
    return system_manager.monitor

def get_executor():
    return system_manager.executor

def get_system_status():
    return system_manager.system_status


# 委託函數 (保持向後兼容)
async def init_system():
    """初始化系統"""
    await system_manager.init_system()


async def add_exchange(exchange_name: str, exchange_type: str):
    """動態添加交易所"""
    return await system_manager.add_exchange(exchange_name, exchange_type)


async def remove_exchange(exchange_name: str):
    """移除交易所"""
    await system_manager.remove_exchange(exchange_name)


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
            monitor = get_monitor()
            adapters = get_adapters()
            executor = get_executor()
            system_status = get_system_status()

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
                        ob = await standx.get_orderbook('BTC-USD', depth=50)
                        if ob and ob.bids and ob.asks:
                            bids = [[float(b[0]), float(b[1])] for b in ob.bids[:50]]
                            asks = [[float(a[0]), float(a[1])] for a in ob.asks[:50]]
                            data['orderbooks']['STANDX'] = {
                                'BTC-USD': {
                                    'bids': bids,
                                    'asks': asks
                                }
                            }
                    except Exception as e:
                        logger.warning(f"獲取 StandX 訂單簿失敗: {e}")

                # 獲取 GRVT 訂單簿深度
                if 'GRVT' in adapters:
                    try:
                        grvt = adapters['GRVT']
                        ob = await grvt.get_orderbook('BTC_USDT_Perp', limit=50)
                        if ob and ob.bids and ob.asks:
                            bids = [[float(b[0]), float(b[1])] for b in ob.bids[:50]]
                            asks = [[float(a[0]), float(a[1])] for a in ob.asks[:50]]
                            data['orderbooks']['GRVT'] = {
                                'BTC_USDT_Perp': {
                                    'bids': bids,
                                    'asks': asks
                                }
                            }
                    except Exception as e:
                        logger.warning(f"獲取 GRVT 訂單簿失敗: {e}")

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

                # StandX 做市商狀態
                data['mm_status'] = mm_status.copy()
                if mm_executor:
                    data['mm_executor'] = serialize_for_json(mm_executor.to_dict())
                    # 添加運行時控制狀態到 mm_status
                    data['mm_status']['hedge_enabled'] = mm_executor.is_hedge_enabled()
                    data['mm_status']['instant_close_enabled'] = mm_executor.is_instant_close_enabled()
                else:
                    # 未啟動時預設為 False
                    data['mm_status']['hedge_enabled'] = False
                    data['mm_status']['instant_close_enabled'] = False

                # 做市商實時倉位 (統一從 executor.state 讀取)
                import time as time_module
                positions = {
                    'status': 'disconnected',
                    'standx': {'btc': 0, 'equity': 0},
                    'grvt': {'btc': 0, 'usdt': 0},
                    'net_btc': 0,
                    'is_hedged': True,
                    'seconds_ago': None,
                }
                if mm_executor:
                    # 從 executor.state 讀取 (統一資料來源)
                    state = mm_executor.state
                    standx_pos = float(state.get_standx_position())
                    hedge_pos = float(state.get_hedge_position())
                    last_sync = state.get_last_position_sync()
                    seconds_ago = round(time_module.time() - last_sync, 1) if last_sync > 0 else None

                    positions = {
                        'status': 'connected',
                        'standx': {'btc': standx_pos, 'equity': 0},
                        'grvt': {'btc': hedge_pos, 'usdt': 0},
                        'net_btc': standx_pos + hedge_pos,
                        'is_hedged': abs(standx_pos + hedge_pos) < 0.0001,
                        'seconds_ago': seconds_ago,
                    }

                    # 餘額和 PnL 從 adapter 查詢
                    if 'STANDX' in adapters:
                        try:
                            balance = await adapters['STANDX'].get_balance()
                            positions['standx']['equity'] = float(balance.equity)
                            positions['standx']['pnl'] = float(balance.unrealized_pnl)
                        except Exception as e:
                            logger.debug(f"查詢 StandX 餘額失敗: {e}")

                    # 對沖帳戶 (STANDX_HEDGE)
                    if 'STANDX_HEDGE' in adapters:
                        try:
                            balance = await adapters['STANDX_HEDGE'].get_balance()
                            positions['hedge'] = {
                                'btc': hedge_pos,
                                'equity': float(balance.equity),
                                'pnl': float(balance.unrealized_pnl),
                            }
                        except Exception as e:
                            logger.debug(f"查詢對沖帳戶餘額失敗: {e}")

                    # GRVT 帳戶 (兼容舊版)
                    if 'GRVT' in adapters:
                        try:
                            balance = await adapters['GRVT'].get_balance()
                            positions['grvt']['usdt'] = float(balance.available_balance) if balance else 0
                        except Exception as e:
                            logger.debug(f"查詢 GRVT 餘額失敗: {e}")

                    # 計算合計淨利潤
                    standx_pnl = positions.get('standx', {}).get('pnl', 0) or 0
                    hedge_pnl = positions.get('hedge', {}).get('pnl', 0) or 0
                    positions['total_pnl'] = standx_pnl + hedge_pnl

                data['mm_positions'] = positions

                # 成交歷史 (從 executor.state 讀取)
                if mm_executor:
                    data['fill_history'] = mm_executor.state.get_fill_history()
                else:
                    data['fill_history'] = []

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

    # 使用 system_manager 關閉系統
    await system_manager.shutdown()

    logger.info("Application shutdown complete")


# FastAPI app
app = FastAPI(lifespan=lifespan)

# 註冊模組路由
from src.web.modules.orderbook_monitor import register_routes as register_orderbook_routes
from src.web.modules.strategy_analyzer import register_routes as register_strategy_routes
register_orderbook_routes(app, get_adapters)
register_strategy_routes(app, get_adapters)

# 準備 API 路由依賴項
def _get_mm_executor():
    return mm_executor

def _set_mm_executor(value):
    global mm_executor
    mm_executor = value

api_dependencies = {
    'config_manager': config_manager,
    'adapters_getter': get_adapters,
    'executor_getter': get_executor,
    'mm_executor_getter': _get_mm_executor,
    'mm_executor_setter': _set_mm_executor,
    'monitor_getter': get_monitor,
    'system_status': get_system_status(),
    'mm_status': mm_status,
    'init_system': init_system,
    'add_exchange': add_exchange,
    'remove_exchange': remove_exchange,
    'serialize_for_json': serialize_for_json,
    'logger': logger,
}
register_all_routes(app, api_dependencies)

# ==================== React 前端服務 ====================
# 前端靜態檔案目錄
FRONTEND_DIST = Path(__file__).parent / "frontend_dist"

# 掛載靜態資源 (JS, CSS, images)
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    """
    SPA (Single Page Application) 服務
    - API 路由 (/api/*) 和 WebSocket (/ws) 由上方的路由處理
    - 其他所有路徑都返回 index.html，由 React Router 處理
    """
    # 排除 API 和 WebSocket 路徑
    if full_path.startswith("api/") or full_path == "ws":
        raise HTTPException(status_code=404, detail="Not found")

    # 檢查前端是否已建置
    index_file = FRONTEND_DIST / "index.html"
    if not index_file.exists():
        return HTMLResponse(
            content="""
            <html>
            <head><title>Frontend Not Built</title></head>
            <body style="font-family: sans-serif; padding: 40px; background: #0f1419; color: #e5e7eb;">
                <h1>Frontend Not Built</h1>
                <p>Please build the frontend first:</p>
                <pre style="background: #1a1f2e; padding: 20px; border-radius: 8px;">
cd frontend
npm install
npm run build</pre>
                <p>Then restart the server.</p>
            </body>
            </html>
            """,
            status_code=503
        )

    return FileResponse(index_file)


# ==================== Legacy HTML (已被 React 前端取代) ====================
# 以下代碼保留供參考，未來可移除
_LEGACY_HTML_REMOVED = True  # 標記舊代碼已移除

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 連接"""
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass  # 正常斷開
    except Exception as e:
        logger.debug(f"WebSocket error: {e}")
    finally:
        # 安全移除：可能已經在 broadcast_data 中被移除
        if websocket in connected_clients:
            connected_clients.remove(websocket)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9999, log_level="info")
