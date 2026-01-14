"""
參數比較頁面 HTML
"""


def get_comparison_page() -> str:
    """返回參數比較頁面 HTML"""
    return '''
            <!-- ==================== 參數比較頁面 ==================== -->
            <div id="page-comparison" class="page">
                <div style="margin-bottom: 20px;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <h2 style="font-size: 24px; font-weight: 700; color: #667eea;">參數比較模擬</h2>
                        <div style="display: flex; gap: 10px; align-items: center;">
                            <span id="simStatusBadge" class="badge" style="background: #2a3347; padding: 6px 12px;">未運行</span>
                            <button id="simStartBtn" class="btn btn-primary" onclick="startSimulation()">開始比較</button>
                            <button id="simStopBtn" class="btn btn-danger" onclick="stopSimulation()" style="display:none;">停止</button>
                        </div>
                    </div>
                    <p style="color: #9ca3af; margin-top: 8px; font-size: 13px;">
                        同時運行多組參數，比較 Uptime、成交次數、PnL 等指標，找出最佳參數組合
                    </p>
                </div>

                <div class="grid-2" style="gap: 20px;">
                    <!-- 左側：參數組選擇 -->
                    <div class="card">
                        <div class="card-title" style="display: flex; justify-content: space-between; align-items: center;">
                            <span>選擇參數組</span>
                            <button class="btn" style="padding: 4px 10px; font-size: 11px;" onclick="openParamSetEditor()">+ 新增</button>
                        </div>
                        <div id="paramSetList" style="display: flex; flex-direction: column; gap: 8px; max-height: 400px; overflow-y: auto;">
                            <p style="color: #9ca3af; text-align: center;">載入中...</p>
                        </div>
                        <div style="margin-top: 15px; padding-top: 15px; border-top: 1px solid #2a3347;">
                            <div style="display: flex; align-items: center; gap: 15px;">
                                <label style="font-size: 12px; color: #9ca3af;">持續時間</label>
                                <select id="simDuration" style="padding: 6px 12px; background: #0f1419; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                                    <option value="5">5 分鐘</option>
                                    <option value="15">15 分鐘</option>
                                    <option value="30">30 分鐘</option>
                                    <option value="60" selected>1 小時</option>
                                    <option value="120">2 小時</option>
                                    <option value="240">4 小時</option>
                                </select>
                            </div>
                        </div>
                    </div>

                    <!-- 右側：即時比較結果 -->
                    <div class="card">
                        <div class="card-title">即時比較 <span id="simProgress" style="color: #9ca3af; font-size: 11px; margin-left: 10px;"></span></div>
                        <div style="font-size: 10px; color: #6b7280; margin-bottom: 8px;">
                            積分規則：<span style="color: #10b981;">0-10bps=100%</span> |
                            <span style="color: #f59e0b;">10-30bps=50%</span> |
                            <span style="color: #9ca3af;">30-100bps=10%</span>
                        </div>
                        <div id="liveComparison" style="overflow-x: auto;">
                            <table class="price-table" style="font-size: 11px;">
                                <thead>
                                    <tr>
                                        <th>參數組</th>
                                        <th style="color: #667eea;">有效積分</th>
                                        <th style="color: #10b981;">100%檔</th>
                                        <th style="color: #f59e0b;">50%檔</th>
                                        <th style="color: #9ca3af;">10%檔</th>
                                        <th>成交</th>
                                        <th>PnL</th>
                                        <th>撤單</th>
                                    </tr>
                                </thead>
                                <tbody id="liveComparisonBody">
                                    <tr><td colspan="8" style="text-align: center; color: #9ca3af; padding: 20px;">選擇參數組後點擊「開始比較」</td></tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>

                <!-- 歷史運行記錄 -->
                <div class="card" style="margin-top: 20px;">
                    <div class="card-title" style="display: flex; justify-content: space-between; align-items: center;">
                        <span>歷史比較記錄</span>
                        <button class="btn" style="padding: 4px 10px; font-size: 11px;" onclick="loadSimulationRuns()">刷新</button>
                    </div>
                    <div id="simRunsList" style="overflow-x: auto;">
                        <table class="price-table" style="font-size: 12px;">
                            <thead>
                                <tr>
                                    <th>運行ID</th>
                                    <th>開始時間</th>
                                    <th>持續時間</th>
                                    <th>參數組數</th>
                                    <th>推薦</th>
                                    <th>操作</th>
                                </tr>
                            </thead>
                            <tbody id="simRunsBody">
                                <tr><td colspan="6" style="text-align: center; color: #9ca3af; padding: 20px;">無歷史記錄</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <!-- 模擬操作歷史 -->
                <div id="simOperationHistoryCard" class="card" style="margin-top: 20px; display: none;">
                    <div class="card-title" style="display: flex; justify-content: space-between; align-items: center;">
                        <span>操作歷史 <span style="font-size: 10px; color: #9ca3af;">(最近 50 筆)</span></span>
                        <select id="simHistoryParamSetSelect" onchange="updateSimOperationHistory()" style="padding: 4px 8px; background: #0f1419; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 11px;">
                            <option value="">載入中...</option>
                        </select>
                    </div>
                    <div id="simOperationHistoryList" style="max-height: 350px; overflow-y: auto; font-size: 11px;">
                        <div style="color: #9ca3af; text-align: center; padding: 20px;">載入操作歷史中...</div>
                    </div>
                </div>

                <!-- 詳細結果展開區 -->
                <div id="simResultDetail" class="card" style="margin-top: 20px; display: none;">
                    <div class="card-title" style="display: flex; justify-content: space-between; align-items: center;">
                        <span>比較結果詳情</span>
                        <button class="btn" style="padding: 4px 10px; font-size: 11px;" onclick="closeResultDetail()">關閉</button>
                    </div>
                    <div id="simResultContent"></div>
                </div>

                <!-- 參數組編輯彈窗 -->
                <div id="paramSetModal" style="display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); z-index: 2000; align-items: center; justify-content: center;">
                    <div style="background: #1a1f2e; border: 1px solid #2a3347; border-radius: 8px; padding: 20px; width: 450px; max-width: 90%;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                            <h3 id="paramSetModalTitle" style="font-size: 16px; color: #667eea;">編輯參數組</h3>
                            <button onclick="closeParamSetEditor()" style="background: none; border: none; color: #9ca3af; font-size: 20px; cursor: pointer;">&times;</button>
                        </div>
                        <div style="display: flex; flex-direction: column; gap: 12px;">
                            <input type="hidden" id="psEditId">
                            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
                                <div>
                                    <label style="font-size: 11px; color: #9ca3af; display: block; margin-bottom: 4px;">ID (唯一標識)</label>
                                    <input type="text" id="psEditIdInput" placeholder="例: my_strategy" style="width: 100%; padding: 8px; background: #0f1419; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                                </div>
                                <div>
                                    <label style="font-size: 11px; color: #9ca3af; display: block; margin-bottom: 4px;">名稱</label>
                                    <input type="text" id="psEditName" placeholder="例: 我的策略" style="width: 100%; padding: 8px; background: #0f1419; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                                </div>
                            </div>
                            <div>
                                <label style="font-size: 11px; color: #9ca3af; display: block; margin-bottom: 4px;">描述</label>
                                <input type="text" id="psEditDesc" placeholder="策略描述" style="width: 100%; padding: 8px; background: #0f1419; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                            </div>
                            <div style="background: #0f1419; padding: 12px; border-radius: 6px;">
                                <div style="font-size: 11px; color: #6b7280; margin-bottom: 10px;">報價參數</div>
                                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
                                    <div>
                                        <label style="font-size: 10px; color: #9ca3af;">掛單距離 (bps)</label>
                                        <input type="number" id="psEditOrderDist" min="1" max="20" step="1" style="width: 100%; padding: 6px; background: #1a1f2e; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                                    </div>
                                    <div>
                                        <label style="font-size: 10px; color: #9ca3af;">撤單距離 (bps)</label>
                                        <input type="number" id="psEditCancelDist" min="1" max="10" step="1" style="width: 100%; padding: 6px; background: #1a1f2e; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                                    </div>
                                    <div>
                                        <label style="font-size: 10px; color: #9ca3af;">重掛距離 (bps)</label>
                                        <input type="number" id="psEditRebalDist" min="8" max="30" step="1" style="width: 100%; padding: 6px; background: #1a1f2e; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                                    </div>
                                    <div>
                                        <label style="font-size: 10px; color: #9ca3af;">隊列風控 (檔)</label>
                                        <input type="number" id="psEditQueueLimit" min="1" max="10" step="1" style="width: 100%; padding: 6px; background: #1a1f2e; border: 1px solid #2a3347; border-radius: 4px; color: #e4e6eb; font-size: 12px;">
                                    </div>
                                </div>
                            </div>
                            <div style="display: flex; gap: 10px; margin-top: 10px;">
                                <button onclick="saveParamSet()" class="btn btn-primary" style="flex: 1;">保存</button>
                                <button onclick="closeParamSetEditor()" class="btn" style="flex: 1;">取消</button>
                            </div>
                            <div id="psEditDeleteBtn" style="display: none; margin-top: 5px;">
                                <button onclick="deleteParamSet()" class="btn btn-danger" style="width: 100%;">刪除此參數組</button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
'''
