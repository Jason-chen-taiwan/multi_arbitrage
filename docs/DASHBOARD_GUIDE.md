# Dashboard 監控系統使用指南

## 概述

Dashboard 監控系統提供實時追蹤做市商的所有關鍵性能指標，包括：

✅ **總成交量** - 累計成交數量  
✅ **已實現 PnL** - 已平倉損益  
✅ **未實現 PnL** - 當前持倉損益  
✅ **當前倉位** - 多空持倉數量  
✅ **訂單成交率** - 成交訂單 / 總訂單  
✅ **平均價差** - 實際成交價差  
✅ **庫存周轉率** - 倉位變化頻率  
✅ **正常運行時間** - Uptime Program 資格追蹤

## 系統架構

```
src/monitor/
├── __init__.py          # 模組初始化
├── metrics.py           # MetricsTracker - 指標追蹤器
└── dashboard.py         # Dashboard - 顯示控制器
```

### MetricsTracker

負責收集和計算所有性能指標。

**主要方法**：

- `update_trade()` - 記錄交易
- `update_position()` - 更新倉位
- `update_unrealized_pnl()` - 更新未實現損益
- `record_order()` - 記錄訂單統計
- `record_uptime_check()` - 記錄正常運行時間檢查
- `get_summary()` - 獲取完整摘要

**計算屬性**：

- `fill_rate` - 訂單成交率
- `average_spread_bps` - 平均價差（bps）
- `inventory_turnover` - 庫存周轉率（次/小時）
- `total_pnl` - 總損益
- `uptime_percentage` - 正常運行時間百分比

### Dashboard

負責格式化和顯示指標。

**顯示模式**：

1. **Full Dashboard** - 完整儀表板

   ```python
   dashboard.display_full_dashboard(
       strategy_name="Uptime Market Maker",
       mark_price=Decimal('95000'),
       clear=True  # 清除屏幕
   )
   ```

2. **Compact Dashboard** - 單行摘要
   ```python
   dashboard.display_compact(
       strategy_name="Test MM",
       mark_price=Decimal('95000')
   )
   ```

## 使用方式

### 1. 在策略中集成

Dashboard 已經整合到 `BaseStrategy` 中，所有策略自動擁有：

```python
class MyStrategy(BaseStrategy):
    def __init__(self, exchange, config):
        super().__init__(exchange, config)
        # self.metrics_tracker 和 self.dashboard 已經可用
```

### 2. 配置 Dashboard

在 `config.yaml` 中配置：

```yaml
strategy:
  dashboard_mode: full # 'full', 'compact', 或 'minimal'
  dashboard_interval: 30 # 顯示間隔（秒）
```

**顯示模式說明**：

- `full` - 每 N 秒顯示完整儀表板
- `compact` - 每次迭代顯示單行摘要
- `minimal` - 僅在重要事件時顯示

### 3. 記錄指標

在策略執行過程中記錄指標：

```python
# 記錄交易
self.metrics_tracker.update_trade(
    side='buy',
    price=Decimal('95000'),
    size=Decimal('2.0'),
    pnl=Decimal('15.50'),
    spread_bps=Decimal('8.0')
)

# 更新倉位
self.metrics_tracker.update_position(new_position)

# 記錄訂單
self.metrics_tracker.record_order(filled=True)

# 記錄正常運行時間檢查
self.metrics_tracker.record_uptime_check(qualified=True)
```

### 4. 顯示 Dashboard

```python
# 在策略迭代中
async def run_iteration(self):
    # ... 執行交易邏輯 ...

    # 獲取當前 mark price
    orderbook = await self.exchange.get_orderbook(self.symbol)
    mark_price = (orderbook.best_bid + orderbook.best_ask) / 2

    # 顯示 Dashboard
    if self.dashboard.should_display():
        self.dashboard.display_full_dashboard(
            strategy_name=self.__class__.__name__,
            mark_price=mark_price,
            clear=True
        )
```

## Dashboard 顯示範例

### 完整儀表板

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                          📊 Uptime Market Maker                              ║
║                            2026-01-12 15:30:45                               ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ 💰 Performance Metrics                                                       ║
╠──────────────────────────────────────────────────────────────────────────────╣
║   運行時間: 12.50 小時                                                        ║
║   已實現 PnL: 🟢 $+234.56                                                    ║
║   未實現 PnL: 🟢 $+45.23                                                     ║
║   總 PnL:     🟢 $+279.79                                                    ║
║   時均 PnL: $+22.38/hr                                                       ║
╠──────────────────────────────────────────────────────────────────────────────╣
║ 📍 Position & Volume                                                         ║
╠──────────────────────────────────────────────────────────────────────────────╣
║   當前倉位: +0.2500 BTC                                                      ║
║   倉位價值: $23,750.00                                                       ║
║   累計成交量: 45.6000 BTC                                                    ║
║   庫存周轉率: 3.65 次/小時                                                   ║
╠──────────────────────────────────────────────────────────────────────────────╣
║ 📋 Order Statistics                                                          ║
╠──────────────────────────────────────────────────────────────────────────────╣
║   總訂單數: 1,250                                                            ║
║   成交訂單: 892                                                              ║
║   取消訂單: 125                                                              ║
║   成交率: 🟢 71.4%                                                           ║
║   平均價差: 8.25 bps                                                         ║
╠──────────────────────────────────────────────────────────────────────────────╣
║ ⏱️  Uptime Program Status                                                    ║
╠──────────────────────────────────────────────────────────────────────────────╣
║   正常運行時間: 75.3%                                                        ║
║   獎勵層級: 🟢 Boosted (1.0x)                                                ║
║   符合資格: 452/600 次檢查                                                   ║
║   預估 Maker Hours: 1.00/小時 (720/月)                                       ║
║   費率層級: ⭐ MM1 (2.25 bps taker + 0.25 bps maker)                        ║
╠──────────────────────────────────────────────────────────────────────────────╣
║ 最後更新: 15:30:45                                                           ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

### 緊湊顯示

```
[15:30:45] Test MM | 運行: 12.5h | PnL: 🟢$+279.79 | 倉位: +0.2500 | 成交率: 71.4% | 正常運行: 75.3%
```

## 測試 Dashboard

運行測試腳本查看 Dashboard 實際效果：

```bash
# 運行 60 秒測試
python scripts/test_dashboard.py

# 運行 2 分鐘測試
python scripts/test_dashboard.py --duration 120
```

測試腳本會模擬做市商活動：

- 隨機價格波動
- 訂單創建和成交
- 倉位變化
- PnL 更新
- 正常運行時間檢查

## 關鍵指標說明

### 1. 總成交量（Total Volume）

累計所有成交的數量，單位 BTC。反映做市商的活躍度。

### 2. 已實現 PnL（Realized PnL）

已平倉交易的損益總和。綠色 🟢 表示盈利，紅色 🔴 表示虧損。

### 3. 未實現 PnL（Unrealized PnL）

當前持倉的浮動損益，隨市場價格實時變化。

### 4. 當前倉位（Current Position）

當前持有的 BTC 數量。正數表示多頭，負數表示空頭。

### 5. 訂單成交率（Fill Rate）

```
成交率 = 成交訂單數 / 總訂單數
```

- 🟢 > 70%：優秀
- 🟡 40-70%：正常
- 🔴 < 40%：需要調整

### 6. 平均價差（Average Spread）

實際成交的平均價差，單位 basis points (bps)。

對於 Uptime Program：

- ✅ ≤ 10 bps：符合資格
- ❌ > 10 bps：不符合資格

### 7. 庫存周轉率（Inventory Turnover）

```
周轉率 = 倉位變化次數 / 運行時間（小時）
```

反映做市商的交易頻率和風險管理效率。

### 8. 正常運行時間（Uptime Percentage）

```
正常運行時間 = 符合資格的檢查次數 / 總檢查次數
```

**Uptime Program 層級**：

- 🟢 ≥ 70%：Boosted tier (1.0x multiplier)
- 🟡 ≥ 50%：Standard tier (0.5x multiplier)
- ⚪ < 50%：Inactive (0x multiplier)

## 實際應用示例

### 示例 1: 基本監控

```python
from src.monitor import MetricsTracker, Dashboard

# 初始化
metrics = MetricsTracker()
dashboard = Dashboard(metrics)

# 交易循環
while True:
    # ... 執行交易 ...

    # 記錄交易
    metrics.update_trade('buy', Decimal('95000'), Decimal('2.0'))

    # 每 30 秒顯示一次
    if dashboard.should_display():
        dashboard.display_full_dashboard("My Strategy", mark_price)
```

### 示例 2: 自定義顯示間隔

```python
# 設置為 60 秒更新一次
dashboard.set_display_interval(60)

# 或在配置中設置
config = {
    'dashboard_interval': 60
}
```

### 示例 3: 獲取摘要數據

```python
# 獲取完整摘要
summary = metrics.get_summary()

print(f"運行時間: {summary['runtime_hours']:.2f} 小時")
print(f"總 PnL: ${summary['total_pnl']:,.2f}")
print(f"成交率: {summary['fill_rate']*100:.1f}%")
print(f"正常運行時間: {summary['uptime_percentage']:.1f}%")
```

## 性能考慮

1. **顯示頻率**：

   - 建議間隔 ≥ 30 秒
   - 過於頻繁會影響終端性能

2. **清屏操作**：

   - `clear=True` 會清除終端屏幕
   - 如需保留歷史輸出，設為 `False`

3. **緊湊模式**：
   - 適合高頻交易
   - 降低輸出開銷

## 故障排除

### 問題：Dashboard 不顯示

**檢查**：

1. 是否正確初始化 `MetricsTracker` 和 `Dashboard`
2. 是否調用 `should_display()` 或設置了正確的間隔
3. 是否有錯誤阻止了顯示

### 問題：指標不更新

**檢查**：

1. 是否正確調用 `update_trade()`, `update_position()` 等方法
2. 是否傳遞了正確的參數類型（Decimal）
3. 是否在交易邏輯中集成了指標更新

### 問題：Uptime 指標為 0

**檢查**：

1. 是否調用了 `record_uptime_check()`
2. 檢查頻率是否合理（建議每分鐘 1-2 次）

## 最佳實踐

1. **定期顯示**：

   - 使用 `should_display()` 控制顯示頻率
   - 避免每次迭代都顯示完整 Dashboard

2. **記錄所有事件**：

   - 交易執行時調用 `update_trade()`
   - 倉位變化時調用 `update_position()`
   - 訂單創建/取消時調用 `record_order()`

3. **Uptime 追蹤**：

   - 定期檢查訂單資格（每 30-60 秒）
   - 確保符合 10 bps 價差要求
   - 追蹤目標 70%+ 正常運行時間

4. **性能監控**：
   - 定期檢查 `fill_rate`
   - 監控 `inventory_turnover`
   - 追蹤 `total_pnl` 趨勢

## 總結

Dashboard 監控系統提供：

- ✅ 實時性能指標追蹤
- ✅ 多種顯示模式（完整/緊湊）
- ✅ Uptime Program 專屬監控
- ✅ 易於集成和自定義
- ✅ 完整的指標計算

使用 Dashboard，您可以：

- 實時了解做市商狀態
- 快速發現問題和機會
- 優化 Uptime Program 參與
- 追蹤長期性能表現

---

**相關文檔**：

- [README.md](../README.md) - 系統概述
- [UPTIME_PROGRAM_GUIDE.md](UPTIME_PROGRAM_GUIDE.md) - Uptime Program 指南
- [STRATEGY_DESIGN.md](STRATEGY_DESIGN.md) - 策略設計
