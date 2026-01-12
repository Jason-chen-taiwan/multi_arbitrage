# 添加新交易所適配器指南
# Guide to Adding New Exchange Adapters

本文檔說明如何在現有系統中添加新的永續合約交易所支持。

## 目錄

1. [架構概述](#架構概述)
2. [實現新適配器的步驟](#實現新適配器的步驟)
3. [參考實現](#參考實現)
4. [測試新適配器](#測試新適配器)
5. [配置示例](#配置示例)

---

## 架構概述

我們的系統使用 **適配器模式（Adapter Pattern）** 來支持多個交易所。這種設計模式的優勢：

```
┌─────────────────────────────────────────┐
│         Trading Strategy                │
│    (Strategy-specific logic)            │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│      BasePerpAdapter (Interface)        │
│  - get_balance()                        │
│  - get_positions()                      │
│  - place_order()                        │
│  - cancel_order()                       │
│  - get_orderbook()                      │
└──────────────┬──────────────────────────┘
               │
       ┌───────┴──────┬──────────┬────────┐
       ▼              ▼          ▼        ▼
┌──────────┐   ┌──────────┐  ┌────┐  ┌────┐
│ StandX   │   │  GRVT    │  │VAR │  │... │
│ Adapter  │   │ Adapter  │  │... │  │    │
└──────────┘   └──────────┘  └────┘  └────┘
```

### 核心組件

1. **BasePerpAdapter** ([src/adapters/base_adapter.py](../src/adapters/base_adapter.py))
   - 定義所有適配器必須實現的接口
   - 提供標準化的數據結構（Balance, Position, Order）

2. **AdapterFactory** ([src/adapters/factory.py](../src/adapters/factory.py))
   - 負責創建適配器實例
   - 動態加載和註冊交易所適配器

3. **具體適配器** (例如 [src/adapters/standx_adapter.py](../src/adapters/standx_adapter.py))
   - 實現特定交易所的 API 調用
   - 處理認證、簽名、WebSocket 連接等

---

## 實現新適配器的步驟

### 步驟 1: 創建適配器文件

在 `src/adapters/` 目錄下創建新的適配器文件，例如 `grvt_adapter.py`：

```python
"""
GRVT Exchange Adapter Implementation
"""
from typing import Dict, Any, Optional, List
from decimal import Decimal

from .base_adapter import (
    BasePerpAdapter,
    Balance,
    Position,
    Order,
    OrderSide,
    OrderType,
    OrderStatus,
    TimeInForce
)


class GRVTAdapter(BasePerpAdapter):
    """GRVT 交易所適配器實現"""

    def __init__(self, config: Dict[str, Any]):
        """
        初始化 GRVT 適配器

        Args:
            config: 配置字典，必須包含：
                - exchange_name: "grvt"
                - api_key: API 密鑰
                - api_secret: API 密鑰
                - base_url: API 基礎 URL（可選）
        """
        super().__init__(config)

        self.api_key = config.get("api_key")
        self.api_secret = config.get("api_secret")
        self.base_url = config.get("base_url", "https://api.grvt.io")

        # 驗證必需配置
        if not self.api_key or not self.api_secret:
            raise ValueError("配置中必須包含 api_key 和 api_secret")

        # 初始化 HTTP session
        self.session = None

    async def connect(self) -> bool:
        """連接到 GRVT"""
        try:
            # TODO: 實現連接邏輯
            # - 創建 HTTP session
            # - 驗證 API 憑證
            # - 建立 WebSocket 連接（如需要）
            return True
        except Exception as e:
            print(f"❌ Failed to connect to GRVT: {e}")
            return False

    async def disconnect(self) -> bool:
        """斷開連接"""
        try:
            if self.session:
                await self.session.close()
            return True
        except Exception as e:
            print(f"❌ Failed to disconnect from GRVT: {e}")
            return False

    async def get_balance(self) -> Balance:
        """查詢賬戶餘額"""
        # TODO: 實現 API 調用
        # GET /api/v1/account/balance
        pass

    async def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """查詢持倉"""
        # TODO: 實現 API 調用
        # GET /api/v1/positions
        pass

    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Optional[Decimal] = None,
        time_in_force: TimeInForce = TimeInForce.GTC,
        reduce_only: bool = False,
        post_only: bool = False
    ) -> Order:
        """下單"""
        # TODO: 實現 API 調用
        # POST /api/v1/orders
        pass

    async def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> bool:
        """取消訂單"""
        # TODO: 實現 API 調用
        # DELETE /api/v1/orders/{order_id}
        pass

    async def get_order(self, order_id: str, symbol: Optional[str] = None) -> Optional[Order]:
        """查詢訂單"""
        # TODO: 實現 API 調用
        # GET /api/v1/orders/{order_id}
        pass

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """查詢未成交訂單"""
        # TODO: 實現 API 調用
        # GET /api/v1/orders?status=open
        pass

    async def get_orderbook(self, symbol: str, limit: int = 20) -> Dict[str, Any]:
        """獲取訂單簿"""
        # TODO: 實現 API 調用
        # GET /api/v1/orderbook/{symbol}
        pass
```

### 步驟 2: 在 Factory 中註冊

修改 `src/adapters/factory.py`，添加新的適配器：

```python
def create_adapter(config: Dict[str, Any]) -> BasePerpAdapter:
    """
    創建適配器實例

    Args:
        config: 配置字典，必須包含 exchange_name

    Returns:
        BasePerpAdapter: 適配器實例
    """
    exchange_name = config.get("exchange_name", "").lower()

    if exchange_name == "standx":
        from .standx_adapter import StandXAdapter
        return StandXAdapter(config)

    elif exchange_name == "grvt":  # 添加新的交易所
        from .grvt_adapter import GRVTAdapter
        return GRVTAdapter(config)

    # ... 其他交易所

    else:
        raise ValueError(
            f"Unknown exchange: {exchange_name}. "
            f"Supported exchanges: standx, grvt"
        )
```

### 步驟 3: 添加環境變量支持

在 `.env.example` 中添加新交易所的配置：

```bash
# GRVT API Configuration
GRVT_API_KEY=your_api_key_here
GRVT_API_SECRET=your_api_secret_here
GRVT_BASE_URL=https://api.grvt.io
```

### 步驟 4: 實現認證邏輯

如果交易所需要特殊的認證流程（如 StandX 需要錢包簽名），在 `src/auth/` 目錄下創建對應的認證模塊：

```python
# src/auth/grvt_auth.py

class GRVTAuth:
    """GRVT API 認證管理器"""

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret

    def sign_request(self, method: str, endpoint: str, params: dict) -> dict:
        """生成請求簽名"""
        # 實現 GRVT 特定的簽名邏輯
        pass

    def get_auth_headers(self) -> dict:
        """獲取認證 headers"""
        return {
            "X-API-KEY": self.api_key,
            # 其他必需的 headers
        }
```

---

## 參考實現

### 現有的 StandX 適配器

查看 [src/adapters/standx_adapter.py](../src/adapters/standx_adapter.py) 作為完整實現的參考：

- ✅ 完整的認證流程（錢包簽名）
- ✅ HTTP 請求處理
- ✅ 錯誤處理和重試邏輯
- ✅ 數據結構轉換

### 其他開源項目參考

1. **Perp DEX Toolkit**
   - GitHub: https://github.com/earthskyorg/perp-dex-toolkit
   - 支持: EdgeX, Backpack, Paradex, Aster, Lighter, GRVT
   - 特點: 使用 Factory 模式，清晰的適配器接口

2. **ccxt (Cryptocurrency Exchange Trading Library)**
   - GitHub: https://github.com/ccxt/ccxt
   - 支持: 100+ 交易所
   - 特點: 統一的 API 接口，豐富的文檔

---

## 測試新適配器

### 單元測試

創建測試文件 `tests/test_grvt_adapter.py`：

```python
import pytest
import asyncio
from decimal import Decimal
from src.adapters.factory import create_adapter
from src.adapters.base_adapter import OrderSide, OrderType


@pytest.mark.asyncio
async def test_grvt_connection():
    """測試 GRVT 連接"""
    config = {
        "exchange_name": "grvt",
        "api_key": "test_key",
        "api_secret": "test_secret"
    }

    adapter = create_adapter(config)

    # 測試連接
    connected = await adapter.connect()
    assert connected is True

    # 測試斷開
    disconnected = await adapter.disconnect()
    assert disconnected is True


@pytest.mark.asyncio
async def test_grvt_get_balance():
    """測試獲取餘額"""
    config = {
        "exchange_name": "grvt",
        "api_key": "test_key",
        "api_secret": "test_secret"
    }

    adapter = create_adapter(config)
    await adapter.connect()

    balance = await adapter.get_balance()
    assert balance.total_balance >= 0
    assert balance.available_balance >= 0

    await adapter.disconnect()
```

### 集成測試

創建測試腳本 `scripts/test_grvt.py`：

```python
"""
測試 GRVT 適配器
"""
import asyncio
import os
from dotenv import load_dotenv
from src.adapters.factory import create_adapter


async def main():
    load_dotenv()

    config = {
        "exchange_name": "grvt",
        "api_key": os.getenv("GRVT_API_KEY"),
        "api_secret": os.getenv("GRVT_API_SECRET"),
        "base_url": os.getenv("GRVT_BASE_URL", "https://api.grvt.io")
    }

    print("🧪 Testing GRVT Adapter")
    print("=" * 60)

    adapter = create_adapter(config)

    # 測試連接
    print("\n📡 Testing connection...")
    connected = await adapter.connect()
    print(f"✅ Connected: {connected}")

    # 測試獲取餘額
    print("\n💰 Testing get_balance...")
    balance = await adapter.get_balance()
    print(f"Total Balance: ${balance.total_balance}")
    print(f"Available: ${balance.available_balance}")

    # 測試獲取持倉
    print("\n📊 Testing get_positions...")
    positions = await adapter.get_positions()
    print(f"Open Positions: {len(positions)}")

    # 測試獲取訂單簿
    print("\n📖 Testing get_orderbook...")
    orderbook = await adapter.get_orderbook("BTC-USD")
    print(f"Best Bid: ${orderbook['bids'][0][0] if orderbook['bids'] else 'N/A'}")
    print(f"Best Ask: ${orderbook['asks'][0][0] if orderbook['asks'] else 'N/A'}")

    # 斷開連接
    await adapter.disconnect()
    print("\n✅ All tests completed!")


if __name__ == "__main__":
    asyncio.run(main())
```

運行測試：

```bash
source venv/bin/activate
python scripts/test_grvt.py
```

---

## 配置示例

### Dashboard 配置

修改 `src/web/adapter_dashboard.py` 支持多個交易所：

```python
async def initialize_adapter():
    """初始化適配器"""
    global adapter

    load_dotenv()

    # 從環境變量讀取交易所類型
    exchange_name = os.getenv("EXCHANGE_NAME", "standx").lower()

    if exchange_name == "standx":
        config = {
            "exchange_name": "standx",
            "private_key": os.getenv("WALLET_PRIVATE_KEY"),
            "chain": os.getenv("CHAIN", "bsc"),
            "base_url": os.getenv("STANDX_BASE_URL"),
            "perps_url": os.getenv("STANDX_PERPS_URL")
        }

    elif exchange_name == "grvt":
        config = {
            "exchange_name": "grvt",
            "api_key": os.getenv("GRVT_API_KEY"),
            "api_secret": os.getenv("GRVT_API_SECRET"),
            "base_url": os.getenv("GRVT_BASE_URL")
        }

    else:
        raise ValueError(f"Unsupported exchange: {exchange_name}")

    adapter = create_adapter(config)
    await adapter.connect()
```

### Strategy 配置

策略可以同時使用多個交易所：

```python
# 示例：跨交易所套利策略
from src.adapters.factory import create_adapter

# 創建多個適配器
standx_adapter = create_adapter({"exchange_name": "standx", ...})
grvt_adapter = create_adapter({"exchange_name": "grvt", ...})

# 連接到兩個交易所
await standx_adapter.connect()
await grvt_adapter.connect()

# 獲取兩個交易所的價格
standx_price = await standx_adapter.get_orderbook("BTC-USD")
grvt_price = await grvt_adapter.get_orderbook("BTC-USD")

# 計算價差並執行套利
price_diff = grvt_price['asks'][0][0] - standx_price['bids'][0][0]
if price_diff > threshold:
    # 在 StandX 買入，在 GRVT 賣出
    await standx_adapter.place_order(...)
    await grvt_adapter.place_order(...)
```

---

## 常見問題

### Q: 如何處理不同交易所的 API 限制？

A: 在適配器中實現速率限制：

```python
import time
from collections import deque

class RateLimiter:
    def __init__(self, max_requests: int, time_window: float):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = deque()

    async def acquire(self):
        now = time.time()
        # 移除過期的請求
        while self.requests and self.requests[0] < now - self.time_window:
            self.requests.popleft()

        # 如果達到限制，等待
        if len(self.requests) >= self.max_requests:
            sleep_time = self.requests[0] + self.time_window - now
            await asyncio.sleep(sleep_time)

        self.requests.append(now)
```

### Q: 如何處理不同的數據格式？

A: 在適配器中進行數據轉換，統一返回 BasePerpAdapter 定義的數據結構：

```python
def _convert_to_position(self, raw_data: dict) -> Position:
    """將交易所原始數據轉換為標準 Position 對象"""
    return Position(
        symbol=raw_data['symbol'],
        side=self._map_side(raw_data['side']),
        size=Decimal(str(raw_data['size'])),
        entry_price=Decimal(str(raw_data['entry_price'])),
        # ... 其他字段
    )
```

### Q: 如何處理 WebSocket 連接？

A: 在適配器的 `connect()` 方法中建立 WebSocket 連接，並設置回調處理：

```python
async def connect(self) -> bool:
    # HTTP session
    self.session = aiohttp.ClientSession()

    # WebSocket connection
    self.ws = await websockets.connect(self.ws_url)

    # 啟動 WebSocket 監聽任務
    self.ws_task = asyncio.create_task(self._listen_websocket())

    return True

async def _listen_websocket(self):
    """監聽 WebSocket 消息"""
    async for message in self.ws:
        data = json.loads(message)
        await self._handle_ws_message(data)
```

---

## 總結

通過遵循這個指南，您可以輕鬆地為系統添加新的交易所支持：

1. ✅ 創建新的適配器類，繼承 `BasePerpAdapter`
2. ✅ 實現所有必需的方法
3. ✅ 在 Factory 中註冊新適配器
4. ✅ 添加環境變量配置
5. ✅ 編寫測試驗證功能
6. ✅ 更新文檔

這種模塊化設計使得系統易於擴展和維護！

---

## 相關文檔

- [StandX Adapter 測試報告](./STANDX_ADAPTER_TEST.md)
- [Web Dashboard 使用指南](./WEB_DASHBOARD_GUIDE.md)
- [策略設計文檔](./STRATEGY_DESIGN.md)

## 參考資源

- [Perp DEX Toolkit](https://github.com/earthskyorg/perp-dex-toolkit) - 多交易所永續合約交易機器人
- [CCXT Library](https://github.com/ccxt/ccxt) - 加密貨幣交易庫
- [Adapter Pattern](https://refactoring.guru/design-patterns/adapter) - 設計模式文檔
