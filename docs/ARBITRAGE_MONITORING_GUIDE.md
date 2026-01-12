
# 套利監控系統使用指南
# Arbitrage Monitoring System Guide

本指南說明如何使用多交易所實時監控系統來監控價格並發現套利機會。

## 目錄

1. [系統概述](#系統概述)
2. [功能特點](#功能特點)
3. [快速開始](#快速開始)
4. [配置選項](#配置選項)
5. [監控指標](#監控指標)
6. [套利策略](#套利策略)

---

## 系統概述

多交易所監控系統實時跟蹤多個交易所的價格和訂單簿，自動檢測套利機會。

### 架構

```
┌─────────────────────────────────────────────────────────┐
│            Multi-Exchange Monitor                        │
│                                                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │  Exchange   │  │  Exchange   │  │  Exchange   │     │
│  │  Monitor 1  │  │  Monitor 2  │  │  Monitor 3  │     │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘     │
│         │                 │                 │            │
│         └─────────────────┴─────────────────┘            │
│                           │                              │
│                           ▼                              │
│              ┌─────────────────────────┐                │
│              │  Arbitrage Detector     │                │
│              │  - Price comparison     │                │
│              │  - Profit calculation   │                │
│              │  - Opportunity alert    │                │
│              └─────────────────────────┘                │
└─────────────────────────────────────────────────────────┘
```

### 監控流程

1. **數據採集** - 並行從所有交易所獲取訂單簿
2. **數據處理** - 計算最佳買賣價、價差、深度
3. **套利檢測** - 比較所有交易所對，尋找價差
4. **機會通知** - 實時顯示符合條件的套利機會
5. **數據導出** - 保存歷史數據供分析

---

## 功能特點

### 1. 實時價格監控

✅ **多交易所並行監控**
- 同時監控多個 DEX 和 CEX
- 獨立的更新頻率控制
- 自動錯誤處理和重試

✅ **低延遲數據更新**
- 默認 2 秒更新間隔
- 可配置更新頻率
- 異步並行請求

✅ **完整訂單簿數據**
- 買賣盤前 10 檔
- 實時價格和深度
- 價差百分比計算

### 2. 套利機會檢測

✅ **自動價差分析**
- 實時比較所有交易所對
- 雙向套利檢測
- 可配置最小利潤閾值

✅ **深度考慮**
- 計算可執行的最大數量
- 考慮買賣盤深度
- 滑點影響評估

✅ **實時通知**
- 發現機會立即顯示
- 包含完整執行細節
- 利潤和利潤率計算

### 3. 統計和分析

✅ **實時統計**
- 總更新次數
- 發現的套利機會數量
- 每個交易所的成功/失敗率

✅ **數據導出**
- JSON 格式導出
- 包含所有市場數據
- 套利機會歷史記錄

---

## 快速開始

### 步驟 1: 配置環境變量

編輯 `.env` 文件，配置至少 2 個交易所：

```bash
# DEX 配置（至少一個）
WALLET_PRIVATE_KEY=your_standx_private_key
CHAIN=bsc

# CEX 配置（至少一個）
BINANCE_API_KEY=your_binance_api_key
BINANCE_API_SECRET=your_binance_api_secret

OKX_API_KEY=your_okx_api_key
OKX_API_SECRET=your_okx_api_secret
OKX_PASSPHRASE=your_okx_passphrase
```

### 步驟 2: 運行監控器

```bash
# 激活虛擬環境
source venv/bin/activate

# 運行監控腳本
python scripts/monitor_arbitrage.py
```

### 步驟 3: 觀察輸出

監控器會顯示：

```
================================================================================
🚀 Starting Multi-Exchange Monitor
================================================================================
📊 Monitoring 2 symbols on 3 exchanges
⏱️  Update interval: 2.0s
💰 Min profit threshold: 0.1%
================================================================================

================================================================================
📊 MONITOR STATISTICS
================================================================================
⏱️  Runtime: 2026-01-12 16:30:45
📈 Total Updates: 150
💰 Total Opportunities Found: 3

📊 Exchange Status:
  BINANCE         - Symbols: 2/2, Failures: 0
  OKX             - Symbols: 2/2, Failures: 0
  BITGET          - Symbols: 2/2, Failures: 1

💵 Current Prices:

  BTC/USDT:USDT:
    BINANCE         - Bid: $ 95,234.50 | Ask: $ 95,236.80 | Spread: 0.0024%
    OKX             - Bid: $ 95,233.90 | Ask: $ 95,237.10 | Spread: 0.0034%
    BITGET          - Bid: $ 95,234.20 | Ask: $ 95,236.50 | Spread: 0.0024%

================================================================================
💰 ARBITRAGE OPPORTUNITIES DETECTED: 1
================================================================================

🔥 BTC/USDT:USDT Arbitrage:
  Buy:  BITGET     @ $ 95,236.50 (size: 2.5)
  Sell: BINANCE    @ $ 95,234.50 (size: 3.2)
  💰 Profit: $   -2.00 (-0.0021%)
  📊 Max Qty: 2.5
```

### 步驟 4: 停止監控

按 `Ctrl+C` 停止監控器。數據會自動導出到 `market_data.json`。

---

## 配置選項

### 監控參數

在 `monitor_arbitrage.py` 中可以配置：

```python
monitor = MultiExchangeMonitor(
    adapters=adapters,
    symbols=['BTC/USDT:USDT', 'ETH/USDT:USDT'],
    update_interval=2.0,      # 更新間隔（秒）
    min_profit_pct=0.1        # 最小利潤百分比
)
```

### 監控的交易對

**CEX（CCXT 格式）**:
```python
symbols_cex = [
    'BTC/USDT:USDT',   # Bitcoin 永續合約
    'ETH/USDT:USDT',   # Ethereum 永續合約
    'SOL/USDT:USDT',   # Solana 永續合約
    'AVAX/USDT:USDT',  # Avalanche 永續合約
]
```

**DEX（原生格式）**:
```python
symbols_dex = [
    'BTC-USD',   # Bitcoin
    'ETH-USD',   # Ethereum
]
```

### 利潤閾值

根據您的需求調整最小利潤閾值：

- **0.05%** - 激進（更多機會，但手續費可能吃掉利潤）
- **0.1%** - 平衡（默認，扣除手續費後仍有利潤）
- **0.2%** - 保守（只顯示高利潤機會）
- **0.5%** - 極保守（罕見但利潤豐厚）

### 更新頻率

- **1 秒** - 高頻（需要穩定網絡，可能觸發 API 限制）
- **2 秒** - 平衡（默認，適合大多數情況）
- **5 秒** - 低頻（節省 API 配額）

---

## 監控指標

### 價格指標

| 指標 | 說明 | 用途 |
|------|------|------|
| Best Bid | 最佳買入價 | 您可以賣出的最高價格 |
| Best Ask | 最佳賣出價 | 您需要買入的最低價格 |
| Spread | 價差（Ask - Bid） | 市場流動性指標 |
| Spread % | 價差百分比 | 相對價差，便於比較 |

### 深度指標

| 指標 | 說明 | 重要性 |
|------|------|--------|
| Bid Size | 買盤掛單量 | 可賣出的最大量 |
| Ask Size | 賣盤掛單量 | 可買入的最大量 |
| Max Quantity | 可套利的最大量 | min(Bid Size, Ask Size) |

### 套利指標

| 指標 | 說明 | 計算公式 |
|------|------|----------|
| Profit | 絕對利潤 | Sell Price - Buy Price |
| Profit % | 利潤百分比 | (Profit / Buy Price) × 100 |
| Net Profit | 扣除手續費後利潤 | Profit - (Buy Fee + Sell Fee) |

---

## 套利策略

### 1. 簡單套利（Simple Arbitrage）

**原理**: 同時在兩個交易所執行相反操作

**步驟**:
1. 發現機會：A 交易所 Ask < B 交易所 Bid
2. 在 A 交易所買入
3. 在 B 交易所賣出
4. 鎖定利潤

**風險**:
- 執行延遲風險
- 價格變動風險
- 資金分散需求

**適用場景**:
- 兩個交易所都有充足資金
- 網絡連接穩定
- 價差足夠大（>0.2%）

### 2. 三角套利（Triangular Arbitrage）

**原理**: 通過三個交易對的匯率差異套利

**示例**:
1. BTC → USDT
2. USDT → ETH
3. ETH → BTC

**優勢**:
- 無需跨交易所轉賬
- 資金利用效率高

**實現**:
```python
# 檢測三角套利機會
btc_usdt = get_price('BTC/USDT')
eth_usdt = get_price('ETH/USDT')
eth_btc = get_price('ETH/BTC')

# 計算理論 BTC/USDT 價格
theoretical_btc_usdt = eth_usdt / eth_btc

# 如果實際價格偏離理論價格超過閾值，存在套利機會
if abs(btc_usdt - theoretical_btc_usdt) / btc_usdt > 0.002:
    print("三角套利機會!")
```

### 3. 資金費率套利（Funding Rate Arbitrage）

**原理**: 利用永續合約的資金費率差異

**步驟**:
1. 在資金費率為正的交易所做空
2. 在資金費率為負的交易所做多
3. 每 8 小時收取資金費率

**長期策略**:
- 低風險
- 穩定收益
- 需要對沖

**實現**:
```python
# 獲取各交易所的資金費率
funding_rates = {}
for exchange in exchanges:
    rate = await exchange.get_funding_rate('BTC/USDT:USDT')
    funding_rates[exchange] = rate

# 尋找資金費率差異
max_rate = max(funding_rates.values())
min_rate = min(funding_rates.values())

if (max_rate - min_rate) > 0.0005:  # 0.05%
    print(f"資金費率套利機會: {max_rate - min_rate}")
```

### 4. 跨市場套利（Cross-Market Arbitrage）

**DEX ↔ CEX 套利**

**優勢**:
- DEX 通常價格發現較慢
- CEX 流動性更好
- 價差可能更大

**挑戰**:
- 需要處理不同的認證方式
- Gas 費用（DEX）
- 轉賬時間

**最佳實踐**:
1. 在兩邊都保持足夠資金
2. 監控 Gas 價格（DEX）
3. 考慮滑點影響
4. 設置合理的利潤閾值（>0.3%）

---

## 手續費計算

### CEX 手續費

| 交易所 | Maker | Taker | VIP 折扣 |
|--------|-------|-------|----------|
| Binance | 0.02% | 0.04% | 最高 50% |
| OKX | 0.02% | 0.05% | 最高 40% |
| Bitget | 0.02% | 0.06% | 最高 45% |
| Bybit | 0.01% | 0.06% | 最高 50% |

### DEX 手續費

| 交易所 | Trading Fee | Gas Fee | 總成本 |
|--------|-------------|---------|--------|
| StandX | 0.05% | 低 | ~0.1% |
| GRVT | 0.03% | 中 | ~0.15% |

### 淨利潤計算

```python
def calculate_net_profit(
    buy_price: Decimal,
    sell_price: Decimal,
    quantity: Decimal,
    buy_fee_rate: Decimal = Decimal('0.0004'),  # 0.04%
    sell_fee_rate: Decimal = Decimal('0.0004')
) -> Decimal:
    """計算扣除手續費後的淨利潤"""

    # 買入成本
    buy_cost = buy_price * quantity
    buy_fee = buy_cost * buy_fee_rate

    # 賣出收入
    sell_revenue = sell_price * quantity
    sell_fee = sell_revenue * sell_fee_rate

    # 淨利潤
    net_profit = sell_revenue - sell_fee - buy_cost - buy_fee

    return net_profit
```

---

## 風險管理

### 1. 執行風險

**問題**: 價格在執行期間變動

**解決方案**:
- 使用限價單而非市價單
- 設置價格保護範圍
- 監控執行狀態

```python
# 價格保護示例
max_slippage = 0.001  # 0.1%
protected_buy_price = buy_price * (1 + max_slippage)
protected_sell_price = sell_price * (1 - max_slippage)
```

### 2. 流動性風險

**問題**: 訂單簿深度不足

**解決方案**:
- 檢查訂單簿深度
- 分批執行大額訂單
- 監控市場影響

```python
# 深度檢查示例
def check_liquidity(orderbook, target_quantity):
    total_volume = sum([bid[1] for bid in orderbook.bids[:5]])
    if total_volume < target_quantity:
        print("⚠️  流動性不足")
        return False
    return True
```

### 3. 資金風險

**問題**: 資金被鎖定在某個交易所

**解決方案**:
- 在多個交易所保持資金平衡
- 定期再平衡
- 設置資金使用上限

```python
# 資金平衡檢查
def check_balance_distribution(balances, min_ratio=0.2):
    total = sum(balances.values())
    for exchange, balance in balances.items():
        ratio = balance / total
        if ratio < min_ratio:
            print(f"⚠️  {exchange} 資金比例過低: {ratio:.1%}")
```

### 4. API 限制風險

**問題**: 超過交易所 API 限制

**解決方案**:
- CCXT 自動限速（`enableRateLimit=True`）
- 監控 API 使用量
- 使用 WebSocket 減少 REST 請求

---

## 進階功能

### 1. WebSocket 實時數據

**優勢**:
- 更低延遲（<100ms）
- 更少 API 調用
- 實時推送更新

**實現**:
```python
# TODO: 添加 WebSocket 支持
# 每個交易所的 WebSocket 實現不同
# CCXT Pro 提供統一的 WebSocket 接口
```

### 2. 機器學習預測

**應用**:
- 預測價格趨勢
- 優化執行時機
- 風險評估

**示例**:
```python
from sklearn.ensemble import RandomForestClassifier

# 訓練模型預測套利成功率
model = RandomForestClassifier()
features = [spread, volume, volatility, time_of_day]
labels = [success, fail]
model.fit(features, labels)

# 預測新機會的成功率
probability = model.predict_proba(new_opportunity)
```

### 3. 自動執行

**注意**: 自動執行有風險，請謹慎使用

**實現框架**:
```python
async def execute_arbitrage(opportunity):
    # 1. 驗證機會仍然存在
    if not await verify_opportunity(opportunity):
        return False

    # 2. 檢查資金充足
    if not await check_funds(opportunity):
        return False

    # 3. 並行執行買賣訂單
    buy_task = place_order(
        opportunity.buy_exchange,
        'BUY',
        opportunity.quantity,
        opportunity.buy_price
    )
    sell_task = place_order(
        opportunity.sell_exchange,
        'SELL',
        opportunity.quantity,
        opportunity.sell_price
    )

    results = await asyncio.gather(buy_task, sell_task)

    # 4. 驗證執行結果
    return verify_execution(results)
```

---

## 故障排除

### 問題 1: 無法連接到交易所

**可能原因**:
- API 密鑰錯誤
- IP 未加入白名單
- 網絡問題

**解決方法**:
```bash
# 測試單個交易所連接
python test_connection.py

# 檢查 API 密鑰權限
# 確保有 "讀取" 和 "交易" 權限
```

### 問題 2: 找不到套利機會

**可能原因**:
- 利潤閾值設置過高
- 市場效率高，價差小
- 監控的交易所太少

**解決方法**:
- 降低 `min_profit_pct` 閾值
- 增加更多交易所
- 監控更多交易對

### 問題 3: API 限制錯誤

**可能原因**:
- 請求頻率過高
- 超過交易所限制

**解決方法**:
```python
# 增加更新間隔
update_interval=5.0  # 從 2 秒改為 5 秒

# CCXT 會自動處理限速
# 確保 enableRateLimit=True
```

---

## 最佳實踐

### 1. 從小開始

- ✅ 先用小額資金測試
- ✅ 驗證策略有效性
- ✅ 熟悉系統操作

### 2. 監控成本

- ✅ 計算實際手續費
- ✅ 考慮滑點影響
- ✅ 包括 Gas 費用（DEX）

### 3. 分散風險

- ✅ 不要把所有資金放在一個交易所
- ✅ 監控多個交易對
- ✅ 設置止損

### 4. 持續優化

- ✅ 記錄所有交易
- ✅ 分析成功/失敗原因
- ✅ 優化參數設置

---

## 相關資源

- [多交易所架構指南](./ADDING_NEW_EXCHANGES.md)
- [CEX 集成指南](./CEX_INTEGRATION_GUIDE.md)
- [CCXT 文檔](https://docs.ccxt.com/)

---

## 總結

多交易所監控系統提供：

✅ **實時監控** - 低延遲價格更新
✅ **自動檢測** - 智能套利機會發現
✅ **風險管理** - 深度分析和保護
✅ **易於擴展** - 支持添加新交易所

開始使用：

```bash
# 1. 配置 .env
# 2. 運行監控
python scripts/monitor_arbitrage.py
# 3. 觀察並學習
# 4. 優化策略
```

祝您套利成功！🚀
