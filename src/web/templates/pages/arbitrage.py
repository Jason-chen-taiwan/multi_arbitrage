"""
套利頁面 HTML
"""


def get_arbitrage_page() -> str:
    """返回套利頁面 HTML"""
    return '''
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
'''
