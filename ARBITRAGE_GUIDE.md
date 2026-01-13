# 🤖 自動套利交易指南

## 📋 目錄

- [系統要求](#系統要求)
- [快速開始](#快速開始)
- [運行模式](#運行模式)
- [配置參數](#配置參數)
- [安全建議](#安全建議)
- [常見問題](#常見問題)

## 系統要求

### 最低要求

- ✅ **至少 2 個交易所已配置**（才能進行跨所套利）
- ✅ **足夠的資金餘額**（建議至少 $1000 USD）
- ✅ **穩定的網絡連接**
- ✅ **API 權限**：讀取市場數據 + 下單權限

### 推薦交易所組合

1. **DEX + CEX**:
   - StandX + Binance
   - GRVT + OKX

2. **多個 CEX**:
   - Binance + OKX + Bitget
   - Bybit + Bitget + OKX

3. **多個 DEX**:
   - StandX + GRVT

## 快速開始

### 方法 1：使用主程序（推薦）

```bash
# 啟動主程序
python arbitrage.py

# 選擇選項 3 - 自動套利
```

### 方法 2：直接運行腳本

```bash
# 僅監控模式（不執行交易，安全）
python scripts/run_auto_arbitrage.py --dry-run

# 自動執行套利（模擬模式，推薦用於測試）
python scripts/run_auto_arbitrage.py --auto --dry-run

# 自動執行套利（實際交易，危險！）
python scripts/run_auto_arbitrage.py --auto --no-dry-run
```

### 方法 3：使用 start.sh

```bash
./start.sh arbitrage
```

## 運行模式

### 1. 監控模式（Monitor Only）

**特點**：
- ✅ 實時監控所有交易所價格
- ✅ 檢測並顯示套利機會
- ❌ **不執行任何交易**
- 💡 完全安全，用於觀察市場

**啟動命令**：
```bash
python scripts/run_auto_arbitrage.py --dry-run
```

**輸出示例**：
```
💰 ARBITRAGE OPPORTUNITIES DETECTED: 1
================================================================================

🔥 BTC/USDT:USDT Arbitrage:
  Buy:  BINANCE     @ $ 95,123.50 (size: 1.5)
  Sell: OKX         @ $ 95,245.20 (size: 1.2)
  💰 Profit: $  121.70 (0.1280%)
  📊 Max Qty: 1.2
```

### 2. 自動執行模式 - 模擬（Auto Execute - Dry Run）

**特點**：
- ✅ 實時監控價格
- ✅ 自動檢測套利機會
- ✅ **模擬執行交易**（不實際下單）
- ✅ 記錄交易歷史和統計
- 💡 安全，用於測試策略

**啟動命令**：
```bash
python scripts/run_auto_arbitrage.py --auto --dry-run
```

**輸出示例**：
```
⚡ Executing Arbitrage
================================================================================
  Symbol: BTC/USDT:USDT
  Buy:  BINANCE @ $95123.50
  Sell: OKX @ $95245.20
  Expected Profit: $146.04
================================================================================

  🔵 DRY RUN MODE - No real orders placed

✅ Arbitrage executed successfully!
   Profit: $146.04
```

### 3. 自動執行模式 - 實際交易（Auto Execute - Live）

**特點**：
- ✅ 實時監控價格
- ✅ 自動檢測套利機會
- ✅ **實際執行交易**（使用真實資金）
- ⚠️ **高風險**：可能導致損失
- 💡 僅建議經驗豐富的交易者使用

**啟動命令**：
```bash
python scripts/run_auto_arbitrage.py --auto --no-dry-run
```

**安全確認**：
```
⚠️  警告：您即將啟用實際交易模式！
   這將使用真實資金進行交易，可能導致損失。
   確定繼續嗎？(輸入 'YES' 確認):
```

## 配置參數

### 基本參數

| 參數 | 默認值 | 說明 |
|------|--------|------|
| `--auto` | False | 啟用自動執行 |
| `--dry-run` | True | 模擬模式（不實際下單） |
| `--max-position` | 0.1 | 單次最大交易量 |
| `--min-profit` | 5.0 | 最小利潤閾值（USD） |
| `--min-profit-pct` | 0.1 | 最小套利利潤百分比（%） |
| `--update-interval` | 2.0 | 市場數據更新間隔（秒） |

### 高級示例

```bash
# 保守策略：小倉位，高利潤要求
python scripts/run_auto_arbitrage.py \
  --auto \
  --dry-run \
  --max-position 0.05 \
  --min-profit 10.0 \
  --min-profit-pct 0.2

# 激進策略：大倉位，低利潤要求
python scripts/run_auto_arbitrage.py \
  --auto \
  --dry-run \
  --max-position 0.5 \
  --min-profit 3.0 \
  --min-profit-pct 0.05

# 高頻策略：更快的更新間隔
python scripts/run_auto_arbitrage.py \
  --auto \
  --dry-run \
  --update-interval 1.0
```

## 安全建議

### ⚠️ 重要警告

1. **首次使用必須使用模擬模式**
   ```bash
   python scripts/run_auto_arbitrage.py --auto --dry-run
   ```

2. **測試至少 24 小時後再考慮實際交易**

3. **從小倉位開始**
   - 建議 `--max-position 0.01`（非常保守）
   - 逐步增加到 `0.05` → `0.1` → `0.2`

4. **設置合理的利潤閾值**
   - 考慮手續費：通常 0.05% - 0.1%
   - 最小利潤應該 > 手續費 * 2

5. **監控系統狀態**
   - 定期檢查執行歷史
   - 關注失敗率
   - 分析實際利潤 vs 預期利潤

### 🔒 風險控制

1. **API 權限設置**
   - 僅授予必要的權限（讀取 + 交易）
   - 禁用提幣權限
   - 設置 IP 白名單

2. **資金管理**
   - 不要投入全部資金
   - 建議套利專用賬戶
   - 定期提取利潤

3. **網絡要求**
   - 使用穩定的網絡
   - 考慮使用 VPS
   - 設置斷線重連機制

## 統計監控

系統會自動記錄和顯示統計數據：

```
📊 ARBITRAGE EXECUTOR SUMMARY
================================================================================
  Total Attempts: 45
  Successful: 42
  Failed: 3
  Total Profit: $1,234.56
  Total Loss: $12.34
  Net P&L: $1,222.22
  Avg Profit/Trade: $29.39
================================================================================
```

## 常見問題

### Q1: 需要多少資金才能開始？

**A**:
- **最低**：$100-200（僅測試用）
- **推薦**：$1,000-5,000（可以捕獲大部分機會）
- **理想**：$10,000+（完全發揮系統潛力）

### Q2: 預期收益率是多少？

**A**:
- 取決於市場波動性和資金量
- 典型情況：0.5% - 2% 日收益（波動性高時）
- 低波動期：0.1% - 0.5% 日收益
- ⚠️ **不保證盈利**

### Q3: 系統安全嗎？

**A**:
- ✅ 模擬模式完全安全
- ⚠️ 實際交易有風險
- 建議使用專用 API Key 並限制權限
- 從小額資金開始測試

### Q4: 為什麼找不到套利機會？

**可能原因**：
1. 市場效率高，價差小
2. `min_profit_pct` 設置太高
3. 交易所連接不穩定
4. 網絡延遲過高

**解決方案**：
```bash
# 降低利潤閾值
python scripts/run_auto_arbitrage.py --auto --dry-run --min-profit-pct 0.05

# 增加更新頻率
python scripts/run_auto_arbitrage.py --auto --dry-run --update-interval 1.0
```

### Q5: 如何停止系統？

**A**: 按 `Ctrl+C` 即可安全停止。系統會：
1. 停止接收新訂單
2. 等待進行中的訂單完成
3. 顯示執行摘要

### Q6: 執行失敗怎麼辦？

**常見原因**：
- 餘額不足
- API 權限不夠
- 網絡超時
- 價格已變化

**建議**：
- 檢查 API 配置
- 確保足夠餘額
- 使用穩定網絡
- 調整 `execution_timeout` 參數

## 實戰技巧

### 1. 選擇合適的時間段

- **高波動期**：美股開盤、重要新聞發布
- **避開**：周末、節假日（流動性低）

### 2. 優化參數

```bash
# 市場波動大時
--min-profit-pct 0.05 --update-interval 1.0

# 市場平穩時
--min-profit-pct 0.15 --update-interval 3.0
```

### 3. 分散風險

- 不要只交易一個交易對
- 監控多個 symbols
- 使用多個交易所組合

### 4. 持續優化

- 記錄每日表現
- 分析成功/失敗原因
- 調整參數以適應市場

## 技術支持

如有問題：
1. 查看日誌文件：`logs/arbitrage.log`
2. 檢查 GitHub Issues
3. 參考系統文檔

---

**免責聲明**：加密貨幣交易存在高風險。使用本系統進行實際交易可能導致資金損失。請在充分了解風險的情況下使用，並自行承擔所有交易風險。
