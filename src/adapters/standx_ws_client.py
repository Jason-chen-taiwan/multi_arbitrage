"""
StandX WebSocket 客戶端
StandX WebSocket Client for Real-time Order and Price Updates

基於 StandX 官方 WebSocket API 文檔:
https://docs.standx.com/standx-api/perps-ws

Endpoints:
- Market Stream: wss://perps.standx.com/ws-stream/v1
- Order Response Stream: wss://perps.standx.com/ws-api/v1
"""
import asyncio
import json
import logging
import time
from typing import Optional, Callable, Awaitable, List, Dict, Any
from decimal import Decimal
from dataclasses import dataclass
from datetime import datetime

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class PriceUpdate:
    """價格更新事件"""
    symbol: str
    mark_price: Decimal
    index_price: Decimal
    best_bid: Decimal
    best_ask: Decimal
    timestamp: datetime


@dataclass
class OrderUpdate:
    """訂單更新事件"""
    order_id: str
    client_order_id: str
    symbol: str
    side: str           # "buy" or "sell"
    order_type: str
    price: Decimal
    qty: Decimal
    filled_qty: Decimal
    remaining_qty: Decimal
    status: str         # "open", "filled", "cancelled", "rejected"
    avg_fill_price: Optional[Decimal]
    timestamp: datetime


@dataclass
class PositionUpdate:
    """倉位更新事件"""
    symbol: str
    size: Decimal       # 正數=多頭, 負數=空頭
    entry_price: Decimal
    mark_price: Decimal
    unrealized_pnl: Decimal
    timestamp: datetime


# 回調類型定義
PriceCallback = Callable[[PriceUpdate], Awaitable[None]]
OrderCallback = Callable[[OrderUpdate], Awaitable[None]]
PositionCallback = Callable[[PositionUpdate], Awaitable[None]]
FillCallback = Callable[[OrderUpdate], Awaitable[None]]


class StandXWebSocketClient:
    """
    StandX WebSocket 客戶端

    基於官方 API 文檔:
    - Market Stream: wss://perps.standx.com/ws-stream/v1
    - 支援公開頻道: price, depth_book, public_trade
    - 支援認證頻道: order, position, balance, trade
    """

    # 正確的 WebSocket endpoint
    WS_STREAM_URL = "wss://perps.standx.com/ws-stream/v1"

    def __init__(
        self,
        ws_url: str = None,  # 保持兼容性，但會被忽略
        auth_token: Optional[str] = None,
        reconnect_delay: int = 5,
    ):
        # 強制使用正確的 URL
        self.ws_url = self.WS_STREAM_URL
        self.auth_token = auth_token
        self.reconnect_delay = reconnect_delay

        # WebSocket 連接 (單一連接)
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None

        # 連接狀態
        self._connected = False
        self._authenticated = False
        self._running = False

        # 回調列表
        self._price_callbacks: List[PriceCallback] = []
        self._order_callbacks: List[OrderCallback] = []
        self._position_callbacks: List[PositionCallback] = []
        self._fill_callbacks: List[FillCallback] = []

        # 訂閱的符號
        self._subscribed_symbols: set = set()

        # 統計
        self._message_count = 0
        self._last_heartbeat = time.time()

    # ==================== 回調註冊 ====================

    def on_price(self, callback: PriceCallback):
        """註冊價格回調"""
        self._price_callbacks.append(callback)

    def on_order(self, callback: OrderCallback):
        """註冊訂單回調"""
        self._order_callbacks.append(callback)

    def on_position(self, callback: PositionCallback):
        """註冊倉位回調"""
        self._position_callbacks.append(callback)

    def on_fill(self, callback: FillCallback):
        """註冊成交回調 (訂單完全或部分成交)"""
        self._fill_callbacks.append(callback)

    # ==================== 連接管理 ====================

    async def connect(self) -> bool:
        """建立 WebSocket 連接"""
        try:
            logger.info(f"[StandX WS] Connecting to {self.ws_url}")

            self._session = aiohttp.ClientSession()

            # 連接到 Market Stream
            self._ws = await self._session.ws_connect(
                self.ws_url,
                heartbeat=10,  # StandX 每 10 秒發送 ping
                receive_timeout=300,  # 5 分鐘超時
            )

            self._connected = True
            logger.info(f"[StandX WS] Connected to Market Stream")

            # 如果有 auth token，進行認證並訂閱用戶頻道
            if self.auth_token:
                auth_success = await self._authenticate()
                if auth_success:
                    self._authenticated = True
                    logger.info("[StandX WS] Authenticated successfully")
                else:
                    logger.warning("[StandX WS] Authentication failed, user channels disabled")
            else:
                logger.warning("[StandX WS] No auth token, user channels disabled")

            self._running = True
            return True

        except Exception as e:
            logger.error(f"[StandX WS] Connection failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    async def _authenticate(self) -> bool:
        """
        認證並訂閱用戶頻道

        格式: { "auth": { "token": "<jwt>", "streams": [{ "channel": "order" }, ...] } }
        """
        try:
            auth_message = {
                "auth": {
                    "token": self.auth_token,
                    "streams": [
                        {"channel": "order"},
                        {"channel": "trade"},
                        {"channel": "position"},
                        {"channel": "balance"},
                    ]
                }
            }

            logger.info("[StandX WS] Sending auth message...")
            await self._ws.send_json(auth_message)

            # 等待認證響應 (可能需要一點時間)
            try:
                response = await asyncio.wait_for(
                    self._ws.receive(),
                    timeout=10
                )

                if response.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(response.data)
                    logger.info(f"[StandX WS] Auth response: {data}")

                    # 檢查是否認證成功
                    if data.get("code") == 0 or data.get("success") or "auth" in data:
                        return True
                    else:
                        logger.error(f"[StandX WS] Auth failed: {data}")
                        return False
                else:
                    logger.warning(f"[StandX WS] Unexpected response type: {response.type}")
                    return False

            except asyncio.TimeoutError:
                logger.warning("[StandX WS] Auth response timeout, assuming success")
                return True  # 某些情況下可能沒有明確的響應

        except Exception as e:
            logger.error(f"[StandX WS] Authentication error: {e}")
            return False

    async def disconnect(self):
        """斷開連接"""
        self._running = False
        self._connected = False
        self._authenticated = False

        if self._ws:
            await self._ws.close()
            self._ws = None

        if self._session:
            await self._session.close()
            self._session = None

        logger.info("[StandX WS] Disconnected")

    async def _reconnect(self):
        """重新連接"""
        logger.info(f"[StandX WS] Reconnecting in {self.reconnect_delay} seconds...")
        await asyncio.sleep(self.reconnect_delay)

        # 清理舊連接
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        # 重新連接
        await self.connect()

        # 重新訂閱
        for symbol in self._subscribed_symbols:
            await self.subscribe_symbol(symbol)

    # ==================== 訂閱管理 ====================

    async def subscribe_symbol(self, symbol: str):
        """
        訂閱符號的價格更新

        格式: { "subscribe": { "channel": "depth_book", "symbol": "BTC-USD" } }
        """
        if not self._connected or not self._ws:
            logger.warning("[StandX WS] Not connected, cannot subscribe")
            return

        # 訂閱 depth_book 頻道
        subscribe_message = {
            "subscribe": {
                "channel": "depth_book",
                "symbol": symbol
            }
        }

        await self._ws.send_json(subscribe_message)
        self._subscribed_symbols.add(symbol)
        logger.info(f"[StandX WS] Subscribed to depth_book for {symbol}")

        # 也訂閱 price 頻道
        price_message = {
            "subscribe": {
                "channel": "price",
                "symbol": symbol
            }
        }
        await self._ws.send_json(price_message)
        logger.info(f"[StandX WS] Subscribed to price for {symbol}")

    async def subscribe_orders(self):
        """訂閱訂單更新 (已在 auth 時訂閱)"""
        if not self._authenticated:
            logger.warning("[StandX WS] Not authenticated, cannot subscribe to orders")
            return
        logger.info("[StandX WS] Order channel already subscribed via auth")

    async def subscribe_positions(self):
        """訂閱倉位更新 (已在 auth 時訂閱)"""
        if not self._authenticated:
            logger.warning("[StandX WS] Not authenticated, cannot subscribe to positions")
            return
        logger.info("[StandX WS] Position channel already subscribed via auth")

    # ==================== 消息處理循環 ====================

    async def run(self):
        """運行消息處理循環"""
        while self._running:
            try:
                if not self._ws or self._ws.closed:
                    logger.warning("[StandX WS] Connection lost, reconnecting...")
                    await self._reconnect()
                    continue

                # 接收消息
                msg = await asyncio.wait_for(
                    self._ws.receive(),
                    timeout=60  # 1 分鐘超時
                )

                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._process_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.PING:
                    # 響應 ping
                    await self._ws.pong()
                    self._last_heartbeat = time.time()
                elif msg.type == aiohttp.WSMsgType.PONG:
                    self._last_heartbeat = time.time()
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"[StandX WS] WebSocket error: {msg.data}")
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logger.warning("[StandX WS] WebSocket closed")
                    break

            except asyncio.TimeoutError:
                # 超時，發送 ping 保持連接
                if self._ws and not self._ws.closed:
                    try:
                        await self._ws.ping()
                    except Exception:
                        pass
            except asyncio.CancelledError:
                logger.info("[StandX WS] Message loop cancelled")
                break
            except Exception as e:
                logger.error(f"[StandX WS] Message loop error: {e}")
                if self._running:
                    await self._reconnect()

        self._connected = False

    async def _process_message(self, data: str):
        """處理接收到的消息"""
        try:
            message = json.loads(data)
            self._message_count += 1

            # 識別消息類型
            channel = message.get("channel")

            if channel == "depth_book":
                await self._handle_depth_book(message)
            elif channel == "price":
                await self._handle_price(message)
            elif channel == "order":
                await self._handle_order(message)
            elif channel == "trade":
                await self._handle_trade(message)
            elif channel == "position":
                await self._handle_position(message)
            elif channel == "balance":
                await self._handle_balance(message)
            elif "ping" in message or message.get("type") == "ping":
                # 響應心跳
                await self._ws.send_json({"pong": message.get("ping", time.time())})
                self._last_heartbeat = time.time()
            else:
                # 其他消息 (可能是訂閱確認等)
                logger.debug(f"[StandX WS] Unknown message: {message}")

        except json.JSONDecodeError as e:
            logger.error(f"[StandX WS] JSON decode error: {e}, data: {data[:200]}")
        except Exception as e:
            logger.error(f"[StandX WS] Message processing error: {e}")

    async def _handle_depth_book(self, message: Dict):
        """處理深度數據"""
        try:
            data = message.get("data", message)
            symbol = data.get("symbol", "")

            bids = data.get("bids", [])
            asks = data.get("asks", [])

            if bids and asks:
                best_bid = Decimal(str(bids[0][0])) if bids else Decimal("0")
                best_ask = Decimal(str(asks[0][0])) if asks else Decimal("0")
                mid_price = (best_bid + best_ask) / 2

                price_update = PriceUpdate(
                    symbol=symbol,
                    mark_price=mid_price,
                    index_price=mid_price,
                    best_bid=best_bid,
                    best_ask=best_ask,
                    timestamp=datetime.now(),
                )

                for callback in self._price_callbacks:
                    try:
                        await callback(price_update)
                    except Exception as e:
                        logger.error(f"[StandX WS] Price callback error: {e}")

        except Exception as e:
            logger.error(f"[StandX WS] Depth book handler error: {e}")

    async def _handle_price(self, message: Dict):
        """處理價格更新"""
        try:
            data = message.get("data", message)
            symbol = data.get("symbol", "")

            price_update = PriceUpdate(
                symbol=symbol,
                mark_price=Decimal(str(data.get("mark_price", 0))),
                index_price=Decimal(str(data.get("index_price", 0))),
                best_bid=Decimal(str(data.get("best_bid", 0))),
                best_ask=Decimal(str(data.get("best_ask", 0))),
                timestamp=datetime.now(),
            )

            for callback in self._price_callbacks:
                try:
                    await callback(price_update)
                except Exception as e:
                    logger.error(f"[StandX WS] Price callback error: {e}")

        except Exception as e:
            logger.error(f"[StandX WS] Price handler error: {e}")

    async def _handle_order(self, message: Dict):
        """處理訂單更新"""
        try:
            data = message.get("data", message)

            order_update = OrderUpdate(
                order_id=str(data.get("id", data.get("order_id", ""))),
                client_order_id=data.get("cl_ord_id", data.get("client_order_id", "")),
                symbol=data.get("symbol", ""),
                side=data.get("side", ""),
                order_type=data.get("order_type", ""),
                price=Decimal(str(data.get("price", 0))),
                qty=Decimal(str(data.get("qty", 0))),
                filled_qty=Decimal(str(data.get("filled_qty", 0))),
                remaining_qty=Decimal(str(data.get("remaining_qty", data.get("qty", 0)))),
                status=data.get("status", ""),
                avg_fill_price=Decimal(str(data.get("fill_avg_price", 0))) if data.get("fill_avg_price") else None,
                timestamp=datetime.now(),
            )

            logger.info(f"[StandX WS] Order update: {order_update.order_id} {order_update.status} "
                       f"filled={order_update.filled_qty}/{order_update.qty}")

            # 觸發訂單回調
            for callback in self._order_callbacks:
                try:
                    await callback(order_update)
                except Exception as e:
                    logger.error(f"[StandX WS] Order callback error: {e}")

            # 如果有成交，觸發成交回調
            if order_update.status == "filled" or order_update.filled_qty > 0:
                for callback in self._fill_callbacks:
                    try:
                        await callback(order_update)
                    except Exception as e:
                        logger.error(f"[StandX WS] Fill callback error: {e}")

        except Exception as e:
            logger.error(f"[StandX WS] Order handler error: {e}")

    async def _handle_trade(self, message: Dict):
        """處理交易/成交更新"""
        try:
            data = message.get("data", message)

            # Trade 頻道通常是成交記錄
            order_update = OrderUpdate(
                order_id=str(data.get("order_id", "")),
                client_order_id=data.get("cl_ord_id", ""),
                symbol=data.get("symbol", ""),
                side=data.get("side", ""),
                order_type="",
                price=Decimal(str(data.get("price", 0))),
                qty=Decimal(str(data.get("qty", 0))),
                filled_qty=Decimal(str(data.get("qty", 0))),  # trade 就是成交
                remaining_qty=Decimal("0"),
                status="filled",
                avg_fill_price=Decimal(str(data.get("price", 0))),
                timestamp=datetime.now(),
            )

            logger.info(f"[StandX WS] Trade: {order_update.side} {order_update.filled_qty} @ {order_update.price}")

            # 觸發成交回調
            for callback in self._fill_callbacks:
                try:
                    await callback(order_update)
                except Exception as e:
                    logger.error(f"[StandX WS] Fill callback error: {e}")

        except Exception as e:
            logger.error(f"[StandX WS] Trade handler error: {e}")

    async def _handle_position(self, message: Dict):
        """處理倉位更新"""
        try:
            data = message.get("data", message)

            position_update = PositionUpdate(
                symbol=data.get("symbol", ""),
                size=Decimal(str(data.get("qty", data.get("size", 0)))),
                entry_price=Decimal(str(data.get("entry_price", 0))),
                mark_price=Decimal(str(data.get("mark_price", 0))),
                unrealized_pnl=Decimal(str(data.get("upnl", data.get("unrealized_pnl", 0)))),
                timestamp=datetime.now(),
            )

            for callback in self._position_callbacks:
                try:
                    await callback(position_update)
                except Exception as e:
                    logger.error(f"[StandX WS] Position callback error: {e}")

        except Exception as e:
            logger.error(f"[StandX WS] Position handler error: {e}")

    async def _handle_balance(self, message: Dict):
        """處理餘額更新"""
        # 目前只記錄，不觸發回調
        data = message.get("data", message)
        logger.debug(f"[StandX WS] Balance update: {data}")

    # ==================== 狀態查詢 ====================

    @property
    def is_connected(self) -> bool:
        """是否已連接"""
        return self._connected and self._ws is not None and not self._ws.closed

    @property
    def is_user_connected(self) -> bool:
        """用戶頻道是否已連接 (已認證)"""
        return self._authenticated

    @property
    def message_count(self) -> int:
        """消息計數"""
        return self._message_count

    def get_stats(self) -> Dict:
        """獲取統計"""
        return {
            "connected": self.is_connected,
            "authenticated": self._authenticated,
            "message_count": self._message_count,
            "subscribed_symbols": list(self._subscribed_symbols),
            "last_heartbeat": self._last_heartbeat,
            "ws_url": self.ws_url,
        }


class StandXWebSocketClientSimple:
    """
    簡化版 WebSocket 客戶端

    使用現有的 HTTP API 輪詢模擬，用於初期測試
    之後可替換為真正的 WebSocket 實現
    """

    def __init__(
        self,
        adapter,  # StandXAdapter
        poll_interval: float = 1.0,
    ):
        self.adapter = adapter
        self.poll_interval = poll_interval
        self._running = False

        # 回調
        self._price_callbacks: List[PriceCallback] = []
        self._order_callbacks: List[OrderCallback] = []
        self._fill_callbacks: List[FillCallback] = []

        # 狀態
        self._last_orders: Dict[str, str] = {}  # client_order_id -> status

    def on_price(self, callback: PriceCallback):
        """註冊價格回調"""
        self._price_callbacks.append(callback)

    def on_order(self, callback: OrderCallback):
        """註冊訂單回調"""
        self._order_callbacks.append(callback)

    def on_fill(self, callback: FillCallback):
        """註冊成交回調"""
        self._fill_callbacks.append(callback)

    async def start(self, symbol: str = "BTC-USD"):
        """開始輪詢"""
        self._running = True
        logger.info(f"Starting WebSocket polling for {symbol}")

        while self._running:
            try:
                # 獲取訂單簿 (價格)
                orderbook = await self.adapter.get_orderbook(symbol)
                if orderbook and orderbook.bids and orderbook.asks:
                    mid_price = (orderbook.bids[0][0] + orderbook.asks[0][0]) / 2
                    price_update = PriceUpdate(
                        symbol=symbol,
                        mark_price=mid_price,
                        index_price=mid_price,
                        best_bid=orderbook.bids[0][0],
                        best_ask=orderbook.asks[0][0],
                        timestamp=datetime.now(),
                    )

                    for callback in self._price_callbacks:
                        try:
                            await callback(price_update)
                        except Exception as e:
                            logger.error(f"Price callback error: {e}")

                # 獲取訂單狀態
                open_orders = await self.adapter.get_open_orders(symbol)
                for order in open_orders:
                    client_id = order.client_order_id
                    if client_id:
                        prev_status = self._last_orders.get(client_id)
                        current_status = order.status

                        # 狀態變更
                        if prev_status != current_status:
                            order_update = OrderUpdate(
                                order_id=order.order_id or "",
                                client_order_id=client_id,
                                symbol=symbol,
                                side=order.side,
                                order_type=order.order_type,
                                price=order.price or Decimal("0"),
                                qty=order.qty,
                                filled_qty=order.filled_qty,
                                remaining_qty=order.qty - order.filled_qty,
                                status=current_status,
                                avg_fill_price=None,
                                timestamp=datetime.now(),
                            )

                            for callback in self._order_callbacks:
                                try:
                                    await callback(order_update)
                                except Exception as e:
                                    logger.error(f"Order callback error: {e}")

                            # 成交回調
                            if current_status == "filled" or order.filled_qty > 0:
                                for callback in self._fill_callbacks:
                                    try:
                                        await callback(order_update)
                                    except Exception as e:
                                        logger.error(f"Fill callback error: {e}")

                        self._last_orders[client_id] = current_status

                await asyncio.sleep(self.poll_interval)

            except Exception as e:
                logger.error(f"Polling error: {e}")
                await asyncio.sleep(self.poll_interval)

    async def stop(self):
        """停止輪詢"""
        self._running = False
        logger.info("WebSocket polling stopped")
