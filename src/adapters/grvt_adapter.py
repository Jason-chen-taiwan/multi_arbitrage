"""
GRVT Exchange Adapter Implementation

使用官方 GRVT Python SDK (grvt-pysdk) 實現
API Documentation: https://api-docs.grvt.io/
"""
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

# GRVT SDK imports
from pysdk.grvt_raw_env import GrvtEnv
from pysdk.grvt_raw_base import GrvtApiConfig, GrvtError
from pysdk.grvt_raw_sync import GrvtRawSync
from pysdk.grvt_raw_types import (
    EmptyRequest,
    ApiSubAccountSummaryRequest,
    ApiOpenOrdersRequest,
    ApiCreateOrderRequest,
    ApiCancelOrderRequest,
    ApiCancelAllOrdersRequest,
    ApiOrderbookLevelsRequest,
    ApiPositionsRequest,
    OrderLeg,
    OrderMetadata,
)


class GRVTAdapter(BasePerpAdapter):
    """GRVT 交易所適配器實現 - 使用官方 SDK"""

    def __init__(self, config: Dict[str, Any]):
        """
        初始化 GRVT 適配器

        Args:
            config: 配置字典，必須包含：
                - exchange_name: "grvt"
                - api_key: API 密鑰
                - api_secret: API Secret (私鑰)
                - testnet: 是否使用測試網（可選，默認 False）
                - trading_account_id: 交易帳戶 ID（可選）
        """
        super().__init__(config)

        self.api_key = config.get("api_key")
        self.api_secret = config.get("api_secret")
        self.testnet = config.get("testnet", False)
        self.trading_account_id = config.get("trading_account_id")

        # 驗證必需配置
        if not self.api_key or not self.api_secret:
            raise ValueError("配置中必須包含 api_key 和 api_secret")

        # 設置環境
        self.env = GrvtEnv.TESTNET if self.testnet else GrvtEnv.PROD

        # SDK 客戶端
        self._client: Optional[GrvtRawSync] = None
        self._connected = False
        self._main_account_id: Optional[str] = None

    async def connect(self) -> bool:
        """連接到 GRVT"""
        try:
            # 創建 SDK 配置
            sdk_config = GrvtApiConfig(
                env=self.env,
                trading_account_id=self.trading_account_id,
                private_key=self.api_secret,
                api_key=self.api_key,
                logger=None
            )

            # 初始化客戶端
            self._client = GrvtRawSync(sdk_config)

            # 測試連接 - 獲取帳戶摘要
            result = self._client.aggregated_account_summary_v1(EmptyRequest())

            if isinstance(result, GrvtError):
                raise Exception(f"API Error: {result}")

            self._main_account_id = result.result.main_account_id
            self._connected = True

            print(f"✅ Connected to GRVT ({'Testnet' if self.testnet else 'Mainnet'})")
            print(f"   Main Account: {self._main_account_id}")
            return True

        except Exception as e:
            print(f"❌ Failed to connect to GRVT: {e}")
            self._client = None
            return False

    async def disconnect(self) -> bool:
        """斷開連接"""
        try:
            self._client = None
            self._connected = False
            return True
        except Exception as e:
            print(f"❌ Failed to disconnect from GRVT: {e}")
            return False

    async def get_balance(self) -> Balance:
        """查詢賬戶餘額"""
        if not self._client:
            raise Exception("Not connected. Call connect() first.")

        try:
            result = self._client.aggregated_account_summary_v1(EmptyRequest())

            if isinstance(result, GrvtError):
                raise Exception(f"API Error: {result}")

            summary = result.result

            # 計算總餘額
            total = Decimal(str(summary.total_equity or "0"))
            available = total  # GRVT 可能需要額外計算可用餘額

            return Balance(
                total_balance=total,
                available_balance=available,
                used_margin=Decimal("0"),
                unrealized_pnl=Decimal("0"),
                equity=total
            )

        except Exception as e:
            print(f"❌ Failed to get balance from GRVT: {e}")
            raise

    async def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """查詢持倉"""
        if not self._client:
            raise Exception("Not connected. Call connect() first.")

        try:
            req = ApiPositionsRequest(
                sub_account_id=self.trading_account_id or self._main_account_id,
                kind=["PERPETUAL"],
                base=[],
                quote=[]
            )

            result = self._client.positions_v1(req)

            if isinstance(result, GrvtError):
                raise Exception(f"API Error: {result}")

            positions = []
            for pos_data in result.result or []:
                # 過濾 symbol
                if symbol and pos_data.instrument != symbol:
                    continue

                position = Position(
                    symbol=pos_data.instrument,
                    side="long" if Decimal(str(pos_data.balance)) > 0 else "short",
                    size=abs(Decimal(str(pos_data.balance))),
                    entry_price=Decimal(str(pos_data.entry_price or "0")),
                    mark_price=Decimal(str(pos_data.mark_price or "0")),
                    liquidation_price=Decimal(str(pos_data.liquidation_price or "0")),
                    unrealized_pnl=Decimal(str(pos_data.unrealized_pnl or "0")),
                    leverage=1,  # GRVT 可能需要另外查詢
                    margin=Decimal(str(pos_data.notional or "0"))
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
        post_only: bool = False,
        client_order_id: Optional[str] = None,
        **kwargs
    ) -> Order:
        """下單"""
        if not self._client:
            raise Exception("Not connected. Call connect() first.")

        try:
            # 轉換參數
            is_bid = side in [OrderSide.BUY, "buy", "long"]

            # 構建訂單腿
            legs = [OrderLeg(
                instrument=symbol,
                is_buying_asset=is_bid,
                size=str(quantity),
                limit_price=str(price) if price else "0"
            )]

            # 時間有效性映射
            tif_map = {
                TimeInForce.GTC: "GOOD_TILL_TIME",
                TimeInForce.IOC: "IMMEDIATE_OR_CANCEL",
                TimeInForce.FOK: "FILL_OR_KILL",
            }

            req = ApiCreateOrderRequest(
                sub_account_id=self.trading_account_id or self._main_account_id,
                is_market=order_type == OrderType.MARKET,
                time_in_force=tif_map.get(time_in_force, "GOOD_TILL_TIME"),
                post_only=post_only,
                reduce_only=reduce_only,
                legs=legs,
                metadata=OrderMetadata(
                    client_order_id=client_order_id or ""
                ) if client_order_id else None
            )

            result = self._client.create_order_v1(req)

            if isinstance(result, GrvtError):
                raise Exception(f"API Error: {result}")

            order_data = result.result

            return Order(
                order_id=order_data.order_id,
                symbol=symbol,
                side=side.value if hasattr(side, 'value') else str(side),
                order_type=order_type.value if hasattr(order_type, 'value') else str(order_type),
                price=price,
                quantity=quantity,
                filled_quantity=Decimal("0"),
                remaining_quantity=quantity,
                status="NEW",
                timestamp=datetime.now(),
                time_in_force=time_in_force.value if hasattr(time_in_force, 'value') else str(time_in_force),
                reduce_only=reduce_only,
                post_only=post_only
            )

        except Exception as e:
            print(f"❌ Failed to place order on GRVT: {e}")
            raise

    async def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> bool:
        """取消訂單"""
        if not self._client:
            raise Exception("Not connected. Call connect() first.")

        try:
            req = ApiCancelOrderRequest(
                sub_account_id=self.trading_account_id or self._main_account_id,
                order_id=order_id
            )

            result = self._client.cancel_order_v1(req)

            if isinstance(result, GrvtError):
                print(f"❌ Cancel order error: {result}")
                return False

            return True

        except Exception as e:
            print(f"❌ Failed to cancel order on GRVT: {e}")
            return False

    async def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """取消所有訂單"""
        if not self._client:
            raise Exception("Not connected. Call connect() first.")

        try:
            req = ApiCancelAllOrdersRequest(
                sub_account_id=self.trading_account_id or self._main_account_id,
                kind=["PERPETUAL"],
                base=[],
                quote=[]
            )

            result = self._client.cancel_all_orders_v1(req)

            if isinstance(result, GrvtError):
                print(f"❌ Cancel all orders error: {result}")
                return 0

            return result.result.num_cancelled if hasattr(result.result, 'num_cancelled') else 0

        except Exception as e:
            print(f"❌ Failed to cancel all orders on GRVT: {e}")
            return 0

    async def get_order(self, order_id: str, symbol: Optional[str] = None) -> Optional[Order]:
        """查詢訂單"""
        if not self._client:
            raise Exception("Not connected. Call connect() first.")

        try:
            from pysdk.grvt_raw_types import ApiGetOrderRequest

            req = ApiGetOrderRequest(
                sub_account_id=self.trading_account_id or self._main_account_id,
                order_id=order_id
            )

            result = self._client.get_order_v1(req)

            if isinstance(result, GrvtError):
                return None

            return self._parse_order(result.result)

        except Exception as e:
            print(f"❌ Failed to get order from GRVT: {e}")
            return None

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """查詢未成交訂單"""
        if not self._client:
            raise Exception("Not connected. Call connect() first.")

        try:
            req = ApiOpenOrdersRequest(
                sub_account_id=self.trading_account_id or self._main_account_id,
                kind=["PERPETUAL"],
                base=[],
                quote=[]
            )

            result = self._client.open_orders_v1(req)

            if isinstance(result, GrvtError):
                raise Exception(f"API Error: {result}")

            orders = []
            for order_data in result.result or []:
                # 過濾 symbol
                if symbol and order_data.legs[0].instrument != symbol:
                    continue
                orders.append(self._parse_order(order_data))

            return orders

        except Exception as e:
            print(f"❌ Failed to get open orders from GRVT: {e}")
            return []

    def _normalize_symbol(self, symbol: str) -> str:
        """將通用 symbol 轉換為 GRVT 格式"""
        # GRVT 格式: BTC_USDT_Perp (注意大小寫)
        # 常見輸入: BTC-USD, BTCUSDT, BTC/USDT

        # 如果已經是正確格式 (包含 _Perp)
        if '_Perp' in symbol:
            return symbol

        # 標準化分隔符
        normalized = symbol.upper().replace('-', '_').replace('/', '_')

        # 轉換常見格式
        if normalized in ['BTC_USD', 'BTCUSD', 'BTC_USDT', 'BTCUSDT']:
            return 'BTC_USDT_Perp'
        elif normalized in ['ETH_USD', 'ETHUSD', 'ETH_USDT', 'ETHUSDT']:
            return 'ETH_USDT_Perp'
        elif normalized in ['SOL_USD', 'SOLUSD', 'SOL_USDT', 'SOLUSDT']:
            return 'SOL_USDT_Perp'

        # 嘗試構建格式: XXX_USDT_Perp
        if normalized.endswith('USDT'):
            base = normalized[:-4]
            return f'{base}_USDT_Perp'
        elif normalized.endswith('_USDT'):
            return normalized + '_Perp'

        # 默認添加 _USDT_Perp
        return f'{normalized}_USDT_Perp'

    async def get_orderbook(self, symbol: str, limit: int = 20) -> Orderbook:
        """獲取訂單簿"""
        if not self._client:
            raise Exception("Not connected. Call connect() first.")

        try:
            # 標準化 symbol
            grvt_symbol = self._normalize_symbol(symbol)

            # GRVT 只支持特定的 depth 值: 10, 50, 100
            valid_depths = [10, 50, 100]
            depth = min(valid_depths, key=lambda x: abs(x - limit))

            req = ApiOrderbookLevelsRequest(
                instrument=grvt_symbol,
                depth=depth
            )

            result = self._client.orderbook_levels_v1(req)

            if isinstance(result, GrvtError):
                raise Exception(f"API Error: {result}")

            ob = result.result

            return Orderbook(
                symbol=symbol,
                bids=[[Decimal(str(b.price)), Decimal(str(b.size))] for b in ob.bids or []],
                asks=[[Decimal(str(a.price)), Decimal(str(a.size))] for a in ob.asks or []],
                timestamp=datetime.now()
            )

        except Exception as e:
            print(f"❌ Failed to get orderbook from GRVT: {e}")
            raise

    def _parse_order(self, order_data) -> Order:
        """解析訂單數據"""
        leg = order_data.legs[0] if order_data.legs else None

        return Order(
            order_id=order_data.order_id,
            symbol=leg.instrument if leg else "",
            side="buy" if leg and leg.is_buying_asset else "sell",
            order_type="market" if order_data.is_market else "limit",
            price=Decimal(str(leg.limit_price)) if leg else Decimal("0"),
            quantity=Decimal(str(leg.size)) if leg else Decimal("0"),
            filled_quantity=Decimal(str(order_data.filled_size or "0")),
            remaining_quantity=Decimal(str(order_data.remaining_size or "0")),
            status=order_data.state or "UNKNOWN",
            timestamp=datetime.now(),
            time_in_force=order_data.time_in_force or "GTC",
            reduce_only=order_data.reduce_only or False,
            post_only=order_data.post_only or False
        )
