"""
GRVT 做市商頁面 HTML
"""


def get_grvt_marketmaker_page() -> str:
    """返回 GRVT 做市商頁面 HTML"""
    return '''
            <!-- ==================== GRVT 做市商頁面 ==================== -->
            <div id="page-grvt-marketmaker" class="page">
                <div class="mm-grid">
                    <div class="mm-header-bar">
                        <div class="mm-title">GRVT 做市商</div>
                        <div class="mm-stats">
                            <div class="mm-stat">
                                <div class="mm-stat-value" id="grvtMmMidPrice">-</div>
                                <div class="mm-stat-label">BTC_USDT_Perp 中間價</div>
                            </div>
                            <div class="mm-stat">
                                <div class="mm-stat-value text-green" id="grvtMmSpread">-</div>
                                <div class="mm-stat-label">價差 (bps)</div>
                            </div>
                            <div class="mm-stat">
                                <div class="mm-stat-value" id="grvtMmRuntime">0m</div>
                                <div class="mm-stat-label">運行時間</div>
                            </div>
                        </div>
                        <div class="mm-controls" style="display: flex; gap: 10px; align-items: center;">
                            <span id="grvtMmStatusBadge" class="badge" style="background: #2a3347; padding: 6px 12px;">停止</span>
                            <button id="grvtMmStartBtn" class="btn btn-primary" onclick="startGrvtMM()">啟動</button>
                            <button id="grvtMmStopBtn" class="btn btn-danger" onclick="stopGrvtMM()" style="display:none;">停止</button>
                        </div>
                    </div>

                    <!-- 控制面板 -->
                    <div class="card" style="grid-column: 1 / -1;">
                        <div class="card-title">策略配置 <span id="grvtMmConfigStatus" style="font-size: 10px; color: #9ca3af; margin-left: 10px;"></span></div>
                        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 15px;">
                            <!-- 報價參數 -->
                            <div style="background: #0f1419; padding: 12px; border-radius: 6px;">
                                <div style="font-size: 11px; color: #6b7280; margin-bottom: 8px;">報價參數</div>
                                <div style="display: flex; flex-direction: column; gap: 8px;">
                                    <div style="display: flex; align-items: center; justify-content: space-between;">
                                        <label style="font-size: 11px; color: #9ca3af;">掛單距離</label>
                                        <div style="display: flex; align-items: center; gap: 4px;">
                                            <input type="number" id="grvtMmOrderDistance" value="8" step="1" min="1" max="20" style="width: 50px; padding: 4px; background: #1a1f2e; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                                            <span style="font-size: 10px; color: #6b7280;">bps</span>
                                        </div>
                                    </div>
                                    <div style="display: flex; align-items: center; justify-content: space-between;">
                                        <label style="font-size: 11px; color: #9ca3af;">撤單距離</label>
                                        <div style="display: flex; align-items: center; gap: 4px;">
                                            <input type="number" id="grvtMmCancelDistance" value="3" step="1" min="1" max="10" style="width: 50px; padding: 4px; background: #1a1f2e; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                                            <span style="font-size: 10px; color: #6b7280;">bps</span>
                                        </div>
                                    </div>
                                    <div style="display: flex; align-items: center; justify-content: space-between;">
                                        <label style="font-size: 11px; color: #9ca3af;">重掛距離</label>
                                        <div style="display: flex; align-items: center; gap: 4px;">
                                            <input type="number" id="grvtMmRebalanceDistance" value="12" step="1" min="10" max="30" style="width: 50px; padding: 4px; background: #1a1f2e; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                                            <span style="font-size: 10px; color: #6b7280;">bps</span>
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
                                            <input type="number" id="grvtMmOrderSize" value="0.01" step="0.001" min="0.001" max="0.1" style="width: 60px; padding: 4px; background: #1a1f2e; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                                            <span style="font-size: 10px; color: #6b7280;">BTC</span>
                                        </div>
                                    </div>
                                    <div style="display: flex; align-items: center; justify-content: space-between;">
                                        <label style="font-size: 11px; color: #9ca3af;">最大持倉</label>
                                        <div style="display: flex; align-items: center; gap: 4px;">
                                            <input type="number" id="grvtMmMaxPosition" value="1" step="0.01" min="0.01" max="10" style="width: 60px; padding: 4px; background: #1a1f2e; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
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
                                            <input type="number" id="grvtMmVolatilityWindow" value="5" step="1" min="1" max="60" style="width: 50px; padding: 4px; background: #1a1f2e; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                                            <span style="font-size: 10px; color: #6b7280;">秒</span>
                                        </div>
                                    </div>
                                    <div style="display: flex; align-items: center; justify-content: space-between;">
                                        <label style="font-size: 11px; color: #9ca3af;">閾值</label>
                                        <div style="display: flex; align-items: center; gap: 4px;">
                                            <input type="number" id="grvtMmVolatilityThreshold" value="5" step="0.5" min="1" max="20" style="width: 50px; padding: 4px; background: #1a1f2e; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                                            <span style="font-size: 10px; color: #6b7280;">bps</span>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <!-- 執行控制 -->
                            <div style="background: #0f1419; padding: 12px; border-radius: 6px;">
                                <div style="font-size: 11px; color: #6b7280; margin-bottom: 8px;">執行控制</div>
                                <div style="display: flex; gap: 8px;">
                                    <button class="btn btn-primary" onclick="saveGrvtMMConfig()" style="flex: 1; font-size: 11px; padding: 6px;">保存配置</button>
                                    <button class="btn" onclick="loadGrvtMMConfig()" style="flex: 1; font-size: 11px; padding: 6px; background: #2a3347;">重載</button>
                                </div>
                            </div>
                        </div>
                        <!-- 倉位狀態 -->
                        <div style="display: flex; gap: 15px; font-size: 11px; color: #9ca3af; padding-top: 10px; border-top: 1px solid #2a3347;">
                            <span>GRVT: <span id="grvtMmGrvtPos" style="color: #e4e6eb;">0</span> BTC</span>
                            <span>StandX: <span id="grvtMmStandxPos" style="color: #e4e6eb;">0</span> BTC</span>
                            <span>淨敞口: <span id="grvtMmNetPos" style="color: #10b981;">0</span></span>
                            <span>GRVT USDT: $<span id="grvtMmGrvtUsdt" style="color: #e4e6eb;">0</span></span>
                            <span>StandX 權益: $<span id="grvtMmStandxEquity" style="color: #e4e6eb;">0</span></span>
                        </div>
                    </div>

                    <!-- 訂單簿 -->
                    <div class="card">
                        <div class="card-title">訂單簿深度</div>
                        <div class="orderbook">
                            <div class="ob-side">
                                <div class="ob-header"><span>買價</span><span style="text-align:right">數量</span></div>
                                <div id="grvtMmBidRows"></div>
                            </div>
                            <div class="ob-side">
                                <div class="ob-header"><span>賣價</span><span style="text-align:right">數量</span></div>
                                <div id="grvtMmAskRows"></div>
                            </div>
                        </div>
                        <div class="spread-bar">Spread: <span id="grvtMmSpreadDisplay" class="text-green">- bps</span></div>
                    </div>

                    <!-- 當前掛單 -->
                    <div class="card">
                        <div class="card-title">當前掛單</div>
                        <div class="quote-box">
                            <div class="quote-label">買單價格</div>
                            <div class="quote-price quote-bid" id="grvtMmSuggestedBid">-</div>
                            <div class="quote-status" id="grvtMmBidStatus" style="font-size: 10px; margin-top: 4px;">-</div>
                        </div>
                        <div class="quote-box">
                            <div class="quote-label">賣單價格</div>
                            <div class="quote-price quote-ask" id="grvtMmSuggestedAsk">-</div>
                            <div class="quote-status" id="grvtMmAskStatus" style="font-size: 10px; margin-top: 4px;">-</div>
                        </div>
                        <p style="font-size: 10px; color: #9ca3af; text-align: center; margin-top: 8px;" id="grvtMmStrategyDesc">
                            載入配置中...
                        </p>
                    </div>

                    <!-- 深度分析 -->
                    <div class="card">
                        <div class="card-title">深度分析</div>
                        <div class="depth-bar">
                            <div class="depth-bid" id="grvtMmDepthBid" style="width:50%">0 BTC</div>
                            <div class="depth-ask" id="grvtMmDepthAsk" style="width:50%">0 BTC</div>
                        </div>
                        <div style="display: flex; justify-content: space-between; font-size: 10px; color: #9ca3af; margin-bottom: 15px;">
                            <span>買方深度</span><span id="grvtMmImbalance">平衡: 0%</span><span>賣方深度</span>
                        </div>
                        <div class="card-title" style="margin-top: 10px;">報價排隊位置</div>
                        <div class="risk-row"><span>買單位置</span><span id="grvtMmBidPosition" style="font-weight:600">-</span></div>
                        <div class="risk-row"><span>賣單位置</span><span id="grvtMmAskPosition" style="font-weight:600">-</span></div>
                    </div>

                    <!-- 執行統計 -->
                    <div class="card">
                        <div class="card-title">執行統計</div>
                        <div class="sim-grid">
                            <div class="sim-stat"><div class="sim-value" id="grvtMmTotalQuotes">0秒</div><div class="sim-label">運行時間</div></div>
                            <div class="sim-stat"><div class="sim-value" id="grvtMmQualifiedRate">-</div><div class="sim-label">狀態</div></div>
                            <div class="sim-stat"><div class="sim-value" id="grvtMmFillCount" style="color:#10b981">0</div><div class="sim-label">成交次數</div></div>
                            <div class="sim-stat"><div class="sim-value" id="grvtMmPnl" style="color:#10b981">$0.00</div><div class="sim-label">實盤 PnL</div></div>
                        </div>
                        <!-- 撤單統計 -->
                        <div style="margin-top: 10px; display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 11px;">
                            <div style="background: #0f1419; padding: 8px; border-radius: 4px; text-align: center;">
                                <div id="grvtMmBidFillRate" style="font-weight: 600; color: #10b981;">0/0/0</div>
                                <div style="color: #9ca3af; font-size: 9px;">買撤/隊列/重掛</div>
                            </div>
                            <div style="background: #0f1419; padding: 8px; border-radius: 4px; text-align: center;">
                                <div id="grvtMmAskFillRate" style="font-weight: 600; color: #ef4444;">0/0/0</div>
                                <div style="color: #9ca3af; font-size: 9px;">賣撤/隊列/重掛</div>
                            </div>
                        </div>
                        <!-- 波動率統計 -->
                        <div style="margin-top: 10px; background: #0f1419; padding: 10px; border-radius: 6px;">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <div>
                                    <span style="color: #9ca3af; font-size: 10px;">波動率</span>
                                    <span id="grvtMmVolatility" style="font-weight: 600; margin-left: 8px;">0.0</span>
                                    <span style="color: #9ca3af; font-size: 10px;"> bps</span>
                                    <span id="grvtMmVolatilityStatus" style="margin-left: 8px; font-size: 10px; color: #10b981;">正常</span>
                                </div>
                                <div style="font-size: 10px; color: #9ca3af;">
                                    暫停: <span id="grvtMmVolatilityPauseCount">0</span>次
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- 訂單操作歷史 -->
                    <div class="card">
                        <div class="card-title">操作歷史 <span style="font-size: 10px; color: #9ca3af;">(最近 50 筆)</span></div>
                        <div id="grvtMmHistoryList" style="max-height: 300px; overflow-y: auto; font-size: 11px;">
                            <div style="color: #9ca3af; text-align: center; padding: 20px;">等待訂單操作...</div>
                        </div>
                    </div>

                    <!-- 對沖狀態 -->
                    <div class="card">
                        <div class="card-title">對沖狀態 (StandX)</div>
                        <div class="stat-row"><span class="stat-label">對沖交易所</span><span class="stat-value">StandX</span></div>
                        <div class="stat-row"><span class="stat-label">對沖交易對</span><span class="stat-value">BTC-USD</span></div>
                        <div class="stat-row"><span class="stat-label">對沖成功率</span><span class="stat-value" id="grvtMmHedgeSuccessRate">-</span></div>
                        <div class="stat-row"><span class="stat-label">最後對沖</span><span class="stat-value" id="grvtMmLastHedge">-</span></div>
                    </div>
                </div>
            </div>
'''
