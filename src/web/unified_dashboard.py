#!/usr/bin/env python3
"""
統一 Dashboard - 整合所有功能
Unified Dashboard - All-in-One Interface

單一介面包含：
1. 配置管理
2. 套利監控
3. 交易所狀態
4. 系統設置
"""
import asyncio
import json
import os
from datetime import datetime
from typing import Dict, List, Optional
from decimal import Decimal
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import uvicorn
from pathlib import Path
from dotenv import load_dotenv, set_key, unset_key

# Import modules
import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
from src.adapters.factory import create_adapter
from src.monitor.multi_exchange_monitor import MultiExchangeMonitor

# Global variables
monitor: Optional[MultiExchangeMonitor] = None
connected_clients: List[WebSocket] = []
env_file = Path(__file__).parent.parent.parent / ".env"


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>統一控制台 - Unified Dashboard</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f1419;
            color: #e4e6eb;
            display: flex;
            height: 100vh;
            overflow: hidden;
        }

        /* Sidebar */
        .sidebar {
            width: 250px;
            background: #1a1f2e;
            border-right: 1px solid #2a3347;
            display: flex;
            flex-direction: column;
            padding: 20px;
        }

        .logo {
            font-size: 24px;
            font-weight: 700;
            margin-bottom: 30px;
            text-align: center;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .nav-item {
            padding: 12px 15px;
            margin-bottom: 8px;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.3s;
            display: flex;
            align-items: center;
            gap: 10px;
            color: #9ca3af;
        }

        .nav-item:hover {
            background: #2a3347;
            color: #ffffff;
        }

        .nav-item.active {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #ffffff;
        }

        .nav-icon {
            font-size: 20px;
        }

        /* Main Content */
        .main-content {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        /* Header */
        .header {
            background: #1a1f2e;
            border-bottom: 1px solid #2a3347;
            padding: 20px 30px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .header-title {
            font-size: 24px;
            font-weight: 700;
        }

        .status-indicator {
            display: flex;
            align-items: center;
            gap: 15px;
        }

        .status-badge {
            padding: 6px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }

        .badge-online {
            background: #10b981;
            color: white;
        }

        .badge-offline {
            background: #ef4444;
            color: white;
        }

        /* Content Area */
        .content-area {
            flex: 1;
            overflow-y: auto;
            padding: 30px;
        }

        .page {
            display: none;
        }

        .page.active {
            display: block;
        }

        /* Cards */
        .card {
            background: #1a1f2e;
            border: 1px solid #2a3347;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }

        .card-header {
            font-size: 18px;
            font-weight: 700;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #2a3347;
        }

        /* Stats Grid */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }

        .stat-card {
            background: linear-gradient(135deg, #374151 0%, #1f2937 100%);
            padding: 20px;
            border-radius: 10px;
            border: 1px solid #2a3347;
        }

        .stat-label {
            font-size: 12px;
            color: #9ca3af;
            margin-bottom: 5px;
        }

        .stat-value {
            font-size: 24px;
            font-weight: 700;
        }

        /* Exchange Grid */
        .exchange-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 15px;
        }

        .exchange-card {
            background: #1a1f2e;
            border: 1px solid #2a3347;
            border-radius: 10px;
            overflow: hidden;
        }

        .exchange-header {
            background: linear-gradient(135deg, #374151 0%, #1f2937 100%);
            padding: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .exchange-name {
            font-size: 16px;
            font-weight: 700;
        }

        .exchange-body {
            padding: 15px;
        }

        .price-row {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #2a3347;
        }

        .price-row:last-child {
            border-bottom: none;
        }

        /* Arbitrage Opportunities */
        .opportunity-card {
            background: linear-gradient(135deg, #1e3a8a 0%, #7c3aed 100%);
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 10px;
        }

        .opportunity-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 15px;
        }

        .opportunity-symbol {
            font-size: 18px;
            font-weight: 700;
        }

        .opportunity-profit {
            font-size: 20px;
            font-weight: 700;
            color: #10b981;
        }

        .opportunity-body {
            display: grid;
            grid-template-columns: 1fr auto 1fr;
            gap: 15px;
            align-items: center;
        }

        .trade-side {
            padding: 12px;
            background: rgba(255,255,255,0.1);
            border-radius: 8px;
        }

        .trade-label {
            font-size: 11px;
            color: #9ca3af;
            margin-bottom: 3px;
        }

        .trade-exchange {
            font-size: 14px;
            font-weight: 700;
        }

        .trade-price {
            font-size: 16px;
            font-weight: 700;
            margin-top: 3px;
        }

        .arrow-icon {
            font-size: 24px;
            color: #fbbf24;
        }

        /* Config Forms */
        .config-section {
            margin-bottom: 30px;
        }

        .config-header {
            font-size: 16px;
            font-weight: 700;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 2px solid #667eea;
        }

        .exchange-list {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
            gap: 15px;
        }

        .exchange-item {
            background: #2a3347;
            padding: 15px;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.3s;
        }

        .exchange-item:hover {
            background: #374151;
            transform: translateY(-2px);
        }

        .exchange-item.configured {
            border: 2px solid #10b981;
        }

        .exchange-item-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }

        .exchange-item-name {
            font-weight: 700;
            font-size: 14px;
        }

        .config-badge {
            font-size: 10px;
            padding: 2px 8px;
            border-radius: 8px;
            background: #10b981;
        }

        .exchange-item-status {
            font-size: 12px;
            color: #9ca3af;
        }

        /* Modal */
        .modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.8);
            z-index: 1000;
            align-items: center;
            justify-content: center;
        }

        .modal.active {
            display: flex;
        }

        .modal-content {
            background: #1a1f2e;
            padding: 30px;
            border-radius: 12px;
            max-width: 500px;
            width: 90%;
            max-height: 80vh;
            overflow-y: auto;
        }

        .modal-header {
            font-size: 20px;
            font-weight: 700;
            margin-bottom: 20px;
        }

        .form-group {
            margin-bottom: 15px;
        }

        .form-label {
            display: block;
            margin-bottom: 5px;
            font-size: 14px;
            color: #9ca3af;
        }

        .form-input {
            width: 100%;
            padding: 10px;
            background: #2a3347;
            border: 1px solid #374151;
            border-radius: 6px;
            color: #e4e6eb;
            font-size: 14px;
        }

        .form-input:focus {
            outline: none;
            border-color: #667eea;
        }

        .form-actions {
            display: flex;
            gap: 10px;
            margin-top: 20px;
        }

        .btn {
            padding: 10px 20px;
            border: none;
            border-radius: 6px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
        }

        .btn-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }

        .btn-primary:hover {
            transform: translateY(-2px);
        }

        .btn-secondary {
            background: #374151;
            color: #9ca3af;
        }

        .btn-secondary:hover {
            background: #4b5563;
        }

        .btn-danger {
            background: #ef4444;
            color: white;
        }

        /* Loading */
        .loading {
            text-align: center;
            padding: 40px;
            color: #6b7280;
        }

        .spinner {
            border: 4px solid #2a3347;
            border-top: 4px solid #667eea;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 0 auto 15px;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        .no-data {
            text-align: center;
            padding: 40px;
            color: #6b7280;
        }
    </style>
</head>
<body>
    <!-- Sidebar -->
    <div class="sidebar">
        <div class="logo">🚀 Arbitrage</div>
        <div class="nav-item active" data-page="overview">
            <span class="nav-icon">📊</span>
            <span>總覽</span>
        </div>
        <div class="nav-item" data-page="arbitrage">
            <span class="nav-icon">💰</span>
            <span>套利監控</span>
        </div>
        <div class="nav-item" data-page="exchanges">
            <span class="nav-icon">🏦</span>
            <span>交易所狀態</span>
        </div>
        <div class="nav-item" data-page="config">
            <span class="nav-icon">⚙️</span>
            <span>配置管理</span>
        </div>
    </div>

    <!-- Main Content -->
    <div class="main-content">
        <!-- Header -->
        <div class="header">
            <div class="header-title" id="page-title">系統總覽</div>
            <div class="status-indicator">
                <span id="connection-status" class="status-badge badge-offline">🔴 離線</span>
                <span style="font-size: 14px; color: #9ca3af;">
                    <span id="last-update">-</span>
                </span>
            </div>
        </div>

        <!-- Content Area -->
        <div class="content-area">
            <!-- Overview Page -->
            <div id="overview-page" class="page active">
                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="stat-label">交易所數量</div>
                        <div class="stat-value" id="overview-exchanges">0</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">套利機會</div>
                        <div class="stat-value" style="color: #10b981;" id="overview-opportunities">0</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">總更新次數</div>
                        <div class="stat-value" id="overview-updates">0</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">運行時間</div>
                        <div class="stat-value" id="overview-runtime">00:00:00</div>
                    </div>
                </div>

                <div class="card">
                    <div class="card-header">🔥 當前套利機會</div>
                    <div id="overview-opportunities-list">
                        <div class="loading">
                            <div class="spinner"></div>
                            <div>載入中...</div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Arbitrage Page -->
            <div id="arbitrage-page" class="page">
                <div class="card">
                    <div class="card-header">💰 套利機會詳情</div>
                    <div id="arbitrage-list">
                        <div class="loading">載入中...</div>
                    </div>
                </div>
            </div>

            <!-- Exchanges Page -->
            <div id="exchanges-page" class="page">
                <div class="card">
                    <div class="card-header">🏦 交易所實時價格</div>
                    <div id="exchanges-grid" class="exchange-grid">
                        <div class="loading">載入中...</div>
                    </div>
                </div>
            </div>

            <!-- Config Page -->
            <div id="config-page" class="page">
                <div class="config-section">
                    <div class="config-header">DEX 去中心化交易所</div>
                    <div class="exchange-list" id="dex-list"></div>
                </div>
                <div class="config-section">
                    <div class="config-header">CEX 中心化交易所</div>
                    <div class="exchange-list" id="cex-list"></div>
                </div>
            </div>
        </div>
    </div>

    <!-- Config Modal -->
    <div id="config-modal" class="modal">
        <div class="modal-content">
            <div class="modal-header" id="modal-title">配置交易所</div>
            <form id="config-form">
                <div id="form-fields"></div>
                <div class="form-actions">
                    <button type="submit" class="btn btn-primary">保存</button>
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">取消</button>
                    <button type="button" class="btn btn-danger" onclick="deleteConfig()" style="margin-left: auto;">刪除</button>
                </div>
            </form>
        </div>
    </div>

    <script>
        let ws = null;
        let startTime = Date.now();
        let updateCount = 0;
        let currentExchange = null;

        // Page Navigation
        document.querySelectorAll('.nav-item').forEach(item => {
            item.addEventListener('click', () => {
                const page = item.dataset.page;
                switchPage(page);
            });
        });

        function switchPage(page) {
            // Update nav
            document.querySelectorAll('.nav-item').forEach(item => {
                item.classList.remove('active');
            });
            document.querySelector(`[data-page="${page}"]`).classList.add('active');

            // Update pages
            document.querySelectorAll('.page').forEach(p => {
                p.classList.remove('active');
            });
            document.getElementById(`${page}-page`).classList.add('active');

            // Update title
            const titles = {
                'overview': '系統總覽',
                'arbitrage': '套利監控',
                'exchanges': '交易所狀態',
                'config': '配置管理'
            };
            document.getElementById('page-title').textContent = titles[page];

            // Load config if needed
            if (page === 'config') {
                loadConfigPage();
            }
        }

        // WebSocket Connection
        function connectWebSocket() {
            const wsUrl = `ws://${window.location.host}/ws`;
            ws = new WebSocket(wsUrl);

            ws.onopen = () => {
                document.getElementById('connection-status').className = 'status-badge badge-online';
                document.getElementById('connection-status').textContent = '✅ 在線';
            };

            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                updateDashboard(data);
            };

            ws.onclose = () => {
                document.getElementById('connection-status').className = 'status-badge badge-offline';
                document.getElementById('connection-status').textContent = '🔴 離線';
                setTimeout(connectWebSocket, 3000);
            };
        }

        function updateDashboard(data) {
            updateCount++;
            document.getElementById('last-update').textContent = new Date(data.timestamp).toLocaleTimeString();

            // Update overview stats
            document.getElementById('overview-exchanges').textContent = data.exchanges?.length || 0;
            document.getElementById('overview-opportunities').textContent = data.total_opportunities || 0;
            document.getElementById('overview-updates').textContent = updateCount;

            // Update runtime
            const runtime = Math.floor((Date.now() - startTime) / 1000);
            const hours = Math.floor(runtime / 3600).toString().padStart(2, '0');
            const minutes = Math.floor((runtime % 3600) / 60).toString().padStart(2, '0');
            const seconds = (runtime % 60).toString().padStart(2, '0');
            document.getElementById('overview-runtime').textContent = `${hours}:${minutes}:${seconds}`;

            // Update opportunities
            updateOpportunities(data.opportunities || []);

            // Update exchanges
            updateExchanges(data.market_data || {});
        }

        function updateOpportunities(opportunities) {
            const container1 = document.getElementById('overview-opportunities-list');
            const container2 = document.getElementById('arbitrage-list');

            const html = opportunities.length === 0
                ? '<div class="no-data">暫無套利機會</div>'
                : opportunities.map(opp => `
                    <div class="opportunity-card">
                        <div class="opportunity-header">
                            <div class="opportunity-symbol">${opp.symbol}</div>
                            <div class="opportunity-profit">+$${opp.profit.toFixed(2)} (${opp.profit_pct.toFixed(2)}%)</div>
                        </div>
                        <div class="opportunity-body">
                            <div class="trade-side">
                                <div class="trade-label">買入 BUY</div>
                                <div class="trade-exchange">${opp.buy_exchange}</div>
                                <div class="trade-price">$${opp.buy_price.toFixed(2)}</div>
                            </div>
                            <div class="arrow-icon">→</div>
                            <div class="trade-side">
                                <div class="trade-label">賣出 SELL</div>
                                <div class="trade-exchange">${opp.sell_exchange}</div>
                                <div class="trade-price">$${opp.sell_price.toFixed(2)}</div>
                            </div>
                        </div>
                    </div>
                `).join('');

            container1.innerHTML = html;
            container2.innerHTML = html;
        }

        function updateExchanges(marketData) {
            const container = document.getElementById('exchanges-grid');
            const exchanges = Object.keys(marketData);

            if (exchanges.length === 0) {
                container.innerHTML = '<div class="no-data">暫無交易所數據</div>';
                return;
            }

            container.innerHTML = exchanges.map(exchange => {
                const symbols = Object.keys(marketData[exchange] || {});
                return symbols.map(symbol => {
                    const data = marketData[exchange][symbol];
                    if (!data) return '';

                    return `
                        <div class="exchange-card">
                            <div class="exchange-header">
                                <div class="exchange-name">${exchange}</div>
                            </div>
                            <div class="exchange-body">
                                <div style="font-size: 14px; color: #9ca3af; margin-bottom: 10px;">${symbol}</div>
                                ${data.error ? `<div style="color: #ef4444;">${data.error}</div>` : `
                                    <div class="price-row">
                                        <span>最佳買價</span>
                                        <span style="color: #10b981;">$${data.best_bid?.toFixed(2) || 'N/A'}</span>
                                    </div>
                                    <div class="price-row">
                                        <span>最佳賣價</span>
                                        <span style="color: #ef4444;">$${data.best_ask?.toFixed(2) || 'N/A'}</span>
                                    </div>
                                    <div class="price-row">
                                        <span>價差</span>
                                        <span style="color: #60a5fa;">${data.spread_pct?.toFixed(4) || 'N/A'}%</span>
                                    </div>
                                `}
                            </div>
                        </div>
                    `;
                }).join('');
            }).join('');
        }

        // Config Management
        async function loadConfigPage() {
            const dexList = ['StandX', 'GRVT'];
            const cexList = ['Binance', 'OKX', 'Bitget', 'Bybit'];

            const response = await fetch('/api/configs');
            const configs = await response.json();

            document.getElementById('dex-list').innerHTML = dexList.map(ex => {
                const configured = configs.dex[ex.toLowerCase()] !== undefined;
                return `
                    <div class="exchange-item ${configured ? 'configured' : ''}" onclick="openConfigModal('${ex}', 'dex')">
                        <div class="exchange-item-header">
                            <div class="exchange-item-name">${ex}</div>
                            ${configured ? '<div class="config-badge">已配置</div>' : ''}
                        </div>
                        <div class="exchange-item-status">${configured ? '點擊編輯配置' : '點擊添加配置'}</div>
                    </div>
                `;
            }).join('');

            document.getElementById('cex-list').innerHTML = cexList.map(ex => {
                const configured = configs.cex[ex.toLowerCase()] !== undefined;
                return `
                    <div class="exchange-item ${configured ? 'configured' : ''}" onclick="openConfigModal('${ex}', 'cex')">
                        <div class="exchange-item-header">
                            <div class="exchange-item-name">${ex}</div>
                            ${configured ? '<div class="config-badge">已配置</div>' : ''}
                        </div>
                        <div class="exchange-item-status">${configured ? '點擊編輯配置' : '點擊添加配置'}</div>
                    </div>
                `;
            }).join('');
        }

        function openConfigModal(exchange, type) {
            currentExchange = { name: exchange, type: type };
            document.getElementById('modal-title').textContent = `配置 ${exchange}`;

            // Generate form fields based on exchange type
            const fields = getConfigFields(exchange, type);
            document.getElementById('form-fields').innerHTML = fields;

            document.getElementById('config-modal').classList.add('active');
        }

        function closeModal() {
            document.getElementById('config-modal').classList.remove('active');
            currentExchange = null;
        }

        function getConfigFields(exchange, type) {
            if (type === 'dex') {
                if (exchange === 'StandX') {
                    return `
                        <div class="form-group">
                            <label class="form-label">Private Key *</label>
                            <input type="password" name="private_key" class="form-input" required>
                        </div>
                        <div class="form-group">
                            <label class="form-label">Wallet Address *</label>
                            <input type="text" name="wallet_address" class="form-input" required>
                        </div>
                    `;
                } else {
                    return `
                        <div class="form-group">
                            <label class="form-label">API Key *</label>
                            <input type="text" name="api_key" class="form-input" required>
                        </div>
                        <div class="form-group">
                            <label class="form-label">API Secret *</label>
                            <input type="password" name="api_secret" class="form-input" required>
                        </div>
                    `;
                }
            } else {
                let html = `
                    <div class="form-group">
                        <label class="form-label">API Key *</label>
                        <input type="text" name="api_key" class="form-input" required>
                    </div>
                    <div class="form-group">
                        <label class="form-label">API Secret *</label>
                        <input type="password" name="api_secret" class="form-input" required>
                    </div>
                `;

                if (['OKX', 'Bitget'].includes(exchange)) {
                    html += `
                        <div class="form-group">
                            <label class="form-label">Passphrase *</label>
                            <input type="password" name="passphrase" class="form-input" required>
                        </div>
                    `;
                }

                return html;
            }
        }

        document.getElementById('config-form').addEventListener('submit', async (e) => {
            e.preventDefault();

            const formData = new FormData(e.target);
            const config = {};
            for (let [key, value] of formData.entries()) {
                config[key] = value;
            }

            const response = await fetch('/api/configs', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    exchange_name: currentExchange.name.toLowerCase(),
                    exchange_type: currentExchange.type,
                    config: config,
                    testnet: false
                })
            });

            if (response.ok) {
                alert('配置保存成功！');
                closeModal();
                loadConfigPage();
            } else {
                alert('配置保存失敗！');
            }
        });

        async function deleteConfig() {
            if (!confirm('確定要刪除此配置嗎？')) return;

            const response = await fetch(`/api/configs/${currentExchange.name.toLowerCase()}`, {
                method: 'DELETE'
            });

            if (response.ok) {
                alert('配置已刪除！');
                closeModal();
                loadConfigPage();
            } else {
                alert('刪除失敗！');
            }
        }

        // Initialize
        connectWebSocket();
        setInterval(() => {
            const runtime = Math.floor((Date.now() - startTime) / 1000);
            const hours = Math.floor(runtime / 3600).toString().padStart(2, '0');
            const minutes = Math.floor((runtime % 3600) / 60).toString().padStart(2, '0');
            const seconds = (runtime % 60).toString().padStart(2, '0');
            document.getElementById('overview-runtime').textContent = `${hours}:${minutes}:${seconds}`;
        }, 1000);
    </script>
</body>
</html>
"""


# Config Management
class ConfigManager:
    def __init__(self):
        self.env_file = Path(__file__).parent.parent.parent / ".env"
        if not self.env_file.exists():
            self.env_file.touch()

    def get_all_configs(self):
        """獲取所有配置"""
        load_dotenv(self.env_file)

        configs = {
            'dex': {},
            'cex': {}
        }

        # DEX configs
        if os.getenv('WALLET_PRIVATE_KEY'):
            configs['dex']['standx'] = {'configured': True}
        if os.getenv('GRVT_API_KEY'):
            configs['dex']['grvt'] = {'configured': True}

        # CEX configs
        for exchange in ['binance', 'okx', 'bitget', 'bybit']:
            if os.getenv(f'{exchange.upper()}_API_KEY'):
                configs['cex'][exchange] = {'configured': True}

        return configs

    def save_config(self, exchange_name: str, exchange_type: str, config: dict, testnet: bool = False):
        """保存配置"""
        exchange_name = exchange_name.lower()

        if exchange_type == 'dex':
            if exchange_name == 'standx':
                set_key(self.env_file, 'WALLET_PRIVATE_KEY', config.get('private_key', ''))
                set_key(self.env_file, 'WALLET_ADDRESS', config.get('wallet_address', ''))
            else:
                prefix = exchange_name.upper()
                set_key(self.env_file, f'{prefix}_API_KEY', config.get('api_key', ''))
                set_key(self.env_file, f'{prefix}_API_SECRET', config.get('api_secret', ''))
        else:
            prefix = exchange_name.upper()
            set_key(self.env_file, f'{prefix}_API_KEY', config.get('api_key', ''))
            set_key(self.env_file, f'{prefix}_API_SECRET', config.get('api_secret', ''))
            if 'passphrase' in config:
                set_key(self.env_file, f'{prefix}_PASSPHRASE', config['passphrase'])

        set_key(self.env_file, f'{exchange_name.upper()}_TESTNET', str(testnet).lower())

    def delete_config(self, exchange_name: str):
        """刪除配置"""
        exchange_name = exchange_name.lower()
        prefix = exchange_name.upper()

        # Try to delete all possible keys
        for key in [f'{prefix}_API_KEY', f'{prefix}_API_SECRET', f'{prefix}_PASSPHRASE',
                    f'{prefix}_TESTNET', 'WALLET_PRIVATE_KEY', 'WALLET_ADDRESS']:
            try:
                unset_key(self.env_file, key)
            except:
                pass


config_manager = ConfigManager()


async def get_dashboard():
    """返回統一儀表板 HTML"""
    return HTML_TEMPLATE


async def get_configs():
    """獲取所有配置"""
    return JSONResponse(config_manager.get_all_configs())


async def save_config(request: Request):
    """保存配置"""
    data = await request.json()
    config_manager.save_config(
        data['exchange_name'],
        data['exchange_type'],
        data['config'],
        data.get('testnet', False)
    )
    return JSONResponse({'success': True})


async def delete_config_endpoint(exchange_name: str):
    """刪除配置"""
    config_manager.delete_config(exchange_name)
    return JSONResponse({'success': True})


async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 連接處理"""
    await websocket.accept()
    connected_clients.append(websocket)
    print(f"✅ Client connected. Total: {len(connected_clients)}")

    try:
        while True:
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        connected_clients.remove(websocket)
        print(f"❌ Client disconnected. Total: {len(connected_clients)}")


async def broadcast_data():
    """廣播數據"""
    while True:
        try:
            if monitor is None or len(connected_clients) == 0:
                await asyncio.sleep(1)
                continue

            # 收集數據
            market_data = {}
            for exchange_name, data_dict in monitor.latest_data.items():
                market_data[exchange_name] = {}
                for symbol, md in data_dict.items():
                    market_data[exchange_name][symbol] = {
                        "best_bid": float(md.best_bid) if md.best_bid else None,
                        "best_ask": float(md.best_ask) if md.best_ask else None,
                        "spread_pct": float(md.spread_pct) if md.spread_pct else None,
                    }

            opportunities = []
            for opp in monitor.opportunities:
                opportunities.append({
                    "symbol": opp["symbol"],
                    "buy_exchange": opp["buy_exchange"],
                    "sell_exchange": opp["sell_exchange"],
                    "buy_price": float(opp["buy_price"]),
                    "sell_price": float(opp["sell_price"]),
                    "profit": float(opp["profit"]),
                    "profit_pct": float(opp["profit_pct"]),
                })

            data = {
                "timestamp": datetime.now().isoformat(),
                "exchanges": list(monitor.adapters.keys()),
                "symbols": monitor.symbols,
                "market_data": market_data,
                "opportunities": opportunities,
                "total_opportunities": monitor.total_opportunities_found,
            }

            # 廣播
            disconnected = []
            for client in connected_clients:
                try:
                    await client.send_json(data)
                except:
                    disconnected.append(client)

            for client in disconnected:
                if client in connected_clients:
                    connected_clients.remove(client)

            await asyncio.sleep(1)

        except Exception as e:
            print(f"❌ Broadcast error: {e}")
            await asyncio.sleep(2)


async def initialize_monitor():
    """初始化監控系統"""
    global monitor

    load_dotenv()

    symbols_config = {
        'cex': ['BTC/USDT:USDT', 'ETH/USDT:USDT'],
        'dex': ['BTC-USD', 'ETH-USD']
    }

    dex_exchanges = ['standx', 'grvt']
    cex_exchanges = ['binance', 'okx', 'bitget', 'bybit']

    adapters = {}
    symbols = []

    print("🔌 連接交易所...")

    # DEX
    for exchange in dex_exchanges:
        try:
            if exchange == 'standx' and not os.getenv('WALLET_PRIVATE_KEY'):
                continue
            if exchange == 'grvt' and not os.getenv('GRVT_API_KEY'):
                continue

            config = {
                'exchange_name': exchange,
                'testnet': os.getenv(f'{exchange.upper()}_TESTNET', 'false').lower() == 'true'
            }

            adapter = create_adapter(config)
            adapters[exchange.upper()] = adapter
            symbols.extend(symbols_config['dex'])
            print(f"  ✅ {exchange.upper()}")
        except Exception as e:
            print(f"  ⚠️  {exchange.upper()}: {e}")

    # CEX
    for exchange in cex_exchanges:
        try:
            api_key = os.getenv(f'{exchange.upper()}_API_KEY')
            if not api_key:
                continue

            config = {
                'exchange_name': exchange,
                'api_key': api_key,
                'api_secret': os.getenv(f'{exchange.upper()}_API_SECRET'),
                'testnet': os.getenv(f'{exchange.upper()}_TESTNET', 'false').lower() == 'true'
            }

            if exchange in ['okx', 'bitget']:
                passphrase = os.getenv(f'{exchange.upper()}_PASSPHRASE')
                if passphrase:
                    config['passphrase'] = passphrase

            adapter = create_adapter(config)
            adapters[exchange.upper()] = adapter
            if symbols_config['cex'] not in symbols:
                symbols.extend(symbols_config['cex'])
            print(f"  ✅ {exchange.upper()}")
        except Exception as e:
            print(f"  ⚠️  {exchange.upper()}: {e}")

    if adapters:
        symbols = list(set(symbols))
        monitor = MultiExchangeMonitor(
            adapters=adapters,
            symbols=symbols,
            update_interval=2.0,
            min_profit_pct=0.1
        )
        asyncio.create_task(monitor.start())
        print(f"\n✅ 監控已啟動: {len(adapters)} 個交易所\n")
    else:
        print("\n⚠️  無可用交易所，請先配置\n")


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """生命週期管理"""
    await initialize_monitor()
    task = asyncio.create_task(broadcast_data())
    print("🚀 Unified Dashboard started")
    yield
    task.cancel()
    if monitor:
        await monitor.stop()
    print("👋 Unified Dashboard stopped")


# Create app
app = FastAPI(title="Unified Arbitrage Dashboard", lifespan=lifespan)

# Routes
app.get("/", response_class=HTMLResponse)(get_dashboard)
app.get("/api/configs")(get_configs)
app.post("/api/configs")(save_config)
app.delete("/api/configs/{exchange_name}")(delete_config_endpoint)
app.websocket("/ws")(websocket_endpoint)


def run_dashboard(host: str = "127.0.0.1", port: int = 8888):
    """啟動統一儀表板"""
    print(f"\n{'='*60}")
    print(f"🚀 Starting Unified Dashboard")
    print(f"{'='*60}")
    print(f"📡 Server: http://{host}:{port}")
    print(f"🌐 Open your browser and visit the URL above")
    print(f"{'='*60}\n")

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_dashboard()
