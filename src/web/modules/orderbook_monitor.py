"""
StandX 訂單簿監控模組

純數據監控 - 只負責顯示訂單簿數據，不包含策略分析或交易執行
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse, HTMLResponse

router = APIRouter(prefix="/api/mm", tags=["market_maker"])

# 模組配置
MODULE_CONFIG = {
    'name': 'StandX 訂單簿監控',
    'id': 'orderbook-monitor',
    'exchange': 'standx',
    'symbol': 'BTC-USD',
    'enabled': True
}


def get_html() -> str:
    """返回訂單簿監控模組的 HTML"""
    return """
    <!-- StandX 訂單簿監控模組 -->
    <div class="section" id="orderbookMonitorSection">
        <h2>📊 StandX BTC-USD 訂單簿</h2>
        <p style="color: #9ca3af; margin-bottom: 15px;">實時訂單簿深度監控</p>

        <div class="stats-grid" style="margin-bottom: 20px;">
            <div class="card">
                <h3 style="color: #10b981; margin-bottom: 10px;">📈 市場概況</h3>
                <div class="stat">
                    <span class="stat-label">最佳買價 (Bid)</span>
                    <span class="stat-value" id="mmBestBid" style="color: #10b981;">-</span>
                </div>
                <div class="stat">
                    <span class="stat-label">最佳賣價 (Ask)</span>
                    <span class="stat-value" id="mmBestAsk" style="color: #ef4444;">-</span>
                </div>
                <div class="stat">
                    <span class="stat-label">價差 (Spread)</span>
                    <span class="stat-value" id="mmSpread">-</span>
                </div>
                <div class="stat">
                    <span class="stat-label">價差比例</span>
                    <span class="stat-value" id="mmSpreadPct">-</span>
                </div>
                <div class="stat">
                    <span class="stat-label">中間價</span>
                    <span class="stat-value" id="mmMidPrice">-</span>
                </div>
            </div>

            <div class="card">
                <h3 style="color: #f59e0b; margin-bottom: 10px;">⚖️ 訂單簿平衡</h3>
                <div class="stat">
                    <span class="stat-label">買單總量</span>
                    <span class="stat-value" id="mmBidVolume" style="color: #10b981;">-</span>
                </div>
                <div class="stat">
                    <span class="stat-label">賣單總量</span>
                    <span class="stat-value" id="mmAskVolume" style="color: #ef4444;">-</span>
                </div>
                <div class="stat">
                    <span class="stat-label">買賣比例</span>
                    <span class="stat-value" id="mmImbalance">-</span>
                </div>
                <div class="stat">
                    <span class="stat-label">市場傾向</span>
                    <span class="stat-value" id="mmBias">-</span>
                </div>
            </div>
        </div>

        <!-- 訂單簿視覺化 -->
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
            <!-- 買單 (Bids) -->
            <div class="card">
                <h3 style="color: #10b981; margin-bottom: 15px;">🟢 買單 (Bids)</h3>
                <table style="width: 100%; font-size: 13px;">
                    <thead>
                        <tr style="color: #9ca3af;">
                            <th style="text-align: left; padding: 8px;">價格</th>
                            <th style="text-align: right; padding: 8px;">數量</th>
                            <th style="text-align: right; padding: 8px;">總價值</th>
                            <th style="text-align: right; padding: 8px;">累計</th>
                        </tr>
                    </thead>
                    <tbody id="mmBidsTable">
                        <tr><td colspan="4" style="text-align: center; color: #9ca3af; padding: 20px;">載入中...</td></tr>
                    </tbody>
                </table>
            </div>

            <!-- 賣單 (Asks) -->
            <div class="card">
                <h3 style="color: #ef4444; margin-bottom: 15px;">🔴 賣單 (Asks)</h3>
                <table style="width: 100%; font-size: 13px;">
                    <thead>
                        <tr style="color: #9ca3af;">
                            <th style="text-align: left; padding: 8px;">價格</th>
                            <th style="text-align: right; padding: 8px;">數量</th>
                            <th style="text-align: right; padding: 8px;">總價值</th>
                            <th style="text-align: right; padding: 8px;">累計</th>
                        </tr>
                    </thead>
                    <tbody id="mmAsksTable">
                        <tr><td colspan="4" style="text-align: center; color: #9ca3af; padding: 20px;">載入中...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- 深度圖 -->
        <div class="card" style="margin-top: 20px;">
            <h3 style="margin-bottom: 15px;">📉 深度分佈</h3>
            <div id="depthChart" style="height: 60px; display: flex; align-items: center;">
                <div id="bidDepthBar" style="height: 30px; background: linear-gradient(to right, #065f46, #10b981); border-radius: 4px 0 0 4px; transition: width 0.3s;"></div>
                <div style="width: 2px; height: 40px; background: #fff; margin: 0 2px;"></div>
                <div id="askDepthBar" style="height: 30px; background: linear-gradient(to left, #991b1b, #ef4444); border-radius: 0 4px 4px 0; transition: width 0.3s;"></div>
            </div>
            <div style="display: flex; justify-content: space-between; margin-top: 10px; font-size: 12px; color: #9ca3af;">
                <span>買單深度: <span id="bidDepthPct">50%</span></span>
                <span>賣單深度: <span id="askDepthPct">50%</span></span>
            </div>
        </div>
    </div>
    """


def get_javascript() -> str:
    """返回訂單簿監控模組的 JavaScript"""
    return """// ==================== 訂單簿監控模組 JavaScript ====================
const OrderbookMonitor = {
    exchange: 'standx',
    symbol: 'BTC-USD',
    updateInterval: null,

    init: function() {
        console.log('OrderbookMonitor.init() called');
        this.loadOrderbook();
        this.updateInterval = setInterval(() => this.loadOrderbook(), 1000);
    },

    destroy: function() {
        if (this.updateInterval) {
            clearInterval(this.updateInterval);
            this.updateInterval = null;
        }
    },

    loadOrderbook: async function() {
        try {
            const response = await fetch('/api/mm/orderbook/' + this.exchange + '/' + this.symbol);
            if (!response.ok) return;
            const data = await response.json();
            if (data.error) return;
            this.updateUI(data);
        } catch (error) {
            console.log('OrderbookMonitor: Failed to load orderbook:', error);
        }
    },

    updateUI: function(data) {
        const stats = data.stats;

        // 更新市場概況
        const setBestBid = document.getElementById('mmBestBid');
        const setBestAsk = document.getElementById('mmBestAsk');
        if (setBestBid) setBestBid.textContent = '$' + stats.best_bid.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
        if (setBestAsk) setBestAsk.textContent = '$' + stats.best_ask.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});

        const setSpread = document.getElementById('mmSpread');
        const setSpreadPct = document.getElementById('mmSpreadPct');
        const setMidPrice = document.getElementById('mmMidPrice');
        if (setSpread) setSpread.textContent = '$' + stats.spread.toFixed(2);
        if (setSpreadPct) setSpreadPct.textContent = stats.spread_pct.toFixed(4) + '%';
        if (setMidPrice) setMidPrice.textContent = '$' + stats.mid_price.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});

        // 更新訂單簿平衡
        const setBidVol = document.getElementById('mmBidVolume');
        const setAskVol = document.getElementById('mmAskVolume');
        const setImbalance = document.getElementById('mmImbalance');
        const setBias = document.getElementById('mmBias');
        if (setBidVol) setBidVol.textContent = stats.bid_volume.toFixed(4) + ' BTC';
        if (setAskVol) setAskVol.textContent = stats.ask_volume.toFixed(4) + ' BTC';
        if (setImbalance) setImbalance.textContent = stats.imbalance.toFixed(2) + 'x';
        if (setBias) setBias.textContent = stats.bias;

        // 更新深度圖
        const bidPct = stats.bid_depth_pct;
        const askPct = stats.ask_depth_pct;
        const bidBar = document.getElementById('bidDepthBar');
        const askBar = document.getElementById('askDepthBar');
        const bidPctLabel = document.getElementById('bidDepthPct');
        const askPctLabel = document.getElementById('askDepthPct');
        if (bidBar) bidBar.style.width = bidPct + '%';
        if (askBar) askBar.style.width = askPct + '%';
        if (bidPctLabel) bidPctLabel.textContent = bidPct.toFixed(1) + '%';
        if (askPctLabel) askPctLabel.textContent = askPct.toFixed(1) + '%';

        // 更新訂單表格
        this.updateOrderTable('mmBidsTable', data.bids, '#10b981', true);
        this.updateOrderTable('mmAsksTable', data.asks, '#ef4444', false);
    },

    updateOrderTable: function(tableId, orders, color, isBid) {
        const tbody = document.getElementById(tableId);
        if (!tbody) return;

        if (!orders || orders.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: #9ca3af; padding: 20px;">無數據</td></tr>';
            return;
        }

        let cumulative = 0;
        const maxCumulative = orders.reduce((sum, o) => sum + o[1], 0);

        tbody.innerHTML = orders.slice(0, 10).map((order, idx) => {
            const price = order[0];
            const qty = order[1];
            const value = price * qty;
            cumulative += qty;
            const pct = (cumulative / maxCumulative * 100).toFixed(0);

            const bgOpacity = (0.1 + (idx / 10) * 0.2).toFixed(2);
            const bgColor = isBid ? 'rgba(16, 185, 129, ' + bgOpacity + ')' : 'rgba(239, 68, 68, ' + bgOpacity + ')';

            return '<tr style="background: linear-gradient(to ' + (isBid ? 'left' : 'right') + ', ' + bgColor + ' ' + pct + '%, transparent ' + pct + '%);">' +
                '<td style="padding: 6px 8px; color: ' + color + '; font-family: monospace;">$' + price.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2}) + '</td>' +
                '<td style="padding: 6px 8px; text-align: right; font-family: monospace;">' + qty.toFixed(4) + '</td>' +
                '<td style="padding: 6px 8px; text-align: right; font-family: monospace; color: #9ca3af;">$' + value.toLocaleString(undefined, {minimumFractionDigits: 0, maximumFractionDigits: 0}) + '</td>' +
                '<td style="padding: 6px 8px; text-align: right; font-family: monospace; color: #6b7280;">' + cumulative.toFixed(4) + '</td>' +
                '</tr>';
        }).join('');
    }
};
"""


def register_routes(app, adapters_getter):
    """
    註冊做市商模組的 API 路由

    Args:
        app: FastAPI 應用
        adapters_getter: 獲取 adapters 字典的函數
    """

    @router.get("/orderbook/{exchange}/{symbol}")
    async def get_orderbook(exchange: str, symbol: str):
        """獲取指定交易所和交易對的詳細訂單簿"""
        try:
            adapters = adapters_getter()
            exchange_upper = exchange.upper()

            if exchange_upper not in adapters:
                return JSONResponse({'error': f'Exchange {exchange} not found'}, status_code=404)

            adapter = adapters[exchange_upper]
            orderbook = await adapter.get_orderbook(symbol, depth=20)

            # 計算統計數據
            bids = [[float(p), float(q)] for p, q in orderbook.bids[:20]]
            asks = [[float(p), float(q)] for p, q in orderbook.asks[:20]]

            best_bid = bids[0][0] if bids else 0
            best_ask = asks[0][0] if asks else 0
            spread = best_ask - best_bid if best_bid and best_ask else 0
            spread_pct = (spread / best_bid * 100) if best_bid else 0
            mid_price = (best_bid + best_ask) / 2 if best_bid and best_ask else 0

            # 計算總量
            bid_volume = sum(q for p, q in bids)
            ask_volume = sum(q for p, q in asks)
            total_volume = bid_volume + ask_volume

            # 買賣比例和市場傾向
            imbalance = bid_volume / ask_volume if ask_volume > 0 else 0
            if imbalance > 1.2:
                bias = "買方主導 📈"
            elif imbalance < 0.8:
                bias = "賣方主導 📉"
            else:
                bias = "平衡 ⚖️"

            return JSONResponse({
                'exchange': exchange_upper,
                'symbol': symbol,
                'timestamp': orderbook.timestamp.isoformat(),
                'bids': bids,
                'asks': asks,
                'stats': {
                    'best_bid': best_bid,
                    'best_ask': best_ask,
                    'spread': spread,
                    'spread_pct': spread_pct,
                    'mid_price': mid_price,
                    'bid_volume': bid_volume,
                    'ask_volume': ask_volume,
                    'imbalance': imbalance,
                    'bias': bias,
                    'bid_depth_pct': (bid_volume / total_volume * 100) if total_volume > 0 else 50,
                    'ask_depth_pct': (ask_volume / total_volume * 100) if total_volume > 0 else 50
                }
            })
        except Exception as e:
            return JSONResponse({'error': str(e)}, status_code=500)

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
