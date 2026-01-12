# StandX Uptime Program 策略更新總結

## 🎉 更新完成

您的 StandX 做市商系統已成功針對 **Market Maker Uptime Program** 進行全面優化！

## ✅ 已完成的更新

### 1. 新增 Uptime 優化策略 (`UptimeMarketMaker`)

**位置**：`src/strategy/uptime_mm.py`

**核心特性**：

- ✅ 嚴格 10 bps 價差控制（帶 2 bps 安全緩衝）
- ✅ Mark price 追蹤（而非 mid price）
- ✅ 最大化訂單大小（2 BTC cap for BTC-USD）
- ✅ 70%+ 正常運行時間維護
- ✅ 實時 Maker Hours 計算和顯示
- ✅ 自動資格追蹤

### 2. 專用配置文件

**位置**：`config/uptime_config.yaml`

**關鍵設置**：

```yaml
trading:
  base_spread: 0.0008 # 8 bps（安全範圍內）
  max_spread: 0.0010 # 10 bps 硬上限
  order_size: 2.0 # 最大化 Maker Hours
  target_uptime: 0.75 # 超過 70% Boosted 門檻

strategy:
  name: uptime_mm # 使用 Uptime 策略
```

### 3. 更新主配置文件

**位置**：`config/config.yaml`

**主要調整**：

- 價差範圍調整為 5-10 bps（符合要求）
- 訂單大小增加到 2.0 BTC
- 刷新間隔調整為 30 秒（平衡穩定性和響應性）
- 新增 Uptime 模式相關設置

### 4. 完整文檔

#### 📚 Uptime Program 指南

**位置**：`docs/UPTIME_PROGRAM_GUIDE.md`

**包含內容**：

- 計劃概述和獎勵結構
- 參與資格詳細說明
- Maker Hours 計算公式和實例
- MM1/MM2 層級費率說明
- 系統優化策略解析
- 每月目標規劃
- 收益計算示例

#### 📝 更新的文檔

- `README.md`：新增 Uptime Program 整合說明
- `QUICKSTART.md`：新增 Uptime 策略快速入門

## 🎯 Uptime Program 關鍵要求

### 參與資格

| 要求         | 說明                                    |
| ------------ | --------------------------------------- |
| **價差**     | ≤ 10 bps from mark price                |
| **雙邊訂單** | 買單和賣單都必須存在                    |
| **最低時間** | ≥ 30 分鐘/小時（50%）for Standard       |
| **推薦時間** | ≥ 42 分鐘/小時（70%）for Boosted (1.0x) |
| **訂單上限** | BTC-USD: 2 BTC per side                 |

### 獎勵層級

| 層級     | 正常運行時間 | 乘數 |
| -------- | ------------ | ---- |
| Boosted  | ≥ 70%        | 1.0x |
| Standard | ≥ 50%        | 0.5x |

### 特殊費率

| 層級 | 月度要求   | Taker Fee | Maker Rebate |
| ---- | ---------- | --------- | ------------ |
| MM1  | > 360 小時 | 2.25 bps  | +0.25 bps    |
| MM2  | > 504 小時 | 2.00 bps  | +0.50 bps    |

## 🚀 如何使用

### 1. 快速啟動（推薦）

```bash
# 使用 Uptime 優化配置
python scripts/run_mm.py config/uptime_config.yaml
```

### 2. 標準配置（已更新）

```bash
# 使用主配置（已調整為符合 Uptime 要求）
python scripts/run_mm.py
```

### 3. 自定義配置

修改 `config/uptime_config.yaml` 中的參數：

```yaml
trading:
  symbol: BTC-USD # 或 ETH-USD
  order_size: 2.0 # 根據資本調整
  target_uptime: 0.75 # 目標正常運行時間

strategy:
  name: uptime_mm # 使用 Uptime 策略
```

## 📊 系統顯示

運行時會看到：

```
🎯 Uptime Market Maker Status
   Mark Price: $95,234.56
   Current Uptime: 75.3% | Target: 70%
   Tier: 🟢 Boosted (1.0x)
   Runtime: 12.5 hours

   📍 Bid:  2.000 BTC @ $95,158.23 (8.00 bps)
   📍 Ask:  2.000 BTC @ $95,310.89 (8.00 bps)

   ✅ Within 10 bps requirement (8.00 bps)

   Est. Maker Hours/hour: 1.000
   Est. Monthly Hours: 720.0 (Target: 504 (MM2))

   Position: +0.0000 BTC (+0.0% of max)
   PnL: Realized $+0.00 | Unrealized $+0.00
   ======================================================================
```

## 💡 策略優化建議

### 最大化 Maker Hours

1. **使用最大訂單大小**

   - BTC-USD: 2 BTC
   - ETH-USD: 60 ETH
   - Maker Hours = (size / 2) × multiplier

2. **維持高正常運行時間**

   - 目標：75%（安全超過 70% Boosted 門檻）
   - 使用穩定服務器和網絡
   - 設置自動重啟

3. **保持在價差範圍內**
   - 使用 8 bps 基礎價差（留有 2 bps 緩衝）
   - 持續監控 mark price
   - 快速調整訂單位置

### 達成目標

#### MM1 層級（360+ 小時/月）

```
策略：50%+ 正常運行時間
訂單：1-2 BTC
預期：0.5-1.0 Maker Hours/hour
月度：360-720 小時
```

#### MM2 層級（504+ 小時/月）- 推薦

```
策略：70%+ 正常運行時間（Boosted tier）
訂單：2 BTC（最大）
預期：1.0 Maker Hours/hour
月度：720 小時（遠超要求）
```

## 📈 預期收益

### 假設場景

- 訂單：2 BTC
- 正常運行時間：75%（Boosted）
- 運行：24/7 × 30 天

### Maker Hours

```
每小時：1.0 Maker Hours
每天：24 Maker Hours
每月：720 Maker Hours ✅ (超過 MM2 要求的 504)
```

### 獎勵 + 費用節省

```
代幣獎勵：依照你的 Maker Hours 佔總池比例
MM2 費用折扣：
  - Taker fee: 4 bps → 2 bps (省 50%)
  - Maker rebate: +0.5 bps (獲得收益)

月度節省：取決於交易量
```

## ⚠️ 重要提醒

1. **價差要求嚴格**

   - 必須在 mark price 的 10 bps 範圍內
   - 建議保留 2 bps 緩衝應對波動
   - 系統會自動檢查並調整

2. **雙邊訂單必需**

   - 買賣兩側都要有訂單
   - 任一側缺失 = 該時段不符合資格
   - 系統取較小的訂單量

3. **持續運行重要**

   - 目標 70%+ 正常運行時間獲得最大乘數
   - 使用穩定基礎設施
   - 監控系統狀態

4. **資本需求**
   - 2 BTC 訂單需要足夠保證金
   - 建議使用 5-10x 槓桿
   - 留有餘裕應對市場波動

## 📚 相關文檔

- [README.md](../README.md) - 系統概述
- [QUICKSTART.md](../QUICKSTART.md) - 快速入門
- [UPTIME_PROGRAM_GUIDE.md](UPTIME_PROGRAM_GUIDE.md) - 詳細指南
- [STRATEGY_DESIGN.md](STRATEGY_DESIGN.md) - 策略理論

## 🎯 下一步行動

1. ✅ 確認環境配置（`.env` 文件）
2. ✅ 檢查配置參數（`config/uptime_config.yaml`）
3. ✅ 啟動 Uptime 策略
4. ✅ 監控正常運行時間和 Maker Hours
5. ✅ 追蹤月度進度，目標 MM2 層級

## 🏆 成功指標

- ✅ 正常運行時間 > 70%
- ✅ 價差始終 ≤ 10 bps
- ✅ 訂單大小接近 2 BTC
- ✅ 月度 Maker Hours > 504
- ✅ 達成 MM2 層級並享受特殊費率

---

**活動時間**：2026 年 1 月 5 日起

立即開始，最大化您的做市商收益！🚀
