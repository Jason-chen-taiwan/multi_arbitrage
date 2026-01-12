# Web Dashboard 使用指南

## 🌐 前端 Web Dashboard

除了終端文字界面，系統現在提供完整的 **Web 前端 Dashboard**，具備實時圖表和視覺化監控！

## 功能特色

### ✨ 視覺化功能

- 📊 **實時圖表**

  - PnL 趨勢圖（總 PnL + 已實現 PnL）
  - 倉位變化圖
  - Chart.js 驅動的平滑動畫

- 🎨 **現代化介面**

  - 深色主題（護眼設計）
  - 響應式佈局（支援手機/平板）
  - 流暢動畫效果

- ⚡ **實時更新**

  - WebSocket 連接
  - 自動重連機制
  - 毫秒級更新延遲

- 📈 **完整指標**
  - 所有終端 Dashboard 的指標
  - 視覺化進度條
  - 顏色指示器（綠色盈利/紅色虧損）

## 快速開始

### 1. 安裝依賴

```bash
pip install -r requirements.txt
```

新增依賴：

- `fastapi` - Web 框架
- `uvicorn` - ASGI 服務器

### 2. 啟動 Web Dashboard

#### 方式 A: 僅啟動 Dashboard Server

```bash
python scripts/run_dashboard.py
```

默認訪問：http://localhost:8000

**選項**：

```bash
# 自定義端口
python scripts/run_dashboard.py --port 8080

# 開發模式（自動重載）
python scripts/run_dashboard.py --reload

# 綁定到所有網絡介面
python scripts/run_dashboard.py --host 0.0.0.0
```

#### 方式 B: Dashboard + 模擬數據

```bash
# 運行 5 分鐘模擬
python scripts/demo_web_dashboard.py

# 自定義時長
python scripts/demo_web_dashboard.py --duration 600

# 自定義端口
python scripts/demo_web_dashboard.py --port 8080
```

這會：

1. 啟動 Web Dashboard（後台運行）
2. 模擬做市商活動
3. 實時更新數據到 Dashboard

### 3. 訪問 Dashboard

打開瀏覽器訪問：

```
http://localhost:8000
```

## Dashboard 界面

### 頂部狀態欄

```
📊 StandX Market Maker Dashboard    [🟢 已連接]
```

### 摘要卡片（5 個）

| 卡片         | 顯示內容                   |
| ------------ | -------------------------- |
| 總 PnL       | 總損益 + 已實現/未實現分解 |
| 運行時間     | 總時長 + 時均 PnL          |
| 當前倉位     | BTC 數量 + 周轉率          |
| 成交率       | 百分比 + 成交/總訂單數     |
| 正常運行時間 | 百分比 + 獎勵層級          |

### 圖表區域

#### 📈 PnL 趨勢

- 綠色線：總 PnL
- 藍色線：已實現 PnL
- 最多顯示 50 個數據點
- 自動滾動

#### 📍 倉位變化

- 橙色線：BTC 倉位
- 顯示多空變化
- 零軸參考線

### 指標面板

#### 💰 Performance Metrics

- 已實現 PnL
- 未實現 PnL
- 累計成交量
- 時均 PnL

#### 📋 Order Statistics

- 總訂單數
- 成交訂單
- 取消訂單
- 平均價差
- 庫存周轉率

#### ⏱️ Uptime Program Status

- 進度條（視覺化正常運行時間）
- 獎勵層級
- 符合資格次數
- 預估 Maker Hours
- 費率層級進度

## 與做市商集成

### 在策略中啟用 Web Dashboard

編輯您的做市商運行腳本：

```python
import threading
from src.web import create_app
from src.web.api import update_global_metrics
import uvicorn

# 啟動 Dashboard
def start_dashboard():
    app = create_app()
    config = uvicorn.Config(app, host="0.0.0.0", port=8000)
    server = uvicorn.Server(config)
    asyncio.run(server.serve())

# 在後台線程啟動
dashboard_thread = threading.Thread(target=start_dashboard, daemon=True)
dashboard_thread.start()

# 在策略迭代中更新數據
async def run_iteration(self):
    # ... 執行交易邏輯 ...

    # 更新 Dashboard
    metrics_dict = self.metrics_tracker.get_summary()
    update_global_metrics(metrics_dict)
```

### 完整集成示例

```python
# scripts/run_mm_with_dashboard.py

import asyncio
import threading
from src.strategy import UptimeMarketMaker
from src.exchange import StandXExchange
from src.web import create_app
from src.web.api import update_global_metrics
import uvicorn

# 1. 啟動 Web Dashboard
def start_dashboard(port=8000):
    app = create_app()
    config = uvicorn.Config(app, host="0.0.0.0", port=port)
    server = uvicorn.Server(config)
    asyncio.run(server.serve())

dashboard_thread = threading.Thread(
    target=start_dashboard,
    args=(8000,),
    daemon=True
)
dashboard_thread.start()

# 2. 初始化做市商
exchange = StandXExchange(config)
strategy = UptimeMarketMaker(exchange, config)

# 3. 在策略循環中更新
async def trading_loop():
    while True:
        await strategy.run_iteration()

        # 更新 Web Dashboard
        metrics = strategy.metrics_tracker.get_summary()
        update_global_metrics(metrics)

        await asyncio.sleep(5)

# 4. 運行
asyncio.run(trading_loop())
```

## API 端點

### REST API

#### GET /api/health

健康檢查

```json
{
  "status": "healthy",
  "timestamp": "2026-01-12T15:30:45",
  "connections": 2
}
```

#### GET /api/metrics

獲取當前指標

```json
{
  "runtime_hours": 12.5,
  "total_pnl": 279.79,
  "realized_pnl": 234.56,
  "unrealized_pnl": 45.23,
  "current_position": 0.25,
  "fill_rate": 0.714,
  "uptime_percentage": 75.3,
  ...
}
```

### WebSocket

#### ws://localhost:8000/ws

**連接後接收**：

```json
{
  "type": "init",
  "data": {
    /* 初始指標 */
  }
}
```

**實時更新**：

```json
{
  "type": "update",
  "data": {
    /* 更新的指標 */
  },
  "timestamp": "2026-01-12T15:30:45"
}
```

**心跳**：

```json
{ "type": "ping" }
```

## 配置選項

### Dashboard 服務器

```yaml
# config/config.yaml 或 config/uptime_config.yaml

dashboard:
  enabled: true # 啟用 Web Dashboard
  host: "0.0.0.0" # 綁定地址
  port: 8000 # 端口
  update_interval: 2 # 更新間隔（秒）
```

### 在代碼中配置

```python
from src.web import create_app

app = create_app()

# 使用 uvicorn 運行
uvicorn.run(
    app,
    host="0.0.0.0",     # 允許外部訪問
    port=8000,          # 端口
    reload=False,       # 生產環境關閉 reload
    log_level="info"
)
```

## 進階功能

### 1. 遠程訪問

如果您的做市商運行在遠程服務器：

```bash
# 服務器端
python scripts/run_dashboard.py --host 0.0.0.0 --port 8000

# 瀏覽器訪問
http://your-server-ip:8000
```

⚠️ **安全提示**：

- 考慮使用反向代理（Nginx）
- 添加身份驗證
- 使用 HTTPS

### 2. 多個做市商監控

每個做市商使用不同端口：

```bash
# 做市商 1
python scripts/demo_web_dashboard.py --port 8000

# 做市商 2
python scripts/demo_web_dashboard.py --port 8001
```

### 3. 自定義更新頻率

在 `app.js` 中修改：

```javascript
// 更快的更新（每秒）
const updateInterval = 1000;

// 更多歷史數據
const maxHistoryLength = 100;
```

## 性能考慮

### CPU 和內存

- **輕量級**：Dashboard 服務器佔用 < 50MB 內存
- **低 CPU**：異步 I/O，CPU 使用率 < 1%
- **WebSocket**：每個連接約 1-2KB 內存

### 網絡帶寬

- **REST API**：按需請求，最小帶寬
- **WebSocket**：每次更新約 1-2KB
- **圖表**：Chart.js 在客戶端渲染

### 瀏覽器兼容性

- ✅ Chrome/Edge (推薦)
- ✅ Firefox
- ✅ Safari
- ⚠️ IE 11（不支持）

## 故障排除

### 問題：Dashboard 無法訪問

**解決方案**：

1. 檢查服務器是否啟動：

   ```bash
   curl http://localhost:8000/api/health
   ```

2. 檢查端口是否被佔用：

   ```bash
   lsof -i :8000
   ```

3. 檢查防火牆設置

### 問題：數據不更新

**解決方案**：

1. 檢查 WebSocket 連接（右上角狀態點應該是綠色）
2. 打開瀏覽器開發者工具查看 Console
3. 確認 `update_global_metrics()` 被調用

### 問題：圖表顯示異常

**解決方案**：

1. 清除瀏覽器緩存
2. 確認 Chart.js CDN 可訪問
3. 檢查瀏覽器 Console 錯誤

## 與終端 Dashboard 對比

| 功能     | 終端 Dashboard | Web Dashboard |
| -------- | -------------- | ------------- |
| 實時更新 | ✅             | ✅            |
| 歷史圖表 | ❌             | ✅            |
| 視覺化   | 文字           | 圖形          |
| 遠程訪問 | ❌             | ✅            |
| 多用戶   | ❌             | ✅            |
| 資源佔用 | 極低           | 低            |
| 易用性   | 中等           | 高            |

**建議**：

- **開發/測試**：使用終端 Dashboard
- **生產/監控**：使用 Web Dashboard
- **最佳實踐**：同時運行兩者

## 截圖預覽

### 桌面視圖

```
╔══════════════════════════════════════════════════════════╗
║  📊 StandX Market Maker Dashboard      [🟢 已連接]     ║
╠══════════════════════════════════════════════════════════╣
║  [總 PnL]  [運行時間]  [當前倉位]  [成交率]  [正常運行]  ║
╠══════════════════════════════════════════════════════════╣
║  📈 PnL 趨勢圖                                          ║
║  ～～～～～～～～～～～～～～～～～～～～～～～～～～～～  ║
╠══════════════════════════════════════════════════════════╣
║  💰 Performance    📋 Statistics    ⏱️ Uptime Program   ║
╚══════════════════════════════════════════════════════════╝
```

### 手機視圖

```
╔════════════════╗
║  📊 Dashboard  ║
║  [🟢 已連接]   ║
╠════════════════╣
║  [總 PnL]      ║
║  [運行時間]    ║
║  [倉位]        ║
║  [成交率]      ║
║  [正常運行]    ║
╠════════════════╣
║  📈 圖表       ║
╠════════════════╣
║  📊 指標       ║
╚════════════════╝
```

## 未來增強

計劃中的功能：

- [ ] 身份驗證系統
- [ ] 多策略並行監控
- [ ] 歷史數據導出
- [ ] 告警通知
- [ ] 交易日誌查看
- [ ] 策略參數動態調整
- [ ] 手機 App

## 總結

Web Dashboard 提供：

✅ **專業級監控介面**  
✅ **實時視覺化圖表**  
✅ **遠程訪問能力**  
✅ **低資源佔用**  
✅ **易於集成**

立即啟動體驗：

```bash
python scripts/demo_web_dashboard.py
```

然後訪問：http://localhost:8000

---

**相關文檔**：

- [README.md](../README.md) - 系統概述
- [DASHBOARD_GUIDE.md](DASHBOARD_GUIDE.md) - 終端 Dashboard 指南
- [UPTIME_PROGRAM_GUIDE.md](UPTIME_PROGRAM_GUIDE.md) - Uptime Program 詳解
