"""
CCXT Exchange Adapter
使用 CCXT 庫封裝中心化交易所（CEX）的統一適配器

支持的交易所：
- Binance
- OKX
- Bitget
- Bybit
- Gate.io
- 以及 CCXT 支持的其他 100+ 交易所
"""
import ccxt.async_support as ccxt
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

    使用 CCXT 庫提供統一的接口訪問多個中心化交易所。
    """

    # CEX 使用 CCXT 格式的 symbol
    SYMBOL_MAP = {
        'BTC-USD': 'BTC/USDT:USDT',
        'ETH-USD': 'ETH/USDT:USDT',
        'SOL-USD': 'SOL/USDT:USDT',
    }

    def __init__(self, config: Dict[str, Any]):
        """
        初始化 CCXT 適配器

        Args:
            config: 配置字典，必須包含：
                - exchange_name: 交易所名稱（如 "binance", "okx", "bitget"）
                - api_key: API 密鑰
                - api_secret: API 密鑰
                - password: API 密碼（OKX/Bitget 需要）
                - testnet: 是否使用測試網（可選，默認 False）
                - options: CCXT 額外選項（可選）
        """
        super().__init__(config)

        self.exchange_name = config.get("exchange_name", "").lower()
        self.api_key = config.get("api_key")
        self.api_secret = config.get("api_secret")
        self.password = config.get("password")  # OKX/Bitget 需要
        self.testnet = config.get("testnet", False)

        # 驗證必需配置
        if not self.api_key or not self.api_secret:
            raise ValueError("配置中必須包含 api_key 和 api_secret")

        # 創建 CCXT 交易所實例
        exchange_class = getattr(ccxt, self.exchange_name, None)
        if not exchange_class:
            raise ValueError(
                f"CCXT 不支持的交易所: {self.exchange_name}。\n"
                f"支持的交易所列表: https://github.com/ccxt/ccxt#supported-cryptocurrency-exchange-markets"
            )

        # CCXT 配置
        ccxt_config = {
            'apiKey': self.api_key,
            'secret': self.api_secret,
            'enableRateLimit': True,  # 自動限速，防止超過 API 限制
            'options': {
                'defaultType': 'swap',  # 默認使用永續合約
                **(config.get('options', {}))
            }
        }

        # 添加 password（如果需要）
        if self.password:
            ccxt_config['password'] = self.password

        # 測試網配置
        if self.testnet:
            if self.exchange_name == 'binance':
                ccxt_config['options']['sandboxMode'] = True
            elif self.exchange_name == 'okx':
                ccxt_config['hostname'] = 'aws.testnet.okx.com'
            elif self.exchange_name == 'bybit':
                ccxt_config['urls'] = {'api': 'https://api-testnet.bybit.com'}

        self.exchange = exchange_class(ccxt_config)
        self._connected = False

    async def connect(self) -> bool:
        """連接到交易所並驗證 API 憑證"""
        try:
            # 加載市場數據
            await self.exchange.load_markets()
            print(f"📊 Loaded {len(self.exchange.markets)} markets from {self.exchange_name.upper()}")

            # 驗證 API 憑證（查詢餘額）
            balance = await self.exchange.fetch_balance()

            self._connected = True
            print(f"✅ Connected to {self.exchange_name.upper()} ({'Testnet' if self.testnet else 'Mainnet'})")
            return True

        except Exception as e:
            print(f"❌ Failed to connect to {self.exchange_name}: {e}")
            return False

    async def disconnect(self) -> bool:
        """斷開連接並關閉 HTTP 會話"""
        try:
            await self.exchange.close()
            self._connected = False
            return True
        except Exception as e:
            print(f"❌ Failed to disconnect from {self.exchange_name}: {e}")
            return False

    async def get_balance(self) -> Balance:
        """
        查詢賬戶餘額

        Returns:
            Balance: 賬戶餘額信息
        """
        try:
            balance = await self.exchange.fetch_balance({'type': 'swap'})

            # CCXT 統一格式：balance[currency] = {'free', 'used', 'total'}
            # 永續合約通常使用 USDT 作為保證金
            usdt_balance = balance.get('USDT', {})

            return Balance(
                total_balance=Decimal(str(usdt_balance.get('total', 0))),
                available_balance=Decimal(str(usdt_balance.get('free', 0))),
                used_margin=Decimal(str(usdt_balance.get('used', 0))),
                unrealized_pnl=Decimal(str(balance.get('info', {}).get('totalUnrealizedProfit', 0))),
                equity=Decimal(str(usdt_balance.get('total', 0)))
            )

        except Exception as e:
            print(f"❌ Failed to get balance from {self.exchange_name}: {e}")
            raise

    async def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """
        查詢持倉

        Args:
            symbol: 交易對符號（可選），統一格式如 "BTC-USD"

        Returns:
            List[Position]: 持倉列表
        """
        try:
            # CCXT 格式：fetch_positions([symbols])
            exchange_symbol = self.normalize_symbol(symbol) if symbol else None
            symbols = [exchange_symbol] if exchange_symbol else None
            positions = await self.exchange.fetch_positions(symbols)

            result = []
            for pos in positions:
                # 過濾空倉位
                contracts = float(pos.get('contracts', 0))
                if contracts > 0:
                    # 將交易所 symbol 轉回統一格式
                    unified_symbol = self.denormalize_symbol(pos['symbol'])
                    result.append(Position(
                        symbol=unified_symbol,
                        side=pos['side'].upper() if pos.get('side') else 'LONG',
                        size=Decimal(str(contracts)),
                        entry_price=Decimal(str(pos.get('entryPrice', 0))),
                        mark_price=Decimal(str(pos.get('markPrice', 0))),
                        liquidation_price=Decimal(str(pos.get('liquidationPrice', 0))),
                        unrealized_pnl=Decimal(str(pos.get('unrealizedPnl', 0))),
                        leverage=int(pos.get('leverage', 1)),
                        margin=Decimal(str(pos.get('initialMargin', 0)))
                    ))

            return result

        except Exception as e:
            print(f"❌ Failed to get positions from {self.exchange_name}: {e}")
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
        """
        下單

        Args:
            symbol: 交易對符號，格式如 "BTC/USDT:USDT"
            side: 訂單方向
            order_type: 訂單類型
            quantity: 數量
            price: 價格（限價單需要）
            time_in_force: 有效期類型
            reduce_only: 只減倉
            post_only: 只做 Maker

        Returns:
            Order: 訂單信息
        """
        try:
            # 轉換 symbol 為交易所格式
            exchange_symbol = self.normalize_symbol(symbol)
            # 轉換為 CCXT 格式
            ccxt_side = side.value.lower()
            ccxt_type = order_type.value.lower()

            # 構建參數
            params = {}
            if reduce_only:
                params['reduceOnly'] = True
            if post_only:
                params['postOnly'] = True

            # 下單
            order = await self.exchange.create_order(
                symbol=exchange_symbol,
                type=ccxt_type,
                side=ccxt_side,
                amount=float(quantity),
                price=float(price) if price else None,
                params=params
            )

            return self._parse_order(order, original_symbol=symbol)

        except Exception as e:
            print(f"❌ Failed to place order on {self.exchange_name}: {e}")
            raise

    async def cancel_order(
        self,
        symbol: str,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None
    ) -> bool:
        """
        取消訂單

        Args:
            symbol: 交易對符號
            order_id: 訂單 ID
            client_order_id: 客戶端訂單 ID

        Returns:
            bool: 是否成功
        """
        try:
            # 轉換 symbol 為交易所格式
            exchange_symbol = self.normalize_symbol(symbol)
            if order_id:
                await self.exchange.cancel_order(order_id, exchange_symbol)
            elif client_order_id:
                # 某些交易所支持通過 client_order_id 取消
                params = {'clientOrderId': client_order_id}
                await self.exchange.cancel_order(client_order_id, exchange_symbol, params)
            else:
                raise ValueError("必須提供 order_id 或 client_order_id")
            return True

        except Exception as e:
            print(f"❌ Failed to cancel order on {self.exchange_name}: {e}")
            return False

    async def cancel_all_orders(self, symbol: str) -> int:
        """
        取消所有訂單

        Args:
            symbol: 交易對符號（統一格式如 BTC-USD）

        Returns:
            int: 成功取消的訂單數量
        """
        try:
            # 轉換 symbol 為交易所格式
            exchange_symbol = self.normalize_symbol(symbol)
            # 獲取所有未成交訂單
            open_orders = await self.exchange.fetch_open_orders(exchange_symbol)
            cancelled = 0

            for order in open_orders:
                try:
                    await self.exchange.cancel_order(order['id'], exchange_symbol)
                    cancelled += 1
                except Exception as e:
                    print(f"❌ Failed to cancel order {order['id']}: {e}")

            return cancelled

        except Exception as e:
            print(f"❌ Failed to cancel all orders on {self.exchange_name}: {e}")
            return 0

    async def get_order(self, order_id: str, symbol: Optional[str] = None) -> Optional[Order]:
        """
        查詢訂單

        Args:
            order_id: 訂單 ID
            symbol: 交易對符號（統一格式）

        Returns:
            Optional[Order]: 訂單信息
        """
        try:
            exchange_symbol = self.normalize_symbol(symbol) if symbol else None
            order = await self.exchange.fetch_order(order_id, exchange_symbol)
            return self._parse_order(order, original_symbol=symbol)

        except Exception as e:
            print(f"❌ Failed to get order from {self.exchange_name}: {e}")
            return None

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """
        查詢未成交訂單

        Args:
            symbol: 交易對符號（統一格式，可選）

        Returns:
            List[Order]: 訂單列表
        """
        try:
            exchange_symbol = self.normalize_symbol(symbol) if symbol else None
            orders = await self.exchange.fetch_open_orders(exchange_symbol)
            return [self._parse_order(o) for o in orders]

        except Exception as e:
            print(f"❌ Failed to get open orders from {self.exchange_name}: {e}")
            return []

    async def get_orderbook(self, symbol: str, limit: int = 20) -> Orderbook:
        """
        獲取訂單簿

        Args:
            symbol: 交易對符號，統一格式如 "BTC-USD" 或交易所格式 "BTC/USDT:USDT"
            limit: 深度限制

        Returns:
            Orderbook: 訂單簿數據
        """
        try:
            # 轉換為交易所格式
            exchange_symbol = self.normalize_symbol(symbol)
            ob = await self.exchange.fetch_order_book(exchange_symbol, limit)

            return Orderbook(
                symbol=symbol,  # 返回原始請求的 symbol
                bids=[[Decimal(str(b[0])), Decimal(str(b[1]))] for b in ob['bids'][:limit]],
                asks=[[Decimal(str(a[0])), Decimal(str(a[1]))] for a in ob['asks'][:limit]],
                timestamp=datetime.fromtimestamp(ob['timestamp'] / 1000) if ob.get('timestamp') else datetime.now()
            )

        except Exception as e:
            print(f"❌ Failed to get orderbook from {self.exchange_name}: {e}")
            raise

    async def set_leverage(self, symbol: str, leverage: int) -> bool:
        """
        設置槓桿倍數

        Args:
            symbol: 交易對符號（統一格式如 BTC-USD）
            leverage: 槓桿倍數

        Returns:
            bool: 是否成功
        """
        try:
            exchange_symbol = self.normalize_symbol(symbol)
            await self.exchange.set_leverage(leverage, exchange_symbol)
            print(f"✅ Set leverage to {leverage}x for {symbol}")
            return True

        except Exception as e:
            print(f"❌ Failed to set leverage: {e}")
            return False

    async def get_funding_rate(self, symbol: str) -> Dict[str, Any]:
        """
        查詢資金費率

        Args:
            symbol: 交易對符號（統一格式如 BTC-USD）

        Returns:
            Dict: 資金費率信息
        """
        try:
            exchange_symbol = self.normalize_symbol(symbol)
            funding_rate = await self.exchange.fetch_funding_rate(exchange_symbol)
            return {
                'symbol': symbol,  # 返回原始請求的 symbol
                'funding_rate': Decimal(str(funding_rate.get('fundingRate', 0))),
                'next_funding_time': funding_rate.get('fundingTimestamp'),
                'funding_interval': funding_rate.get('fundingDatetime')
            }

        except Exception as e:
            print(f"❌ Failed to get funding rate: {e}")
            return {}

    def _parse_order(self, order: Dict, original_symbol: Optional[str] = None) -> Order:
        """
        解析 CCXT 訂單格式到統一格式

        Args:
            order: CCXT 訂單數據
            original_symbol: 原始請求的 symbol（統一格式）

        Returns:
            Order: 統一訂單格式
        """
        # 使用原始 symbol 或轉換回統一格式
        symbol = original_symbol or self.denormalize_symbol(order['symbol'])
        return Order(
            order_id=order['id'],
            symbol=symbol,
            side=order['side'].upper(),
            order_type=order['type'].upper(),
            price=Decimal(str(order.get('price', 0) or 0)),
            quantity=Decimal(str(order['amount'])),
            filled_quantity=Decimal(str(order.get('filled', 0))),
            remaining_quantity=Decimal(str(order.get('remaining', 0))),
            status=order['status'].upper(),
            timestamp=datetime.fromtimestamp(order['timestamp'] / 1000) if order.get('timestamp') else datetime.now(),
            time_in_force=TimeInForce.GTC.value,
            reduce_only=order.get('reduceOnly', False),
            post_only=order.get('postOnly', False)
        )

    def __del__(self):
        """析構函數：確保連接被關閉"""
        try:
            if hasattr(self, 'exchange') and self.exchange:
                # 由於是異步，這裡只能盡力而為
                pass
        except:
            pass
