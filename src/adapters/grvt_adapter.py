"""
GRVT Exchange Adapter Implementation

使用官方 GRVT Python SDK (grvt-pysdk) 實現
API Documentation: https://api-docs.grvt.io/

注意：GRVT SDK 是同步的，所有方法使用 asyncio.to_thread 包裝
支援 WebSocket 即時推送 (v1.fill, v1.state, v1.position)
"""
import asyncio
import logging
from typing import Dict, Any, Optional, List, Callable, Awaitable
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

# WebSocket client (conditional import to avoid circular deps)
try:
    from .grvt_ws_client import GRVTWebSocketClient, GRVTFillEvent, GRVTOrderStateEvent
except ImportError:
    GRVTWebSocketClient = None
    GRVTFillEvent = None
    GRVTOrderStateEvent = None

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

        # WebSocket client for real-time updates
        self._ws_client: Optional[GRVTWebSocketClient] = None
        self._ws_task: Optional[asyncio.Task] = None
        self._ws_enabled = False

        # WebSocket callbacks (external handlers)
        self._fill_callbacks: List[Callable[[GRVTFillEvent], Awaitable[None]]] = []
        self._order_state_callbacks: List[Callable[[GRVTOrderStateEvent], Awaitable[None]]] = []

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

    # ==================== WebSocket Support ====================

    def on_fill(self, callback: Callable[[GRVTFillEvent], Awaitable[None]]):
        """
        Register callback for fill events (WebSocket)

        Args:
            callback: Async function to call when a fill occurs
        """
        if GRVTWebSocketClient is None:
            logger.warning("WebSocket client not available")
            return self
        self._fill_callbacks.append(callback)
        return self

    def on_order_state(self, callback: Callable[[GRVTOrderStateEvent], Awaitable[None]]):
        """
        Register callback for order state events (WebSocket)

        Args:
            callback: Async function to call when order state changes
        """
        if GRVTWebSocketClient is None:
            logger.warning("WebSocket client not available")
            return self
        self._order_state_callbacks.append(callback)
        return self

    async def start_websocket(self, instruments: List[str] = None) -> bool:
        """
        Start WebSocket connection for real-time updates

        Args:
            instruments: List of instruments to subscribe (default: ["BTC_USDT_Perp"])

        Returns:
            True if WebSocket started successfully
        """
        logger.info("[WebSocket] ========== Starting WebSocket initialization ==========")

        if GRVTWebSocketClient is None:
            logger.error("[WebSocket] GRVTWebSocketClient not available - check import")
            return False

        if self._ws_enabled:
            logger.warning("[WebSocket] WebSocket already running")
            return True

        # 從 SDK client 獲取 session cookie
        session_cookie = None
        try:
            if self._client and hasattr(self._client, '_session'):
                logger.info("[WebSocket] Found SDK _session attribute")
                cookies = self._client._session.cookies

                # 列出所有 cookies 以便調試
                all_cookies = dict(cookies)
                logger.info(f"[WebSocket] SDK session cookies: {list(all_cookies.keys())}")

                # 嘗試多種可能的 cookie 名稱
                cookie_names = ['gravity', 'grvt_session', 'grvt', 'session', 'auth']
                for name in cookie_names:
                    if name in all_cookies:
                        session_cookie = all_cookies[name]
                        logger.info(f"[WebSocket] Found cookie '{name}' (length={len(session_cookie) if session_cookie else 0})")
                        break

                if not session_cookie:
                    # 嘗試刷新 cookie
                    logger.info("[WebSocket] No cookie found, attempting refresh...")
                    try:
                        self._client._refresh_cookie()
                        cookies = self._client._session.cookies
                        all_cookies = dict(cookies)
                        logger.info(f"[WebSocket] After refresh, cookies: {list(all_cookies.keys())}")

                        for name in cookie_names:
                            if name in all_cookies:
                                session_cookie = all_cookies[name]
                                logger.info(f"[WebSocket] Found cookie '{name}' after refresh")
                                break
                    except Exception as refresh_err:
                        logger.warning(f"[WebSocket] Cookie refresh failed: {refresh_err}")
            else:
                logger.warning("[WebSocket] SDK client or _session not available")
        except Exception as e:
            logger.warning(f"[WebSocket] Failed to get session cookie: {e}", exc_info=True)

        # 如果沒有 session cookie，使用 API key 作為 fallback
        if not session_cookie:
            logger.warning("[WebSocket] No session cookie found, using API key as fallback")
            session_cookie = self.api_key

        # 確保有 trading_account_id
        trading_account = self.trading_account_id or self._main_account_id
        if not trading_account:
            logger.error("[WebSocket] No trading_account_id available")
            return False

        logger.info(f"[WebSocket] Creating client with account_id={trading_account}, testnet={self.testnet}")
        logger.info(f"[WebSocket] Cookie/API key length: {len(session_cookie) if session_cookie else 0}")

        try:
            # Create WebSocket client
            self._ws_client = GRVTWebSocketClient(
                api_key=session_cookie,
                trading_account_id=trading_account,
                testnet=self.testnet,
            )

            # Register internal handlers that forward to external callbacks
            async def _on_fill(fill: GRVTFillEvent):
                logger.info(
                    f"[GRVT WS] Fill received: {fill.side} {fill.size} @ {fill.price} "
                    f"(maker={fill.is_maker}, fee={fill.fee})"
                )
                for cb in self._fill_callbacks:
                    try:
                        await cb(fill)
                    except Exception as e:
                        logger.error(f"Fill callback error: {e}")

            async def _on_order_state(order: GRVTOrderStateEvent):
                logger.debug(f"[GRVT WS] Order state: {order.order_id} {order.state}")
                for cb in self._order_state_callbacks:
                    try:
                        await cb(order)
                    except Exception as e:
                        logger.error(f"Order state callback error: {e}")

            self._ws_client.on_fill(_on_fill)
            self._ws_client.on_order_state(_on_order_state)

            # Connect
            logger.info("[WebSocket] Attempting to connect...")
            success = await self._ws_client.connect()
            if not success:
                logger.error("[WebSocket] Failed to connect GRVT WebSocket")
                return False

            logger.info("[WebSocket] Connected successfully, subscribing to instruments...")

            # Subscribe to instruments
            instruments = instruments or ["BTC_USDT_Perp"]
            for inst in instruments:
                await self._ws_client.subscribe_fills(inst)
                await self._ws_client.subscribe_order_states(inst)
                logger.info(f"[WebSocket] Subscribed: {inst}")

            # Start message processing loop
            self._ws_task = asyncio.create_task(self._ws_client.run())
            self._ws_enabled = True

            logger.info(f"[WebSocket] ========== WebSocket started successfully for {instruments} ==========")
            return True

        except Exception as e:
            logger.error(f"[WebSocket] Failed to start GRVT WebSocket: {e}", exc_info=True)
            return False

    async def stop_websocket(self):
        """Stop WebSocket connection"""
        if not self._ws_enabled:
            return

        self._ws_enabled = False

        if self._ws_client:
            await self._ws_client.disconnect()

        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
            self._ws_task = None

        logger.info("GRVT WebSocket stopped")

    @property
    def ws_connected(self) -> bool:
        """Whether WebSocket is connected"""
        return self._ws_client.is_connected if self._ws_client else False

    def get_ws_stats(self) -> Dict[str, Any]:
        """Get WebSocket statistics"""
        if self._ws_client:
            return self._ws_client.get_stats()
        return {"enabled": False}

    async def disconnect(self) -> bool:
        """斷開連接"""
        try:
            # Stop WebSocket if running
            if self._ws_enabled:
                await self.stop_websocket()

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
            # 診斷日誌
            logger.info(f"[GRVT] Position data: instrument={pos_data.instrument}, balance={pos_data.balance}")

            # 過濾 symbol（更智能的匹配）
            if symbol:
                # 提取 base asset (BTC, ETH, etc.)
                symbol_base = symbol.upper().replace("-", "_").replace("/", "_").split("_")[0]
                instrument_base = pos_data.instrument.upper().split("_")[0]

                # 只要 base asset 匹配就算匹配成功
                if symbol_base != instrument_base:
                    logger.debug(f"[GRVT] Skipping position: {pos_data.instrument} (base {instrument_base} != {symbol_base})")
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
        # GRVT 響應格式可能是: {"result": {"order": {"order_id": "..."}}}
        # 或 {"result": {"order_id": "..."}}
        order_data = result.get("result", {})
        logger.debug(f"[GRVT Place] Response: {result}")

        # 嘗試多種路徑獲取 order_id
        order_id_result = (
            order_data.get("order_id")
            or order_data.get("order", {}).get("order_id")
            or order_data.get("ack", {}).get("order_id")  # 某些 API 用 ack
        )

        logger.info(f"[GRVT Place] Order placed: order_id={order_id_result}, client_order_id={client_order_id}")

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

    async def cancel_order(
        self,
        symbol: str,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None
    ) -> bool:
        """
        取消訂單

        Args:
            symbol: 交易對 (為了兼容 StandX 介面，但 GRVT 不需要)
            order_id: GRVT 訂單 ID (優先使用)
            client_order_id: 客戶端訂單 ID

        Note: GRVT 支持用 order_id 或 client_order_id 取消
        """
        if not self._client:
            raise Exception("Not connected. Call connect() first.")

        # 檢查 order_id 是否有效（不是 None, 空字串, 或 "0x00"）
        valid_order_id = order_id and order_id not in [None, "", "0x00", "0x0"]

        if not valid_order_id and not client_order_id:
            logger.warning(f"[GRVT Cancel] No valid order_id or client_order_id provided")
            return False

        return await asyncio.to_thread(self._cancel_order_sync, order_id if valid_order_id else None, client_order_id)

    def _cancel_order_sync(self, order_id: Optional[str], client_order_id: Optional[str] = None) -> bool:
        """同步取消訂單"""
        try:
            # 構建取消請求，優先使用 order_id，否則使用 client_order_id
            if order_id:
                logger.info(f"[GRVT Cancel] Cancelling by order_id={order_id}")
                req = ApiCancelOrderRequest(
                    sub_account_id=self.trading_account_id or self._main_account_id,
                    order_id=order_id
                )
            else:
                logger.info(f"[GRVT Cancel] Cancelling by client_order_id={client_order_id}")
                req = ApiCancelOrderRequest(
                    sub_account_id=self.trading_account_id or self._main_account_id,
                    client_order_id=client_order_id
                )

            result = self._client.cancel_order_v1(req)

            if isinstance(result, GrvtError):
                logger.warning(f"Cancel order error: {result}")
                return False

            logger.info(f"[GRVT Cancel] Successfully cancelled")
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

        # 診斷日誌：原始返回
        raw_count = len(result.result) if result.result else 0
        logger.debug(f"[GRVT OpenOrders] Raw count={raw_count}, filter_symbol={symbol}")

        orders = []
        for order_data in result.result or []:
            # 過濾 symbol（使用包含匹配，更靈活）
            instrument = order_data.legs[0].instrument if order_data.legs else ""
            if symbol:
                # 同時支持精確匹配和包含匹配
                if instrument != symbol and symbol not in instrument and instrument not in symbol:
                    logger.debug(f"[GRVT OpenOrders] Skipping order: instrument={instrument}, filter={symbol}")
                    continue
            orders.append(self._parse_order(order_data))

        logger.debug(f"[GRVT OpenOrders] Returning {len(orders)} orders after filter")
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

        # client_order_id 在 metadata 對象中（下單時設置的位置）
        metadata = getattr(order_data, 'metadata', None)
        client_order_id = getattr(metadata, 'client_order_id', None) if metadata else None
        # 如果 metadata 沒有，嘗試直接從 order_data 獲取（兼容不同版本）
        if not client_order_id:
            client_order_id = getattr(order_data, 'client_order_id', None)

        # 診斷日誌：訂單解析
        order_id = getattr(order_data, 'order_id', None)
        logger.debug(
            f"[GRVT ParseOrder] order_id={order_id}, client_order_id={client_order_id}, "
            f"metadata={metadata}, filled_size={filled_size}"
        )

        return Order(
            order_id=order_data.order_id,
            client_order_id=client_order_id,
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
