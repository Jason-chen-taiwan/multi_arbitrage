"""
StandX WebSocket 客戶端
StandX WebSocket Client for Real-time Order and Price Updates

參考 frozen-cherry/standx-mm 的 ws_client.py 設計
- 雙 WebSocket 連接 (市場數據 + 用戶數據)
- 自動重連機制
- 事件回調系統
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

    實現:
    - 市場數據 WebSocket (價格推送)
    - 用戶數據 WebSocket (訂單/倉位更新)
    - 自動重連 (5秒延遲)
    - 心跳維持
    """

    def __init__(
        self,
        ws_url: str = "wss://perps.standx.com/ws",
        auth_token: Optional[str] = None,
        reconnect_delay: int = 5,
    ):
        self.ws_url = ws_url
        self.auth_token = auth_token
        self.reconnect_delay = reconnect_delay

        # WebSocket 連接
        self._market_ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._user_ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None

        # 連接狀態
        self._market_connected = False
        self._user_connected = False
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
            self._session = aiohttp.ClientSession()

            # 連接市場數據 WebSocket
            market_success = await self._connect_market_ws()

            # 連接用戶數據 WebSocket (需要認證)
            if self.auth_token:
                user_success = await self._connect_user_ws()
            else:
                user_success = True  # 沒有 token 則跳過用戶 WS
                logger.warning("No auth token provided, user WebSocket disabled")

            self._running = market_success
            return market_success and user_success

        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            return False

    async def _connect_market_ws(self) -> bool:
        """連接市場數據 WebSocket"""
        try:
            # StandX 市場 WebSocket URL
            market_url = f"{self.ws_url}/market"

            self._market_ws = await self._session.ws_connect(
                market_url,
                heartbeat=30,
                receive_timeout=60,
            )

            self._market_connected = True
            logger.info(f"Market WebSocket connected: {market_url}")
            return True

        except Exception as e:
            logger.error(f"Market WebSocket connection failed: {e}")
            self._market_connected = False
            return False

    async def _connect_user_ws(self) -> bool:
        """連接用戶數據 WebSocket (需要認證)"""
        try:
            # StandX 用戶 WebSocket URL
            user_url = f"{self.ws_url}/user"

            self._user_ws = await self._session.ws_connect(
                user_url,
                heartbeat=30,
                receive_timeout=60,
            )

            # 發送認證消息
            auth_message = {
                "type": "auth",
                "token": self.auth_token
            }
            await self._user_ws.send_json(auth_message)

            # 等待認證響應
            response = await asyncio.wait_for(
                self._user_ws.receive_json(),
                timeout=10
            )

            if response.get("type") == "auth_success":
                self._user_connected = True
                logger.info("User WebSocket authenticated")
                return True
            else:
                logger.error(f"User WebSocket auth failed: {response}")
                return False

        except Exception as e:
            logger.error(f"User WebSocket connection failed: {e}")
            self._user_connected = False
            return False

    async def disconnect(self):
        """斷開連接"""
        self._running = False

        if self._market_ws:
            await self._market_ws.close()
            self._market_ws = None
            self._market_connected = False

        if self._user_ws:
            await self._user_ws.close()
            self._user_ws = None
            self._user_connected = False

        if self._session:
            await self._session.close()
            self._session = None

        logger.info("WebSocket disconnected")

    async def _reconnect(self):
        """重新連接"""
        logger.info(f"Reconnecting in {self.reconnect_delay} seconds...")
        await asyncio.sleep(self.reconnect_delay)
        await self.connect()

    # ==================== 訂閱管理 ====================

    async def subscribe_symbol(self, symbol: str):
        """訂閱符號的價格更新"""
        if not self._market_connected or not self._market_ws:
            logger.warning("Market WebSocket not connected")
            return

        subscribe_message = {
            "type": "subscribe",
            "channel": "ticker",
            "symbol": symbol
        }

        await self._market_ws.send_json(subscribe_message)
        self._subscribed_symbols.add(symbol)
        logger.info(f"Subscribed to {symbol} price updates")

    async def subscribe_orders(self):
        """訂閱訂單更新"""
        if not self._user_connected or not self._user_ws:
            logger.warning("User WebSocket not connected")
            return

        subscribe_message = {
            "type": "subscribe",
            "channel": "orders"
        }

        await self._user_ws.send_json(subscribe_message)
        logger.info("Subscribed to order updates")

    async def subscribe_positions(self):
        """訂閱倉位更新"""
        if not self._user_connected or not self._user_ws:
            logger.warning("User WebSocket not connected")
            return

        subscribe_message = {
            "type": "subscribe",
            "channel": "positions"
        }

        await self._user_ws.send_json(subscribe_message)
        logger.info("Subscribed to position updates")

    # ==================== 消息處理循環 ====================

    async def run(self):
        """運行消息處理循環"""
        while self._running:
            try:
                # 並行處理兩個 WebSocket
                tasks = []

                if self._market_ws and self._market_connected:
                    tasks.append(self._handle_market_messages())

                if self._user_ws and self._user_connected:
                    tasks.append(self._handle_user_messages())

                if tasks:
                    await asyncio.gather(*tasks)
                else:
                    # 沒有連接，嘗試重連
                    await self._reconnect()

            except Exception as e:
                logger.error(f"WebSocket run loop error: {e}")
                if self._running:
                    await self._reconnect()

    async def _handle_market_messages(self):
        """處理市場數據消息"""
        try:
            async for msg in self._market_ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._process_market_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"Market WS error: {msg.data}")
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logger.warning("Market WS closed")
                    break

        except Exception as e:
            logger.error(f"Market message handler error: {e}")

        self._market_connected = False

    async def _handle_user_messages(self):
        """處理用戶數據消息"""
        try:
            async for msg in self._user_ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._process_user_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"User WS error: {msg.data}")
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logger.warning("User WS closed")
                    break

        except Exception as e:
            logger.error(f"User message handler error: {e}")

        self._user_connected = False

    async def _process_market_message(self, data: str):
        """處理市場數據消息"""
        try:
            message = json.loads(data)
            self._message_count += 1

            msg_type = message.get("type")

            if msg_type == "ticker":
                # 價格更新
                price_update = PriceUpdate(
                    symbol=message.get("symbol", ""),
                    mark_price=Decimal(str(message.get("mark_price", 0))),
                    index_price=Decimal(str(message.get("index_price", 0))),
                    best_bid=Decimal(str(message.get("best_bid", 0))),
                    best_ask=Decimal(str(message.get("best_ask", 0))),
                    timestamp=datetime.now(),
                )

                # 觸發回調
                for callback in self._price_callbacks:
                    try:
                        await callback(price_update)
                    except Exception as e:
                        logger.error(f"Price callback error: {e}")

            elif msg_type == "ping":
                # 響應心跳
                await self._market_ws.send_json({"type": "pong"})
                self._last_heartbeat = time.time()

        except Exception as e:
            logger.error(f"Market message parse error: {e}")

    async def _process_user_message(self, data: str):
        """處理用戶數據消息"""
        try:
            message = json.loads(data)
            self._message_count += 1

            msg_type = message.get("type")

            if msg_type == "order_update":
                # 訂單更新
                order_update = self._parse_order_update(message)

                # 觸發訂單回調
                for callback in self._order_callbacks:
                    try:
                        await callback(order_update)
                    except Exception as e:
                        logger.error(f"Order callback error: {e}")

                # 如果是成交，觸發成交回調
                if order_update.status == "filled" or order_update.filled_qty > 0:
                    for callback in self._fill_callbacks:
                        try:
                            await callback(order_update)
                        except Exception as e:
                            logger.error(f"Fill callback error: {e}")

            elif msg_type == "position_update":
                # 倉位更新
                position_update = PositionUpdate(
                    symbol=message.get("symbol", ""),
                    size=Decimal(str(message.get("size", 0))),
                    entry_price=Decimal(str(message.get("entry_price", 0))),
                    mark_price=Decimal(str(message.get("mark_price", 0))),
                    unrealized_pnl=Decimal(str(message.get("upnl", 0))),
                    timestamp=datetime.now(),
                )

                for callback in self._position_callbacks:
                    try:
                        await callback(position_update)
                    except Exception as e:
                        logger.error(f"Position callback error: {e}")

            elif msg_type == "ping":
                await self._user_ws.send_json({"type": "pong"})
                self._last_heartbeat = time.time()

        except Exception as e:
            logger.error(f"User message parse error: {e}")

    def _parse_order_update(self, message: Dict[str, Any]) -> OrderUpdate:
        """解析訂單更新消息"""
        return OrderUpdate(
            order_id=str(message.get("order_id", "")),
            client_order_id=message.get("cl_ord_id", ""),
            symbol=message.get("symbol", ""),
            side=message.get("side", ""),
            order_type=message.get("order_type", ""),
            price=Decimal(str(message.get("price", 0))),
            qty=Decimal(str(message.get("qty", 0))),
            filled_qty=Decimal(str(message.get("filled_qty", 0))),
            remaining_qty=Decimal(str(message.get("remaining_qty", 0))),
            status=message.get("status", ""),
            avg_fill_price=Decimal(str(message.get("avg_price", 0))) if message.get("avg_price") else None,
            timestamp=datetime.now(),
        )

    # ==================== 狀態查詢 ====================

    @property
    def is_connected(self) -> bool:
        """是否已連接"""
        return self._market_connected

    @property
    def is_user_connected(self) -> bool:
        """用戶 WebSocket 是否已連接"""
        return self._user_connected

    @property
    def message_count(self) -> int:
        """消息計數"""
        return self._message_count

    def get_stats(self) -> Dict:
        """獲取統計"""
        return {
            "market_connected": self._market_connected,
            "user_connected": self._user_connected,
            "message_count": self._message_count,
            "subscribed_symbols": list(self._subscribed_symbols),
            "last_heartbeat": self._last_heartbeat,
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
