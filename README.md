# StandX Market Maker

[![Version](https://img.shields.io/badge/version-1.0.1-blue.svg)](https://github.com/Jason-chen-taiwan/multi_arbitrage)

專為 **StandX Uptime Program** 優化的自動化做市商系統。

## 功能特點

- **雙邊掛單**：自動在買賣兩側提供流動性
- **Uptime Program 優化**：維持 10 bps 內價差，達成 70%+ 運行時間
- **實時監控**：React Dashboard 即時顯示倉位、PnL、訂單狀態
- **智能風控**：庫存管理、最大倉位限制、智能波動率暫停（雙閾值 + 穩定期確認）
- **多帳戶對沖**：支援 StandX 多帳戶對沖
- **運行時控制**：對沖開關、即時平倉開關可在運行中即時切換，重啟後保留設定
- **自動淨敞口對沖**：開啟對沖模式後自動檢測並平衡兩帳戶倉位
- **雙邊 PnL 監控**：即時顯示主帳戶、對沖帳戶的 Unrealized PnL 和合計淨利潤
- **清算保護**：監控保證金比率，接近清算時自動緊急平倉
- **女巫防護**：對沖帳戶支援獨立代理 (SOCKS5/HTTP)，避免 IP 關聯
- **完整交易日誌**：所有交易和對沖操作記錄於 `logs/mm_trades_*.log`

## 系統架構

```text
┌─────────────────────────────────────────────────────────────┐
│                    React Frontend (Vite)                     │
│  - 即時 Dashboard 顯示                                        │
│  - 策略參數配置介面                                           │
│  - 多語言支援 (中/英)                                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ WebSocket + REST API
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Backend                           │
│  - /api/* REST 端點                                          │
│  - /ws WebSocket 即時數據                                     │
│  - 生產模式下同時服務前端靜態檔案                               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              Trading Adapters & Strategy Engine              │
│  - StandX / GRVT 交易所整合                                   │
│  - 做市策略執行                                               │
│  - 倉位管理與對沖                                             │
└─────────────────────────────────────────────────────────────┘
```

## 快速開始

### 0. 註冊 StandX 帳號

如果你還沒有 StandX 帳號，建議使用以下邀請連結註冊，雙方都可獲得額外 5% 積分加成：

👉 <https://standx.com/referral?code=Jasoncrypto>

### 1. 環境需求

```bash
python --version  # 需要 Python 3.8+
```

> **Note**: 前端已預先構建，一般使用者**不需要安裝 Node.js**。

### 2. 啟動系統

```bash
# Linux / macOS
./start.sh

# Windows
start.bat
```

腳本會自動處理：

- Python 虛擬環境建立與啟動
- Python 依賴安裝
- 前端已預構建，無需額外處理

#### 開發者選項

如需修改前端代碼，需安裝 Node.js 18+：

```bash
# 開發模式（前後端分開運行，支援熱重載）
./start.sh --dev

# 強制重建前端後啟動
./start.sh --rebuild
```

### 3. 配置 StandX

1. 訪問 <http://localhost:9999>
2. 進入「Settings」頁面
3. 選擇 StandX，填入 API Token 和 Ed25519 Private Key
4. 點擊「Save Configuration」

### 4. 配置對沖帳戶

#### StandX 多帳戶對沖

使用另一個 StandX 帳戶進行對沖：

1. 在 Settings 頁面的「對沖帳戶配置」區塊
2. 選擇「StandX 對沖帳戶」
3. 填入對沖帳戶的 API Token 和 Ed25519 Private Key
4. （可選）配置代理以實現女巫防護
5. 保存後重新連接交易所

#### 女巫防護（代理設定）

讓對沖帳戶走不同 IP，避免項目方識別兩個帳戶為同一人：

1. 在對沖配置區塊填入 Proxy URL（例如 `socks5://host:port`）
2. 如需認證，填入用戶名和密碼
3. 支援 HTTP/HTTPS/SOCKS5 代理

健康檢查會顯示對沖帳戶的外部 IP，驗證代理是否生效。

#### 清算保護

自動監控帳戶保證金狀態，接近清算時緊急平倉：

- **保證金比率閾值**：低於此值觸發保護（預設 15%）
- **清算距離閾值**：價格距清算價低於此比例觸發（預設 5%）
- 觸發後自動市價平倉所有持倉

#### 運行時對沖控制

在做市商頁面可即時控制：

- **對沖開關**：開啟後，成交時自動執行對沖，並定期檢查淨敞口自動平衡
- **即時平倉開關**：開啟後，當持倉超過閾值時自動市價平倉

> ⚠️ 兩個開關預設為 **關閉** 狀態，需手動開啟

## Web Dashboard

訪問 <http://localhost:9999> 進入 Dashboard。

| 頁面 | 功能 |
|------|------|
| **Market Maker** | 做市商控制、實時狀態、訂單簿深度、成交歷史、對沖統計、雙邊 PnL |
| **Arbitrage** | 跨交易所價格比較（未來功能） |
| **Settings** | 配置交易所 API、對沖帳戶、緊急平倉 |
| **Comparison** | 參數組合比較（未來功能） |

### API 文件

啟動後訪問 <http://localhost:9999/docs> 可查看 Swagger API 文件。

## 做市策略參數

在 Dashboard 的「Strategy Configuration」區塊可調整：

### 報價參數

| 參數 | 說明 | 建議值 |
|------|------|--------|
| 掛單距離 | 距離中間價多少 bps 掛單 | 5-9 bps |
| 撤單距離 | 價格靠近多少 bps 撤單 | 3-5 bps |
| 重掛距離 | 價格遠離多少 bps 重掛 | 10-15 bps |
| 隊列風控 | 排在前 N 檔時撤單 | 3 檔 |

### 倉位參數

| 參數 | 說明 | 預設值 |
|------|------|--------|
| 訂單大小 | 單邊訂單量 (BTC) | 0.01 |
| 最大持倉 | 允許的最大倉位 (BTC) | 0.05 |

### 波動率控制

系統採用**雙閾值 + 穩定期**機制避免在劇烈波動時被吃單：

| 參數 | 說明 | 建議值 |
|------|------|--------|
| 觀察窗口 | 計算波動率的時間窗口 | 2 秒 |
| 暫停閾值 | 波動率超過此值暫停掛單 | 4-5 bps |
| 恢復閾值 | 波動率低於此值才考慮恢復 | 3-4 bps |

**運作原理**：
- 波動率 = (窗口內最高價 - 最低價) / 最新價 × 10000 (bps)
- 當波動率 > 暫停閾值 → 撤銷訂單，暫停掛單
- 當波動率 < 恢復閾值且持續穩定期 → 恢復掛單
- 雙閾值設計避免在臨界點頻繁開關（hysteresis）

## Uptime Program

StandX 做市商獎勵計劃：

- **Boosted 層級**：70%+ 運行時間 → 1.0x 獎勵乘數
- **MM1 費率**：累積 360+ 小時 → 2.25 bps taker / 0.25 bps maker rebate
- **MM2 費率**：累積 504+ 小時 → 2.00 bps taker / 0.50 bps maker rebate

系統會自動追蹤你的運行時間和 Maker Hours。

## 開發指南

### 目錄結構

```text
arbitrage/
├── frontend/              # React 前端
│   ├── src/
│   │   ├── pages/        # 頁面組件
│   │   ├── components/   # 共用組件
│   │   ├── hooks/        # React Hooks
│   │   └── i18n/         # 多語言翻譯
│   └── vite.config.ts
├── src/
│   ├── web/              # FastAPI 後端
│   │   ├── api/          # REST API 路由
│   │   ├── schemas/      # Pydantic 模型
│   │   └── auto_dashboard.py
│   ├── adapters/         # 交易所適配器
│   ├── strategy/         # 做市策略
│   └── monitor/          # 價格監控
├── config/
│   └── mm_config.yaml    # 做市參數配置
├── start.sh              # Linux/macOS 啟動腳本
└── start.bat             # Windows 啟動腳本
```

### 開發模式

```bash
# 啟動開發伺服器（支援熱重載）
./start.sh --dev

# 後端: http://localhost:9999
# 前端: http://localhost:3000 (代理 API 到 9999)
```

### 單獨構建前端

```bash
cd frontend
npm install
npm run build  # 輸出到 src/web/frontend_dist/
```

## 未來支援

以下功能已有基礎架構，未來將完善：

- [ ] GRVT 交易所做市
- [ ] 跨交易所套利執行
- [ ] CEX 整合（Binance、OKX 等）
- [ ] 更多幣種支援

## 邀請碼說明

本程式在首次啟動時會詢問是否使用開發者的邀請碼：

- **邀請碼**: `Jasoncrypto`
- **好處**: 雙方都可獲得 **5% 積分加成**
- **選擇權**: 你可以選擇「使用」或「不用了」，完全自願
- **只問一次**: 無論選擇什麼，之後不會再詢問

如果你想手動使用邀請碼，可以訪問：
👉 <https://standx.com/referral?code=Jasoncrypto>

> 感謝你的支持！這有助於我持續維護和改進這個開源項目。

## 風險警示

- 做市交易存在風險，可能產生虧損
- 請先用小資金測試
- 設置合理的最大倉位限制
- 持續監控系統運行狀態

## License

MIT License
