# 多交易所永續合約交易系統

一個專業的自動化做市商（Market Maker）系統，支持多個永續合約交易所，提供雙邊掛單、價差管理、庫存控制和風險管理功能。

## 支持的交易所

### 去中心化交易所（DEX）

- ✅ **StandX** - 完整支持（包括 Uptime Program 優化）
- ✅ **GRVT** - 適配器已實現（需要配置）
- 🔄 **其他 DEX** - 易於擴展（參見[添加新交易所指南](docs/ADDING_NEW_EXCHANGES.md)）

### 中心化交易所（CEX）- 通過 CCXT

- ✅ **Binance** - 全球最大交易量，最高 125x 槓桿
- ✅ **OKX** - 綜合衍生品平台，最高 125x 槓桿
- ✅ **Bitget** - 跟單交易領先，最高 125x 槓桿
- ✅ **Bybit** - 專業衍生品，最高 100x 槓桿
- ✅ **Gate.io** - 多樣化產品，最高 100x 槓桿
- ✅ **其他 100+ CEX** - 通過 [CCXT](https://github.com/ccxt/ccxt) 支持

詳見：📖 [CEX 集成指南](docs/CEX_INTEGRATION_GUIDE.md)

## 系統特點

### 🎁 StandX Market Maker Uptime Program 整合

本系統已針對 **StandX 做市商正常運行時間計劃** 進行優化：

- 💰 **被動收入**：每月 500 萬代幣獎勵池
- 🎯 **自動符合條件**：維持 10 bps 價差內的雙邊掛單
- ⏱️ **正常運行時間追蹤**：70%+ 正常運行時間 = 1.0x 乘數（Boosted 層級）
- 💎 **手續費折扣**：累積 360+ 小時（MM1）或 504+ 小時（MM2）解鎖特殊費率
  - MM1: 2.25 bps taker fee + 0.25 bps maker rebate
  - MM2: 2.00 bps taker fee + 0.50 bps maker rebate
- 📊 **最大化 Maker Hours**：智能訂單大小管理（最高 2 BTC）

### 核心功能

- ✅ **多交易所支持**：統一適配器接口，輕鬆添加新交易所
- ✅ **雙邊做市**：同時在買賣兩側提供流動性
- ✅ **動態價差管理**：根據市場波動率自動調整價差（符合 10 bps 要求）
- ✅ **庫存控制**：智能管理持倉偏移，避免單邊風險
- ✅ **風險管理**：實時監控倉位、PnL 和風險指標
- ✅ **跨交易所套利**：同時連接多個交易所，尋找套利機會
- ✅ **正常運行時間優化**：自動維持 70%+ 正常運行時間以獲得最大獎勵
- ✅ **WebSocket 實時更新**：即時接收訂單狀態和市場數據

### 做市策略

1. **基礎做市策略**：固定價差的簡單雙邊報價
2. **自適應做市策略**：根據市場條件動態調整
3. **Uptime 優化策略**：專門針對 StandX Uptime Program 優化（推薦）
   - 嚴格 10 bps 價差控制
   - 最大化訂單大小（2 BTC）
   - 70%+ 正常運行時間維護
   - 自動 Maker Hours 追蹤

## 多交易所架構

系統使用 **適配器模式（Adapter Pattern）** 來支持多個交易所，使得添加新交易所變得簡單：

```text
         Strategy Layer
              │
              ▼
    BasePerpAdapter (Interface)
              │
      ┌───────┴───────┬─────────┐
      ▼               ▼         ▼
   StandX          GRVT       其他...
   Adapter        Adapter     Adapter
```

### 快速測試多交易所

```bash
# 測試所有已配置的交易所並比較價格
python scripts/test_multi_exchange.py
```

輸出示例：

```text
📊 PRICE COMPARISON SUMMARY
Symbol: BTC-USD
--------------------------------------------------------------------------------
Exchange        Best Bid        Best Ask          Spread     Spread %
--------------------------------------------------------------------------------
STANDX          $95,123.50      $95,145.20         $21.70       0.0228%
GRVT            $95,125.80      $95,142.90         $17.10       0.0180%

💰 ARBITRAGE OPPORTUNITIES
STANDX ↔ GRVT:
  ✅ Buy on STANDX @ $95,145.20
     Sell on GRVT @ $95,125.80
     Profit: $-19.40 (-0.0204%)
```

### 添加新交易所

只需 3 步即可添加新交易所支持：

1. 創建適配器類（繼承 `BasePerpAdapter`）
2. 在 Factory 中註冊
3. 添加環境變量配置

詳細指南：📖 [添加新交易所指南](docs/ADDING_NEW_EXCHANGES.md)

## 🔍 實時套利監控系統

系統提供完整的 **跨交易所實時監控和套利檢測** 功能：

### 核心功能

- ✅ **實時價格監控**：並行監控多個交易所的 BTC/ETH 價格
- ✅ **訂單簿深度分析**：實時獲取最佳買賣價和深度
- ✅ **自動套利檢測**：智能檢測跨交易所套利機會
- ✅ **利潤計算**：考慮交易費用後的淨利潤
- ✅ **統計報告**：實時顯示市場數據和套利機會

### 啟動監控

```bash
# 使用統一啟動介面（推薦）
python arbitrage.py monitor

# 或直接運行監控腳本
python scripts/monitor_arbitrage.py
```

監控系統會：

1. 自動連接所有已配置的交易所（從 .env 讀取）
2. 實時獲取 BTC 和 ETH 永續合約價格
3. 每 2 秒更新一次價格數據
4. 自動檢測套利機會（利潤閾值：0.1%）
5. 每 10 秒顯示統計報告

### 輸出示例

```text
================================================================================
💰 ARBITRAGE OPPORTUNITIES DETECTED: 2
================================================================================

🔥 BTC/USDT:USDT Arbitrage:
  Buy:  BINANCE     @ $ 95,123.50 (size: 1.5)
  Sell: OKX         @ $ 95,245.20 (size: 1.2)
  💰 Profit: $  121.70 (0.1280%)
  📊 Max Qty: 1.2

🔥 ETH/USDT:USDT Arbitrage:
  Buy:  BITGET      @ $  3,245.80 (size: 10.0)
  Sell: BYBIT       @ $  3,251.50 (size: 8.5)
  💰 Profit: $    5.70 (0.1756%)
  📊 Max Qty: 8.5
================================================================================

================================================================================
📊 MONITOR STATISTICS
================================================================================
⏱️  Runtime: 2026-01-12 15:30:45
📈 Total Updates: 1,234
💰 Total Opportunities Found: 45

📊 Exchange Status:
  BINANCE         - Symbols: 2/2, Failures: 0
  OKX             - Symbols: 2/2, Failures: 0
  BITGET          - Symbols: 2/2, Failures: 1
  BYBIT           - Symbols: 2/2, Failures: 0

💵 Current Prices:

  BTC/USDT:USDT:
    BINANCE         - Bid: $ 95,123.50 | Ask: $ 95,145.20 | Spread: 0.0228%
    OKX             - Bid: $ 95,125.80 | Ask: $ 95,142.90 | Spread: 0.0180%
    BITGET          - Bid: $ 95,120.30 | Ask: $ 95,148.60 | Spread: 0.0298%
    BYBIT           - Bid: $ 95,124.70 | Ask: $ 95,144.10 | Spread: 0.0204%

  ETH/USDT:USDT:
    BINANCE         - Bid: $  3,245.80 | Ask: $  3,247.50 | Spread: 0.0524%
    OKX             - Bid: $  3,246.20 | Ask: $  3,247.10 | Spread: 0.0277%
================================================================================
```

### 配置選項

編輯 [scripts/monitor_arbitrage.py](scripts/monitor_arbitrage.py:42-44) 修改監控參數：

```python
# 配置要監控的交易對
symbols_config = {
    'cex': ['BTC/USDT:USDT', 'ETH/USDT:USDT'],  # CEX 符號
    'dex': ['BTC-USD', 'ETH-USD']  # DEX 符號
}

# 創建監控器
monitor = MultiExchangeMonitor(
    adapters=adapters,
    symbols=symbols,
    update_interval=2.0,  # 更新間隔（秒）
    min_profit_pct=0.1    # 最小套利利潤（%）
)
```

詳細指南：📖 [套利監控指南](docs/ARBITRAGE_MONITORING_GUIDE.md)

## 架構設計

```text
arbitrage/
├── src/
│   ├── auth/              # 認證模組
│   │   └── standx_auth.py # StandX 認證實現
│   ├── exchange/          # 交易所連接器
│   │   ├── base.py        # 基礎交易所介面
│   │   └── standx.py      # StandX API 實現
│   ├── strategy/          # 做市策略
│   │   ├── base.py        # 基礎策略類
│   │   ├── simple_mm.py   # 簡單做市策略
│   │   └── adaptive_mm.py # 自適應做市策略
│   ├── risk/              # 風險管理
│   │   ├── position.py    # 倉位管理
│   │   └── risk_manager.py # 風險控制器
│   ├── monitor/           # 監控系統
│   │   └── dashboard.py   # 實時監控面板
│   └── utils/             # 工具函數
│       ├── logger.py      # 日誌系統
│       └── metrics.py     # 性能指標
├── config/
│   ├── config.yaml        # 主配置文件
│   └── strategies.yaml    # 策略配置
├── tests/                 # 測試文件
├── scripts/               # 運行腳本
│   └── run_mm.py         # 啟動做市商
├── requirements.txt       # Python 依賴
└── .env.example          # 環境變數範例

```

## 做市商核心概念

### 1. 價差（Spread）

```python
# 中間價 = (最佳買價 + 最佳賣價) / 2
mid_price = (best_bid + best_ask) / 2

# 做市商報價
bid_price = mid_price * (1 - spread / 2)
ask_price = mid_price * (1 + spread / 2)
```

### 2. 庫存管理（Inventory Management）

```python
# 目標倉位：維持接近中性
target_position = 0

# 當前庫存偏移
inventory_skew = current_position - target_position

# 根據庫存調整價差
if inventory_skew > 0:  # 多頭過多
    bid_price -= inventory_adjustment
    ask_price -= inventory_adjustment
elif inventory_skew < 0:  # 空頭過多
    bid_price += inventory_adjustment
    ask_price += inventory_adjustment
```

### 3. 風險控制

- **最大倉位限制**：避免單邊風險過大
- **每日損失限制**：達到損失閾值後停止交易
- **訂單數量限制**：控制同時掛單數量
- **價格保護**：避免在不利價格成交

## 🚀 快速開始

**最簡單的方式** - 自動處理虛擬環境和依賴：

```bash
# 首次使用（賦予執行權限）
chmod +x start.sh

# 互動式選單（推薦）
./start.sh

# 或直接啟動特定功能
./start.sh dashboard   # Web UI 整合介面（推薦）
./start.sh monitor     # 終端監控（適合伺服器）
./start.sh test        # 測試交易所連接
./start.sh mm          # 做市商策略
```

start.sh 腳本會自動：

- ✅ 檢查並創建虛擬環境
- ✅ 安裝缺失的依賴
- ✅ 檢查並創建 .env 文件
- ✅ 啟動系統

### 手動啟動（進階用戶）

如果您想手動管理環境：

```bash
# 1. 安裝依賴
pip install -r requirements.txt

# 2. 啟動系統
python arbitrage.py              # 互動式選單
python arbitrage.py dashboard    # Web UI 整合介面（推薦）
python arbitrage.py monitor      # 終端監控
python arbitrage.py test         # 測試交易所連接
python arbitrage.py mm           # 做市商策略
```

### 配置交易所

#### 🌐 使用 Web Dashboard 配置（推薦）

```bash
# 啟動整合 Dashboard
python arbitrage.py dashboard
```

訪問 <http://localhost:8888>，點擊「⚙️ 配置管理」頁面：

- ✅ **視覺化配置**：無需手動編輯 .env
- ✅ **自動驗證**：確保配置正確性
- ✅ **安全遮罩**：憑證自動隱藏敏感部分
- ✅ **一鍵操作**：保存/刪除配置
- ✅ **支援所有交易所**：DEX (StandX, GRVT) + CEX (Binance, OKX, Bitget, Bybit)

#### 📝 或手動編輯 .env

```bash
cp .env.example .env
# 編輯 .env 填入您的配置
```

### 開始使用

配置完成後，Dashboard 提供 4 個功能頁面：

- **📊 總覽** - 實時統計和套利機會預覽
- **💰 套利監控** - 詳細的跨交易所套利數據
- **🏦 交易所狀態** - 所有交易所價格對比
- **⚙️ 配置管理** - 管理交易所 API 憑證

## 📋 系統功能詳解

### 🎯 整合 Web Dashboard（推薦）

**一站式 Web UI** - 所有功能整合在一個介面中！

```bash
./start.sh dashboard
# 或
python arbitrage.py dashboard
```

**訪問**: <http://localhost:8888>

**4 大功能頁面**:

#### 📊 系統總覽
- 實時統計數據（運行時間、更新次數、套利機會總數）
- 各交易所狀態摘要
- 最新套利機會預覽

#### 💰 套利監控
- 🎨 **現代化深色主題** - 專業金融 UI 設計
- 📊 **實時價格對比** - 並排顯示所有交易所價格
- 💰 **套利機會卡片** - 清晰顯示買賣雙方和利潤
- 📈 **詳細市場數據** - 訂單簿深度、價差百分比
- ⚡ **1秒刷新** - 超低延遲實時更新
- 🔄 **WebSocket 連接** - 高效的實時數據推送

#### 🏦 交易所狀態
- 所有交易所的實時價格對比表
- 最佳買價/賣價顯示
- 訂單簿深度（買盤/賣盤數量）
- 價差百分比
- 交易所連接狀態

#### ⚙️ 配置管理
- 視覺化配置所有 DEX/CEX 交易所
- 安全的憑證遮罩顯示
- 一鍵保存/刪除配置
- Testnet 模式切換
- 無需手動編輯 .env 文件

### 🔍 終端監控（適合伺服器）

命令行版套利監控，適合伺服器環境或喜歡命令行的用戶。

```bash
./start.sh monitor
# 或
python arbitrage.py monitor
```

**功能**:

- 並行監控多交易所 BTC/ETH 價格
- 實時訂單簿深度分析
- 自動檢測套利機會（考慮手續費）
- 每 2 秒更新價格數據
- 每 10 秒顯示統計報告

### 🧪 測試交易所連接

快速測試所有已配置交易所的連接狀態。

```bash
./start.sh test
# 或
python arbitrage.py test
```

## 策略配置

### 標準做市策略

編輯 `config/config.yaml`：

```yaml
strategy:
  name: simple_mm
  symbol: BTC-USD
  base_spread: 0.001 # 0.1% 價差
  order_size: 0.01 # 每次下單數量
```

#### 🎯 Uptime Program 策略（推薦用於獎勵計劃）

使用專門的 `config/uptime_config.yaml`：

```yaml
strategy:
  name: uptime_mm # Uptime 優化策略
  symbol: BTC-USD
  base_spread: 0.0008 # 8 bps（符合 10 bps 要求）
  order_size: 2.0 # 2 BTC（最大化 Maker Hours）
  target_uptime: 0.70 # 70%+ 獲得 Boosted tier
```

**Uptime Program 優勢**：

- 每月 500 萬代幣獎勵池
- MM1 (360+ hrs): 2.25 bps taker + 0.25 bps maker rebate
- MM2 (504+ hrs): 2.00 bps taker + 0.50 bps maker rebate

### 4. 運行做市商

#### 使用便捷腳本（推薦）

```bash
# Uptime Program 優化策略
./run.sh start-uptime

# 標準模式
./run.sh start

# 自定義配置
./run.sh start config/my_config.yaml
```

#### 手動運行

激活虛擬環境後運行：

```bash
# 激活虛擬環境
source venv/bin/activate

# 標準模式
python scripts/run_mm.py

# 🎯 Uptime Program 模式（推薦）
python scripts/run_mm.py config/uptime_config.yaml
```

## 做市策略說明

### 簡單做市策略（Simple Market Making）

在市場中間價上下固定價差處掛單：

```python
mid_price = market.get_mid_price()
spread = config.base_spread

bid_price = mid_price * (1 - spread)
bid_size = config.order_size

ask_price = mid_price * (1 + spread)
ask_size = config.order_size
```

**適用場景**：

- 低波動市場
- 高流動性交易對
- 初學者練習

### 自適應做市策略（Adaptive Market Making）

根據市場條件動態調整價差和訂單數量：

```python
# 計算波動率
volatility = calculate_volatility(recent_prices, window=20)

# 動態調整價差
spread = base_spread * (1 + volatility_multiplier * volatility)

# 根據庫存調整報價
inventory_factor = current_position / max_position
bid_adjustment = inventory_factor * skew_coefficient
ask_adjustment = -inventory_factor * skew_coefficient

bid_price = mid_price * (1 - spread) + bid_adjustment
ask_price = mid_price * (1 + spread) + ask_adjustment
```

**適用場景**：

- 中高波動市場
- 需要更好的風險控制
- 專業做市商

## 監控指標

### 🌐 Web 前端 Dashboard

系統提供專業的 **Web 前端 Dashboard**，具備實時圖表和視覺化監控：

**功能特色**：

- 📊 實時 PnL 和倉位趨勢圖（Chart.js）
- 🎨 現代化深色主題介面
- ⚡ WebSocket 實時更新
- 📱 響應式設計（支援手機/平板）
- 🌍 遠程訪問能力

**快速啟動**：

```bash
# 僅啟動 Web Dashboard
python scripts/run_dashboard.py

# Dashboard + 模擬數據（推薦體驗）
python scripts/demo_web_dashboard.py
```

然後訪問：**http://localhost:8000**

### 實時終端 Dashboard

系統同時配備完整的終端實時監控 Dashboard：

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                          📊 Uptime Market Maker                              ║
║                            2026-01-12 15:30:45                               ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ 💰 Performance Metrics                                                       ║
║   運行時間: 12.50 小時                                                        ║
║   已實現 PnL: 🟢 $+234.56                                                    ║
║   未實現 PnL: 🟢 $+45.23                                                     ║
║   總 PnL:     🟢 $+279.79                                                    ║
╠──────────────────────────────────────────────────────────────────────────────╣
║ 📍 Position & Volume                                                         ║
║   當前倉位: +0.2500 BTC                                                      ║
║   累計成交量: 45.6000 BTC                                                    ║
║   庫存周轉率: 3.65 次/小時                                                   ║
╠──────────────────────────────────────────────────────────────────────────────╣
║ 📋 Order Statistics                                                          ║
║   訂單成交率: 🟢 71.4%                                                       ║
║   平均價差: 8.25 bps                                                         ║
╠──────────────────────────────────────────────────────────────────────────────╣
║ ⏱️  Uptime Program Status                                                    ║
║   正常運行時間: 75.3%                                                        ║
║   獎勵層級: 🟢 Boosted (1.0x)                                                ║
║   預估 Maker Hours: 1.00/小時 (720/月)                                       ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

### 追蹤指標

系統實時追蹤以下指標：

- **總成交量**：累計成交數量
- **已實現 PnL**：已平倉損益
- **未實現 PnL**：當前持倉損益
- **當前倉位**：多空持倉數量
- **訂單成交率**：成交訂單 / 總訂單
- **平均價差**：實際成交價差
- **庫存周轉率**：倉位變化頻率
- **正常運行時間**：Uptime Program 資格追蹤（70%+ 獲得 Boosted tier）
- **Maker Hours**：預估每月累計時數

### 測試 Dashboard

**Web Dashboard（推薦）**：

```bash
# 運行 Web Dashboard 演示（5 分鐘）
python scripts/demo_web_dashboard.py

# 自定義時長
python scripts/demo_web_dashboard.py --duration 300

# 僅啟動 Dashboard Server
python scripts/run_dashboard.py
```

**終端 Dashboard**：

```bash
# 運行終端 Dashboard 測試（60 秒模擬）
python scripts/test_dashboard.py

# 運行更長時間的測試
python scripts/test_dashboard.py --duration 120
```

詳細使用說明：

- [Web Dashboard 使用指南](docs/WEB_DASHBOARD_GUIDE.md) - **圖形化介面**
- [終端 Dashboard 使用指南](docs/DASHBOARD_GUIDE.md) - 命令行介面

## 風險警示

⚠️ **重要提醒**：

1. **私鑰安全**：妥善保管您的私鑰，切勿提交至版本控制
2. **從小開始**：先用小資金測試策略
3. **風險控制**：設置合理的止損和倉位限制
4. **監控系統**：持續監控系統運行狀態
5. **網絡風險**：注意 API 延遲和連接問題
6. **市場風險**：極端市場條件下可能產生大額虧損

## 性能優化建議

1. **使用 WebSocket**：減少 API 調用延遲
2. **批量操作**：合併訂單操作減少請求次數
3. **本地緩存**：緩存市場數據和訂單狀態
4. **異步處理**：使用 asyncio 提高併發能力

## License

MIT License

## 支援

如有問題或建議，請開啟 Issue 或聯繫開發團隊。

---

**免責聲明**：本系統僅供學習和研究使用。實際交易存在風險，使用者需自行承擔所有投資風險。
