# StandX 做市商系統架構文件

> 版本：1.0
> 更新日期：2026-01-18

---

## 目錄

1. [系統概覽](#1-系統概覽)
2. [核心組件](#2-核心組件)
3. [報價邏輯](#3-報價邏輯)
4. [風控機制](#4-風控機制)
5. [數據流](#5-數據流)
6. [配置參數](#6-配置參數)
7. [日誌與監控](#7-日誌與監控)
8. [故障排查](#8-故障排查)

---

## 1. 系統概覽

### 1.1 做市商目標

StandX 做市商是一個自動化報價系統，目標是：

1. **維持雙邊掛單**：始終保持一個買單（bid）和一個賣單（ask）在市場上
2. **賺取價差/返佣**：透過 maker 訂單賺取交易所返佣或價差收益
3. **控制庫存風險**：使用 Inventory Skew 動態調整報價，避免單邊累積過多倉位

### 1.2 策略模式

系統支援兩種策略模式：

| 模式 | 目標 | 報價策略 | 適用場景 |
|------|------|----------|----------|
| **uptime** | StandX Uptime Program 獎勵 | 固定距離掛單（order_distance_bps） | 追求穩定報價時間 |
| **rebate** | 交易所 maker 返佣 | 更激進的報價（可掛在 best bid/ask） | 高流動性市場 |

### 1.3 系統架構圖

```
┌─────────────────────────────────────────────────────────────────────┐
│                        MarketMakerExecutor                          │
│                    (src/strategy/market_maker_executor.py)          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐  │
│  │   MMConfig   │    │   MMState    │    │   StandX Adapter     │  │
│  │  (配置參數)   │    │  (狀態管理)  │    │   (交易所連接)        │  │
│  └──────────────┘    └──────────────┘    └──────────────────────┘  │
│         │                   │                      │                │
│         │                   │            ┌─────────┴─────────┐      │
│         │                   │            │                   │      │
│         ▼                   ▼            ▼                   ▼      │
│  ┌──────────────────────────────┐  ┌──────────┐      ┌──────────┐  │
│  │      Price Calculator        │  │ REST API │      │WebSocket │  │
│  │  (Skew + Breakeven + Vol)   │  │ (下單/查詢)│      │(即時事件) │  │
│  └──────────────────────────────┘  └──────────┘      └──────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                        ┌───────────────────────┐
                        │    StandX Exchange    │
                        │   (perps.standx.com)  │
                        └───────────────────────┘
```

### 1.4 核心文件清單

| 文件路徑 | 說明 | 行數 |
|----------|------|------|
| `src/strategy/market_maker_executor.py` | 主執行器 | ~2,700 |
| `src/strategy/mm_state.py` | 狀態管理 | ~900 |
| `src/strategy/mm_config_manager.py` | 配置管理 | ~200 |
| `src/adapters/standx_adapter.py` | REST API 封裝 | ~750 |
| `src/adapters/standx_ws_client.py` | WebSocket 客戶端 | ~450 |
| `config/mm_config.yaml` | 配置文件 | ~100 |

---

## 2. 核心組件

### 2.1 MarketMakerExecutor（主執行器）

**位置**：`src/strategy/market_maker_executor.py`

#### 2.1.1 初始化流程

```python
# Line 343-491: start() 方法
async def start():
    1. 創建交易日誌文件（logs/mm_trades_YYYYMMDD_HHMMSS.log）
    2. 記錄完整配置到日誌
    3. 調用 _initialize() 進行狀態同步
    4. 啟動主循環
```

```python
# Line 458-490: _initialize() 方法
async def _initialize():
    1. 獲取交易對 tick_size（最小價格單位）
    2. 同步 StandX 倉位（REST API 查詢）
    3. 同步 Hedge 倉位（如啟用）
    4. 取消所有現有訂單（clean slate）
    5. 初始化 WebSocket 連接
```

#### 2.1.2 主循環結構

```python
# Line 809-821: _run_loop()
while _running:
    await _tick()                              # 執行單次邏輯
    await asyncio.sleep(tick_interval_ms/1000) # 默認 100ms
```

```python
# Line 823-1038: _tick() 單次執行
async def _tick():
    ┌─────────────────────────────────────────────────────────────┐
    │ Step 1: 硬停自動恢復檢查                                      │
    │   - 如果 status == PAUSED 且超過冷卻時間                      │
    │   - 檢查倉位是否 < resume_position_btc                        │
    │   - 連續 3 次確認後恢復                                       │
    ├─────────────────────────────────────────────────────────────┤
    │ Step 2: 價格更新                                             │
    │   - 獲取 orderbook（best_bid, best_ask, mid_price）          │
    │   - 更新價格歷史（用於波動率計算）                             │
    │   - 記錄 uptime 統計                                         │
    ├─────────────────────────────────────────────────────────────┤
    │ Step 3: 成交檢測                                             │
    │   - WebSocket 模式：即時回調處理                              │
    │   - 輪詢模式：檢測倉位變化                                    │
    ├─────────────────────────────────────────────────────────────┤
    │ Step 4: 波動率控制                                           │
    │   - 計算 5 秒窗口波動率                                       │
    │   - 超過閾值 → 暫停並撤單                                     │
    ├─────────────────────────────────────────────────────────────┤
    │ Step 5: 訂單管理                                             │
    │   - 價格逼近 → 撤單（cancel_distance_bps）                    │
    │   - 價格偏離 → 重掛（rebalance_distance_bps）                 │
    ├─────────────────────────────────────────────────────────────┤
    │ Step 6: 下單                                                 │
    │   - 調用 _place_orders(mid_price, best_bid, best_ask)        │
    └─────────────────────────────────────────────────────────────┘
```

#### 2.1.3 訂單生命週期

```
                    ┌────────────┐
                    │  計算價格   │
                    └─────┬──────┘
                          │
                          ▼
            ┌─────────────────────────┐
            │  REST Gate 查詢交易所    │
            │  get_open_orders()      │
            └─────────────┬───────────┘
                          │
              ┌───────────┴───────────┐
              │                       │
              ▼                       ▼
    ┌─────────────────┐     ┌─────────────────┐
    │ 交易所已有訂單   │     │ 交易所無訂單     │
    │ → 跳過下單      │     │ → 發送下單請求   │
    └─────────────────┘     └────────┬────────┘
                                     │
                                     ▼
                          ┌───────────────────┐
                          │  place_order()    │
                          │  REST API 下單    │
                          └────────┬──────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │                             │
                    ▼                             ▼
          ┌─────────────────┐           ┌─────────────────┐
          │ WebSocket 確認   │           │  輪詢檢測倉位    │
          │ order_id 更新   │           │  變化判定成交    │
          └────────┬────────┘           └────────┬────────┘
                   │                             │
                   └──────────────┬──────────────┘
                                  │
                                  ▼
                        ┌─────────────────┐
                        │  成交處理       │
                        │  - 更新倉位     │
                        │  - 清除訂單     │
                        │  - 觸發對沖     │
                        └─────────────────┘
```

### 2.2 MMState（狀態管理）

**位置**：`src/strategy/mm_state.py`

#### 2.2.1 OrderInfo 訂單追蹤

```python
# Line 130-158
@dataclass
class OrderInfo:
    order_id: Optional[str]          # 交易所訂單 ID
    client_order_id: Optional[str]   # 客戶端訂單 ID（用於追蹤）
    side: str                        # "buy" 或 "sell"
    price: Decimal                   # 訂單價格
    qty: Decimal                     # 訂單數量
    status: str                      # "pending", "open", "filled", "canceled_or_unknown"

    # 進階追蹤
    orig_qty: Optional[Decimal]           # 原始數量
    last_remaining_qty: Optional[Decimal] # 上次查詢剩餘量
    cum_filled_qty: Decimal               # 累計成交量
    disappeared_since_ts: Optional[float] # 訂單消失時間戳
    unknown_pending_checks: int           # 未知狀態確認次數
```

#### 2.2.2 倉位管理

```python
# Universal Position Map（通用倉位映射）
_positions: Dict[Tuple[str, str], Decimal] = {}
# Key: (exchange, symbol) → Value: position_qty

# 方法
get_position(exchange, symbol) → Decimal    # 獲取指定交易對倉位
set_position(exchange, symbol, pos)         # 設置倉位

# Legacy 欄位（向後兼容）
_standx_position: Decimal   # StandX 主倉位
_hedge_position: Decimal    # GRVT 對沖倉位
```

#### 2.2.3 EventDeduplicator 事件去重

```python
# Line 22-68
class EventDeduplicator:
    """
    防止 WebSocket 重複事件被處理多次

    Key: "{order_id}:{filled_qty}"
    TTL: 60 秒自動過期
    """

    def is_duplicate(self, order_id: str, filled_qty: Decimal) -> bool:
        # 1. 構建唯一 key
        # 2. 檢查是否在 TTL 內已見過
        # 3. 如果是新事件，記錄並返回 False
```

#### 2.2.4 OrderThrottle 下單節流

```python
# Line 72-127
class OrderThrottle:
    """
    防止同方向快速重複下單

    Cooldown: 2 秒（可配置）
    """

    def can_place(self, side: str) -> bool:
        # 檢查距離上次下單是否超過 cooldown

    def record_order(self, side: str):
        # 記錄下單時間（必須在下單前調用，防止競爭條件）
```

### 2.3 Exchange Adapters

#### 2.3.1 StandX REST API

**位置**：`src/adapters/standx_adapter.py`

| 方法 | 用途 | API 端點 |
|------|------|----------|
| `place_order()` | 下單 | POST `/api/new_order` |
| `cancel_order()` | 撤單 | POST `/api/cancel_order` |
| `get_open_orders()` | 查詢掛單 | GET `/api/query_open_orders` |
| `get_positions()` | 查詢倉位 | GET `/api/query_positions` |
| `get_orderbook()` | 獲取盤口 | GET `/api/query_depth` |
| `get_balance()` | 查詢餘額 | GET `/api/query_balance` |

**錯誤重試機制**：
- 最多重試 3 次
- 指數退避：2s → 4s → 6s
- 捕獲：`ClientConnectorError`, `TimeoutError`

#### 2.3.2 WebSocket 即時事件

**位置**：`src/adapters/standx_ws_client.py`

**連接端點**：
- Market Stream: `wss://perps.standx.com/ws-stream/v1`
- Order Stream: `wss://perps.standx.com/ws-api/v1`

**事件類型**：

| Channel | 事件 | 處理函數 |
|---------|------|----------|
| `order` | 訂單狀態更新 | `_on_ws_order_state()` |
| `trade` | 成交事件 | `_on_ws_fill()` |
| `position` | 倉位變化 | Position callback |
| `depth_book` | 盤口更新 | Price callback |

#### 2.3.3 雙通道同步機制

```
┌─────────────────────────────────────────────────────────────┐
│                     WebSocket（即時）                        │
│  - 成交通知 ~100-500ms 延遲                                  │
│  - 訂單狀態更新                                              │
│  - 用於：快速響應                                            │
├─────────────────────────────────────────────────────────────┤
│                     REST API（權威）                         │
│  - 每個 tick 查詢 get_open_orders()                         │
│  - 用於：狀態驗證、清理孤兒訂單                               │
│  - 是「真相來源」                                            │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 報價邏輯

### 3.1 價格計算流程

**位置**：`market_maker_executor.py` Line 1255-1491 `_calculate_prices()`

```
┌─────────────────────────────────────────────────────────────┐
│ Step 1: 基礎距離                                             │
│   uptime 模式：bid = mid - (mid * order_distance_bps/10000) │
│   rebate 模式：bid = best_bid（更激進）                      │
├─────────────────────────────────────────────────────────────┤
│ Step 2: 庫存偏斜（Inventory Skew）                           │
│   - 計算 pos_ratio = position / max_position (-1 ~ +1)      │
│   - Long 偏多：bid 拉遠，ask 拉近                            │
│   - Short 偏多：bid 拉近，ask 拉遠                           │
├─────────────────────────────────────────────────────────────┤
│ Step 3: 保本回補（Breakeven Reversion）                      │
│   - 如果有建倉記錄，回補方向用 entry_price                    │
│   - 確保平倉時不虧損                                         │
├─────────────────────────────────────────────────────────────┤
│ Step 4: 波動率調整                                           │
│   - 高波動時擴大價差                                         │
│   - 70% 閾值開始調整，100% 時最大擴展                        │
├─────────────────────────────────────────────────────────────┤
│ Step 5: 對齊 tick_size                                       │
│   - bid 向下取整                                             │
│   - ask 向上取整                                             │
└─────────────────────────────────────────────────────────────┘
```

#### 3.1.1 Inventory Skew 詳解

```python
# 計算倉位比例
pos_ratio = current_position / effective_max_position
pos_ratio = clamp(pos_ratio, -1, +1)

# 偏斜參數
push_bps = 6    # 偏倉方向拉遠
pull_bps = 4.5  # 回補方向拉近

# Long 偏多 (pos_ratio > 0)
bid_bps = base_bps + (pos_ratio * push_bps)      # bid 更遠（不想再買）
ask_bps = base_bps - (pos_ratio * pull_bps)      # ask 更近（想賣出）

# Short 偏多 (pos_ratio < 0)
bid_bps = base_bps - (|pos_ratio| * pull_bps)    # bid 更近（想買回）
ask_bps = base_bps + (|pos_ratio| * push_bps)    # ask 更遠（不想再賣）
```

### 3.2 REST Gate 機制

**位置**：`market_maker_executor.py` Line 1041-1171

#### 3.2.1 工作流程

```python
async def _place_orders(mid_price, best_bid, best_ask):
    # 1. 查詢交易所現有訂單
    try:
        open_orders = await self.primary.get_open_orders(symbol)
        self._rest_gate_failures = 0  # 重置失敗計數
    except Exception:
        self._rest_gate_failures += 1
        if self._rest_gate_failures >= 3:
            logger.warning("REST Gate: Safe mode activated")
        return  # 不下單

    # 2. 分類訂單
    exchange_bids = [o for o in open_orders if o.side == "buy"]
    exchange_asks = [o for o in open_orders if o.side == "sell"]

    # 3. 同步本地狀態
    # - 交易所無訂單但本地有 → 清除本地
    # - 交易所有訂單但本地無 → 取消孤兒訂單
    # - 交易所有多個同方向訂單 → 保留最新，取消其他

    # 4. 根據交易所狀態決定是否下單
    has_bid = len(exchange_bids) > 0
    has_ask = len(exchange_asks) > 0

    if not has_bid and can_place_bid:
        await _place_bid(bid_price)
    if not has_ask and can_place_ask:
        await _place_ask(ask_price)
```

#### 3.2.2 孤兒訂單處理

| 情況 | 處理 | 原因 |
|------|------|------|
| 交易所有訂單，本地無 | 取消 | 避免無追蹤的訂單 |
| 本地有訂單，交易所無 | 清除本地 | 訂單已被成交/取消 |
| 交易所同方向多訂單 | 保留最新，取消舊的 | 防止重複訂單 |

---

## 4. 風控機制

### 4.1 倉位控制

#### 4.1.1 三層倉位限制

```
                        Position
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
   -max_pos            0            +max_pos
        │                  │                  │
        ▼                  ▼                  ▼
   ┌─────────┐       ┌─────────┐       ┌─────────┐
   │ 只能買  │       │ 雙邊掛單│       │ 只能賣  │
   │(回補Short)│      │         │       │(回補Long)│
   └─────────┘       └─────────┘       └─────────┘
                           │
            ┌──────────────┼──────────────┐
            │              │              │
     -hard_stop       0        +hard_stop
            │              │              │
            ▼              ▼              ▼
      ┌─────────┐    ┌─────────┐    ┌─────────┐
      │ 硬停    │    │ 正常    │    │ 硬停    │
      │ 撤所有單│    │         │    │ 撤所有單│
      └─────────┘    └─────────┘    └─────────┘
```

| 參數 | 默認值 | 說明 |
|------|--------|------|
| `max_position_btc` | 0.01 | 軟停：超過後只能掛回補方向 |
| `hard_stop_position_btc` | 0.007 | 硬停：超過後撤銷所有訂單 |
| `resume_position_btc` | 0.0045 | 恢復：低於此值後自動恢復 |

#### 4.1.2 硬停恢復機制

```python
# 觸發硬停
if abs(position) >= hard_stop_position_btc:
    await _cancel_all_orders()
    _status = PAUSED
    _hard_stop_time = time.time()

# 恢復條件（全部滿足）
1. time.time() - _hard_stop_time > hard_stop_cooldown_sec  # 冷卻 30 秒
2. abs(position) < resume_position_btc                     # 倉位降低
3. 連續 resume_check_count 次確認（默認 3 次）              # Hysteresis
```

### 4.2 訂單保護

#### 4.2.1 價格距離控制

```
                    best_bid         mid_price         best_ask
                        │                │                │
    ◄───────────────────┼────────────────┼────────────────┼───────────────────►
                        │                │                │
                   ┌────┴────┐      ┌────┴────┐      ┌────┴────┐
                   │cancel_  │      │order_   │      │cancel_  │
                   │distance │      │distance │      │distance │
                   │(3 bps)  │      │(7 bps)  │      │(3 bps)  │
                   └─────────┘      └─────────┘      └─────────┘
                        │                                │
                        ▼                                ▼
                   價格進入此範圍                    價格進入此範圍
                   → 撤銷買單                       → 撤銷賣單
```

| 參數 | 默認值 | 說明 |
|------|--------|------|
| `order_distance_bps` | 7 | 掛單距離 mid price |
| `cancel_distance_bps` | 5 | 價格逼近時撤單 |
| `rebalance_distance_bps` | 10 | 價格偏離時重掛 |

#### 4.2.2 波動率暫停

```python
# Line 937-952
volatility = state.get_volatility_bps()  # 5 秒滾動窗口

if volatility > volatility_threshold_bps:  # 默認 5 bps
    await _cancel_all_orders()
    logger.warning(f"Volatility pause: {volatility:.1f} bps")
    return  # 跳過本次 tick
```

### 4.3 重複訂單防護

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 1: OrderThrottle                                      │
│   - 同方向 2 秒冷卻                                          │
│   - record_order() 在 await 前調用，防止競爭條件             │
├─────────────────────────────────────────────────────────────┤
│ Layer 2: EventDeduplicator                                  │
│   - key = "{order_id}:{filled_qty}"                         │
│   - 60 秒 TTL 自動過期                                       │
│   - 防止 WebSocket 重複事件                                  │
├─────────────────────────────────────────────────────────────┤
│ Layer 3: REST Gate                                          │
│   - 每次下單前查詢交易所                                     │
│   - 只有交易所無訂單時才下單                                 │
│   - 是最終防線                                               │
├─────────────────────────────────────────────────────────────┤
│ Layer 4: _placing_bid / _placing_ask 標記                    │
│   - 下單期間設為 True                                        │
│   - 防止同一 tick 內重複下單                                 │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. 數據流

### 5.1 主循環數據流

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Main Loop (100ms)                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌───────────┐     ┌───────────┐     ┌───────────┐     ┌───────────┐   │
│  │ Orderbook │────►│ Volatility│────►│ Price     │────►│ Order     │   │
│  │ Update    │     │ Check     │     │ Calculate │     │ Management│   │
│  └───────────┘     └───────────┘     └───────────┘     └───────────┘   │
│       │                 │                 │                 │           │
│       ▼                 ▼                 ▼                 ▼           │
│  get_orderbook()   vol > threshold?   Skew + Break-   REST Gate +      │
│  → mid_price       → pause/resume     even + Vol adj  place_orders()   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.2 WebSocket 事件流

```
StandX WebSocket
      │
      ├──► "trade" channel ──► _on_ws_fill()
      │         │
      │         ├──► 過濾 qty=0 事件
      │         ├──► EventDeduplicator 去重
      │         ├──► 創建 FillEvent
      │         ├──► 清除對應訂單
      │         └──► 觸發 on_fill_event()
      │
      └──► "order" channel ──► _on_ws_order_state()
                │
                ├──► status == "rejected" → 記錄 post_only reject
                └──► status == "cancelled" → 清除本地訂單
```

### 5.3 狀態同步流

```
┌─────────────────┐         ┌─────────────────┐
│  Local State    │◄───────►│ Exchange State  │
│  (MMState)      │  sync   │ (StandX API)    │
└────────┬────────┘         └────────┬────────┘
         │                           │
         │  REST Gate 每 tick 查詢   │
         │◄──────────────────────────┤
         │                           │
         │  WebSocket 即時推送       │
         │◄──────────────────────────┤
         │                           │
         │  衝突時以交易所為準        │
         └───────────────────────────┘
```

---

## 6. 配置參數

### 6.1 完整參數表

**文件**：`config/mm_config.yaml`

#### 6.1.1 交易對設定

```yaml
symbols:
  standx: "BTC-USD"           # 主交易對
  hedge: "BTC_USDT_Perp"      # 對沖交易對（GRVT）
  binance: "BTC/USDT:USDT"    # Binance 參考價格
```

#### 6.1.2 報價參數

```yaml
quote:
  order_distance_bps: 7       # 掛單距離 mid price (bps)
  cancel_distance_bps: 5      # 價格逼近撤單距離 (bps)
  rebalance_distance_bps: 10  # 價格偏離重掛距離 (bps)
  queue_position_limit: 3     # 排在前 N 檔時撤單
```

#### 6.1.3 倉位參數

```yaml
position:
  order_size_btc: 0.02        # 單筆訂單量
  max_position_btc: 0.1       # 軟停倉位
```

#### 6.1.4 波動率控制

```yaml
volatility:
  window_sec: 5               # 觀察窗口
  threshold_bps: 5            # 暫停閾值
```

#### 6.1.5 執行參數

```yaml
execution:
  tick_interval_ms: 100       # 主循環間隔
  dry_run: false              # 模擬模式
  disappear_time_sec: 2.0     # 訂單消失判定時間
```

#### 6.1.6 對沖參數

```yaml
hedge:
  enabled: false              # 是否啟用對沖
  exchange: "grvt"            # 對沖交易所
  timeout_ms: 1000            # 對沖超時
  max_unhedged_position: 0.01 # 最大未對沖倉位
```

### 6.2 進階配置（代碼內）

**位置**：`market_maker_executor.py` Line 150-248 `MMConfig`

| 參數 | 默認值 | 說明 |
|------|--------|------|
| `strategy_mode` | "uptime" | 策略模式 |
| `hard_stop_position_btc` | 0.007 | 硬停倉位 |
| `resume_position_btc` | 0.0045 | 恢復倉位 |
| `hard_stop_cooldown_sec` | 30 | 硬停冷卻時間 |
| `inventory_skew_enabled` | True | 啟用庫存偏斜 |
| `inventory_skew_max_bps` | 6 | 最大偏斜距離 |
| `breakeven_reversion_enabled` | True | 啟用保本回補 |
| `maker_fee_bps` | -1 | Maker 費率（負=返佣） |
| `taker_fee_bps` | 3 | Taker 費率 |

---

## 7. 日誌與監控

### 7.1 Trade Log 格式

**位置**：`logs/mm_trades_YYYYMMDD_HHMMSS.log`

每次啟動創建新文件，記錄所有交易操作。

#### 7.1.1 事件類型

| 事件 | 格式 | 說明 |
|------|------|------|
| `PLACE_BID` | `price=... qty=... order_id=...` | 下買單 |
| `PLACE_ASK` | `price=... qty=... order_id=...` | 下賣單 |
| `CANCEL` | `side=... reason=...` | 撤單 |
| `FILL` | `side=... qty=... price=... pos=...` | 成交 |
| `REST_GATE_CANCEL` | `order_id=... reason=orphan` | 清理孤兒訂單 |
| `REST_GATE_SAFE_MODE` | `failures=3` | 進入安全模式 |
| `HARD_STOP` | `position=...` | 觸發硬停 |
| `RESUME` | `position=...` | 恢復交易 |

#### 7.1.2 日誌示例

```
2026-01-18 10:30:15 | PLACE_BID | exchange=standx | price=94950.00 | qty=0.02 | best_bid=94955 | best_ask=94960 | pos=0.01 | order_id=abc123
2026-01-18 10:30:16 | PLACE_ASK | exchange=standx | price=94970.00 | qty=0.02 | best_bid=94955 | best_ask=94960 | pos=0.01 | order_id=def456
2026-01-18 10:30:45 | FILL | exchange=standx | side=buy | qty=0.02 | price=94950.00 | pos=0.03
2026-01-18 10:30:46 | CANCEL | exchange=standx | side=sell | reason=fill_triggered
```

### 7.2 監控指標

透過 `state.get_stats()` 獲取：

```python
{
    "total_fills": 42,
    "maker_volume_usdt": 50000.0,
    "rebates_received_usdt": 5.0,
    "fees_paid_usdt": 1.5,
    "net_profit_usdt": 3.5,
    "maker_ratio_pct": 95.0,
    "uptime_effective_pct": 87.5,
}
```

---

## 8. 故障排查

### 8.1 常見問題

#### 問題 1：重複下單

**症狀**：同方向出現多筆訂單

**排查步驟**：
1. 檢查 `[Throttle]` 日誌是否出現
2. 確認 `record_order()` 在 `await` 前調用
3. 檢查 REST Gate 是否正常查詢

**解決方案**：
- 增加 `OrderThrottle` cooldown 時間
- 確認 REST API 連接穩定

#### 問題 2：訂單不見但未成交

**症狀**：本地有訂單記錄，但交易所查不到

**排查步驟**：
1. 檢查 `REST_GATE_CANCEL` 日誌
2. 確認 WebSocket 連接狀態
3. 檢查訂單 `disappeared_since_ts`

**解決方案**：
- 等待 `disappear_time_sec`（2秒）後系統自動處理
- 檢查網絡連接

#### 問題 3：倉位不同步

**症狀**：本地倉位與交易所不一致

**排查步驟**：
1. 檢查 `_sync_primary_position()` 是否成功
2. 確認 WebSocket fill 事件是否被處理
3. 檢查 `EventDeduplicator` 是否誤過濾

**解決方案**：
- 重啟系統重新同步
- 檢查 API 權限

#### 問題 4：REST Gate 進入安全模式

**症狀**：日誌出現 `REST_GATE_SAFE_MODE`

**排查步驟**：
1. 檢查 API 連接
2. 確認 API Key 有效
3. 檢查 rate limit

**解決方案**：
- 等待 API 恢復
- 減少請求頻率
- 檢查 API 配額

### 8.2 診斷命令

```bash
# 查看最新交易日誌
tail -f logs/mm_trades_*.log | grep -E "FILL|PLACE|CANCEL"

# 統計成交次數
grep "FILL" logs/mm_trades_*.log | wc -l

# 檢查錯誤
grep -E "ERROR|FAIL|SAFE_MODE" logs/mm_trades_*.log
```

---

## 附錄：關鍵代碼位置索引

| 功能 | 文件 | 行號 |
|------|------|------|
| 主執行器類定義 | `market_maker_executor.py` | 250-340 |
| 主循環 | `market_maker_executor.py` | 809-821 |
| 單次 tick | `market_maker_executor.py` | 823-1038 |
| REST Gate | `market_maker_executor.py` | 1041-1171 |
| 價格計算 | `market_maker_executor.py` | 1255-1491 |
| 下買單 | `market_maker_executor.py` | 1510-1576 |
| 下賣單 | `market_maker_executor.py` | 1578-1644 |
| WebSocket fill 處理 | `market_maker_executor.py` | 639-723 |
| MMState 類定義 | `mm_state.py` | 203-983 |
| EventDeduplicator | `mm_state.py` | 22-68 |
| OrderThrottle | `mm_state.py` | 72-127 |
| OrderInfo | `mm_state.py` | 130-158 |
| StandX REST API | `standx_adapter.py` | 306-700 |
| WebSocket 客戶端 | `standx_ws_client.py` | 138-450 |
