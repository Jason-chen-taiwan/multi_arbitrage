"""
配置管理 Dashboard
Configuration Management Dashboard

提供 Web 界面來管理交易所 API 配置，無需直接編輯 .env 文件
"""
import os
import json
from pathlib import Path
from typing import Dict, Any, Optional
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn
from dotenv import load_dotenv, set_key, unset_key


# 配置文件路徑
ENV_FILE = Path(__file__).parent.parent.parent / ".env"
CONFIG_FILE = Path(__file__).parent.parent.parent / "config" / "exchanges.json"


class ExchangeConfig(BaseModel):
    """交易所配置模型"""
    exchange_name: str
    exchange_type: str  # 'dex' or 'cex'
    enabled: bool = True
    testnet: bool = False
    config: Dict[str, str]  # 具體配置（API key, secret 等）


class ConfigManager:
    """配置管理器"""

    def __init__(self):
        self.env_file = ENV_FILE
        self.config_file = CONFIG_FILE
        self.config_file.parent.mkdir(exist_ok=True)

        # 加載環境變量
        load_dotenv(self.env_file)

    def get_all_configs(self) -> Dict[str, Any]:
        """獲取所有交易所配置"""
        configs = {
            'dex': {},
            'cex': {}
        }

        # StandX
        if os.getenv('WALLET_PRIVATE_KEY'):
            configs['dex']['standx'] = {
                'enabled': True,
                'testnet': False,
                'config': {
                    'wallet_private_key': self._mask_secret(os.getenv('WALLET_PRIVATE_KEY', '')),
                    'wallet_address': os.getenv('WALLET_ADDRESS', ''),
                    'chain': os.getenv('CHAIN', 'bsc'),
                    'base_url': os.getenv('STANDX_BASE_URL', 'https://api.standx.com'),
                    'perps_url': os.getenv('STANDX_PERPS_URL', 'https://perps.standx.com')
                }
            }

        # GRVT
        if os.getenv('GRVT_API_KEY'):
            configs['dex']['grvt'] = {
                'enabled': True,
                'testnet': os.getenv('GRVT_TESTNET', 'false').lower() == 'true',
                'config': {
                    'api_key': self._mask_secret(os.getenv('GRVT_API_KEY', '')),
                    'api_secret': self._mask_secret(os.getenv('GRVT_API_SECRET', '')),
                    'base_url': os.getenv('GRVT_BASE_URL', 'https://api.grvt.io')
                }
            }

        # Binance
        if os.getenv('BINANCE_API_KEY'):
            configs['cex']['binance'] = {
                'enabled': True,
                'testnet': os.getenv('BINANCE_TESTNET', 'false').lower() == 'true',
                'config': {
                    'api_key': self._mask_secret(os.getenv('BINANCE_API_KEY', '')),
                    'api_secret': self._mask_secret(os.getenv('BINANCE_API_SECRET', ''))
                }
            }

        # OKX
        if os.getenv('OKX_API_KEY'):
            configs['cex']['okx'] = {
                'enabled': True,
                'testnet': os.getenv('OKX_TESTNET', 'false').lower() == 'true',
                'config': {
                    'api_key': self._mask_secret(os.getenv('OKX_API_KEY', '')),
                    'api_secret': self._mask_secret(os.getenv('OKX_API_SECRET', '')),
                    'passphrase': self._mask_secret(os.getenv('OKX_PASSPHRASE', ''))
                }
            }

        # Bitget
        if os.getenv('BITGET_API_KEY'):
            configs['cex']['bitget'] = {
                'enabled': True,
                'testnet': os.getenv('BITGET_TESTNET', 'false').lower() == 'true',
                'config': {
                    'api_key': self._mask_secret(os.getenv('BITGET_API_KEY', '')),
                    'api_secret': self._mask_secret(os.getenv('BITGET_API_SECRET', '')),
                    'passphrase': self._mask_secret(os.getenv('BITGET_PASSPHRASE', ''))
                }
            }

        # Bybit
        if os.getenv('BYBIT_API_KEY'):
            configs['cex']['bybit'] = {
                'enabled': True,
                'testnet': os.getenv('BYBIT_TESTNET', 'false').lower() == 'true',
                'config': {
                    'api_key': self._mask_secret(os.getenv('BYBIT_API_KEY', '')),
                    'api_secret': self._mask_secret(os.getenv('BYBIT_API_SECRET', ''))
                }
            }

        return configs

    def save_exchange_config(self, exchange_name: str, exchange_type: str, config: Dict[str, str], testnet: bool = False):
        """保存交易所配置"""
        exchange_name = exchange_name.lower()
        prefix = exchange_name.upper()

        # 根據交易所類型保存不同的配置
        if exchange_type == 'dex':
            if exchange_name == 'standx':
                self._set_env('WALLET_PRIVATE_KEY', config.get('wallet_private_key', ''))
                self._set_env('WALLET_ADDRESS', config.get('wallet_address', ''))
                self._set_env('CHAIN', config.get('chain', 'bsc'))
                self._set_env('STANDX_BASE_URL', config.get('base_url', 'https://api.standx.com'))
                self._set_env('STANDX_PERPS_URL', config.get('perps_url', 'https://perps.standx.com'))

            elif exchange_name == 'grvt':
                self._set_env('GRVT_API_KEY', config.get('api_key', ''))
                self._set_env('GRVT_API_SECRET', config.get('api_secret', ''))
                self._set_env('GRVT_BASE_URL', config.get('base_url', 'https://api.grvt.io'))
                self._set_env('GRVT_TESTNET', str(testnet).lower())

        elif exchange_type == 'cex':
            self._set_env(f'{prefix}_API_KEY', config.get('api_key', ''))
            self._set_env(f'{prefix}_API_SECRET', config.get('api_secret', ''))

            # OKX 和 Bitget 需要 passphrase
            if exchange_name in ['okx', 'bitget']:
                self._set_env(f'{prefix}_PASSPHRASE', config.get('passphrase', ''))

            self._set_env(f'{prefix}_TESTNET', str(testnet).lower())

        # 重新加載環境變量
        load_dotenv(self.env_file, override=True)

    def delete_exchange_config(self, exchange_name: str, exchange_type: str):
        """刪除交易所配置"""
        exchange_name = exchange_name.lower()
        prefix = exchange_name.upper()

        if exchange_type == 'dex':
            if exchange_name == 'standx':
                self._unset_env('WALLET_PRIVATE_KEY')
                self._unset_env('WALLET_ADDRESS')
                self._unset_env('CHAIN')
                self._unset_env('STANDX_BASE_URL')
                self._unset_env('STANDX_PERPS_URL')
            elif exchange_name == 'grvt':
                self._unset_env('GRVT_API_KEY')
                self._unset_env('GRVT_API_SECRET')
                self._unset_env('GRVT_BASE_URL')
                self._unset_env('GRVT_TESTNET')

        elif exchange_type == 'cex':
            self._unset_env(f'{prefix}_API_KEY')
            self._unset_env(f'{prefix}_API_SECRET')
            if exchange_name in ['okx', 'bitget']:
                self._unset_env(f'{prefix}_PASSPHRASE')
            self._unset_env(f'{prefix}_TESTNET')

        # 重新加載環境變量
        load_dotenv(self.env_file, override=True)

    def _set_env(self, key: str, value: str):
        """設置環境變量"""
        set_key(str(self.env_file), key, value)

    def _unset_env(self, key: str):
        """刪除環境變量"""
        unset_key(str(self.env_file), key)

    def _mask_secret(self, secret: str) -> str:
        """遮蔽敏感信息"""
        if not secret or len(secret) < 8:
            return '****'
        return secret[:4] + '****' + secret[-4:]


# 創建 FastAPI 應用
app = FastAPI(title="Exchange Configuration Manager")
config_manager = ConfigManager()


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>交易所配置管理 - Configuration Manager</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
            min-height: 100vh;
        }

        .container {
            max-width: 1200px;
            margin: 0 auto;
        }

        .header {
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            margin-bottom: 30px;
        }

        h1 {
            color: #667eea;
            margin-bottom: 10px;
        }

        .section {
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }

        .section h2 {
            color: #667eea;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #667eea;
        }

        .exchange-card {
            border: 1px solid #e2e8f0;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            position: relative;
        }

        .exchange-card.configured {
            border-left: 4px solid #10b981;
        }

        .exchange-card.not-configured {
            border-left: 4px solid #ef4444;
        }

        .exchange-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }

        .exchange-name {
            font-size: 18px;
            font-weight: 600;
            color: #1a202c;
        }

        .status-badge {
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }

        .status-configured {
            background: #d1fae5;
            color: #065f46;
        }

        .status-not-configured {
            background: #fee2e2;
            color: #991b1b;
        }

        .config-form {
            display: grid;
            gap: 15px;
            margin-top: 15px;
        }

        .form-group {
            display: flex;
            flex-direction: column;
            gap: 5px;
        }

        .form-group label {
            font-size: 14px;
            font-weight: 500;
            color: #4a5568;
        }

        .form-group input {
            padding: 10px;
            border: 1px solid #cbd5e0;
            border-radius: 5px;
            font-size: 14px;
        }

        .form-group input:focus {
            outline: none;
            border-color: #667eea;
        }

        .checkbox-group {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .button-group {
            display: flex;
            gap: 10px;
            margin-top: 15px;
        }

        button {
            padding: 10px 20px;
            border: none;
            border-radius: 5px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }

        .btn-primary {
            background: #667eea;
            color: white;
        }

        .btn-primary:hover {
            background: #5568d3;
        }

        .btn-secondary {
            background: #e2e8f0;
            color: #4a5568;
        }

        .btn-secondary:hover {
            background: #cbd5e0;
        }

        .btn-danger {
            background: #ef4444;
            color: white;
        }

        .btn-danger:hover {
            background: #dc2626;
        }

        .config-details {
            margin-top: 15px;
            padding: 15px;
            background: #f7fafc;
            border-radius: 5px;
        }

        .config-item {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #e2e8f0;
        }

        .config-item:last-child {
            border-bottom: none;
        }

        .config-label {
            font-weight: 500;
            color: #4a5568;
        }

        .config-value {
            color: #1a202c;
            font-family: monospace;
        }

        .alert {
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
        }

        .alert-success {
            background: #d1fae5;
            color: #065f46;
            border-left: 4px solid #10b981;
        }

        .alert-error {
            background: #fee2e2;
            color: #991b1b;
            border-left: 4px solid #ef4444;
        }

        .hidden {
            display: none;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⚙️ 交易所配置管理</h1>
            <p style="color: #666; margin-top: 10px;">Exchange Configuration Manager</p>
            <p style="color: #999; font-size: 14px; margin-top: 5px;">
                安全地管理您的交易所 API 配置，無需直接編輯配置文件
            </p>
        </div>

        <div id="alert" class="alert hidden"></div>

        <!-- DEX Section -->
        <div class="section">
            <h2>🏦 去中心化交易所 (DEX)</h2>
            <div id="dex-exchanges"></div>
        </div>

        <!-- CEX Section -->
        <div class="section">
            <h2>🏢 中心化交易所 (CEX)</h2>
            <div id="cex-exchanges"></div>
        </div>
    </div>

    <script>
        let allConfigs = {};

        // 交易所模板定義
        const exchangeTemplates = {
            dex: {
                standx: {
                    name: 'StandX',
                    fields: [
                        { key: 'wallet_private_key', label: 'Wallet Private Key', type: 'password', required: true },
                        { key: 'wallet_address', label: 'Wallet Address', type: 'text', required: false },
                        { key: 'chain', label: 'Chain', type: 'text', required: true, default: 'bsc' },
                        { key: 'base_url', label: 'Base URL', type: 'text', required: false, default: 'https://api.standx.com' },
                        { key: 'perps_url', label: 'Perps URL', type: 'text', required: false, default: 'https://perps.standx.com' }
                    ]
                },
                grvt: {
                    name: 'GRVT',
                    fields: [
                        { key: 'api_key', label: 'API Key', type: 'password', required: true },
                        { key: 'api_secret', label: 'API Secret', type: 'password', required: true },
                        { key: 'base_url', label: 'Base URL', type: 'text', required: false, default: 'https://api.grvt.io' }
                    ],
                    testnet: true
                }
            },
            cex: {
                binance: {
                    name: 'Binance',
                    fields: [
                        { key: 'api_key', label: 'API Key', type: 'password', required: true },
                        { key: 'api_secret', label: 'API Secret', type: 'password', required: true }
                    ],
                    testnet: true
                },
                okx: {
                    name: 'OKX',
                    fields: [
                        { key: 'api_key', label: 'API Key', type: 'password', required: true },
                        { key: 'api_secret', label: 'API Secret', type: 'password', required: true },
                        { key: 'passphrase', label: 'Passphrase', type: 'password', required: true }
                    ],
                    testnet: true
                },
                bitget: {
                    name: 'Bitget',
                    fields: [
                        { key: 'api_key', label: 'API Key', type: 'password', required: true },
                        { key: 'api_secret', label: 'API Secret', type: 'password', required: true },
                        { key: 'passphrase', label: 'Passphrase', type: 'password', required: true }
                    ],
                    testnet: true
                },
                bybit: {
                    name: 'Bybit',
                    fields: [
                        { key: 'api_key', label: 'API Key', type: 'password', required: true },
                        { key: 'api_secret', label: 'API Secret', type: 'password', required: true }
                    ],
                    testnet: true
                }
            }
        };

        // 加載配置
        async function loadConfigs() {
            try {
                const response = await fetch('/api/configs');
                allConfigs = await response.json();
                renderExchanges();
            } catch (error) {
                showAlert('Failed to load configurations', 'error');
            }
        }

        // 渲染交易所列表
        function renderExchanges() {
            // 渲染 DEX
            const dexContainer = document.getElementById('dex-exchanges');
            dexContainer.innerHTML = '';
            for (const [id, template] of Object.entries(exchangeTemplates.dex)) {
                const config = allConfigs.dex[id];
                dexContainer.innerHTML += createExchangeCard(id, 'dex', template, config);
            }

            // 渲染 CEX
            const cexContainer = document.getElementById('cex-exchanges');
            cexContainer.innerHTML = '';
            for (const [id, template] of Object.entries(exchangeTemplates.cex)) {
                const config = allConfigs.cex[id];
                cexContainer.innerHTML += createExchangeCard(id, 'cex', template, config);
            }
        }

        // 創建交易所卡片
        function createExchangeCard(id, type, template, config) {
            const isConfigured = config && config.config;
            const statusClass = isConfigured ? 'configured' : 'not-configured';
            const statusBadge = isConfigured ?
                '<span class="status-badge status-configured">✓ 已配置</span>' :
                '<span class="status-badge status-not-configured">未配置</span>';

            let html = `
                <div class="exchange-card ${statusClass}">
                    <div class="exchange-header">
                        <span class="exchange-name">${template.name}</span>
                        ${statusBadge}
                    </div>
            `;

            if (isConfigured) {
                // 顯示配置詳情
                html += '<div class="config-details">';
                for (const field of template.fields) {
                    const value = config.config[field.key] || '';
                    html += `
                        <div class="config-item">
                            <span class="config-label">${field.label}:</span>
                            <span class="config-value">${value}</span>
                        </div>
                    `;
                }
                if (template.testnet && config.testnet) {
                    html += `
                        <div class="config-item">
                            <span class="config-label">Testnet:</span>
                            <span class="config-value">✓ Enabled</span>
                        </div>
                    `;
                }
                html += '</div>';
                html += `
                    <div class="button-group">
                        <button class="btn-secondary" onclick="editExchange('${id}', '${type}')">編輯</button>
                        <button class="btn-danger" onclick="deleteExchange('${id}', '${type}')">刪除</button>
                    </div>
                `;
            } else {
                // 顯示配置表單
                html += `<form id="form-${id}" class="config-form">`;
                for (const field of template.fields) {
                    html += `
                        <div class="form-group">
                            <label>${field.label}${field.required ? ' *' : ''}:</label>
                            <input
                                type="${field.type}"
                                name="${field.key}"
                                value="${field.default || ''}"
                                ${field.required ? 'required' : ''}
                                placeholder="${field.label}"
                            />
                        </div>
                    `;
                }
                if (template.testnet) {
                    html += `
                        <div class="checkbox-group">
                            <input type="checkbox" id="testnet-${id}" name="testnet" />
                            <label for="testnet-${id}">使用測試網 (Testnet)</label>
                        </div>
                    `;
                }
                html += `
                    <div class="button-group">
                        <button type="button" class="btn-primary" onclick="saveExchange('${id}', '${type}')">保存配置</button>
                    </div>
                </form>
                `;
            }

            html += '</div>';
            return html;
        }

        // 保存交易所配置
        async function saveExchange(id, type) {
            const form = document.getElementById(`form-${id}`);
            const formData = new FormData(form);
            const config = {};

            for (const [key, value] of formData.entries()) {
                if (key !== 'testnet') {
                    config[key] = value;
                }
            }

            const testnet = formData.get('testnet') === 'on';

            try {
                const response = await fetch('/api/configs', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        exchange_name: id,
                        exchange_type: type,
                        config: config,
                        testnet: testnet
                    })
                });

                if (response.ok) {
                    showAlert(`${id.toUpperCase()} 配置已保存`, 'success');
                    loadConfigs();
                } else {
                    showAlert('保存配置失敗', 'error');
                }
            } catch (error) {
                showAlert('保存配置失敗: ' + error, 'error');
            }
        }

        // 編輯交易所配置
        function editExchange(id, type) {
            // TODO: 實現編輯功能
            showAlert('編輯功能開發中...', 'error');
        }

        // 刪除交易所配置
        async function deleteExchange(id, type) {
            if (!confirm(`確定要刪除 ${id.toUpperCase()} 的配置嗎？`)) {
                return;
            }

            try {
                const response = await fetch(`/api/configs/${id}?type=${type}`, {
                    method: 'DELETE'
                });

                if (response.ok) {
                    showAlert(`${id.toUpperCase()} 配置已刪除`, 'success');
                    loadConfigs();
                } else {
                    showAlert('刪除配置失敗', 'error');
                }
            } catch (error) {
                showAlert('刪除配置失敗: ' + error, 'error');
            }
        }

        // 顯示提示信息
        function showAlert(message, type) {
            const alert = document.getElementById('alert');
            alert.textContent = message;
            alert.className = `alert alert-${type}`;
            alert.classList.remove('hidden');

            setTimeout(() => {
                alert.classList.add('hidden');
            }, 5000);
        }

        // 初始化
        loadConfigs();
    </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def get_config_page():
    """返回配置管理頁面"""
    return HTML_TEMPLATE


@app.get("/api/configs")
async def get_configs():
    """獲取所有配置"""
    return config_manager.get_all_configs()


@app.post("/api/configs")
async def save_config(config: ExchangeConfig):
    """保存配置"""
    try:
        config_manager.save_exchange_config(
            config.exchange_name,
            config.exchange_type,
            config.config,
            config.testnet
        )
        return {"success": True, "message": "Configuration saved"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/configs/{exchange_name}")
async def delete_config(exchange_name: str, type: str):
    """刪除配置"""
    try:
        config_manager.delete_exchange_config(exchange_name, type)
        return {"success": True, "message": "Configuration deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def run_config_dashboard(host: str = "127.0.0.1", port: int = 8001):
    """啟動配置管理 Dashboard"""
    print(f"\n{'='*60}")
    print(f"⚙️  Starting Configuration Manager")
    print(f"{'='*60}")
    print(f"📡 Server: http://{host}:{port}")
    print(f"🌐 Open your browser and configure your exchanges")
    print(f"{'='*60}\n")

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_config_dashboard()
