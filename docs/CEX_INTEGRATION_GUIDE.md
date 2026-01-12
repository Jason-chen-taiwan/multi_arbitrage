# 中心化交易所（CEX）集成指南
# Centralized Exchange Integration Guide

本指南說明如何使用 CCXT 庫集成主流中心化交易所（Binance、OKX、Bitget 等）的永續合約交易。

## 目錄

1. [為什麼選擇 CCXT](#為什麼選擇-ccxt)
2. [支持的交易所](#支持的交易所)
3. [架構設計](#架構設計)
4. [實現步驟](#實現步驟)
5. [配置示例](#配置示例)
6. [測試指南](#測試指南)

---

## 為什麼選擇 CCXT

[CCXT](https://github.com/ccxt/ccxt) 是一個開源的加密貨幣交易庫，提供統一的 API 接口來訪問 100+ 個交易所。

### 主要優勢

✅ **統一接口**：一套代碼支持多個交易所
✅ **完整支持**：現貨、期貨、永續合約、期權
✅ **活躍維護**：超過 3000+ 貢獻者，持續更新
✅ **豐富文檔**：完整的 API 文檔和示例
✅ **生產就緒**：被數千個項目使用

### CEX vs DEX 對比

| 特性 | CEX (Binance/OKX/Bitget) | DEX (StandX/GRVT) |
|------|--------------------------|-------------------|
| 認證方式 | API Key + Secret | 錢包私鑰簽名 |
| 流動性 | 極高 | 中等 |
| 手續費 | 較低 (0.02-0.1%) | 中等 (0.05-0.3%) |
| KYC 要求 | 是 | 否 |
| API 限制 | 嚴格 (1200 req/min) | 較寬鬆 |
| 集成難度 | 簡單 (CCXT) | 中等 (自定義) |

---

## 支持的交易所

### 主流 CEX 永續合約支持

使用 CCXT，我們可以輕鬆支持：

- ✅ **Binance** - 全球最大交易量
  - USDT 永續合約
  - Coin 永續合約
  - 最高 125x 槓桿

- ✅ **OKX** - 綜合衍生品平台
  - USDT 永續合約
  - Coin 永續合約
  - 最高 125x 槓桿

- ✅ **Bitget** - 跟單交易領先
  - USDT 永續合約
  - Coin 永續合約
  - 最高 125x 槓桿

- ✅ **Bybit** - 專業衍生品交易所
  - USDT 永續合約
  - Inverse 永續合約
  - 最高 100x 槓桿

- ✅ **Gate.io** - 多樣化產品
  - USDT 永續合約
  - 最高 100x 槓桿

---

## 架構設計

### 兩層適配器模式

```
┌─────────────────────────────────────┐
│       Trading Strategy              │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│    BasePerpAdapter (Interface)      │
│  - 統一的交易所接口                  │
└──────────────┬──────────────────────┘
               │
       ┌───────┴───────┬──────────────┐
       ▼               ▼              ▼
┌──────────┐   ┌──────────┐   ┌──────────┐
│  DEX     │   │  CEX     │   │  其他     │
│ Adapter  │   │ Adapter  │   │ Adapter  │
│ (直接API)│   │ (CCXT)   │   │          │
└──────────┘   └────┬─────┘   └──────────┘
                    │
            ┌───────┴────────┬─────────┐
            ▼                ▼         ▼
     ┌──────────┐     ┌──────────┐ ┌──────┐
     │ Binance  │     │   OKX    │ │Bitget│
     │  (CCXT)  │     │  (CCXT)  │ │(CCXT)│
     └──────────┘     └──────────┘ └──────┘
```

### 設計原則

1. **統一接口**：所有適配器實現相同的 `BasePerpAdapter` 接口
2. **CCXT 封裝**：CEX 適配器內部使用 CCXT，對外提供統一接口
3. **配置驅動**：通過配置文件選擇交易所
4. **錯誤處理**：統一的錯誤處理和重試機制

---

## 實現步驟

### 步驟 1: 安裝 CCXT

```bash
pip install ccxt
```

或添加到 `requirements.txt`：

```text
ccxt>=4.0.0
```

### 步驟 2: 創建 CEX 適配器基類

創建 `src/adapters/ccxt_adapter.py`：

```python
"""
CCXT Exchange Adapter Base Class
使用 CCXT 庫封裝中心化交易所的統一適配器
"""
import ccxt
from typing import Dict, Any, Optional, List
from decimal import Decimal
from datetime import datetime

from .base_adapter import (
    BasePerpAdapter,
    Balance,
    Position,
    Order,
    OrderSide,
    OrderType,
    OrderStatus,
    TimeInForce,
    Orderbook
)


class CCXTAdapter(BasePerpAdapter):
    """
    CCXT 適配器基類

    支持的交易所：
    - Binance
    - OKX
    - Bitget
    - Bybit
    - Gate.io
    """

    def __init__(self, config: Dict[str, Any]):
        """
        初始化 CCXT 適配器

        Args:
            config: 配置字典，必須包含：
                - exchange_name: 交易所名稱（如 "binance", "okx"）
                - api_key: API 密鑰
                - api_secret: API 密鑰
                - testnet: 是否使用測試網（可選）
                - options: CCXT 額外選項（可選）
        """
        super().__init__(config)

        self.exchange_name = config.get("exchange_name", "").lower()
        self.api_key = config.get("api_key")
        self.api_secret = config.get("api_secret")
        self.testnet = config.get("testnet", False)

        # 驗證必需配置
        if not self.api_key or not self.api_secret:
            raise ValueError("配置中必須包含 api_key 和 api_secret")

        # 創建 CCXT 交易所實例
        exchange_class = getattr(ccxt, self.exchange_name, None)
        if not exchange_class:
            raise ValueError(f"CCXT 不支持的交易所: {self.exchange_name}")

        # CCXT 配置
        ccxt_config = {
            'apiKey': self.api_key,
            'secret': self.api_secret,
            'enableRateLimit': True,  # 自動限速
            'options': config.get('options', {})
        }

        # 測試網配置
        if self.testnet:
            ccxt_config['options']['defaultType'] = 'future'
            if self.exchange_name == 'binance':
                ccxt_config['options']['sandboxMode'] = True
            elif self.exchange_name == 'okx':
                ccxt_config['hostname'] = 'aws.testnet.okx.com'

        self.exchange = exchange_class(ccxt_config)
        self._connected = False

    async def connect(self) -> bool:
        """連接到交易所"""
        try:
            # 加載市場數據
            await self.exchange.load_markets()

            # 驗證 API 憑證
            balance = await self.exchange.fetch_balance()

            self._connected = True
            print(f"✅ Connected to {self.exchange_name.upper()}")
            return True

        except Exception as e:
            print(f"❌ Failed to connect to {self.exchange_name}: {e}")
            return False

    async def disconnect(self) -> bool:
        """斷開連接"""
        try:
            await self.exchange.close()
            self._connected = False
            return True
        except Exception as e:
            print(f"❌ Failed to disconnect from {self.exchange_name}: {e}")
            return False

    async def get_balance(self) -> Balance:
        """查詢賬戶餘額"""
        try:
            balance = await self.exchange.fetch_balance()

            # CCXT 統一格式
            return Balance(
                total_balance=Decimal(str(balance.get('USDT', {}).get('total', 0))),
                available_balance=Decimal(str(balance.get('USDT', {}).get('free', 0))),
                used_margin=Decimal(str(balance.get('USDT', {}).get('used', 0))),
                unrealized_pnl=Decimal(str(balance.get('info', {}).get('totalUnrealizedProfit', 0))),
                total_equity=Decimal(str(balance.get('USDT', {}).get('total', 0)))
            )

        except Exception as e:
            print(f"❌ Failed to get balance: {e}")
            raise

    async def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """查詢持倉"""
        try:
            positions = await self.exchange.fetch_positions(symbols=[symbol] if symbol else None)

            result = []
            for pos in positions:
                if pos.get('contracts', 0) > 0:  # 過濾空倉位
                    result.append(Position(
                        symbol=pos['symbol'],
                        side=pos['side'].upper(),
                        size=Decimal(str(pos.get('contracts', 0))),
                        entry_price=Decimal(str(pos.get('entryPrice', 0))),
                        mark_price=Decimal(str(pos.get('markPrice', 0))),
                        liquidation_price=Decimal(str(pos.get('liquidationPrice', 0))),
                        unrealized_pnl=Decimal(str(pos.get('unrealizedPnl', 0))),
                        leverage=int(pos.get('leverage', 1)),
                        margin=Decimal(str(pos.get('initialMargin', 0)))
                    ))

            return result

        except Exception as e:
            print(f"❌ Failed to get positions: {e}")
            raise

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
        try:
            # 轉換為 CCXT 格式
            ccxt_side = side.value.lower()
            ccxt_type = order_type.value.lower()

            params = {}
            if reduce_only:
                params['reduceOnly'] = True
            if post_only:
                params['postOnly'] = True

            # 下單
            order = await self.exchange.create_order(
                symbol=symbol,
                type=ccxt_type,
                side=ccxt_side,
                amount=float(quantity),
                price=float(price) if price else None,
                params=params
            )

            return self._parse_order(order)

        except Exception as e:
            print(f"❌ Failed to place order: {e}")
            raise

    async def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> bool:
        """取消訂單"""
        try:
            await self.exchange.cancel_order(order_id, symbol)
            return True
        except Exception as e:
            print(f"❌ Failed to cancel order: {e}")
            return False

    async def get_order(self, order_id: str, symbol: Optional[str] = None) -> Optional[Order]:
        """查詢訂單"""
        try:
            order = await self.exchange.fetch_order(order_id, symbol)
            return self._parse_order(order)
        except Exception as e:
            print(f"❌ Failed to get order: {e}")
            return None

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """查詢未成交訂單"""
        try:
            orders = await self.exchange.fetch_open_orders(symbol)
            return [self._parse_order(o) for o in orders]
        except Exception as e:
            print(f"❌ Failed to get open orders: {e}")
            return []

    async def get_orderbook(self, symbol: str, limit: int = 20) -> Orderbook:
        """獲取訂單簿"""
        try:
            ob = await self.exchange.fetch_order_book(symbol, limit)

            return Orderbook(
                symbol=symbol,
                bids=[[Decimal(str(b[0])), Decimal(str(b[1]))] for b in ob['bids']],
                asks=[[Decimal(str(a[0])), Decimal(str(a[1]))] for a in ob['asks']],
                timestamp=datetime.fromtimestamp(ob['timestamp'] / 1000) if ob.get('timestamp') else datetime.now()
            )

        except Exception as e:
            print(f"❌ Failed to get orderbook: {e}")
            raise

    def _parse_order(self, order: Dict) -> Order:
        """解析 CCXT 訂單格式"""
        return Order(
            order_id=order['id'],
            symbol=order['symbol'],
            side=order['side'].upper(),
            order_type=order['type'].upper(),
            price=Decimal(str(order.get('price', 0))),
            quantity=Decimal(str(order['amount'])),
            filled_quantity=Decimal(str(order.get('filled', 0))),
            remaining_quantity=Decimal(str(order.get('remaining', 0))),
            status=order['status'].upper(),
            timestamp=datetime.fromtimestamp(order['timestamp'] / 1000) if order.get('timestamp') else datetime.now(),
            time_in_force=TimeInForce.GTC.value,
            reduce_only=order.get('reduceOnly', False),
            post_only=order.get('postOnly', False)
        )
```

### 步驟 3: 在 Factory 中註冊

更新 `src/adapters/factory.py`：

```python
from .ccxt_adapter import CCXTAdapter

# CEX 交易所列表（使用 CCXT）
CEX_EXCHANGES = ['binance', 'okx', 'bitget', 'bybit', 'gateio']

def create_adapter(config: Dict[str, Any]) -> BasePerpAdapter:
    exchange_name = config.get("exchange_name", "").lower()

    # DEX 適配器
    if exchange_name == "standx":
        from .standx_adapter import StandXAdapter
        return StandXAdapter(config)

    elif exchange_name == "grvt":
        from .grvt_adapter import GRVTAdapter
        return GRVTAdapter(config)

    # CEX 適配器（使用 CCXT）
    elif exchange_name in CEX_EXCHANGES:
        return CCXTAdapter(config)

    else:
        raise ValueError(f"不支持的交易所: {exchange_name}")
```

---

## 配置示例

### 環境變量配置

更新 `.env`：

```bash
# 選擇交易所
EXCHANGE_NAME=binance  # 選項: binance, okx, bitget, bybit, gateio

# Binance 配置
BINANCE_API_KEY=your_binance_api_key
BINANCE_API_SECRET=your_binance_api_secret
BINANCE_TESTNET=false

# OKX 配置
OKX_API_KEY=your_okx_api_key
OKX_API_SECRET=your_okx_api_secret
OKX_PASSPHRASE=your_okx_passphrase
OKX_TESTNET=false

# Bitget 配置
BITGET_API_KEY=your_bitget_api_key
BITGET_API_SECRET=your_bitget_api_secret
BITGET_PASSPHRASE=your_bitget_passphrase
BITGET_TESTNET=false
```

### 代碼配置

```python
import os
from dotenv import load_dotenv
from src.adapters.factory import create_adapter

load_dotenv()

# Binance 配置
binance_config = {
    "exchange_name": "binance",
    "api_key": os.getenv("BINANCE_API_KEY"),
    "api_secret": os.getenv("BINANCE_API_SECRET"),
    "testnet": os.getenv("BINANCE_TESTNET", "false") == "true"
}

# OKX 配置
okx_config = {
    "exchange_name": "okx",
    "api_key": os.getenv("OKX_API_KEY"),
    "api_secret": os.getenv("OKX_API_SECRET"),
    "password": os.getenv("OKX_PASSPHRASE"),  # OKX 需要 passphrase
    "testnet": os.getenv("OKX_TESTNET", "false") == "true"
}

# 創建適配器
adapter = create_adapter(binance_config)
```

---

## 測試指南

### 單元測試

創建 `tests/test_cex_adapter.py`：

```python
import pytest
import asyncio
from decimal import Decimal
from src.adapters.factory import create_adapter


@pytest.mark.asyncio
async def test_binance_connection():
    """測試 Binance 連接"""
    config = {
        "exchange_name": "binance",
        "api_key": "test_key",
        "api_secret": "test_secret",
        "testnet": True
    }

    adapter = create_adapter(config)
    connected = await adapter.connect()

    assert connected is True
    await adapter.disconnect()
```

### 集成測試

運行多交易所測試：

```bash
# 測試所有 CEX
python scripts/test_multi_exchange.py
```

輸出示例：

```
📊 MULTI-EXCHANGE PRICE COMPARISON
================================================================================
✅ Found 3 configured exchange(s):
  - BINANCE
  - OKX
  - BITGET

🧪 Testing BINANCE Exchange
============================================================
✅ Connected to BINANCE
💰 Balance: $10,523.45
📊 Positions: 2 open

📊 PRICE COMPARISON SUMMARY
Symbol: BTC/USDT:USDT
--------------------------------------------------------------------------------
Exchange        Best Bid        Best Ask          Spread     Spread %
--------------------------------------------------------------------------------
BINANCE         $95,234.50      $95,236.80         $2.30       0.0024%
OKX             $95,233.90      $95,237.10         $3.20       0.0034%
BITGET          $95,234.20      $95,236.50         $2.30       0.0024%

💰 ARBITRAGE OPPORTUNITIES
BINANCE ↔ OKX:
  ✅ Buy on OKX @ $95,237.10
     Sell on BINANCE @ $95,234.50
     Profit: $-2.60 (-0.0027%)
```

---

## 永續合約符號格式

不同交易所的符號格式：

| 交易所 | CCXT 格式 | 原生格式 |
|--------|----------|---------|
| Binance | `BTC/USDT:USDT` | `BTCUSDT` |
| OKX | `BTC/USDT:USDT` | `BTC-USDT-SWAP` |
| Bitget | `BTC/USDT:USDT` | `BTCUSDT_UMCBL` |
| Bybit | `BTC/USDT:USDT` | `BTCUSDT` |

CCXT 自動處理符號轉換，使用統一格式即可。

---

## 進階功能

### 1. 設置槓桿

```python
async def set_leverage(self, symbol: str, leverage: int):
    """設置槓桿倍數"""
    await self.exchange.set_leverage(leverage, symbol)
```

### 2. 設置保證金模式

```python
async def set_margin_mode(self, symbol: str, mode: str):
    """設置保證金模式 (cross/isolated)"""
    await self.exchange.set_margin_mode(mode, symbol)
```

### 3. 查詢資金費率

```python
async def get_funding_rate(self, symbol: str):
    """查詢資金費率"""
    return await self.exchange.fetch_funding_rate(symbol)
```

---

## 注意事項

### API 限制

不同交易所有不同的 API 限制：

- **Binance**: 1200 請求/分鐘
- **OKX**: 20 請求/2秒
- **Bitget**: 20 請求/2秒

CCXT 的 `enableRateLimit=True` 會自動處理限速。

### 測試網

測試網配置：

- **Binance Testnet**: `testnet.binancefuture.com`
- **OKX Demo**: `aws.testnet.okx.com`
- **Bybit Testnet**: `api-testnet.bybit.com`

### 安全建議

1. ✅ 使用 API Key 限制（僅交易權限，不要提現權限）
2. ✅ 使用 IP 白名單
3. ✅ 在測試網先測試
4. ✅ 小資金開始
5. ✅ 定期輪換 API Key

---

## 相關資源

- [CCXT 官方文檔](https://docs.ccxt.com/) - CCXT 完整文檔
- [CCXT GitHub](https://github.com/ccxt/ccxt) - CCXT 源代碼
- [Binance Futures API](https://developers.binance.com/docs/derivatives) - Binance 期貨 API 文檔
- [OKX API](https://www.okx.com/docs-v5/en/) - OKX API 文檔
- [Bitget API](https://bitgetlimited.github.io/apidoc/en/mix/) - Bitget API 文檔

---

## 總結

使用 CCXT 集成 CEX 的優勢：

✅ **快速集成** - 一次開發，支持多個交易所
✅ **維護簡單** - CCXT 團隊維護交易所 API 變更
✅ **統一接口** - 所有交易所使用相同代碼
✅ **生產就緒** - 被數千個項目驗證
✅ **功能完整** - 支持所有主要功能

現在您可以輕鬆地在 Binance、OKX、Bitget 等交易所之間進行套利交易！
