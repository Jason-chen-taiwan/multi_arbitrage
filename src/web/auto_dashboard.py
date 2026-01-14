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
from src.web.api import register_all_routes
from src.web.templates import get_css_styles, get_all_pages
from src.web.config_manager import ConfigManager
from src.web.system_manager import SystemManager

# 全局變量
mm_executor: Optional[MarketMakerExecutor] = None
connected_clients: List[WebSocket] = []
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
                        ob = await standx.get_orderbook('BTC-USD')
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


@app.get("/", response_class=HTMLResponse)
async def root():
    """首頁 - 帶分頁切換"""
    css_styles = get_css_styles()
    html_head = f"""
    <!DOCTYPE html>
    <html lang="zh-TW">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>交易控制台</title>
        <style>{css_styles}</style>
    </head>"""

    # 獲取所有頁面 HTML
    pages_html = get_all_pages()

    html_body = """
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
""" + pages_html + """
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
                    'place': '#10b981',      // 綠色 - 下單
                    'fill': '#8b5cf6'        // 紫色 - 成交
                };

                const actionNames = {
                    'cancel': '撤單',
                    'rebalance': '重掛',
                    'place': '下單',
                    'fill': '成交'
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

                // 波動率配置 (從 API 加載)
                volatilityWindowSec: null,     // 默認 5 秒
                volatilityThresholdBps: null,  // 默認 5.0 bps

                // 價格歷史窗口 [{time: timestamp, price: number}, ...]
                priceWindow: [],

                // 波動率統計
                currentVolatilityBps: 0,
                volatilityPauseCount: 0,       // 因波動率暫停次數

                // 模擬掛單 (null = 無單)
                bidOrder: null,
                askOrder: null,

                // 時間統計 (毫秒)
                startTime: Date.now(),
                lastTickTime: null,
                qualifiedTimeMs: 0,   // 雙邊都合格的總時間 (舊版相容)
                totalTimeMs: 0,       // 總運行時間

                // 分層時間統計 (StandX: 0-10=100%, 10-30=50%, 30-100=10%)
                boostedTimeMs: 0,     // 100% 層時間 (0-10 bps)
                standardTimeMs: 0,    // 50% 層時間 (10-30 bps)
                basicTimeMs: 0,       // 10% 層時間 (30-100 bps)
                outOfRangeTimeMs: 0,  // 超出範圍時間 (>100 bps 或無單)

                // 成交統計
                fillCount: 0,         // 成交次數
                fills: [],            // 成交記錄
                simulatedPnlUsd: 0,   // 模擬 PnL

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

                // 更新價格窗口
                updatePriceWindow(price) {
                    const now = Date.now();
                    this.priceWindow.push({ time: now, price });

                    // 清理過期數據
                    const windowMs = (this.volatilityWindowSec || 5) * 1000;
                    const cutoff = now - windowMs;
                    this.priceWindow = this.priceWindow.filter(p => p.time > cutoff);
                },

                // 計算波動率 (bps)
                getVolatilityBps() {
                    if (this.priceWindow.length < 2) {
                        return Infinity;  // 數據不足，視為高風險
                    }

                    const prices = this.priceWindow.map(p => p.price);
                    const max = Math.max(...prices);
                    const min = Math.min(...prices);
                    const latest = prices[prices.length - 1];

                    if (latest === 0) return Infinity;
                    return (max - min) / latest * 10000;
                },

                // 檢查是否應該因波動率暫停
                shouldPauseForVolatility() {
                    if (this.volatilityThresholdBps === null) return false;
                    return this.getVolatilityBps() > this.volatilityThresholdBps;
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

                    // 更新價格窗口並計算波動率
                    this.updatePriceWindow(midPrice);
                    this.currentVolatilityBps = this.getVolatilityBps();

                    // 波動率檢查：超過閾值則暫停掛單
                    if (this.shouldPauseForVolatility()) {
                        this.volatilityPauseCount++;
                        // 撤銷現有訂單
                        if (this.bidOrder) {
                            this.addHistory('cancel', 'bid', this.bidOrder.price, null, midPrice, '-', '波動率過高 (' + this.currentVolatilityBps.toFixed(1) + ' bps)', {});
                            this.bidOrder = null;
                            this.bidCancels++;
                        }
                        if (this.askOrder) {
                            this.addHistory('cancel', 'ask', this.askOrder.price, null, midPrice, '-', '波動率過高 (' + this.currentVolatilityBps.toFixed(1) + ' bps)', {});
                            this.askOrder = null;
                            this.askCancels++;
                        }
                        return { bidStatus: 'volatility_pause', askStatus: 'volatility_pause' };
                    }

                    // 取得最佳買賣價
                    const bestBid = ob?.bids?.[0]?.[0] || null;
                    const bestAsk = ob?.asks?.[0]?.[0] || null;

                    // === 成交模擬 (最優先檢查) ===
                    // 買單成交：市場 best_bid 跌破我的買單價 (價格穿越)
                    if (this.bidOrder && bestBid && bestBid < this.bidOrder.price) {
                        const fillPrice = this.bidOrder.price;
                        const distBps = (midPrice - fillPrice) / midPrice * 10000;
                        this.simulateFill('bid', fillPrice, midPrice, '價格穿越 (best_bid=$' + bestBid.toFixed(2) + ' < 訂單$' + fillPrice.toFixed(2) + ')');
                        bidStatus = 'filled';
                        this.bidOrder = null;
                    }
                    // 賣單成交：市場 best_ask 漲破我的賣單價 (價格穿越)
                    if (this.askOrder && bestAsk && bestAsk > this.askOrder.price) {
                        const fillPrice = this.askOrder.price;
                        const distBps = (fillPrice - midPrice) / midPrice * 10000;
                        this.simulateFill('ask', fillPrice, midPrice, '價格穿越 (best_ask=$' + bestAsk.toFixed(2) + ' > 訂單$' + fillPrice.toFixed(2) + ')');
                        askStatus = 'filled';
                        this.askOrder = null;
                    }

                    // 處理買單 (未成交的情況)
                    if (this.bidOrder) {
                        const distBps = (midPrice - this.bidOrder.price) / midPrice * 10000;
                        const queuePos = this.getQueuePosition('bid', this.bidOrder.price, ob);
                        const extra = { queuePos, bestBid, bestAsk };

                        // 檢查隊列位置風控
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

                    // 處理賣單 (未成交的情況)
                    if (this.askOrder) {
                        const distBps = (this.askOrder.price - midPrice) / midPrice * 10000;
                        const queuePos = this.getQueuePosition('ask', this.askOrder.price, ob);
                        const extra = { queuePos, bestBid, bestAsk };

                        // 檢查隊列位置風控
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
                        const reason = (bidStatus === 'cancel' || bidStatus === 'queue_cancel') ? '撤單後重掛' :
                                       (bidStatus === 'rebalance' ? '重平衡重掛' :
                                       (bidStatus === 'filled' ? '成交後重掛' : '初始下單'));
                        this.placeOrder('bid', midPrice, reason, ob);
                        if (this.orderDistanceBps <= this.uptimeMaxDistanceBps) {
                            bidStatus = bidStatus === 'filled' ? 'filled' : 'qualified';
                        }
                    }
                    if (!this.askOrder) {
                        const reason = (askStatus === 'cancel' || askStatus === 'queue_cancel') ? '撤單後重掛' :
                                       (askStatus === 'rebalance' ? '重平衡重掛' :
                                       (askStatus === 'filled' ? '成交後重掛' : '初始下單'));
                        this.placeOrder('ask', midPrice, reason, ob);
                        if (this.orderDistanceBps <= this.uptimeMaxDistanceBps) {
                            askStatus = askStatus === 'filled' ? 'filled' : 'qualified';
                        }
                    }

                    // === 分層時間統計 ===
                    // 計算當前雙邊訂單的距離
                    const bidDistBps = this.bidOrder ? (midPrice - this.bidOrder.price) / midPrice * 10000 : 999;
                    const askDistBps = this.askOrder ? (this.askOrder.price - midPrice) / midPrice * 10000 : 999;
                    const maxDistBps = Math.max(bidDistBps, askDistBps);

                    // StandX 分層: 0-10 bps = 100% (boosted), 10-30 bps = 50% (standard), 30-100 bps = 10% (basic)
                    if (this.bidOrder && this.askOrder && maxDistBps <= 10) {
                        this.boostedTimeMs += deltaMs;
                        this.qualifiedTimeMs += deltaMs;  // 舊版相容
                    } else if (this.bidOrder && this.askOrder && maxDistBps <= 30) {
                        this.standardTimeMs += deltaMs;
                        this.qualifiedTimeMs += deltaMs;  // 舊版相容
                    } else if (this.bidOrder && this.askOrder && maxDistBps <= 100) {
                        this.basicTimeMs += deltaMs;
                    } else {
                        this.outOfRangeTimeMs += deltaMs;
                    }

                    return { bidStatus, askStatus, bidDistBps, askDistBps };
                },

                // 模擬成交
                simulateFill(side, fillPrice, midPrice, reason) {
                    const now = new Date();
                    const timeStr = now.toLocaleTimeString('zh-TW', { hour12: false });
                    const fill = {
                        time: timeStr,
                        side,
                        price: fillPrice,
                        midPrice,
                        reason,
                        pnlBps: side === 'bid' ? (midPrice - fillPrice) / midPrice * 10000 : (fillPrice - midPrice) / midPrice * 10000
                    };
                    this.fills.unshift(fill);
                    if (this.fills.length > 50) this.fills.pop();
                    this.fillCount++;
                    // 假設 0.001 BTC 訂單大小
                    const orderSizeBtc = 0.001;
                    this.simulatedPnlUsd += fill.pnlBps / 10000 * fillPrice * orderSizeBtc;
                    this.addHistory('fill', side, null, fillPrice, midPrice, fill.pnlBps.toFixed(2), reason, {});
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
                    // 分層時間
                    this.boostedTimeMs = 0;
                    this.standardTimeMs = 0;
                    this.basicTimeMs = 0;
                    this.outOfRangeTimeMs = 0;
                    // 成交統計
                    this.fillCount = 0;
                    this.fills = [];
                    this.simulatedPnlUsd = 0;
                    // 訂單操作統計
                    this.bidCancels = 0;
                    this.askCancels = 0;
                    this.bidRebalances = 0;
                    this.askRebalances = 0;
                    this.bidQueueCancels = 0;
                    this.askQueueCancels = 0;
                    this.history = [];
                },

                // 獲取 Uptime 百分比 (舊版相容)
                getUptimePct() {
                    return this.totalTimeMs > 0 ? (this.qualifiedTimeMs / this.totalTimeMs * 100) : 0;
                },

                // 獲取各層時間百分比
                getTierPcts() {
                    const total = this.totalTimeMs || 1;
                    return {
                        boosted: this.boostedTimeMs / total * 100,
                        standard: this.standardTimeMs / total * 100,
                        basic: this.basicTimeMs / total * 100,
                        outOfRange: this.outOfRangeTimeMs / total * 100
                    };
                },

                // 獲取有效積分百分比 (StandX 加權計算)
                getEffectivePointsPct() {
                    const total = this.totalTimeMs || 1;
                    // 100% * boosted + 50% * standard + 10% * basic
                    return (this.boostedTimeMs * 1.0 + this.standardTimeMs * 0.5 + this.basicTimeMs * 0.1) / total * 100;
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
                    if (config.volatility) {
                        this.volatilityWindowSec = config.volatility.window_sec;
                        this.volatilityThresholdBps = config.volatility.threshold_bps;
                    }
                    console.log('mmSim config loaded:', {
                        orderDistanceBps: this.orderDistanceBps,
                        cancelDistanceBps: this.cancelDistanceBps,
                        rebalanceDistanceBps: this.rebalanceDistanceBps,
                        queuePositionLimit: this.queuePositionLimit,
                        uptimeMaxDistanceBps: this.uptimeMaxDistanceBps,
                        volatilityWindowSec: this.volatilityWindowSec,
                        volatilityThresholdBps: this.volatilityThresholdBps
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

                // 有效積分 (加權計算)
                const effectivePts = mmSim.getEffectivePointsPct();
                document.getElementById('mmQualifiedRate').textContent = effectivePts.toFixed(1) + '%';

                // 成交統計
                document.getElementById('mmFillCount').textContent = mmSim.fillCount;
                const pnlStr = mmSim.simulatedPnlUsd >= 0
                    ? '+$' + mmSim.simulatedPnlUsd.toFixed(2)
                    : '-$' + Math.abs(mmSim.simulatedPnlUsd).toFixed(2);
                document.getElementById('mmSimPnl').textContent = pnlStr;
                document.getElementById('mmSimPnl').style.color = mmSim.simulatedPnlUsd >= 0 ? '#10b981' : '#ef4444';

                // 分層時間百分比
                const tierPcts = mmSim.getTierPcts();
                document.getElementById('mmTierBoosted').style.width = tierPcts.boosted + '%';
                document.getElementById('mmTierStandard').style.width = tierPcts.standard + '%';
                document.getElementById('mmTierBasic').style.width = tierPcts.basic + '%';
                document.getElementById('mmTierOut').style.width = tierPcts.outOfRange + '%';
                document.getElementById('mmTierBoostedPct').textContent = tierPcts.boosted.toFixed(1) + '%';
                document.getElementById('mmTierStandardPct').textContent = tierPcts.standard.toFixed(1) + '%';
                document.getElementById('mmTierBasicPct').textContent = tierPcts.basic.toFixed(1) + '%';
                document.getElementById('mmTierOutPct').textContent = tierPcts.outOfRange.toFixed(1) + '%';

                // 撤單次數和重掛次數
                document.getElementById('mmBidFillRate').textContent = mmSim.bidCancels + '/' + mmSim.bidQueueCancels + '/' + mmSim.bidRebalances;
                document.getElementById('mmAskFillRate').textContent = mmSim.askCancels + '/' + mmSim.askQueueCancels + '/' + mmSim.askRebalances;

                // 波動率顯示
                const volBps = mmSim.currentVolatilityBps;
                const isVolHigh = mmSim.shouldPauseForVolatility();
                document.getElementById('mmVolatility').textContent = isFinite(volBps) ? volBps.toFixed(1) : '-';
                document.getElementById('mmVolatilityStatus').textContent = isVolHigh ? '暫停' : '正常';
                document.getElementById('mmVolatilityStatus').style.color = isVolHigh ? '#ef4444' : '#10b981';
                document.getElementById('mmVolatility').style.color = isVolHigh ? '#ef4444' : '#f8fafc';
                document.getElementById('mmVolatilityPauseCount').textContent = mmSim.volatilityPauseCount;

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
                    // 切換 DEX 字段顯示
                    const standxFields = document.getElementById('standxFields');
                    const grvtFields = document.getElementById('grvtFields');
                    if (standxFields && grvtFields) {
                        if (name === 'grvt') {
                            standxFields.style.display = 'none';
                            grvtFields.style.display = 'block';
                        } else {
                            standxFields.style.display = 'block';
                            grvtFields.style.display = 'none';
                        }
                    }
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
                } else if (name === 'grvt') {
                    // GRVT 使用 API Key/Secret
                    config.api_key = document.getElementById('grvtApiKey').value;
                    config.api_secret = document.getElementById('grvtApiSecret').value;
                } else {
                    // StandX 使用 Private Key
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

    return html_head + html_body


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


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8888, log_level="info")
