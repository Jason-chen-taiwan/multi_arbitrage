"""
StandX 做市策略分析模組

負責策略分析和模擬統計，不執行實際交易：
- Uptime Program 資格分析
- 建議報價計算
- 模擬下單統計（成交率、被吃單率等）
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse, HTMLResponse
from decimal import Decimal
from datetime import datetime
from collections import deque
from dataclasses import dataclass, field
from typing import List, Dict, Optional
import time

router = APIRouter(prefix="/api/strategy", tags=["strategy_analyzer"])

# 模組配置
MODULE_CONFIG = {
    'name': 'StandX 策略分析',
    'id': 'strategy-analyzer',
    'exchange': 'standx',
    'symbol': 'BTC-USD',
    'enabled': True
}

# Uptime Program 常量
UPTIME_MAX_SPREAD_BPS = 10  # 10 bps 最大價差要求
UPTIME_ORDER_SIZE_CAP = 2.0  # BTC-USD 最大 2 BTC
MM1_HOURS_TARGET = 360  # MM1 目標時數/月
MM2_HOURS_TARGET = 504  # MM2 目標時數/月


@dataclass
class SimulatedQuote:
    """模擬報價"""
    bid_price: float
    ask_price: float
    bid_size: float
    ask_size: float
    timestamp: float
    spread_bps: float
    within_uptime_requirement: bool


@dataclass
class SimulationStats:
    """模擬統計數據"""
    # 報價統計
    total_quotes: int = 0
    quotes_within_spread: int = 0  # 符合 10 bps 要求的報價數

    # 模擬成交統計
    bid_would_fill: int = 0  # 買單會被成交的次數
    ask_would_fill: int = 0  # 賣單會被成交的次數
    bid_partial_fill: int = 0  # 買單部分成交
    ask_partial_fill: int = 0  # 賣單部分成交

    # Uptime 統計
    uptime_qualified_seconds: float = 0
    total_seconds: float = 0

    # 歷史數據
    recent_spreads: deque = field(default_factory=lambda: deque(maxlen=100))
    recent_imbalances: deque = field(default_factory=lambda: deque(maxlen=100))

    def uptime_pct(self) -> float:
        if self.total_seconds == 0:
            return 0
        return (self.uptime_qualified_seconds / self.total_seconds) * 100

    def bid_fill_rate(self) -> float:
        if self.total_quotes == 0:
            return 0
        return (self.bid_would_fill / self.total_quotes) * 100

    def ask_fill_rate(self) -> float:
        if self.total_quotes == 0:
            return 0
        return (self.ask_would_fill / self.total_quotes) * 100


# 全局統計實例
simulation_stats = SimulationStats()
last_quote: Optional[SimulatedQuote] = None
analysis_start_time = time.time()


def calculate_suggested_quotes(mid_price: float, spread_buffer_bps: float = 2) -> Dict:
    """
    計算建議報價（符合 Uptime Program 要求）

    Args:
        mid_price: 中間價
        spread_buffer_bps: 價差緩衝（預留空間避免超出 10 bps）

    Returns:
        建議的 bid/ask 價格和相關信息
    """
    # 安全價差 = 10 bps - 緩衝
    safe_spread_bps = UPTIME_MAX_SPREAD_BPS - spread_buffer_bps
    half_spread = (safe_spread_bps / 10000) / 2

    suggested_bid = mid_price * (1 - half_spread)
    suggested_ask = mid_price * (1 + half_spread)

    return {
        'mid_price': mid_price,
        'suggested_bid': suggested_bid,
        'suggested_ask': suggested_ask,
        'spread': suggested_ask - suggested_bid,
        'spread_bps': safe_spread_bps,
        'order_size_cap': UPTIME_ORDER_SIZE_CAP,
        'within_uptime_requirement': True
    }


def analyze_fill_probability(
    suggested_bid: float,
    suggested_ask: float,
    orderbook_bids: List[List[float]],
    orderbook_asks: List[List[float]]
) -> Dict:
    """
    分析報價被成交的概率

    檢查我們的報價是否會被市場訂單吃掉
    """
    result = {
        'bid_would_fill': False,
        'ask_would_fill': False,
        'bid_fill_type': 'none',  # none, partial, full
        'ask_fill_type': 'none',
        'bid_risk_level': 'low',  # low, medium, high
        'ask_risk_level': 'low',
    }

    if not orderbook_bids or not orderbook_asks:
        return result

    best_bid = orderbook_bids[0][0]
    best_ask = orderbook_asks[0][0]

    # 檢查買單是否會被成交
    # 如果我們的買價 >= 市場最佳賣價，會立即成交
    if suggested_bid >= best_ask:
        result['bid_would_fill'] = True
        result['bid_fill_type'] = 'full'
        result['bid_risk_level'] = 'high'
    elif suggested_bid >= best_ask * 0.9999:  # 非常接近
        result['bid_risk_level'] = 'medium'

    # 檢查賣單是否會被成交
    # 如果我們的賣價 <= 市場最佳買價，會立即成交
    if suggested_ask <= best_bid:
        result['ask_would_fill'] = True
        result['ask_fill_type'] = 'full'
        result['ask_risk_level'] = 'high'
    elif suggested_ask <= best_bid * 1.0001:  # 非常接近
        result['ask_risk_level'] = 'medium'

    # 計算與最佳價的距離
    result['bid_distance_from_best_ask'] = (best_ask - suggested_bid) / best_ask * 10000  # bps
    result['ask_distance_from_best_bid'] = (suggested_ask - best_bid) / best_bid * 10000  # bps

    return result


def calculate_maker_hours(order_size: float, uptime_pct: float) -> Dict:
    """
    計算預估 Maker Hours

    Maker Hours = (X / 2) × Multiplier
    X = 70th percentile order size
    Multiplier: 1.0x (≥70% uptime) or 0.5x (≥50% uptime)
    """
    if uptime_pct >= 70:
        multiplier = 1.0
        tier = 'Boosted'
    elif uptime_pct >= 50:
        multiplier = 0.5
        tier = 'Standard'
    else:
        multiplier = 0
        tier = 'Inactive'

    # 假設我們的訂單是 70th percentile
    maker_hours_per_hour = (order_size / 2) * multiplier
    maker_hours_per_day = maker_hours_per_hour * 24
    maker_hours_per_month = maker_hours_per_day * 30

    return {
        'tier': tier,
        'multiplier': multiplier,
        'maker_hours_per_hour': maker_hours_per_hour,
        'maker_hours_per_day': maker_hours_per_day,
        'maker_hours_per_month': maker_hours_per_month,
        'mm1_progress': (maker_hours_per_month / MM1_HOURS_TARGET) * 100,
        'mm2_progress': (maker_hours_per_month / MM2_HOURS_TARGET) * 100
    }


def get_html() -> str:
    """返回策略分析模組的 HTML"""
    return """
    <!-- StandX 策略分析模組 -->
    <div class="section" id="strategyAnalyzerSection">
        <h2>🎯 StandX 做市策略分析</h2>
        <p style="color: #9ca3af; margin-bottom: 15px;">Uptime Program 資格分析與模擬統計</p>

        <div class="stats-grid" style="margin-bottom: 20px;">
            <!-- Uptime Program 狀態 -->
            <div class="card">
                <h3 style="color: #8b5cf6; margin-bottom: 10px;">🏆 Uptime Program</h3>
                <div class="stat">
                    <span class="stat-label">當前 Uptime</span>
                    <span class="stat-value" id="saUptime" style="color: #10b981;">-</span>
                </div>
                <div class="stat">
                    <span class="stat-label">目標等級</span>
                    <span class="stat-value" id="saTier">-</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Maker Hours/月</span>
                    <span class="stat-value" id="saMakerHours">-</span>
                </div>
                <div class="stat">
                    <span class="stat-label">MM2 進度</span>
                    <span class="stat-value" id="saMM2Progress">-</span>
                </div>
            </div>

            <!-- 建議報價 -->
            <div class="card">
                <h3 style="color: #06b6d4; margin-bottom: 10px;">💡 建議報價</h3>
                <div class="stat">
                    <span class="stat-label">建議買價</span>
                    <span class="stat-value" id="saSuggestedBid" style="color: #10b981;">-</span>
                </div>
                <div class="stat">
                    <span class="stat-label">建議賣價</span>
                    <span class="stat-value" id="saSuggestedAsk" style="color: #ef4444;">-</span>
                </div>
                <div class="stat">
                    <span class="stat-label">價差</span>
                    <span class="stat-value" id="saSuggestedSpread">-</span>
                </div>
                <div class="stat">
                    <span class="stat-label">符合 10bps</span>
                    <span class="stat-value" id="saWithinRequirement">-</span>
                </div>
            </div>
        </div>

        <!-- 模擬成交統計 -->
        <div class="card" style="margin-bottom: 20px;">
            <h3 style="color: #f59e0b; margin-bottom: 15px;">📊 模擬成交統計</h3>
            <p style="color: #6b7280; font-size: 12px; margin-bottom: 15px;">
                基於建議報價，統計如果真的下單會發生什麼
            </p>

            <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px;">
                <div style="text-align: center; padding: 15px; background: #1f2937; border-radius: 8px;">
                    <div style="font-size: 24px; font-weight: bold; color: #10b981;" id="saTotalQuotes">0</div>
                    <div style="font-size: 12px; color: #9ca3af;">總報價次數</div>
                </div>
                <div style="text-align: center; padding: 15px; background: #1f2937; border-radius: 8px;">
                    <div style="font-size: 24px; font-weight: bold; color: #8b5cf6;" id="saQualifiedRate">0%</div>
                    <div style="font-size: 12px; color: #9ca3af;">符合資格率</div>
                </div>
                <div style="text-align: center; padding: 15px; background: #1f2937; border-radius: 8px;">
                    <div style="font-size: 24px; font-weight: bold; color: #f59e0b;" id="saBidFillRate">0%</div>
                    <div style="font-size: 12px; color: #9ca3af;">買單成交率</div>
                </div>
                <div style="text-align: center; padding: 15px; background: #1f2937; border-radius: 8px;">
                    <div style="font-size: 24px; font-weight: bold; color: #ef4444;" id="saAskFillRate">0%</div>
                    <div style="font-size: 12px; color: #9ca3af;">賣單成交率</div>
                </div>
            </div>
        </div>

        <!-- 風險分析 -->
        <div class="card">
            <h3 style="color: #ef4444; margin-bottom: 15px;">⚠️ 即時風險分析</h3>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
                <div>
                    <div style="margin-bottom: 10px;">
                        <span style="color: #9ca3af;">買單風險:</span>
                        <span id="saBidRisk" style="margin-left: 10px; padding: 2px 8px; border-radius: 4px; font-size: 12px;">-</span>
                    </div>
                    <div style="font-size: 12px; color: #6b7280;">
                        距離最佳賣價: <span id="saBidDistance">-</span> bps
                    </div>
                </div>
                <div>
                    <div style="margin-bottom: 10px;">
                        <span style="color: #9ca3af;">賣單風險:</span>
                        <span id="saAskRisk" style="margin-left: 10px; padding: 2px 8px; border-radius: 4px; font-size: 12px;">-</span>
                    </div>
                    <div style="font-size: 12px; color: #6b7280;">
                        距離最佳買價: <span id="saAskDistance">-</span> bps
                    </div>
                </div>
            </div>
            <div style="margin-top: 15px; padding: 10px; background: #1f2937; border-radius: 8px; font-size: 12px;">
                <div style="color: #9ca3af; margin-bottom: 5px;">風險說明:</div>
                <div style="color: #6b7280;">
                    🟢 低風險: 報價安全，不會被立即吃單<br>
                    🟡 中風險: 報價接近市場價，可能被快速成交<br>
                    🔴 高風險: 報價會被立即成交（taker 而非 maker）
                </div>
            </div>
        </div>
    </div>
    """


def get_javascript() -> str:
    """返回策略分析模組的 JavaScript"""
    return """// ==================== 策略分析模組 JavaScript ====================
const StrategyAnalyzer = {
    exchange: 'standx',
    symbol: 'BTC-USD',
    updateInterval: null,

    init: function() {
        console.log('StrategyAnalyzer.init() called');
        this.loadAnalysis();
        this.updateInterval = setInterval(() => this.loadAnalysis(), 1000);
    },

    destroy: function() {
        if (this.updateInterval) {
            clearInterval(this.updateInterval);
            this.updateInterval = null;
        }
    },

    loadAnalysis: async function() {
        try {
            const response = await fetch('/api/strategy/analyze/' + this.exchange + '/' + this.symbol);
            if (!response.ok) return;
            const data = await response.json();
            if (data.error) return;
            this.updateUI(data);
        } catch (error) {
            console.log('StrategyAnalyzer: Failed to load analysis:', error);
        }
    },

    updateUI: function(data) {
        // Uptime Program 狀態
        const uptime = document.getElementById('saUptime');
        const tier = document.getElementById('saTier');
        const makerHours = document.getElementById('saMakerHours');
        const mm2Progress = document.getElementById('saMM2Progress');

        if (uptime) {
            const uptimePct = data.uptime.uptime_pct;
            uptime.textContent = uptimePct.toFixed(1) + '%';
            uptime.style.color = uptimePct >= 70 ? '#10b981' : (uptimePct >= 50 ? '#f59e0b' : '#ef4444');
        }
        if (tier) {
            const tierName = data.maker_hours.tier;
            tier.textContent = tierName;
            tier.style.color = tierName === 'Boosted' ? '#10b981' : (tierName === 'Standard' ? '#f59e0b' : '#6b7280');
        }
        if (makerHours) makerHours.textContent = data.maker_hours.maker_hours_per_month.toFixed(1);
        if (mm2Progress) {
            const progress = data.maker_hours.mm2_progress;
            mm2Progress.textContent = progress.toFixed(1) + '%';
            mm2Progress.style.color = progress >= 100 ? '#10b981' : '#f59e0b';
        }

        // 建議報價
        const suggestedBid = document.getElementById('saSuggestedBid');
        const suggestedAsk = document.getElementById('saSuggestedAsk');
        const suggestedSpread = document.getElementById('saSuggestedSpread');
        const withinReq = document.getElementById('saWithinRequirement');

        if (suggestedBid) suggestedBid.textContent = '$' + data.suggested_quotes.suggested_bid.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
        if (suggestedAsk) suggestedAsk.textContent = '$' + data.suggested_quotes.suggested_ask.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
        if (suggestedSpread) suggestedSpread.textContent = data.suggested_quotes.spread_bps.toFixed(1) + ' bps';
        if (withinReq) {
            withinReq.textContent = data.suggested_quotes.within_uptime_requirement ? '✅ 是' : '❌ 否';
            withinReq.style.color = data.suggested_quotes.within_uptime_requirement ? '#10b981' : '#ef4444';
        }

        // 模擬成交統計
        const totalQuotes = document.getElementById('saTotalQuotes');
        const qualifiedRate = document.getElementById('saQualifiedRate');
        const bidFillRate = document.getElementById('saBidFillRate');
        const askFillRate = document.getElementById('saAskFillRate');

        if (totalQuotes) totalQuotes.textContent = data.simulation_stats.total_quotes;
        if (qualifiedRate) qualifiedRate.textContent = data.simulation_stats.qualified_rate.toFixed(1) + '%';
        if (bidFillRate) bidFillRate.textContent = data.simulation_stats.bid_fill_rate.toFixed(1) + '%';
        if (askFillRate) askFillRate.textContent = data.simulation_stats.ask_fill_rate.toFixed(1) + '%';

        // 風險分析
        const bidRisk = document.getElementById('saBidRisk');
        const askRisk = document.getElementById('saAskRisk');
        const bidDistance = document.getElementById('saBidDistance');
        const askDistance = document.getElementById('saAskDistance');

        if (bidRisk) {
            const risk = data.fill_analysis.bid_risk_level;
            bidRisk.textContent = risk === 'high' ? '🔴 高' : (risk === 'medium' ? '🟡 中' : '🟢 低');
            bidRisk.style.background = risk === 'high' ? '#7f1d1d' : (risk === 'medium' ? '#78350f' : '#14532d');
        }
        if (askRisk) {
            const risk = data.fill_analysis.ask_risk_level;
            askRisk.textContent = risk === 'high' ? '🔴 高' : (risk === 'medium' ? '🟡 中' : '🟢 低');
            askRisk.style.background = risk === 'high' ? '#7f1d1d' : (risk === 'medium' ? '#78350f' : '#14532d');
        }
        if (bidDistance) bidDistance.textContent = data.fill_analysis.bid_distance_from_best_ask ? data.fill_analysis.bid_distance_from_best_ask.toFixed(2) : '-';
        if (askDistance) askDistance.textContent = data.fill_analysis.ask_distance_from_best_bid ? data.fill_analysis.ask_distance_from_best_bid.toFixed(2) : '-';
    }
};
"""


def register_routes(app, adapters_getter):
    """
    註冊策略分析模組的 API 路由
    """
    global simulation_stats, last_quote, analysis_start_time

    @router.get("/analyze/{exchange}/{symbol}")
    async def analyze_strategy(exchange: str, symbol: str):
        """策略分析主端點"""
        global simulation_stats, last_quote

        try:
            adapters = adapters_getter()
            exchange_upper = exchange.upper()

            if exchange_upper not in adapters:
                return JSONResponse({'error': f'Exchange {exchange} not found'}, status_code=404)

            adapter = adapters[exchange_upper]
            orderbook = await adapter.get_orderbook(symbol, depth=20)

            # 計算訂單簿數據
            bids = [[float(p), float(q)] for p, q in orderbook.bids[:20]]
            asks = [[float(p), float(q)] for p, q in orderbook.asks[:20]]

            if not bids or not asks:
                return JSONResponse({'error': 'No orderbook data'}, status_code=400)

            best_bid = bids[0][0]
            best_ask = asks[0][0]
            mid_price = (best_bid + best_ask) / 2
            current_spread_bps = (best_ask - best_bid) / mid_price * 10000

            # 計算建議報價
            suggested = calculate_suggested_quotes(mid_price)

            # 分析成交概率
            fill_analysis = analyze_fill_probability(
                suggested['suggested_bid'],
                suggested['suggested_ask'],
                bids,
                asks
            )

            # 更新模擬統計
            current_time = time.time()
            simulation_stats.total_quotes += 1

            # 檢查是否符合 Uptime 要求
            if current_spread_bps <= UPTIME_MAX_SPREAD_BPS:
                simulation_stats.quotes_within_spread += 1
                simulation_stats.uptime_qualified_seconds += 1
            simulation_stats.total_seconds = current_time - analysis_start_time

            # 更新成交統計
            if fill_analysis['bid_would_fill']:
                simulation_stats.bid_would_fill += 1
            if fill_analysis['ask_would_fill']:
                simulation_stats.ask_would_fill += 1

            # 記錄歷史數據
            simulation_stats.recent_spreads.append(current_spread_bps)

            bid_volume = sum(q for p, q in bids)
            ask_volume = sum(q for p, q in asks)
            imbalance = bid_volume / ask_volume if ask_volume > 0 else 1
            simulation_stats.recent_imbalances.append(imbalance)

            # 計算 Maker Hours
            uptime_pct = simulation_stats.uptime_pct()
            maker_hours = calculate_maker_hours(UPTIME_ORDER_SIZE_CAP, uptime_pct)

            return JSONResponse({
                'exchange': exchange_upper,
                'symbol': symbol,
                'timestamp': datetime.now().isoformat(),
                'market': {
                    'best_bid': best_bid,
                    'best_ask': best_ask,
                    'mid_price': mid_price,
                    'current_spread_bps': current_spread_bps
                },
                'suggested_quotes': suggested,
                'fill_analysis': fill_analysis,
                'uptime': {
                    'uptime_pct': uptime_pct,
                    'qualified_seconds': simulation_stats.uptime_qualified_seconds,
                    'total_seconds': simulation_stats.total_seconds,
                    'max_spread_requirement': UPTIME_MAX_SPREAD_BPS
                },
                'maker_hours': maker_hours,
                'simulation_stats': {
                    'total_quotes': simulation_stats.total_quotes,
                    'quotes_within_spread': simulation_stats.quotes_within_spread,
                    'qualified_rate': (simulation_stats.quotes_within_spread / simulation_stats.total_quotes * 100) if simulation_stats.total_quotes > 0 else 0,
                    'bid_would_fill': simulation_stats.bid_would_fill,
                    'ask_would_fill': simulation_stats.ask_would_fill,
                    'bid_fill_rate': simulation_stats.bid_fill_rate(),
                    'ask_fill_rate': simulation_stats.ask_fill_rate(),
                    'avg_spread_bps': sum(simulation_stats.recent_spreads) / len(simulation_stats.recent_spreads) if simulation_stats.recent_spreads else 0,
                    'avg_imbalance': sum(simulation_stats.recent_imbalances) / len(simulation_stats.recent_imbalances) if simulation_stats.recent_imbalances else 1
                }
            })
        except Exception as e:
            import traceback
            traceback.print_exc()
            return JSONResponse({'error': str(e)}, status_code=500)

    @router.post("/reset")
    async def reset_stats():
        """重置統計數據"""
        global simulation_stats, analysis_start_time
        simulation_stats = SimulationStats()
        analysis_start_time = time.time()
        return JSONResponse({'success': True, 'message': 'Statistics reset'})

    @router.get("/config")
    async def get_config():
        """獲取模組配置"""
        return JSONResponse(MODULE_CONFIG)

    @router.get("/html")
    async def get_module_html():
        """獲取模組 HTML"""
        return HTMLResponse(get_html())

    @router.get("/js")
    async def get_module_js():
        """獲取模組 JavaScript"""
        return HTMLResponse(get_javascript(), media_type="application/javascript")

    app.include_router(router)
    return router
