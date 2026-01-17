"""
GRVT Exchange Adapter Implementation

使用官方 GRVT Python SDK (grvt-pysdk) 實現
API Documentation: https://api-docs.grvt.io/

注意：GRVT SDK 是同步的，所有方法使用 asyncio.to_thread 包裝
"""
import asyncio
import logging
from typing import Dict, Any, Optional, List
from decimal import Decimal, ROUND_FLOOR
from datetime import datetime
from dataclasses import dataclass

import time

from .base_adapter import (
    BasePerpAdapter,
    Balance,
    Position,
    Order,
    OrderSide,
    OrderType,
    OrderStatus,
    TimeInForce,
    Orderbook,
    SymbolInfo
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
    ApiGetOrderRequest,
    ApiGetAllInstrumentsRequest,
    OrderLeg,
    OrderMetadata,
    Order as GrvtOrder,
    TimeInForce as GrvtTimeInForce,
    Signature,
)
from pysdk.grvt_raw_signing import sign_order
from eth_account import Account as EthAccount

logger = logging.getLogger(__name__)


@dataclass
class ContractSpec:
    """合約規格"""
    symbol: str
    min_qty: Decimal
    qty_step: Decimal              # 數量最小跳動
    price_tick: Decimal            # 價格最小跳動
    contract_multiplier: Decimal = Decimal("1")
    qty_must_be_integer: bool = False  # 某些合約只接受整數張


class GRVTAdapter(BasePerpAdapter):
    """
    GRVT 交易所適配器實現 - 使用官方 SDK

    所有同步 SDK 調用都使用 asyncio.to_thread 包裝，避免阻塞 event loop
    """

    # 健康檢查超時 (秒)
    HEALTH_CHECK_TIMEOUT_SEC = 5.0

    # Symbol 規格 TTL (秒)
    SYMBOL_SPECS_TTL_SEC = 3600  # 1 小時

    # Fallback symbol specs (API 失敗時使用)
    # GRVT tick size 通常為 0.1（BTC/ETH）或 0.01（小幣）
    _FALLBACK_SPECS = {
        "BTC_USDT_Perp": SymbolInfo(
            symbol="BTC_USDT_Perp",
            min_qty=Decimal("0.001"),
            qty_step=Decimal("0.001"),
            price_tick=Decimal("0.1"),  # GRVT BTC tick = 0.1
            min_notional=Decimal("10"),
        ),
        "ETH_USDT_Perp": SymbolInfo(
            symbol="ETH_USDT_Perp",
            min_qty=Decimal("0.01"),
            qty_step=Decimal("0.01"),
            price_tick=Decimal("0.01"),  # GRVT ETH tick = 0.01
            min_notional=Decimal("10"),
        ),
        "SOL_USDT_Perp": SymbolInfo(
            symbol="SOL_USDT_Perp",
            min_qty=Decimal("0.1"),
            qty_step=Decimal("0.1"),
            price_tick=Decimal("0.01"),  # GRVT SOL tick = 0.01
            min_notional=Decimal("10"),
        ),
    }

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
        self._sdk_config: Optional[GrvtApiConfig] = None
        self._connected = False
        self._main_account_id: Optional[str] = None

        # Ethereum 帳戶 (用於簽名)
        self._eth_account = EthAccount.from_key(self.api_secret)

        # 合約規格快取
        self._contract_specs: Dict[str, ContractSpec] = {}

        # Instruments 快取 (用於簽名)
        self._instruments: Dict[str, Any] = {}

        # Symbol specs cache (for SymbolInfo)
        self._symbol_specs: Dict[str, SymbolInfo] = {}
        self._symbol_specs_ts: Dict[str, float] = {}

    # ==================== 生命週期 ====================

    async def connect(self) -> bool:
        """連接到 GRVT"""
        try:
            # 創建 SDK 配置
            self._sdk_config = GrvtApiConfig(
                env=self.env,
                trading_account_id=self.trading_account_id,
                private_key=self.api_secret,
                api_key=self.api_key,
                logger=None
            )

            # 初始化客戶端（同步操作，但很快）
            self._client = GrvtRawSync(self._sdk_config)

            # 測試連接 - 使用 to_thread 包裝
            result = await asyncio.to_thread(
                self._client.aggregated_account_summary_v1,
                EmptyRequest()
            )

            if isinstance(result, GrvtError):
                raise Exception(f"API Error: {result}")

            self._main_account_id = result.result.main_account_id
            self._connected = True

            # 獲取 instruments (用於訂單簽名)
            await self._fetch_instruments()

            logger.info(f"Connected to GRVT ({'Testnet' if self.testnet else 'Mainnet'})")
            logger.info(f"Main Account: {self._main_account_id}")
            logger.info(f"Loaded {len(self._instruments)} instruments")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to GRVT: {e}")
            self._client = None
            return False

    async def _fetch_instruments(self):
        """獲取所有 instruments (用於訂單簽名)"""
        try:
            result = await asyncio.to_thread(
                self._client.get_all_instruments_v1,
                ApiGetAllInstrumentsRequest(is_active=True)
            )

            if isinstance(result, GrvtError):
                logger.warning(f"Failed to fetch instruments: {result}")
                return

            # 構建 instrument 字典
            for inst in result.result:
                self._instruments[inst.instrument] = inst
                logger.debug(f"Loaded instrument: {inst.instrument}")

        except Exception as e:
            logger.warning(f"Error fetching instruments: {e}")

    async def disconnect(self) -> bool:
        """斷開連接"""
        try:
            self._client = None
            self._connected = False
            return True
        except Exception as e:
            logger.error(f"Failed to disconnect from GRVT: {e}")
            return False

    # ==================== 健康檢查 ====================

    async def health_check(self) -> dict:
        """
        健康檢查（帶超時）

        檢查 GRVT API 連線和憑證是否正常。
        """
        start = time.time()

        try:
            # 1. 測試帳戶 API（需認證）
            balance = await asyncio.wait_for(
                self.get_balance(),
                timeout=self.HEALTH_CHECK_TIMEOUT_SEC / 2
            )
            if balance is None:
                return {
                    "healthy": False,
                    "latency_ms": (time.time() - start) * 1000,
                    "error": "無法獲取 GRVT 帳戶餘額",
                    "details": {}
                }

            # 2. 測試市場 API
            positions = await asyncio.wait_for(
                self.get_positions(),
                timeout=self.HEALTH_CHECK_TIMEOUT_SEC / 2
            )

            return {
                "healthy": True,
                "latency_ms": (time.time() - start) * 1000,
                "error": None,
                "details": {
                    "available": float(balance.available_balance) if balance else 0,
                    "position_count": len(positions) if positions else 0,
                    "main_account": self._main_account_id,
                }
            }

        except asyncio.TimeoutError:
            return {
                "healthy": False,
                "latency_ms": (time.time() - start) * 1000,
                "error": f"健康檢查超時 ({self.HEALTH_CHECK_TIMEOUT_SEC}s)",
                "details": {}
            }
        except Exception as e:
            return {
                "healthy": False,
                "latency_ms": (time.time() - start) * 1000,
                "error": str(e),
                "details": {}
            }

    async def get_symbol_info(self, symbol: str) -> Optional[SymbolInfo]:
        """
        獲取交易對規格（帶 TTL 快取）

        Args:
            symbol: 交易對符號

        Returns:
            Optional[SymbolInfo]: 交易對規格
        """
        # 標準化 symbol
        grvt_symbol = self._normalize_symbol(symbol)
        now = time.time()

        # 檢查快取是否有效
        if (grvt_symbol in self._symbol_specs and
            grvt_symbol in self._symbol_specs_ts and
            now - self._symbol_specs_ts[grvt_symbol] < self.SYMBOL_SPECS_TTL_SEC):
            return self._symbol_specs[grvt_symbol]

        # TODO: 從 GRVT API 拉取規格（如果有 instruments API）
        # 目前先使用 fallback specs

        # 返回 fallback
        if grvt_symbol in self._FALLBACK_SPECS:
            self._symbol_specs[grvt_symbol] = self._FALLBACK_SPECS[grvt_symbol]
            self._symbol_specs_ts[grvt_symbol] = now
            return self._symbol_specs[grvt_symbol]

        return None

    # ==================== 餘額查詢 ====================

    async def get_balance(self) -> Balance:
        """查詢賬戶餘額"""
        if not self._client:
            raise Exception("Not connected. Call connect() first.")

        return await asyncio.to_thread(self._get_balance_sync)

    def _get_balance_sync(self) -> Balance:
        """同步查詢餘額"""
        result = self._client.aggregated_account_summary_v1(EmptyRequest())

        if isinstance(result, GrvtError):
            raise Exception(f"API Error: {result}")

        summary = result.result

        total = Decimal(str(summary.total_equity or "0"))
        available = total

        return Balance(
            total_balance=total,
            available_balance=available,
            used_margin=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            equity=total
        )

    # ==================== 持倉查詢 ====================

    async def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """查詢持倉"""
        if not self._client:
            raise Exception("Not connected. Call connect() first.")

        return await asyncio.to_thread(self._get_positions_sync, symbol)

    def _get_positions_sync(self, symbol: Optional[str] = None) -> List[Position]:
        """同步查詢持倉"""
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
                leverage=1,
                margin=Decimal(str(pos_data.notional or "0"))
            )
            positions.append(position)

        return positions

    # ==================== 下單 ====================

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

        return await asyncio.to_thread(
            self._place_order_sync,
            symbol, side, order_type, quantity, price,
            time_in_force, reduce_only, post_only, client_order_id
        )

    def _place_order_sync(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Optional[Decimal],
        time_in_force: TimeInForce,
        reduce_only: bool,
        post_only: bool,
        client_order_id: Optional[str]
    ) -> Order:
        """同步下單"""
        import uuid

        # 標準化 symbol
        grvt_symbol = self._normalize_symbol(symbol)

        # 檢查 instrument 是否存在
        if grvt_symbol not in self._instruments:
            raise Exception(f"Unknown instrument: {grvt_symbol}. Available: {list(self._instruments.keys())[:5]}...")

        # 轉換參數
        is_bid = side in [OrderSide.BUY, "buy", "long"]

        # 計算名義價值並記錄
        notional = float(quantity) * float(price) if price else 0
        logger.info(f"[GRVT Order] {grvt_symbol} {side} qty={quantity} price={price} notional=${notional:.2f}")

        # 構建訂單腿
        legs = [OrderLeg(
            instrument=grvt_symbol,
            is_buying_asset=is_bid,
            size=str(quantity),
            limit_price=str(price) if price else "0"
        )]

        # 時間有效性映射 (使用 SDK 的 TimeInForce enum)
        tif_map = {
            TimeInForce.GTC: GrvtTimeInForce.GOOD_TILL_TIME,
            TimeInForce.IOC: GrvtTimeInForce.IMMEDIATE_OR_CANCEL,
            TimeInForce.FOK: GrvtTimeInForce.FILL_OR_KILL,
            "gtc": GrvtTimeInForce.GOOD_TILL_TIME,
            "ioc": GrvtTimeInForce.IMMEDIATE_OR_CANCEL,
            "fok": GrvtTimeInForce.FILL_OR_KILL,
        }
        grvt_tif = tif_map.get(time_in_force, GrvtTimeInForce.GOOD_TILL_TIME)

        # 生成 client_order_id (必須是數字字串，使用 uint32 範圍)
        import random
        if not client_order_id:
            client_order_id = str(random.randint(0, 2**32 - 1))

        # 生成簽名所需的 expiration 和 nonce
        # expiration: 1 小時後，nanoseconds 格式
        expiration_ns = str(int((time.time() + 3600) * 1_000_000_000))
        # nonce: 當前時間的秒數 (必須是 32-bit unsigned integer)
        nonce = int(time.time())

        # 創建未簽名的訂單
        unsigned_order = GrvtOrder(
            sub_account_id=self.trading_account_id or self._main_account_id,
            time_in_force=grvt_tif,
            legs=legs,
            signature=Signature(signer="", r="", s="", v=0, expiration=expiration_ns, nonce=nonce),
            metadata=OrderMetadata(client_order_id=client_order_id),
            is_market=(order_type == OrderType.MARKET),
            post_only=post_only,
            reduce_only=reduce_only,
        )

        # 簽名訂單
        signed_order = sign_order(
            order=unsigned_order,
            config=self._sdk_config,
            account=self._eth_account,
            instruments=self._instruments
        )

        # 構建乾淨的請求 payload（使用 snake_case，與 CCXT SDK 一致）
        payload = {
            "order": {
                "sub_account_id": str(signed_order.sub_account_id),
                "is_market": signed_order.is_market or False,
                "time_in_force": signed_order.time_in_force.name,
                "post_only": signed_order.post_only or False,
                "reduce_only": signed_order.reduce_only or False,
                "legs": [
                    {
                        "instrument": leg.instrument,
                        "size": str(leg.size),
                        "limit_price": str(leg.limit_price),
                        "is_buying_asset": bool(leg.is_buying_asset),
                    }
                    for leg in signed_order.legs
                ],
                "signature": {
                    "r": signed_order.signature.r,
                    "s": signed_order.signature.s,
                    "v": signed_order.signature.v,
                    "expiration": signed_order.signature.expiration,
                    "nonce": signed_order.signature.nonce,
                    "signer": signed_order.signature.signer,
                },
                "metadata": {
                    "client_order_id": signed_order.metadata.client_order_id,
                },
            }
        }

        # 直接發送請求（需要先刷新 cookie）
        import json
        import requests
        self._client._refresh_cookie()  # 確保 auth cookie 有效
        resp = self._client._session.post(
            f"{self._client.td_rpc}/full/v1/create_order",
            data=json.dumps(payload),
            timeout=5
        )
        resp_json = resp.json()

        if resp_json.get("code"):
            raise Exception(f"API Error: {resp_json}")

        result = resp_json

        # 從 dict 響應中獲取 order_id
        order_data = result.get("result", {})
        order_id_result = order_data.get("order_id") or order_data.get("order", {}).get("order_id")

        return Order(
            order_id=order_id_result,
            client_order_id=client_order_id,
            symbol=symbol,
            side=side.value if hasattr(side, 'value') else str(side),
            order_type=order_type.value if hasattr(order_type, 'value') else str(order_type),
            price=price,
            qty=quantity,
            filled_qty=Decimal("0"),
            status="NEW",
            time_in_force=time_in_force.value if hasattr(time_in_force, 'value') else str(time_in_force),
            reduce_only=reduce_only,
            created_at=int(time.time() * 1000),
        )

    # ==================== 取消訂單 ====================

    async def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> bool:
        """取消訂單"""
        if not self._client:
            raise Exception("Not connected. Call connect() first.")

        return await asyncio.to_thread(self._cancel_order_sync, order_id)

    def _cancel_order_sync(self, order_id: str) -> bool:
        """同步取消訂單"""
        try:
            req = ApiCancelOrderRequest(
                sub_account_id=self.trading_account_id or self._main_account_id,
                order_id=order_id
            )

            result = self._client.cancel_order_v1(req)

            if isinstance(result, GrvtError):
                logger.warning(f"Cancel order error: {result}")
                return False

            return True

        except Exception as e:
            logger.error(f"Failed to cancel order on GRVT: {e}")
            return False

    async def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """取消所有訂單"""
        if not self._client:
            raise Exception("Not connected. Call connect() first.")

        return await asyncio.to_thread(self._cancel_all_orders_sync)

    def _cancel_all_orders_sync(self) -> int:
        """同步取消所有訂單"""
        try:
            req = ApiCancelAllOrdersRequest(
                sub_account_id=self.trading_account_id or self._main_account_id,
                kind=["PERPETUAL"],
                base=[],
                quote=[]
            )

            result = self._client.cancel_all_orders_v1(req)

            if isinstance(result, GrvtError):
                logger.warning(f"Cancel all orders error: {result}")
                return 0

            return result.result.num_cancelled if hasattr(result.result, 'num_cancelled') else 0

        except Exception as e:
            logger.error(f"Failed to cancel all orders on GRVT: {e}")
            return 0

    # ==================== 訂單查詢 ====================

    async def get_order(self, order_id: str, symbol: Optional[str] = None) -> Optional[Order]:
        """查詢訂單"""
        if not self._client:
            raise Exception("Not connected. Call connect() first.")

        return await asyncio.to_thread(self._get_order_sync, order_id)

    def _get_order_sync(self, order_id: str) -> Optional[Order]:
        """同步查詢訂單"""
        try:
            req = ApiGetOrderRequest(
                sub_account_id=self.trading_account_id or self._main_account_id,
                order_id=order_id
            )

            result = self._client.get_order_v1(req)

            if isinstance(result, GrvtError):
                return None

            return self._parse_order(result.result)

        except Exception:
            return None

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """查詢未成交訂單"""
        if not self._client:
            raise Exception("Not connected. Call connect() first.")

        return await asyncio.to_thread(self._get_open_orders_sync, symbol)

    def _get_open_orders_sync(self, symbol: Optional[str] = None) -> List[Order]:
        """同步查詢未成交訂單"""
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

    # ==================== 訂單簿 ====================

    async def get_orderbook(self, symbol: str, limit: int = 20) -> Orderbook:
        """獲取訂單簿"""
        if not self._client:
            raise Exception("Not connected. Call connect() first.")

        return await asyncio.to_thread(self._get_orderbook_sync, symbol, limit)

    def _get_orderbook_sync(self, symbol: str, limit: int) -> Orderbook:
        """同步獲取訂單簿"""
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

    # ==================== 合約規格 ====================

    async def get_contract_spec(self, symbol: str) -> Optional[ContractSpec]:
        """獲取合約規格"""
        if symbol in self._contract_specs:
            return self._contract_specs[symbol]

        # 嘗試從 API 獲取（目前使用默認值）
        # TODO: 實現從 GRVT API 獲取 instruments
        # instruments = await asyncio.to_thread(self._get_instruments_sync)

        # 使用 fallback specs 的值（如果有）
        fallback = self._FALLBACK_SPECS.get(symbol)
        if fallback:
            self._contract_specs[symbol] = ContractSpec(
                symbol=symbol,
                min_qty=fallback.min_qty,
                qty_step=fallback.qty_step,
                price_tick=fallback.price_tick,
                contract_multiplier=Decimal("1"),
                qty_must_be_integer=False,
            )
        else:
            # 默認值（BTC tick = 0.1）
            self._contract_specs[symbol] = ContractSpec(
                symbol=symbol,
                min_qty=Decimal("0.001"),
                qty_step=Decimal("0.001"),
                price_tick=Decimal("0.1"),
                contract_multiplier=Decimal("1"),
                qty_must_be_integer=False,
            )

        return self._contract_specs[symbol]

    def normalize_quantity(self, qty: Decimal, spec: ContractSpec) -> Optional[Decimal]:
        """
        正規化下單量（使用 ROUND_FLOOR 避免精度問題）

        Returns:
            正規化後的數量，如果低於最小數量則返回 None
        """
        contract_qty = qty / spec.contract_multiplier

        # 使用 to_integral_value 更穩
        steps = (contract_qty / spec.qty_step).to_integral_value(rounding=ROUND_FLOOR)
        normalized = steps * spec.qty_step

        # 某些合約只接受整數張
        if spec.qty_must_be_integer:
            normalized = Decimal(int(normalized))

        if normalized < spec.min_qty:
            logger.warning(f"Quantity {normalized} below min {spec.min_qty}")
            return None

        return normalized

    def invalidate_contract_specs(self):
        """清除合約規格快取（熱更新用）"""
        self._contract_specs.clear()
        logger.info("GRVT contract specs cache invalidated")

    # ==================== 市場查詢 ====================

    async def get_markets(self) -> List[Any]:
        """
        獲取支援的市場列表

        TODO: 實現從 GRVT API 獲取實際市場列表
        """
        # 目前返回已知的市場
        # 實際實現應該調用 GRVT API
        return [
            {"symbol": "BTC_USDT_Perp"},
            {"symbol": "ETH_USDT_Perp"},
            {"symbol": "SOL_USDT_Perp"},
        ]

    # ==================== 輔助方法 ====================

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

    def _parse_order(self, order_data) -> Order:
        """解析訂單數據"""
        leg = order_data.legs[0] if order_data.legs else None

        # 安全獲取屬性（GRVT SDK 不同版本可能有不同屬性名）
        filled_size = getattr(order_data, 'filled_size', None) or getattr(order_data, 'filled_qty', None) or "0"

        return Order(
            order_id=order_data.order_id,
            client_order_id=getattr(order_data, 'client_order_id', None),
            symbol=leg.instrument if leg else "",
            side="buy" if leg and leg.is_buying_asset else "sell",
            order_type="market" if getattr(order_data, 'is_market', False) else "limit",
            price=Decimal(str(leg.limit_price)) if leg else Decimal("0"),
            qty=Decimal(str(leg.size)) if leg else Decimal("0"),
            filled_qty=Decimal(str(filled_size)),
            status=getattr(order_data, 'state', None) or "UNKNOWN",
            time_in_force=getattr(order_data, 'time_in_force', None) or "GTC",
            reduce_only=getattr(order_data, 'reduce_only', False),
        )
