"""
GRVT Exchange Adapter Implementation

GRVT 是一個去中心化衍生品交易所，提供永續合約交易。
本適配器實現了與 GRVT API 的集成。

API Documentation: https://docs.grvt.io/
"""
import json
from typing import Dict, Any, Optional, List
from decimal import Decimal
from datetime import datetime
import aiohttp

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
                - base_url: API 基礎 URL（可選，默認 https://api.grvt.io）
                - testnet: 是否使用測試網（可選，默認 False）
        """
        super().__init__(config)

        self.api_key = config.get("api_key")
        self.api_secret = config.get("api_secret")
        self.testnet = config.get("testnet", False)

        # 設置 API URL
        if self.testnet:
            self.base_url = config.get("base_url", "https://testnet-api.grvt.io")
        else:
            self.base_url = config.get("base_url", "https://api.grvt.io")

        # 驗證必需配置
        if not self.api_key or not self.api_secret:
            raise ValueError("配置中必須包含 api_key 和 api_secret")

        # Session management
        self.session: Optional[aiohttp.ClientSession] = None
        self._connected = False

    async def connect(self) -> bool:
        """連接到 GRVT"""
        try:
            # Create HTTP session
            self.session = aiohttp.ClientSession()

            # Test connection by fetching account info
            await self._request('GET', '/api/v1/account')

            self._connected = True
            print(f"✅ Connected to GRVT ({'Testnet' if self.testnet else 'Mainnet'})")
            return True

        except Exception as e:
            print(f"❌ Failed to connect to GRVT: {e}")
            if self.session:
                await self.session.close()
                self.session = None
            return False

    async def disconnect(self) -> bool:
        """斷開連接"""
        try:
            if self.session:
                await self.session.close()
                self.session = None
            self._connected = False
            return True
        except Exception as e:
            print(f"❌ Failed to disconnect from GRVT: {e}")
            return False

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None
    ) -> Dict:
        """Make authenticated API request."""
        if not self.session:
            raise Exception("Not connected. Call connect() first.")

        url = f"{self.base_url}{endpoint}"

        # Prepare headers
        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": self.api_key
        }

        # TODO: 實現請求簽名邏輯
        # GRVT 可能需要特殊的簽名方法，參考其 API 文檔

        # Make request
        async with self.session.request(
            method=method,
            url=url,
            params=params,
            json=data if data else None,
            headers=headers
        ) as response:
            response.raise_for_status()
            return await response.json()

    async def get_balance(self) -> Balance:
        """查詢賬戶餘額"""
        try:
            result = await self._request('GET', '/api/v1/account/balance')

            # TODO: 根據 GRVT 實際 API 響應調整字段名
            return Balance(
                total_balance=Decimal(str(result.get('total_equity', '0'))),
                available_balance=Decimal(str(result.get('available', '0'))),
                used_margin=Decimal(str(result.get('used_margin', '0'))),
                unrealized_pnl=Decimal(str(result.get('unrealized_pnl', '0'))),
                total_equity=Decimal(str(result.get('total_equity', '0')))
            )

        except Exception as e:
            print(f"❌ Failed to get balance from GRVT: {e}")
            raise

    async def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """查詢持倉"""
        try:
            params = {}
            if symbol:
                params['symbol'] = symbol

            result = await self._request('GET', '/api/v1/positions', params=params)

            positions = []
            for pos_data in result.get('positions', []):
                position = Position(
                    symbol=pos_data['symbol'],
                    side=pos_data['side'],  # TODO: 可能需要映射
                    size=Decimal(str(pos_data['size'])),
                    entry_price=Decimal(str(pos_data['entry_price'])),
                    mark_price=Decimal(str(pos_data.get('mark_price', pos_data['entry_price']))),
                    liquidation_price=Decimal(str(pos_data.get('liquidation_price', '0'))),
                    unrealized_pnl=Decimal(str(pos_data.get('unrealized_pnl', '0'))),
                    leverage=int(pos_data.get('leverage', 1)),
                    margin=Decimal(str(pos_data.get('margin', '0')))
                )
                positions.append(position)

            return positions

        except Exception as e:
            print(f"❌ Failed to get positions from GRVT: {e}")
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
            order_data = {
                "symbol": symbol,
                "side": side.value,
                "type": order_type.value,
                "quantity": str(quantity),
                "time_in_force": time_in_force.value,
                "reduce_only": reduce_only,
                "post_only": post_only
            }

            if price is not None:
                order_data["price"] = str(price)

            result = await self._request('POST', '/api/v1/orders', data=order_data)

            return self._parse_order(result)

        except Exception as e:
            print(f"❌ Failed to place order on GRVT: {e}")
            raise

    async def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> bool:
        """取消訂單"""
        try:
            await self._request('DELETE', f'/api/v1/orders/{order_id}')
            return True

        except Exception as e:
            print(f"❌ Failed to cancel order on GRVT: {e}")
            return False

    async def get_order(self, order_id: str, symbol: Optional[str] = None) -> Optional[Order]:
        """查詢訂單"""
        try:
            result = await self._request('GET', f'/api/v1/orders/{order_id}')
            return self._parse_order(result)

        except Exception as e:
            print(f"❌ Failed to get order from GRVT: {e}")
            return None

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """查詢未成交訂單"""
        try:
            params = {"status": "open"}
            if symbol:
                params["symbol"] = symbol

            result = await self._request('GET', '/api/v1/orders', params=params)

            orders = []
            for order_data in result.get('orders', []):
                orders.append(self._parse_order(order_data))

            return orders

        except Exception as e:
            print(f"❌ Failed to get open orders from GRVT: {e}")
            return []

    async def get_orderbook(self, symbol: str, limit: int = 20) -> Orderbook:
        """獲取訂單簿"""
        try:
            params = {"symbol": symbol, "limit": limit}
            result = await self._request('GET', '/api/v1/orderbook', params=params)

            return Orderbook(
                symbol=symbol,
                bids=[[Decimal(str(bid[0])), Decimal(str(bid[1]))] for bid in result.get('bids', [])],
                asks=[[Decimal(str(ask[0])), Decimal(str(ask[1]))] for ask in result.get('asks', [])],
                timestamp=datetime.now()
            )

        except Exception as e:
            print(f"❌ Failed to get orderbook from GRVT: {e}")
            raise

    def _parse_order(self, order_data: Dict) -> Order:
        """解析訂單數據"""
        return Order(
            order_id=order_data['order_id'],
            symbol=order_data['symbol'],
            side=order_data['side'],  # TODO: 可能需要映射到 OrderSide enum
            order_type=order_data['type'],  # TODO: 可能需要映射到 OrderType enum
            price=Decimal(str(order_data.get('price', '0'))),
            quantity=Decimal(str(order_data['quantity'])),
            filled_quantity=Decimal(str(order_data.get('filled_quantity', '0'))),
            remaining_quantity=Decimal(str(order_data.get('remaining_quantity', order_data['quantity']))),
            status=order_data.get('status', 'UNKNOWN'),  # TODO: 映射到 OrderStatus enum
            timestamp=datetime.fromisoformat(order_data['created_at']) if 'created_at' in order_data else datetime.now(),
            time_in_force=order_data.get('time_in_force', TimeInForce.GTC.value),
            reduce_only=order_data.get('reduce_only', False),
            post_only=order_data.get('post_only', False)
        )
