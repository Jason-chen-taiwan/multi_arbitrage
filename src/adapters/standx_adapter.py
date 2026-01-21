"""
StandX Exchange Adapter Implementation

This module implements BasePerpAdapter for StandX exchange.
"""
import asyncio
import json
import logging
import time
from typing import Dict, Any, Optional, List, Callable, Awaitable
from decimal import Decimal
from datetime import datetime
from uuid import uuid4

import aiohttp
from eth_account import Account

from .base_adapter import BasePerpAdapter, Balance, Position, Order, OrderSide, OrderType, OrderStatus, Orderbook, SymbolInfo, Trade
from .order_validator import validate_and_normalize_order
from .standx_ws_client import StandXWebSocketClient, OrderUpdate
from ..auth import AsyncStandXAuth

logger = logging.getLogger(__name__)

# 敏感資訊 key 列表（用於日誌遮罩）
SENSITIVE_KEYS = {"api_key", "secret", "signature", "authorization", "private_key", "ed25519", "token"}


class StandXAdapter(BasePerpAdapter):
    """
    StandX 交易所適配器實現

    Symbol 映射由 SymbolManager 統一管理 (config/symbols.yaml)

    支援兩種認證方式:
    1. Token 模式 (推薦): api_token + ed25519_private_key
    2. 錢包簽名模式: private_key (錢包私鑰)
    """

    # Symbol 規格 TTL (秒)
    SYMBOL_SPECS_TTL_SEC = 3600  # 1 小時

    # 健康檢查超時 (秒)
    HEALTH_CHECK_TIMEOUT_SEC = 5.0

    # Fallback symbol specs (API 失敗時使用)
    _FALLBACK_SPECS = {
        "BTC-USD": SymbolInfo(
            symbol="BTC-USD",
            min_qty=Decimal("0.0001"),
            qty_step=Decimal("0.0001"),
            price_tick=Decimal("0.01"),
            min_notional=Decimal("1"),
        ),
        "ETH-USD": SymbolInfo(
            symbol="ETH-USD",
            min_qty=Decimal("0.001"),
            qty_step=Decimal("0.001"),
            price_tick=Decimal("0.01"),
            min_notional=Decimal("1"),
        ),
    }

    def __init__(self, config: Dict[str, Any]):
        """
        初始化 StandX 適配器

        Args:
            config: 配置字典

            Token 模式 (推薦):
                - api_token: StandX 提供的 API Token
                - ed25519_private_key: StandX 提供的 Ed25519 Private Key

            錢包簽名模式:
                - private_key: 錢包私鑰
                - chain: 鏈名稱，如 "bsc" 或 "solana"

            通用參數:
                - base_url: API 基礎 URL（可選，默認 https://api.standx.com）
                - perps_url: Perps API URL（可選，默認 https://perps.standx.com）
        """
        super().__init__(config)

        self.chain = config.get("chain", "bsc")
        self.base_url = config.get("base_url", "https://api.standx.com")
        self.perps_url = config.get("perps_url", "https://perps.standx.com")

        # 檢測認證模式
        api_token = config.get("api_token")
        ed25519_key = config.get("ed25519_private_key")
        wallet_private_key = config.get("private_key") or config.get("wallet_private_key")

        if api_token and ed25519_key:
            # Token 模式
            self._auth_mode = "token"
            self.account = None
            self.wallet_address = None
            self.auth = AsyncStandXAuth(
                base_url=self.base_url,
                api_token=api_token,
                ed25519_private_key=ed25519_key,
            )
        elif wallet_private_key:
            # 錢包簽名模式
            self._auth_mode = "wallet"
            self.account = Account.from_key(wallet_private_key)
            self.wallet_address = self.account.address
            self.auth = AsyncStandXAuth(base_url=self.base_url)
        else:
            raise ValueError(
                "配置錯誤：必須提供以下其中一組認證資訊:\n"
                "  Token 模式: api_token + ed25519_private_key\n"
                "  錢包模式: private_key"
            )

        # Session management
        self.session: Optional[aiohttp.ClientSession] = None
        self.session_id = str(uuid4())

        # Symbol specs cache
        self._symbol_specs: Dict[str, SymbolInfo] = {}
        self._symbol_specs_ts: Dict[str, float] = {}

        # WebSocket support
        self._ws_client: Optional[StandXWebSocketClient] = None
        self._ws_task: Optional[asyncio.Task] = None
        self._fill_callbacks: List[Any] = []
        self._order_state_callbacks: List[Any] = []

        # 代理配置（用於女巫防護）
        self.proxy_url = config.get("proxy_url")
        self.proxy_auth = None
        if self.proxy_url:
            proxy_username = config.get("proxy_username")
            proxy_password = config.get("proxy_password", "")
            if proxy_username:
                self.proxy_auth = aiohttp.BasicAuth(proxy_username, proxy_password)
            logger.info(f"[StandX] 代理已配置: {self.proxy_url[:30]}...")
    
    async def connect(self) -> bool:
        """連接到 StandX 並完成認證"""
        try:
            # Create HTTP session with longer timeout for DNS issues
            timeout = aiohttp.ClientTimeout(
                total=30,        # 總超時 30 秒
                connect=15,      # 連接超時 15 秒（包含 DNS）
                sock_connect=10, # Socket 連接超時 10 秒
                sock_read=10     # Socket 讀取超時 10 秒
            )
            connector = aiohttp.TCPConnector(
                limit=10,        # 最大連接數
                ttl_dns_cache=300,  # DNS 快取 5 分鐘
                use_dns_cache=True,
            )
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector
            )

            if self._auth_mode == "token":
                # Token 模式: 無需認證，直接使用提供的 token
                print(f"✅ Connected to StandX (Token mode)")
                return True

            # 錢包簽名模式: 需要錢包簽名認證
            async def sign_message(message: str) -> str:
                """Sign message with wallet."""
                from eth_account.messages import encode_defunct
                signed_message = self.account.sign_message(
                    encode_defunct(text=message)
                )
                # 確保簽名帶有 0x 前綴（StandX API 要求）
                sig_hex = signed_message.signature.hex()
                if not sig_hex.startswith('0x'):
                    sig_hex = '0x' + sig_hex
                return sig_hex

            # Perform authentication
            login_response = await self.auth.authenticate(
                chain=self.chain,
                wallet_address=self.wallet_address,
                sign_message_fn=sign_message
            )

            # Store the access token
            if 'token' in login_response:
                self.auth.access_token = login_response['token']

            print(f"✅ Connected to StandX as {login_response.get('alias', 'Unknown')}")
            return True

        except Exception as e:
            print(f"❌ Failed to connect to StandX: {e}")
            if self.session:
                await self.session.close()
                self.session = None
            return False
    
    async def disconnect(self) -> bool:
        """斷開連接"""
        try:
            # 先停止 WebSocket
            if self._ws_client:
                await self.stop_websocket()

            if self.session:
                # 取得 connector 引用
                connector = self.session.connector

                # 關閉 session
                await self.session.close()
                self.session = None

                # 確保 connector 也被關閉
                if connector and not connector.closed:
                    await connector.close()

                # 給一點時間讓資源釋放
                await asyncio.sleep(0.1)

            return True
        except Exception as e:
            print(f"❌ Failed to disconnect from StandX: {e}")
            return False

    def _redact_sensitive(self, data: dict) -> dict:
        """遮罩敏感資訊"""
        if not isinstance(data, dict):
            return data

        redacted = {}
        for k, v in data.items():
            if k.lower() in SENSITIVE_KEYS:
                redacted[k] = "***REDACTED***"
            elif isinstance(v, dict):
                redacted[k] = self._redact_sensitive(v)
            else:
                redacted[k] = v
        return redacted

    async def health_check(self) -> dict:
        """
        健康檢查（帶超時）

        檢查 StandX API 連線和憑證是否正常。
        """
        start = time.time()

        try:
            # 1. 測試市場資料 API（公開 API）
            orderbook = await asyncio.wait_for(
                self.get_orderbook("BTC-USD", depth=1),
                timeout=self.HEALTH_CHECK_TIMEOUT_SEC / 2
            )
            if not orderbook or not orderbook.bids:
                return {
                    "healthy": False,
                    "latency_ms": (time.time() - start) * 1000,
                    "error": "無法獲取訂單簿",
                    "details": {}
                }

            # 2. 測試帳戶 API（需認證）
            balance = await asyncio.wait_for(
                self.get_balance(),
                timeout=self.HEALTH_CHECK_TIMEOUT_SEC / 2
            )
            if balance is None:
                return {
                    "healthy": False,
                    "latency_ms": (time.time() - start) * 1000,
                    "error": "無法獲取帳戶餘額，請檢查 API 憑證",
                    "details": {}
                }

            return {
                "healthy": True,
                "latency_ms": (time.time() - start) * 1000,
                "error": None,
                "details": {
                    "equity": float(balance.equity),
                    "available": float(balance.available_balance),
                    "btc_price": float(orderbook.bids[0][0]),
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
        now = time.time()

        # 檢查快取是否有效
        if (symbol in self._symbol_specs and
            symbol in self._symbol_specs_ts and
            now - self._symbol_specs_ts[symbol] < self.SYMBOL_SPECS_TTL_SEC):
            return self._symbol_specs[symbol]

        # TODO: 從 StandX API 拉取規格（如果有 instruments API）
        # 目前先使用 fallback specs

        # 返回 fallback
        if symbol in self._FALLBACK_SPECS:
            self._symbol_specs[symbol] = self._FALLBACK_SPECS[symbol]
            self._symbol_specs_ts[symbol] = now
            return self._symbol_specs[symbol]

        return None

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        sign_body: bool = False,
        max_retries: int = 3
    ) -> Dict:
        """Make authenticated API request with retry for network errors."""
        if not self.session:
            raise Exception("Not connected. Call connect() first.")

        url = f"{self.perps_url}{endpoint}"

        # Prepare headers
        payload_str = json.dumps(data) if data else None
        headers = self.auth.get_auth_headers(
            payload=payload_str if sign_body else None
        )

        # 禁用 brotli 編碼
        headers['Accept-Encoding'] = 'gzip, deflate'

        # Add Bearer token for authenticated endpoints
        if self.auth.access_token:
            headers['Authorization'] = f'Bearer {self.auth.access_token}'

        # Add session ID for order operations
        if '/order' in endpoint or '/cancel' in endpoint:
            headers['x-session-id'] = self.session_id

        # Make request with retry for network errors
        last_error = None
        for attempt in range(max_retries):
            try:
                # 構建請求參數
                request_kwargs = {
                    'method': method,
                    'url': url,
                    'params': params,
                    'json': data if data else None,
                    'headers': headers,
                }

                # 添加代理支援
                if self.proxy_url:
                    request_kwargs['proxy'] = self.proxy_url
                    if self.proxy_auth:
                        request_kwargs['proxy_auth'] = self.proxy_auth

                async with self.session.request(**request_kwargs) as response:
                    # 處理錯誤狀態碼
                    if response.status >= 400:
                        error_text = await response.text()

                        # 400 錯誤：詳細記錄請求資料（遮罩敏感資訊）
                        if response.status == 400:
                            safe_body = self._redact_sensitive(data or {})
                            logger.error(
                                f"StandX API 400 Bad Request:\n"
                                f"  URL: {url}\n"
                                f"  Method: {method}\n"
                                f"  Request Body: {json.dumps(safe_body, indent=2)}\n"
                                f"  Response: {error_text}"
                            )

                        response.raise_for_status()

                    return await response.json()

            except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2  # 2, 4, 6 秒
                    logger.warning(f"StandX connection error (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"StandX connection failed after {max_retries} attempts: {e}")
                    raise

        raise last_error
    
    async def get_balance(self) -> Balance:
        """查詢賬戶餘額"""
        try:
            result = await self._request('GET', '/api/query_balance')
            
            return Balance(
                total_balance=Decimal(str(result.get('balance', '0'))),
                available_balance=Decimal(str(result.get('cross_available', '0'))),
                used_margin=Decimal(str(result.get('cross_margin', '0'))),
                unrealized_pnl=Decimal(str(result.get('upnl', '0'))),
                equity=Decimal(str(result.get('equity', '0')))
            )
        except Exception as e:
            print(f"❌ Failed to get balance: {e}")
            raise
    
    async def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """查詢持倉"""
        try:
            params = {}
            if symbol:
                params['symbol'] = symbol
            
            result = await self._request('GET', '/api/query_positions', params=params)
            
            positions = []
            for pos_data in result:
                qty = Decimal(str(pos_data.get('qty', '0')))
                
                # 跳過零持倉
                if qty == 0:
                    continue
                
                # 根據數量正負判斷方向
                side = "long" if qty > 0 else "short"
                
                position = Position(
                    symbol=pos_data.get("symbol", ""),
                    size=abs(qty),  # 使用絕對值
                    side=side,
                    entry_price=Decimal(str(pos_data.get("entry_price", "0"))),
                    mark_price=Decimal(str(pos_data.get("mark_price", "0"))),
                    unrealized_pnl=Decimal(str(pos_data.get("upnl", "0"))),
                    leverage=int(pos_data.get("leverage", 1)) if pos_data.get("leverage") else None,
                    margin_mode=pos_data.get("margin_mode"),
                    liquidation_price=Decimal(str(pos_data.get("liq_price", "0"))) if pos_data.get("liq_price") else None,
                )
                positions.append(position)
            
            return positions
        except Exception as e:
            print(f"❌ Failed to get positions: {e}")
            raise
    
    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        price: Optional[Decimal] = None,
        time_in_force: str = "gtc",
        reduce_only: bool = False,
        client_order_id: Optional[str] = None,
        **kwargs
    ) -> Order:
        """下單（含驗證）"""
        if order_type == "limit" and price is None:
            raise ValueError("限價單必須指定價格")

        # === 訂單驗證 ===
        spec = await self.get_symbol_info(symbol)

        # 獲取 orderbook 用於市價單估算 notional
        best_bid, best_ask = None, None
        if price is None and spec and spec.min_notional:
            try:
                ob = await self.get_orderbook(symbol, depth=1)
                if ob and ob.bids and ob.asks:
                    best_bid = Decimal(str(ob.bids[0][0]))
                    best_ask = Decimal(str(ob.asks[0][0]))
            except Exception:
                pass

        # 執行驗證
        validation = validate_and_normalize_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            spec=spec,
            best_bid=best_bid,
            best_ask=best_ask,
        )

        if not validation.ok:
            raise ValueError(f"訂單驗證失敗: {validation.reason}")

        # 使用正規化後的值
        quantity = validation.normalized_qty
        if validation.normalized_price is not None:
            price = validation.normalized_price

        try:
            # 轉換 side: "long"/"short" -> "buy"/"sell"
            if side in ["long", "buy"]:
                side_str = "buy"
            elif side in ["short", "sell"]:
                side_str = "sell"
            else:
                side_str = side

            # 轉換 order_type
            if order_type == "post_only":
                order_type_str = "limit"
                time_in_force = "post_only"
            else:
                order_type_str = order_type

            # Prepare order data
            order_data = {
                "symbol": symbol,
                "side": side_str,
                "order_type": order_type_str,
                "qty": str(quantity),
                "time_in_force": time_in_force,
                "reduce_only": reduce_only
            }

            # Add price for limit orders
            if price:
                order_data["price"] = str(price)
            
            # Add client order ID
            if client_order_id:
                order_data["cl_ord_id"] = client_order_id
            else:
                order_data["cl_ord_id"] = f"mm_{uuid4().hex[:16]}"
            
            # Place order
            result = await self._request(
                'POST', '/api/new_order', 
                data=order_data, 
                sign_body=True
            )
            
            # Return order
            return Order(
                order_id=None,  # Will be updated via WebSocket
                client_order_id=order_data["cl_ord_id"],
                symbol=symbol,
                side=side,
                order_type=order_type,
                price=price,
                qty=quantity,
                filled_qty=Decimal("0"),
                status="pending",
                time_in_force=time_in_force,
                reduce_only=reduce_only,
            )
        except Exception as e:
            print(f"❌ Failed to place order: {e}")
            raise
    
    async def cancel_order(
        self,
        symbol: str,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None
    ) -> bool:
        """取消訂單"""
        if not order_id and not client_order_id:
            raise ValueError("必須提供 order_id 或 client_order_id")
        
        try:
            cancel_data = {}
            
            if order_id:
                cancel_data["order_id"] = int(order_id)
            elif client_order_id:
                cancel_data["cl_ord_id"] = client_order_id
            
            await self._request(
                'POST', '/api/cancel_order',
                data=cancel_data,
                sign_body=True
            )
            return True
        except Exception as e:
            print(f"❌ Failed to cancel order: {e}")
            return False
    
    async def cancel_all_orders(self, symbol: str) -> int:
        """取消所有訂單"""
        try:
            open_orders = await self.get_open_orders(symbol)
            
            count = 0
            for order in open_orders:
                success = await self.cancel_order(
                    symbol=symbol,
                    order_id=order.order_id,
                    client_order_id=order.client_order_id
                )
                if success:
                    count += 1
            
            return count
        except Exception as e:
            print(f"❌ Failed to cancel all orders: {e}")
            return 0
    
    async def get_open_orders(self, symbol: str) -> List[Order]:
        """查詢未成交訂單"""
        try:
            result = await self._request(
                'GET', '/api/query_open_orders',
                params={'symbol': symbol}
            )

            orders = []
            for order_data in result.get('result', []):
                orders.append(self._parse_order(order_data))

            return orders
        except Exception as e:
            print(f"❌ Failed to get open orders: {e}")
            return []

    async def get_trades(
        self,
        symbol: str,
        limit: int = 50,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None
    ) -> List[Trade]:
        """
        查詢成交歷史

        Args:
            symbol: 交易對 (如 'BTC-USD')
            limit: 返回記錄數量上限 (默認 50，最大 500)
            start_time: 開始時間戳 (毫秒)
            end_time: 結束時間戳 (毫秒)

        Returns:
            Trade 列表
        """
        try:
            params = {
                'symbol': symbol,
                'limit': min(limit, 500)
            }
            if start_time:
                params['start'] = start_time
            if end_time:
                params['end'] = end_time

            result = await self._request('GET', '/api/query_trades', params=params)

            trades = []
            for trade_data in result.get('result', []):
                trades.append(Trade(
                    trade_id=str(trade_data.get('id', '')),
                    order_id=str(trade_data.get('order_id', '')),
                    symbol=symbol,
                    side=trade_data.get('side', ''),
                    price=Decimal(str(trade_data.get('price', '0'))),
                    qty=Decimal(str(trade_data.get('qty', '0'))),
                    fee=Decimal(str(trade_data.get('fee_qty', '0'))),
                    realized_pnl=Decimal(str(trade_data.get('pnl', '0'))),
                    timestamp=trade_data.get('created_at'),
                ))

            return trades
        except Exception as e:
            logger.error(f"Failed to get trades: {e}")
            return []

    async def get_orderbook(
        self,
        symbol: str,
        depth: int = 20,
        limit: int = None,  # 兼容性參數
    ) -> Orderbook:
        """
        查詢訂單簿

        優先使用 WebSocket 緩存的數據，減少 REST API 調用
        """
        # 如果提供了 limit 參數，使用它而不是 depth
        if limit is not None:
            depth = limit

        # 優先使用 WebSocket 緩存（如果可用且有效）
        if self._ws_client and self._ws_client.is_connected:
            cached = self._ws_client.get_cached_orderbook(symbol, max_age_sec=5.0)
            if cached:
                bids = cached.get("bids", [])
                asks = cached.get("asks", [])
                if bids and asks:
                    return Orderbook(
                        symbol=symbol,
                        bids=[[Decimal(str(p)), Decimal(str(q))] for p, q in bids[:depth]],
                        asks=[[Decimal(str(p)), Decimal(str(q))] for p, q in asks[:depth]],
                        timestamp=datetime.fromtimestamp(cached.get("timestamp", time.time()))
                    )

        # Fallback 到 REST API
        try:
            result = await self._request(
                'GET', '/api/query_depth_book',
                params={'symbol': symbol, 'depth': depth}
            )

            return Orderbook(
                symbol=symbol,
                bids=[[Decimal(p), Decimal(q)] for p, q in result.get('bids', [])],
                asks=[[Decimal(p), Decimal(q)] for p, q in result.get('asks', [])],
                timestamp=datetime.fromtimestamp(result['timestamp'] / 1000) if result.get('timestamp') else datetime.now()
            )
        except Exception as e:
            print(f"❌ Failed to get orderbook: {e}")
            raise
    
    def _parse_order(self, data: Dict) -> Order:
        """Parse order data from API response."""
        return Order(
            order_id=str(data.get('id', '')),
            client_order_id=data.get('cl_ord_id'),
            symbol=data.get('symbol', ''),
            side=data.get('side', ''),
            order_type=data.get('order_type', ''),
            price=Decimal(str(data['price'])) if data.get('price') else None,
            qty=Decimal(str(data.get('qty', '0'))),
            filled_qty=Decimal(str(data.get('filled_qty', '0'))),
            status=data.get('status', 'unknown'),
            time_in_force=data.get('time_in_force', 'gtc'),
            reduce_only=data.get('reduce_only', False),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
        )

    # ==================== WebSocket 支援 ====================

    def on_fill(self, callback):
        """
        註冊成交回調

        Args:
            callback: async def callback(order_update: OrderUpdate)
        """
        self._fill_callbacks.append(callback)
        logger.info(f"[StandX WS] Registered fill callback: {callback.__name__}")

    def on_order_state(self, callback):
        """
        註冊訂單狀態回調

        Args:
            callback: async def callback(order_update: OrderUpdate)
        """
        self._order_state_callbacks.append(callback)
        logger.info(f"[StandX WS] Registered order state callback: {callback.__name__}")

    async def start_websocket(self, instruments: List[str] = None) -> bool:
        """
        啟動 WebSocket 連接

        Args:
            instruments: 要訂閱的交易對列表

        Returns:
            bool: 是否成功啟動
        """
        logger.info("=" * 60)
        logger.info("[StandX WS] ========== Starting WebSocket initialization ==========")
        logger.info(f"[StandX WS] Auth mode: {self._auth_mode}")
        logger.info(f"[StandX WS] Instruments: {instruments}")

        try:
            # 獲取認證 token
            auth_token = None
            if self._auth_mode == "token":
                auth_token = self.auth._api_token
                logger.info(f"[StandX WS] Using API token (length: {len(auth_token) if auth_token else 0})")
            elif self.auth.access_token:
                auth_token = self.auth.access_token
                logger.info(f"[StandX WS] Using access token (length: {len(auth_token)})")

            if not auth_token:
                logger.warning("[StandX WS] No auth token available, user channels will be disabled")

            # 創建 WebSocket 客戶端 (使用正確的官方 endpoint)
            # URL: wss://perps.standx.com/ws-stream/v1
            self._ws_client = StandXWebSocketClient(
                auth_token=auth_token,
                reconnect_delay=5,
                proxy_url=self.proxy_url,
                proxy_auth=self.proxy_auth,
            )
            logger.info(f"[StandX WS] WebSocket URL: {self._ws_client.ws_url}")
            if self.proxy_url:
                logger.info(f"[StandX WS] 使用代理: {self.proxy_url[:30]}...")

            # 註冊內部回調（轉發到外部回調）
            async def internal_fill_callback(order_update: OrderUpdate):
                """內部成交回調 - 轉發到外部"""
                logger.info(f"[StandX WS] Fill event: {order_update.side} {order_update.filled_qty} @ {order_update.avg_fill_price or order_update.price}")
                for callback in self._fill_callbacks:
                    try:
                        await callback(order_update)
                    except Exception as e:
                        logger.error(f"[StandX WS] Fill callback error: {e}")

            async def internal_order_callback(order_update: OrderUpdate):
                """內部訂單回調 - 轉發到外部"""
                logger.debug(f"[StandX WS] Order state: {order_update.client_order_id} -> {order_update.status}")
                for callback in self._order_state_callbacks:
                    try:
                        await callback(order_update)
                    except Exception as e:
                        logger.error(f"[StandX WS] Order state callback error: {e}")

            self._ws_client.on_fill(internal_fill_callback)
            self._ws_client.on_order(internal_order_callback)

            # 連接 WebSocket
            logger.info("[StandX WS] Connecting to WebSocket...")
            success = await self._ws_client.connect()

            if not success:
                logger.error("[StandX WS] Failed to connect WebSocket")
                return False

            logger.info(f"[StandX WS] Connected! Market: {self._ws_client.is_connected}, User: {self._ws_client.is_user_connected}")

            # 訂閱交易對
            if instruments:
                for symbol in instruments:
                    await self._ws_client.subscribe_symbol(symbol)
                    logger.info(f"[StandX WS] Subscribed to {symbol}")

            # 訂閱訂單和倉位更新
            if self._ws_client.is_user_connected:
                await self._ws_client.subscribe_orders()
                await self._ws_client.subscribe_positions()
                logger.info("[StandX WS] Subscribed to orders and positions")

            # 啟動消息處理循環
            self._ws_task = asyncio.create_task(self._ws_client.run())
            logger.info("[StandX WS] WebSocket message loop started")
            logger.info("=" * 60)

            return True

        except Exception as e:
            logger.error(f"[StandX WS] Failed to start WebSocket: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    async def stop_websocket(self):
        """停止 WebSocket 連接"""
        logger.info("[StandX WS] Stopping WebSocket...")

        try:
            if self._ws_task:
                self._ws_task.cancel()
                try:
                    await self._ws_task
                except asyncio.CancelledError:
                    pass
                self._ws_task = None

            if self._ws_client:
                await self._ws_client.disconnect()
                self._ws_client = None

            logger.info("[StandX WS] WebSocket stopped")

        except Exception as e:
            logger.error(f"[StandX WS] Error stopping WebSocket: {e}")

    @property
    def ws_connected(self) -> bool:
        """WebSocket 是否已連接"""
        if self._ws_client:
            # 市場數據連接成功即可使用 WebSocket 模式
            # 用戶頻道認證是可選的 (用於成交即時通知)
            return self._ws_client.is_connected
        return False

    def get_ws_stats(self) -> Dict:
        """獲取 WebSocket 統計"""
        if self._ws_client:
            return self._ws_client.get_stats()
        return {
            "connected": False,
            "authenticated": False,
            "message_count": 0,
            "subscribed_symbols": [],
            "ws_url": "wss://perps.standx.com/ws-stream/v1",
        }
