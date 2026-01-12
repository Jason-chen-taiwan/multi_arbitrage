# StandX Market Maker - 快速設置指南（虛擬環境）

## 🚀 快速開始（推薦方式）

### 1. 首次設置

```bash
# 賦予腳本執行權限（只需執行一次）
chmod +x setup.sh run.sh

# 自動設置虛擬環境並安裝依賴
./setup.sh
```

這會：

- 檢查 Python 版本（需要 3.9+）
- 創建隔離的虛擬環境 `venv/`
- 安裝所有依賴套件

### 2. 配置環境變數

```bash
# 複製環境變數範例
cp .env.example .env

# 編輯 .env 填入您的配置
nano .env  # 或使用其他編輯器
```

必填項目：

- `WALLET_PRIVATE_KEY` - 您的錢包私鑰

### 3. 測試系統

```bash
# 測試終端 Dashboard（60 秒）
./run.sh test

# 測試 Web Dashboard（5 分鐘）- 推薦！
./run.sh web
```

然後訪問：**http://localhost:8000**

### 4. 啟動做市商

```bash
# 使用 Uptime Program 優化配置（推薦）
./run.sh start-uptime

# 或使用默認配置
./run.sh start
```

---

## 📋 可用命令

### 環境管理

```bash
./run.sh setup        # 首次設置虛擬環境
./run.sh install      # 安裝/更新依賴
./run.sh clean        # 清理虛擬環境
./run.sh shell        # 進入虛擬環境 shell
```

### 測試運行

```bash
# 終端 Dashboard 測試
./run.sh test                    # 默認 60 秒
./run.sh test --duration 120     # 自定義時長

# Web Dashboard 測試（推薦）
./run.sh web                     # 默認 5 分鐘
./run.sh web --duration 600      # 自定義時長

# 僅啟動 Web Dashboard Server
./run.sh dashboard               # 默認 8000 端口
./run.sh dashboard --port 8080   # 自定義端口
```

### 生產運行

```bash
# Uptime Program 優化策略（推薦）
./run.sh start-uptime

# 標準策略
./run.sh start

# 自定義配置
./run.sh start config/my_config.yaml
```

---

## 🎁 StandX Market Maker Uptime Program

本系統已針對 **StandX Market Maker Uptime Program** 進行特別優化！

### 活動亮點

- 💰 每月 **500 萬代幣** 獎勵池
- 🎯 70%+ 正常運行時間 = **1.0x 乘數**（Boosted tier）
- 💎 累積 360+ 小時獲得 **MM1** 或 504+ 小時獲得 **MM2** 特殊費率
- 📈 訂單大小最高 **2 BTC**，最大化 Maker Hours

### 使用 Uptime 優化策略

```bash
# 使用專門的 Uptime Program 配置
./run.sh start-uptime
```

詳細說明請參閱：[Uptime Program 指南](docs/UPTIME_PROGRAM_GUIDE.md)

---

## 🔧 手動使用虛擬環境

如果您想手動控制虛擬環境：

```bash
# 激活虛擬環境
source venv/bin/activate

# 運行任何 Python 腳本
python scripts/test_dashboard.py
python scripts/run_mm.py config/uptime_config.yaml

# 退出虛擬環境
deactivate
```

---

```env
# 您的錢包私鑰（請妥善保管，切勿外洩）
WALLET_PRIVATE_KEY=0x...

# 您的錢包地址
WALLET_ADDRESS=0x...

# 區塊鏈網路（bsc 或 solana）
CHAIN=bsc

# 交易對
SYMBOL=BTC-USD
```

⚠️ **安全提醒**：

- 切勿將 `.env` 文件提交到版本控制
- 使用專用的交易錢包，不要使用存有大量資產的主錢包
- 建議先在測試網測試

## 配置策略

編輯 `config/config.yaml` 調整策略參數：

```yaml
# 交易配置
trading:
  symbol: BTC-USD # 交易對
  base_spread: 0.001 # 基礎價差（0.1%）
  order_size: 0.01 # 每次下單量
  max_position: 0.5 # 最大持倉
  refresh_interval: 5 # 刷新間隔（秒）

# 風險管理
risk:
  max_daily_loss: 1000 # 最大每日虧損（USD）
  max_position_value: 10000 # 最大倉位價值
  max_drawdown: 0.2 # 最大回撤（20%）
```

## 運行做市商

### 基礎運行

```bash
python scripts/run_mm.py
```

### 指定配置文件

```bash
python scripts/run_mm.py config/custom_config.yaml
```

### 後台運行（Linux/Mac）

```bash
nohup python scripts/run_mm.py > logs/mm.log 2>&1 &
```

## 監控系統

運行時會顯示實時狀態：

```
🧠 Adaptive Market Making Status
   Mid Price: $95,234.56
   Volatility: 1.23%
   OB Imbalance: +0.234 📈 BUY
   Dynamic Spread: 0.156% (base: 0.100%)
   Position: +0.0234 (+4.7% of max)

   Buy:  0.0100 @ $95,160.12 (-7.8 bps)
   Sell: 0.0105 @ $95,309.00 (+7.8 bps)

   PnL: Realized $+12.34 | Unrealized $-5.67
   ============================================================
```

## 停止運行

按 `Ctrl+C` 優雅停止，系統會：

1. 停止策略循環
2. 取消所有掛單
3. 斷開連接
4. 保存日誌

## 常見問題

### Q: 如何調整價差？

編輯 `config/config.yaml` 中的 `base_spread` 參數：

- 較大的價差 = 更安全但成交機會少
- 較小的價差 = 成交多但風險高

### Q: 如何控制倉位？

設定 `max_position` 參數限制最大持倉：

```yaml
trading:
  max_position: 0.5 # 最多持有 0.5 BTC
```

### Q: 如何處理庫存偏移？

策略會自動調整報價來管理庫存：

- 多頭過多時：降低買價，提高賣價
- 空頭過多時：提高買價，降低賣價

### Q: 出現風險警告怎麼辦？

當觸發風險限制時，系統會自動停止交易：

```
⛔ TRADING HALTED: Daily loss $1,234.56 exceeds limit $1,000.00
```

需要：

1. 檢查並調整風險參數
2. 分析虧損原因
3. 改進策略或等待市場條件改善

### Q: 如何回測策略？

目前版本不包含回測功能，建議：

1. 從極小倉位開始實盤測試
2. 記錄所有交易數據
3. 分析績效後再逐步增加倉位

## 性能優化

### 降低延遲

- 使用靠近交易所的服務器
- 減小 `refresh_interval`（但注意 API 限制）
- 使用 WebSocket 接收實時更新

### 提高成交率

- 縮小價差
- 增加掛單層數
- 使用自適應策略

### 風險控制

- 設置較小的 `max_position`
- 啟用 `max_daily_loss` 限制
- 監控市場波動率

## 進階配置

### 使用自適應策略

```yaml
strategy:
  name: adaptive_mm
  volatility_window: 20
  volatility_multiplier: 2.0
```

### 🎯 使用 Uptime Program 策略（推薦）

```yaml
strategy:
  name: uptime_mm

# 或直接使用專門配置
python scripts/run_mm.py config/uptime_config.yaml
```

**Uptime Program 策略特點**：

- 嚴格 10 bps 價差控制
- 70%+ 正常運行時間維護
- 最大化 2 BTC 訂單大小
- 自動追蹤 mark price
- 目標達成 MM2 層級（504+ 小時/月）

### 多層掛單

```yaml
trading:
  num_levels: 3
  level_spacing: 0.0005
```

### 自定義日誌

```yaml
monitoring:
  log_level: DEBUG
  log_file: logs/my_mm.log
```

## 故障排除

### 連接失敗

檢查：

- API URL 是否正確
- 網絡連接是否正常
- 錢包私鑰是否正確

### 認證失敗

確保：

- 私鑰格式正確（需包含 0x 前綴）
- 錢包有足夠的 gas fee
- 使用正確的 chain 配置

### 下單失敗

可能原因：

- 訂單量小於最小下單量
- 價格超出限制範圍
- 餘額不足
- API 限流

## 獲取幫助

如遇問題：

1. 檢查 `logs/` 目錄下的日誌文件
2. 閱讀錯誤訊息
3. 參考 StandX API 文檔

---

**風險警示**：加密貨幣交易涉及高風險，可能導致全部資金損失。請謹慎評估自身風險承受能力，僅使用可承受損失的資金進行交易。
