"""
CSS 樣式模組

包含交易控制台的所有 CSS 樣式
"""


def get_css_styles() -> str:
    """返回完整的 CSS 樣式字符串"""
    return """
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: 'SF Mono', -apple-system, BlinkMacSystemFont, monospace;
                background: #0a0e14;
                color: #e4e6eb;
                min-height: 100vh;
            }

            /* ===== 頂部導航 ===== */
            .top-nav {
                background: #1a1f2e;
                border-bottom: 1px solid #2a3347;
                padding: 0 20px;
                display: flex;
                align-items: center;
                height: 50px;
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                z-index: 1000;
            }
            .nav-logo {
                font-size: 18px;
                font-weight: 700;
                color: #667eea;
                margin-right: 40px;
            }
            .nav-tabs {
                display: flex;
                gap: 5px;
            }
            .nav-tab {
                padding: 12px 24px;
                background: transparent;
                border: none;
                color: #9ca3af;
                font-size: 14px;
                font-weight: 600;
                cursor: pointer;
                border-bottom: 2px solid transparent;
                transition: all 0.2s;
            }
            .nav-tab:hover {
                color: #e4e6eb;
                background: #2a3347;
            }
            .nav-tab.active {
                color: #667eea;
                border-bottom-color: #667eea;
            }
            .nav-status {
                margin-left: auto;
                display: flex;
                align-items: center;
                gap: 15px;
                font-size: 12px;
            }
            .status-dot {
                width: 8px;
                height: 8px;
                border-radius: 50%;
                background: #10b981;
            }
            .status-dot.offline { background: #ef4444; }

            /* ===== 主內容區 ===== */
            .main-content {
                margin-top: 50px;
                padding: 20px;
            }
            .page { display: none; }
            .page.active { display: block; }

            /* ===== 通用樣式 ===== */
            .card {
                background: #1a1f2e;
                border: 1px solid #2a3347;
                border-radius: 8px;
                padding: 15px;
            }
            .card-title {
                font-size: 13px;
                color: #667eea;
                margin-bottom: 12px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }
            .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
            .grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 15px; }
            .grid-4 { display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 15px; }
            .stat-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #2a334755; }
            .stat-row:last-child { border-bottom: none; }
            .stat-label { color: #9ca3af; font-size: 12px; }
            .stat-value { font-weight: 600; font-size: 13px; }
            .text-green { color: #10b981; }
            .text-red { color: #ef4444; }
            .text-yellow { color: #f59e0b; }

            /* ===== 套利頁面 ===== */
            .arb-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 20px;
            }
            .arb-title { font-size: 24px; font-weight: 700; }
            .arb-controls { display: flex; gap: 15px; align-items: center; }
            .toggle-group { display: flex; align-items: center; gap: 8px; font-size: 13px; }
            .toggle {
                width: 44px; height: 22px;
                background: #2a3347;
                border-radius: 11px;
                position: relative;
                cursor: pointer;
                transition: background 0.2s;
            }
            .toggle.active { background: #10b981; }
            .toggle::after {
                content: '';
                position: absolute;
                width: 18px; height: 18px;
                background: white;
                border-radius: 50%;
                top: 2px; left: 2px;
                transition: transform 0.2s;
            }
            .toggle.active::after { transform: translateX(22px); }

            .opportunity-card {
                background: linear-gradient(135deg, #10b981 0%, #059669 100%);
                padding: 15px;
                border-radius: 8px;
                margin-bottom: 10px;
                color: white;
            }
            .opp-header { display: flex; justify-content: space-between; margin-bottom: 10px; }
            .opp-symbol { font-size: 16px; font-weight: 700; }
            .opp-profit { font-size: 20px; font-weight: 700; }
            .opp-details { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; font-size: 12px; }

            .price-table { width: 100%; border-collapse: collapse; font-size: 13px; }
            .price-table th { color: #9ca3af; font-weight: 600; text-align: left; padding: 10px; border-bottom: 1px solid #2a3347; }
            .price-table td { padding: 10px; border-bottom: 1px solid #2a334755; }
            .badge { padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
            .badge-online { background: #10b98133; color: #10b981; }
            .badge-dex { background: #10b981; color: white; }
            .badge-cex { background: #3b82f6; color: white; }

            /* ===== 做市商頁面 ===== */
            .mm-grid {
                display: grid;
                grid-template-columns: 1fr 1fr 1fr;
                grid-template-rows: auto auto;
                gap: 15px;
            }
            .mm-header-bar {
                grid-column: 1 / -1;
                background: linear-gradient(135deg, #1a1f2e 0%, #0f1419 100%);
                border: 1px solid #2a3347;
                border-radius: 8px;
                padding: 15px 20px;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            .mm-title { font-size: 20px; font-weight: 700; color: #667eea; }
            .mm-stats { display: flex; gap: 40px; }
            .mm-stat { text-align: center; }
            .mm-stat-value { font-size: 22px; font-weight: 700; }
            .mm-stat-label { font-size: 11px; color: #9ca3af; text-transform: uppercase; }

            /* 訂單簿 */
            .orderbook { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
            .ob-side { font-size: 12px; }
            .ob-header { display: grid; grid-template-columns: 1fr 1fr; padding: 5px; color: #9ca3af; font-size: 10px; border-bottom: 1px solid #2a3347; }
            .ob-row { display: grid; grid-template-columns: 1fr 1fr; padding: 3px 5px; position: relative; }
            .ob-row .bg { position: absolute; top: 0; bottom: 0; opacity: 0.15; }
            .ob-row.bid .bg { background: #10b981; right: 0; }
            .ob-row.ask .bg { background: #ef4444; left: 0; }
            .ob-price-bid { color: #10b981; }
            .ob-price-ask { color: #ef4444; }
            .ob-size { text-align: right; color: #9ca3af; }
            .spread-bar { background: #0f1419; padding: 8px; border-radius: 4px; text-align: center; margin-top: 8px; font-size: 13px; }

            /* Uptime 圓圈 */
            .uptime-circle {
                width: 100px; height: 100px;
                border-radius: 50%;
                border: 6px solid #2a3347;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                margin: 0 auto 15px;
            }
            .uptime-circle.boosted { border-color: #10b981; }
            .uptime-circle.standard { border-color: #f59e0b; }
            .uptime-pct { font-size: 24px; font-weight: 700; }
            .uptime-tier { font-size: 10px; text-transform: uppercase; }
            .tier-boosted { color: #10b981; }
            .tier-standard { color: #f59e0b; }
            .tier-inactive { color: #ef4444; }

            /* 建議報價 */
            .quote-box { background: #0f1419; border-radius: 6px; padding: 12px; margin-bottom: 8px; }
            .quote-label { font-size: 10px; color: #9ca3af; text-transform: uppercase; }
            .quote-price { font-size: 16px; font-weight: 600; }
            .quote-bid { color: #10b981; }
            .quote-ask { color: #ef4444; }

            /* 深度條 */
            .depth-bar { display: flex; height: 24px; border-radius: 4px; overflow: hidden; margin: 10px 0; }
            .depth-bid { background: #10b981; display: flex; align-items: center; justify-content: flex-end; padding-right: 6px; font-size: 10px; font-weight: 600; }
            .depth-ask { background: #ef4444; display: flex; align-items: center; padding-left: 6px; font-size: 10px; font-weight: 600; }

            /* 風險標籤 */
            .risk-row { display: flex; justify-content: space-between; padding: 8px; background: #0f1419; border-radius: 4px; margin-bottom: 6px; font-size: 12px; }
            .risk-badge { padding: 3px 8px; border-radius: 4px; font-size: 10px; font-weight: 600; text-transform: uppercase; }
            .risk-low { background: #10b98133; color: #10b981; }
            .risk-medium { background: #f59e0b33; color: #f59e0b; }
            .risk-high { background: #ef444433; color: #ef4444; }

            /* 模擬統計 */
            .sim-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
            .sim-stat { background: #0f1419; border-radius: 6px; padding: 10px; text-align: center; }
            .sim-value { font-size: 18px; font-weight: 700; }
            .sim-label { font-size: 9px; color: #9ca3af; text-transform: uppercase; margin-top: 2px; }

            /* 進度條 */
            .progress-bar { background: #0f1419; border-radius: 4px; height: 20px; position: relative; overflow: hidden; margin-bottom: 8px; }
            .progress-fill { height: 100%; border-radius: 4px; transition: width 0.3s; }
            .progress-fill.mm1 { background: linear-gradient(90deg, #667eea, #764ba2); }
            .progress-fill.mm2 { background: linear-gradient(90deg, #10b981, #059669); }
            .progress-text { position: absolute; right: 8px; top: 50%; transform: translateY(-50%); font-size: 10px; font-weight: 600; }
            .progress-label { font-size: 10px; color: #9ca3af; margin-bottom: 4px; }

            /* ===== 設定頁面 ===== */
            .settings-section { margin-bottom: 30px; }
            .settings-title { font-size: 18px; margin-bottom: 15px; }
            .exchange-card {
                background: #0f1419;
                border: 1px solid #2a3347;
                border-radius: 8px;
                padding: 15px;
                margin-bottom: 10px;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            .exchange-info { display: flex; align-items: center; gap: 12px; }
            .exchange-name { font-size: 16px; font-weight: 600; }
            .exchange-details { font-size: 11px; color: #9ca3af; margin-top: 3px; }
            .btn { padding: 8px 16px; border: none; border-radius: 6px; font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.2s; }
            .btn-primary { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; }
            .btn-danger { background: #ef4444; color: white; }
            .btn:hover { transform: translateY(-1px); }

            .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
            .form-group { display: flex; flex-direction: column; }
            .form-group label { font-size: 12px; color: #9ca3af; margin-bottom: 5px; }
            .form-group input, .form-group select {
                padding: 10px;
                background: #0f1419;
                border: 1px solid #2a3347;
                border-radius: 6px;
                color: #e4e6eb;
                font-size: 13px;
            }
            .form-group input:focus, .form-group select:focus { outline: none; border-color: #667eea; }
"""
