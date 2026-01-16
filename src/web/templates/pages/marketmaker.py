"""
做市商頁面 HTML
"""


def get_marketmaker_page() -> str:
    """返回做市商頁面 HTML"""
    return '''
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
                                <div style="display: flex; gap: 8px;">
                                    <button class="btn btn-primary" onclick="saveMMConfig()" style="flex: 1; font-size: 11px; padding: 6px;">保存配置</button>
                                    <button class="btn" onclick="loadMMConfig()" style="flex: 1; font-size: 11px; padding: 6px; background: #2a3347;">重載</button>
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
                        <div class="stat-row"><span class="stat-label">Boosted (>=70%)</span><span class="stat-value">1.0x</span></div>
                        <div class="stat-row"><span class="stat-label">Standard (>=50%)</span><span class="stat-value">0.5x</span></div>
                        <div class="stat-row"><span class="stat-label">當前乘數</span><span class="stat-value" id="mmMultiplier">0x</span></div>
                    </div>

                    <!-- 當前掛單 -->
                    <div class="card">
                        <div class="card-title">當前掛單 (需在 mark +/- 30 bps 內)</div>
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

                    <!-- 執行統計 -->
                    <div class="card">
                        <div class="card-title">執行統計</div>
                        <div class="sim-grid">
                            <div class="sim-stat"><div class="sim-value" id="mmTotalQuotes">0秒</div><div class="sim-label">運行時間</div></div>
                            <div class="sim-stat"><div class="sim-value" id="mmQualifiedRate">0%</div><div class="sim-label">有效積分</div></div>
                            <div class="sim-stat"><div class="sim-value" id="mmFillCount" style="color:#10b981">0</div><div class="sim-label">成交次數</div></div>
                            <div class="sim-stat"><div class="sim-value" id="mmPnl" style="color:#10b981">$0.00</div><div class="sim-label">實盤 PnL</div></div>
                        </div>
                        <!-- 分層時間統計 -->
                        <div style="margin-top: 12px; padding: 10px; background: #0f1419; border-radius: 6px;">
                            <div style="font-size: 10px; color: #9ca3af; margin-bottom: 8px;">分層時間占比 (StandX)</div>
                            <div style="display: flex; gap: 4px; height: 20px; border-radius: 4px; overflow: hidden; margin-bottom: 8px;">
                                <div id="mmTierBoosted" style="background: #10b981; min-width: 0; transition: all 0.3s;" title="100% (0-10 bps)"></div>
                                <div id="mmTierStandard" style="background: #f59e0b; min-width: 0; transition: all 0.3s;" title="50% (10-30 bps)"></div>
                                <div id="mmTierBasic" style="background: #6366f1; min-width: 0; transition: all 0.3s;" title="10% (30-100 bps)"></div>
                                <div id="mmTierOut" style="background: #374151; flex: 1; transition: all 0.3s;" title="超出範圍"></div>
                            </div>
                            <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; font-size: 10px; text-align: center;">
                                <div><span style="color: #10b981;">&#9632;</span> 100%: <span id="mmTierBoostedPct">0%</span></div>
                                <div><span style="color: #f59e0b;">&#9632;</span> 50%: <span id="mmTierStandardPct">0%</span></div>
                                <div><span style="color: #6366f1;">&#9632;</span> 10%: <span id="mmTierBasicPct">0%</span></div>
                                <div><span style="color: #374151;">&#9632;</span> 超出: <span id="mmTierOutPct">0%</span></div>
                            </div>
                        </div>
                        <!-- 撤單統計 -->
                        <div style="margin-top: 10px; display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 11px;">
                            <div style="background: #0f1419; padding: 8px; border-radius: 4px; text-align: center;">
                                <div id="mmBidFillRate" style="font-weight: 600; color: #10b981;">0/0/0</div>
                                <div style="color: #9ca3af; font-size: 9px;">買撤/隊列/重掛</div>
                            </div>
                            <div style="background: #0f1419; padding: 8px; border-radius: 4px; text-align: center;">
                                <div id="mmAskFillRate" style="font-weight: 600; color: #ef4444;">0/0/0</div>
                                <div style="color: #9ca3af; font-size: 9px;">賣撤/隊列/重掛</div>
                            </div>
                        </div>
                        <!-- 波動率統計 -->
                        <div style="margin-top: 10px; background: #0f1419; padding: 10px; border-radius: 6px;">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <div>
                                    <span style="color: #9ca3af; font-size: 10px;">波動率</span>
                                    <span id="mmVolatility" style="font-weight: 600; margin-left: 8px;">0.0</span>
                                    <span style="color: #9ca3af; font-size: 10px;"> bps</span>
                                    <span id="mmVolatilityStatus" style="margin-left: 8px; font-size: 10px; color: #10b981;">正常</span>
                                </div>
                                <div style="font-size: 10px; color: #9ca3af;">
                                    暫停: <span id="mmVolatilityPauseCount">0</span>次
                                </div>
                            </div>
                        </div>
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
'''
