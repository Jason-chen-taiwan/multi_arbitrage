# StandX Market Maker

專為 **StandX Uptime Program** 優化的自動化做市商系統。

## 功能特點

- **雙邊掛單**：自動在買賣兩側提供流動性
- **Uptime Program 優化**：維持 10 bps 內價差，達成 70%+ 運行時間
- **實時監控**：Web Dashboard 即時顯示倉位、PnL、訂單狀態
- **風險控制**：庫存管理、最大倉位限制、波動率暫停

## 快速開始

### 1. 確認 Python 已安裝

```bash
python --version  # 需要 Python 3.10+
```

### 2. 啟動系統

```bash
# Linux / macOS
./start.sh

# Windows
start.bat
```

腳本會自動處理虛擬環境創建和依賴安裝。

### 3. 配置 StandX

1. 訪問 <http://localhost:8888>
2. 進入「設定」頁面
3. 選擇 StandX，填入 API Token 和 Ed25519 Private Key
4. 點擊「保存並開始監控」

## Web Dashboard

| 頁面 | 功能 |
|------|------|
| **StandX MM** | 做市商控制、實時狀態、訂單簿深度 |
| **套利監控** | 跨交易所價格比較（未來功能） |
| **設定** | 配置交易所 API 憑證 |
| **參數比較** | 回測不同參數組合（未來功能） |

## 做市策略參數

在 Dashboard 的「策略配置」區塊可調整：

| 參數 | 說明 | 建議值 |
|------|------|--------|
| 掛單距離 | 距離中間價多少 bps 掛單 | 5-9 bps |
| 撤單距離 | 價格靠近多少 bps 撤單 | 3-5 bps |
| 重掛距離 | 價格遠離多少 bps 重掛 | 10-15 bps |
| 訂單大小 | 單邊訂單量 (BTC) | 0.001-0.01 |
| 最大持倉 | 允許的最大倉位 (BTC) | 0.01-0.1 |

## Uptime Program

StandX 做市商獎勵計劃：

- **Boosted 層級**：70%+ 運行時間 → 1.0x 獎勵乘數
- **MM1 費率**：累積 360+ 小時 → 2.25 bps taker / 0.25 bps maker rebate
- **MM2 費率**：累積 504+ 小時 → 2.00 bps taker / 0.50 bps maker rebate

系統會自動追蹤你的運行時間和 Maker Hours。

## 未來支援

以下功能已有基礎架構，未來將完善：

- [ ] GRVT 交易所做市
- [ ] 跨交易所套利執行
- [ ] CEX 整合（Binance、OKX 等）
- [ ] 自動對沖功能

## 風險警示

- 做市交易存在風險，可能產生虧損
- 請先用小資金測試
- 設置合理的最大倉位限制
- 持續監控系統運行狀態

## License

MIT License
