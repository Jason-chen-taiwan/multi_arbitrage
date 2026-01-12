# StandX 做市商策略設計文檔

## 一、做市商基礎理論

### 1.1 什麼是做市商（Market Maker）？

做市商是在金融市場中提供流動性的交易者，通過在買賣兩側同時掛單來賺取價差（spread）。

**核心機制**：

- **買單（Bid）**：以略低於市場價的價格買入
- **賣單（Ask）**：以略高於市場價的價格賣出
- **利潤來源**：買賣價差（Ask - Bid）

**示例**：

```
市場中間價：$100,000
做市商掛單：
  - 買單：$99,950 (0.05% 價差)
  - 賣單：$100,050 (0.05% 價差)

當兩邊都成交時，利潤 = $100,050 - $99,950 = $100 (0.1%)
```

### 1.2 做市商的價值

1. **提供流動性**：讓其他交易者能快速成交
2. **縮小價差**：競爭使得市場價差收窄
3. **穩定市場**：減少價格劇烈波動
4. **獲取手續費返傭**：許多交易所對 Maker 提供費用優惠

### 1.3 做市商的風險

1. **庫存風險**：持倉方向錯誤導致虧損
2. **逆向選擇**：在價格快速變動時被套利者利用
3. **市場風險**：極端市場條件下的巨大波動
4. **技術風險**：系統故障、網絡延遲等

## 二、做市策略設計

### 2.1 簡單做市策略（Simple Market Making）

#### 核心邏輯

```python
# 1. 獲取市場中間價
mid_price = (best_bid + best_ask) / 2

# 2. 計算掛單價格
spread = 0.001  # 0.1% 價差
bid_price = mid_price * (1 - spread)
ask_price = mid_price * (1 + spread)

# 3. 掛單
place_order(side=BUY, price=bid_price, size=order_size)
place_order(side=SELL, price=ask_price, size=order_size)
```

#### 優點

- 簡單易懂
- 實現容易
- 適合低波動市場

#### 缺點

- 不考慮市場狀況
- 庫存管理不足
- 可能在極端情況下虧損

### 2.2 庫存管理策略

#### 核心概念

做市商應該維持**接近中性的倉位**，避免單邊風險。

#### 實現方式

```python
# 目標倉位：0（中性）
target_position = 0

# 當前庫存偏移
inventory_skew = current_position - target_position

# 根據庫存調整價格
if inventory_skew > 0:  # 多頭過多
    # 降低買價，提高賣價，鼓勵賣出
    bid_adjustment = -inventory_skew * adjustment_factor
    ask_adjustment = -inventory_skew * adjustment_factor
else:  # 空頭過多
    # 提高買價，降低賣價，鼓勵買入
    bid_adjustment = -inventory_skew * adjustment_factor
    ask_adjustment = -inventory_skew * adjustment_factor

bid_price = base_bid + bid_adjustment
ask_price = base_ask + ask_adjustment
```

#### 示例

假設最大持倉為 1 BTC，當前持倉為 +0.5 BTC（多頭 50%）：

```
中間價：$100,000
基礎價差：0.1%

不調整情況：
  買單：$99,950
  賣單：$100,050

庫存調整後：
  買單：$99,900 (-$50，降低買入意願)
  賣單：$100,000 (-$50，增加賣出吸引力)
```

### 2.3 自適應做市策略

#### 動態價差調整

根據市場波動率調整價差：

```python
# 計算波動率
volatility = calculate_volatility(price_history)

# 動態調整價差
dynamic_spread = base_spread * (1 + volatility_multiplier * volatility)

# 限制範圍
spread = clamp(dynamic_spread, min_spread, max_spread)
```

**邏輯**：

- 高波動 → 擴大價差（保護自己）
- 低波動 → 縮小價差（增加成交）

#### 訂單簿不平衡檢測

```python
# 計算買賣盤力量
bid_volume = sum(top 5 bid levels)
ask_volume = sum(top 5 ask levels)

# 計算不平衡
imbalance = (bid_volume - ask_volume) / (bid_volume + ask_volume)

# 調整報價
if imbalance > threshold:  # 買盤強
    # 提高報價，預期價格上漲
    bid_price += imbalance_adjustment
    ask_price += imbalance_adjustment
elif imbalance < -threshold:  # 賣盤強
    # 降低報價，預期價格下跌
    bid_price -= imbalance_adjustment
    ask_price -= imbalance_adjustment
```

### 2.4 多層掛單策略

在多個價格層級掛單，提高成交機會：

```
層級 1（最接近）：
  買：$99,950 @ 0.01 BTC
  賣：$100,050 @ 0.01 BTC

層級 2：
  買：$99,900 @ 0.008 BTC
  賣：$100,100 @ 0.008 BTC

層級 3：
  買：$99,850 @ 0.006 BTC
  賣：$100,150 @ 0.006 BTC
```

**優點**：

- 更好的價格發現
- 捕捉更多成交機會
- 分散風險

## 三、風險管理

### 3.1 倉位限制

```python
# 最大倉位限制
MAX_POSITION = 1.0  # BTC

# 檢查是否可以開倉
if abs(current_position + new_order_size) > MAX_POSITION:
    reject_order()
```

### 3.2 損失控制

```python
# 每日最大虧損
MAX_DAILY_LOSS = 1000  # USD

# 檢查每日 PnL
if daily_pnl < -MAX_DAILY_LOSS:
    stop_trading()
    cancel_all_orders()
```

### 3.3 最大回撤保護

```python
# 最大回撤 20%
MAX_DRAWDOWN = 0.20

# 計算當前回撤
current_drawdown = (peak_equity - current_equity) / peak_equity

if current_drawdown > MAX_DRAWDOWN:
    halt_trading()
```

### 3.4 熔斷機制

```python
# 價格急劇變動時停止
if abs(current_price - last_price) / last_price > 0.05:  # 5%
    cancel_all_orders()
    wait_for_stability()
```

## 四、性能指標

### 4.1 關鍵指標

1. **總成交量**：累計交易量
2. **已實現 PnL**：已平倉的利潤
3. **未實現 PnL**：當前持倉損益
4. **夏普比率**：風險調整後收益
5. **最大回撤**：最大虧損百分比
6. **成交率**：訂單成交比例

### 4.2 計算示例

```python
# 夏普比率
sharpe_ratio = mean_return / std_return * sqrt(periods_per_year)

# 最大回撤
max_drawdown = max((peak - trough) / peak for all peaks)

# 勝率
win_rate = winning_trades / total_trades

# 平均利潤因子
profit_factor = gross_profit / gross_loss
```

## 五、實戰技巧

### 5.1 選擇合適的交易對

**理想特徵**：

- 高流動性（窄價差）
- 穩定波動（非極端市場）
- 交易量大（成交機會多）
- Maker 手續費優惠

### 5.2 優化參數

**價差設定**：

```
流動性好：0.05% - 0.1%
流動性中：0.1% - 0.2%
流動性差：0.2% - 0.5%
```

**刷新頻率**：

```
高頻：1-3 秒（需要低延遲）
中頻：5-10 秒（平衡性能與成本）
低頻：30-60 秒（適合慢市場）
```

### 5.3 避免常見錯誤

1. **價差過小**：成本高於收益
2. **忽略庫存**：單邊持倉過大
3. **過度交易**：手續費侵蝕利潤
4. **不設止損**：極端情況下巨虧
5. **忽略延遲**：被高頻交易者套利

## 六、進階主題

### 6.1 統計套利

結合多個交易對進行套利：

```python
# BTC-USD vs ETH-USD 價差套利
btc_eth_ratio = btc_price / eth_price
mean_ratio = historical_mean(btc_eth_ratio)

if btc_eth_ratio > mean_ratio * 1.05:
    # BTC 相對高估
    sell_btc()
    buy_eth()
elif btc_eth_ratio < mean_ratio * 0.95:
    # BTC 相對低估
    buy_btc()
    sell_eth()
```

### 6.2 機器學習優化

使用 ML 預測最優參數：

```python
from sklearn.ensemble import RandomForestRegressor

# 特徵：市場狀態
X = [volatility, spread, volume, imbalance, time_of_day]

# 目標：最優價差
y = optimal_spread

# 訓練模型
model = RandomForestRegressor()
model.fit(X_train, y_train)

# 預測
predicted_spread = model.predict(current_features)
```

### 6.3 高頻優化

- 使用 WebSocket 實時數據
- 本地訂單簿維護
- 批量下單減少延遲
- 使用 C++/Rust 重寫關鍵路徑

## 七、總結

成功的做市商需要：

1. ✅ **扎實的理論基礎**：理解市場微觀結構
2. ✅ **良好的風險管理**：嚴格控制倉位和損失
3. ✅ **持續優化**：根據市場變化調整策略
4. ✅ **技術實力**：低延遲、高可靠性的系統
5. ✅ **心理素質**：面對虧損保持冷靜

做市是一個**長期遊戲**，需要不斷學習和改進。從小規模開始，逐步增加複雜度和資金規模。

---

**免責聲明**：本文檔僅供教育目的，不構成投資建議。實際交易存在風險，請謹慎評估。
