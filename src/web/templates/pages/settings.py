"""
設定頁面 HTML
"""


def get_settings_page() -> str:
    """返回設定頁面 HTML"""
    return '''
            <!-- ==================== 設定頁面 ==================== -->
            <div id="page-settings" class="page">
                <div class="settings-section">
                    <div class="settings-title" style="display: flex; justify-content: space-between; align-items: center;">
                        <span>已配置交易所</span>
                        <button class="btn btn-primary" onclick="reinitSystem()" id="reinitBtn">重新連接</button>
                    </div>
                    <div id="reinitStatus" style="color: #9ca3af; margin-bottom: 10px; display: none;"></div>
                    <div id="configuredExchanges">
                        <p style="color: #9ca3af;">載入中...</p>
                    </div>
                </div>

                <div class="settings-section">
                    <div class="settings-title">添加新交易所</div>
                    <div class="card" style="padding: 20px;">
                        <div class="form-grid">
                            <div class="form-group">
                                <label>交易所類型</label>
                                <select id="exchangeType" onchange="updateExchangeOptions()">
                                    <option value="cex">CEX (中心化)</option>
                                    <option value="dex">DEX (去中心化)</option>
                                </select>
                            </div>
                            <div class="form-group">
                                <label>選擇交易所</label>
                                <select id="exchangeName">
                                    <option value="binance">Binance</option>
                                    <option value="okx">OKX</option>
                                    <option value="bitget">Bitget</option>
                                    <option value="bybit">Bybit</option>
                                </select>
                            </div>
                        </div>
                        <div id="cexFields" class="form-grid" style="margin-top: 15px;">
                            <div class="form-group">
                                <label>API Key</label>
                                <input type="text" id="apiKey" placeholder="輸入 API Key">
                            </div>
                            <div class="form-group">
                                <label>API Secret</label>
                                <input type="password" id="apiSecret" placeholder="輸入 API Secret">
                            </div>
                            <div class="form-group" id="passphraseField" style="display: none;">
                                <label>Passphrase</label>
                                <input type="password" id="passphrase" placeholder="OKX/Bitget 需要">
                            </div>
                        </div>
                        <div id="dexFields" class="form-grid" style="margin-top: 15px; display: none;">
                            <!-- StandX 字段 -->
                            <div id="standxFields">
                                <div class="form-group">
                                    <label>Private Key</label>
                                    <input type="password" id="privateKey" placeholder="錢包私鑰">
                                </div>
                                <div class="form-group">
                                    <label>Wallet Address</label>
                                    <input type="text" id="walletAddress" placeholder="錢包地址">
                                </div>
                            </div>
                            <!-- GRVT 字段 -->
                            <div id="grvtFields" style="display: none;">
                                <div class="form-group">
                                    <label>API Key</label>
                                    <input type="text" id="grvtApiKey" placeholder="GRVT API Key">
                                </div>
                                <div class="form-group">
                                    <label>API Secret</label>
                                    <input type="password" id="grvtApiSecret" placeholder="GRVT API Secret">
                                </div>
                            </div>
                        </div>
                        <button class="btn btn-primary" style="margin-top: 20px;" onclick="saveConfig()">保存並開始監控</button>
                    </div>
                </div>
            </div>
'''
