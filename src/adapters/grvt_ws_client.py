"""
GRVT WebSocket Client for Real-time Order and Fill Updates

GRVT WebSocket API:
- Uses JSON-RPC 2.0 format
- v1.fill stream for fill events
- v1.state stream for order state updates
- v1.position stream for position updates

Reference: https://api-docs.grvt.io/
"""
import asyncio
import json
import logging
import time
from typing import Optional, Callable, Awaitable, List, Dict, Any
from decimal import Decimal
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

import aiohttp

logger = logging.getLogger(__name__)


class GRVTFillType(Enum):
    """GRVT Fill Type"""
    FILL = "FILL"
    PARTIAL_FILL = "PARTIAL_FILL"
    LIQUIDATION = "LIQUIDATION"


@dataclass
class GRVTFillEvent:
    """GRVT Fill Event from WebSocket"""
    fill_id: str
    order_id: str
    client_order_id: Optional[str]
    sub_account_id: str
    instrument: str  # e.g., "BTC_USDT_Perp"
    is_buyer: bool
    is_taker: bool  # True = taker, False = maker
    size: Decimal
    price: Decimal
    realized_pnl: Decimal
    fee: Decimal  # Positive = paid, Negative = rebate
    fee_currency: str
    trade_id: str
    timestamp_ns: int
    timestamp: datetime

    @property
    def is_maker(self) -> bool:
        """Whether this fill was a maker order"""
        return not self.is_taker

    @property
    def side(self) -> str:
        """Order side (buy/sell)"""
        return "buy" if self.is_buyer else "sell"

    @property
    def notional(self) -> Decimal:
        """Notional value of the fill"""
        return self.size * self.price


@dataclass
class GRVTOrderStateEvent:
    """GRVT Order State Event from WebSocket"""
    order_id: str
    client_order_id: Optional[str]
    sub_account_id: str
    instrument: str
    is_buying: bool
    size: Decimal
    limit_price: Decimal
    filled_size: Decimal
    remaining_size: Decimal
    state: str  # "PENDING", "OPEN", "FILLED", "REJECTED", "CANCELLED"
    reject_reason: Optional[str]
    timestamp_ns: int
    timestamp: datetime

    @property
    def side(self) -> str:
        return "buy" if self.is_buying else "sell"

    @property
    def is_filled(self) -> bool:
        return self.state == "FILLED"

    @property
    def is_cancelled(self) -> bool:
        return self.state == "CANCELLED"


@dataclass
class GRVTPositionEvent:
    """GRVT Position Event from WebSocket"""
    sub_account_id: str
    instrument: str
    size: Decimal  # Positive = long, Negative = short
    notional: Decimal
    entry_price: Decimal
    exit_price: Decimal
    mark_price: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    total_pnl: Decimal
    roi: Decimal
    timestamp: datetime


# Callback type definitions
FillCallback = Callable[[GRVTFillEvent], Awaitable[None]]
OrderStateCallback = Callable[[GRVTOrderStateEvent], Awaitable[None]]
PositionCallback = Callable[[GRVTPositionEvent], Awaitable[None]]
ErrorCallback = Callable[[str, Any], Awaitable[None]]


class GRVTWebSocketClient:
    """
    GRVT WebSocket Client

    Features:
    - Subscribe to fill events (v1.fill)
    - Subscribe to order state events (v1.state)
    - Subscribe to position events (v1.position)
    - Auto reconnect with exponential backoff
    - Heartbeat/ping-pong handling
    """

    # WebSocket URLs
    WS_URL_MAINNET = "wss://market-data.grvt.io/ws"
    WS_URL_TESTNET = "wss://market-data.testnet.grvt.io/ws"
    WS_URL_PRIVATE_MAINNET = "wss://trades.grvt.io/ws/full"
    WS_URL_PRIVATE_TESTNET = "wss://trades.testnet.grvt.io/ws/full"

    def __init__(
        self,
        api_key: str,
        trading_account_id: str,
        testnet: bool = False,
        reconnect_delay: int = 5,
        max_reconnect_delay: int = 60,
    ):
        """
        Initialize GRVT WebSocket Client

        Args:
            api_key: GRVT API key (used as cookie for auth)
            trading_account_id: Sub account ID for subscriptions
            testnet: Use testnet endpoints
            reconnect_delay: Initial reconnect delay in seconds
            max_reconnect_delay: Maximum reconnect delay
        """
        self.api_key = api_key
        self.trading_account_id = trading_account_id
        self.testnet = testnet
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay

        # WebSocket URLs
        self.ws_url = self.WS_URL_PRIVATE_TESTNET if testnet else self.WS_URL_PRIVATE_MAINNET

        # WebSocket connection
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None

        # Connection state
        self._connected = False
        self._running = False
        self._reconnect_count = 0
        self._current_reconnect_delay = reconnect_delay

        # Message ID counter for JSON-RPC
        self._msg_id = 0

        # Callbacks
        self._fill_callbacks: List[FillCallback] = []
        self._order_state_callbacks: List[OrderStateCallback] = []
        self._position_callbacks: List[PositionCallback] = []
        self._error_callbacks: List[ErrorCallback] = []

        # Subscriptions
        self._subscribed_instruments: set = set()
        self._subscribed_streams: set = set()

        # Statistics
        self._message_count = 0
        self._fill_count = 0
        self._last_message_time = time.time()
        self._connect_time: Optional[float] = None

    # ==================== Callback Registration ====================

    def on_fill(self, callback: FillCallback):
        """Register fill event callback"""
        self._fill_callbacks.append(callback)
        return self

    def on_order_state(self, callback: OrderStateCallback):
        """Register order state event callback"""
        self._order_state_callbacks.append(callback)
        return self

    def on_position(self, callback: PositionCallback):
        """Register position event callback"""
        self._position_callbacks.append(callback)
        return self

    def on_error(self, callback: ErrorCallback):
        """Register error callback"""
        self._error_callbacks.append(callback)
        return self

    # ==================== Connection Management ====================

    async def connect(self) -> bool:
        """
        Establish WebSocket connection

        Returns:
            True if connection successful
        """
        try:
            if self._session is None:
                self._session = aiohttp.ClientSession()

            # Build headers with authentication
            headers = {
                "Cookie": f"gravity={self.api_key}",
                "X-Grvt-Account-Id": self.trading_account_id,
            }

            logger.info(f"[WS Connect] URL: {self.ws_url}")
            logger.info(f"[WS Connect] Account ID: {self.trading_account_id}")
            logger.info(f"[WS Connect] Cookie length: {len(self.api_key) if self.api_key else 0}")

            self._ws = await self._session.ws_connect(
                self.ws_url,
                headers=headers,
                heartbeat=30,
                receive_timeout=60,
            )

            # Check if connection was accepted
            if self._ws.closed:
                logger.error(f"[WS Connect] WebSocket closed immediately, code={self._ws.close_code}")
                return False

            self._connected = True
            self._connect_time = time.time()
            self._reconnect_count = 0
            self._current_reconnect_delay = self.reconnect_delay

            logger.info(f"[WS Connect] Connected successfully ({'testnet' if self.testnet else 'mainnet'})")

            # Re-subscribe to previous streams if reconnecting
            if self._subscribed_streams:
                await self._resubscribe()

            return True

        except aiohttp.WSServerHandshakeError as e:
            logger.error(f"[WS Connect] Handshake failed (likely auth error): status={e.status}, message={e.message}")
            self._connected = False
            return False
        except aiohttp.ClientConnectorError as e:
            logger.error(f"[WS Connect] Connection error: {e}")
            self._connected = False
            return False
        except Exception as e:
            logger.error(f"[WS Connect] Unexpected error: {type(e).__name__}: {e}")
            self._connected = False
            return False

    async def disconnect(self):
        """Disconnect WebSocket"""
        self._running = False
        self._connected = False

        if self._ws:
            await self._ws.close()
            self._ws = None

        if self._session:
            await self._session.close()
            self._session = None

        logger.info("GRVT WebSocket disconnected")

    async def _reconnect(self):
        """Reconnect with exponential backoff"""
        self._connected = False
        self._reconnect_count += 1

        # Calculate delay with exponential backoff
        delay = min(
            self._current_reconnect_delay * (2 ** min(self._reconnect_count - 1, 5)),
            self.max_reconnect_delay
        )

        logger.info(f"GRVT WebSocket reconnecting in {delay}s (attempt {self._reconnect_count})...")
        await asyncio.sleep(delay)

        success = await self.connect()
        if not success and self._running:
            # Schedule another reconnect
            asyncio.create_task(self._reconnect())

    async def _resubscribe(self):
        """Re-subscribe to streams after reconnect"""
        logger.info(f"Re-subscribing to {len(self._subscribed_streams)} streams...")

        for stream_info in list(self._subscribed_streams):
            stream, instrument = stream_info
            try:
                await self._send_subscribe(stream, instrument)
            except Exception as e:
                logger.error(f"Re-subscribe failed for {stream}/{instrument}: {e}")

    # ==================== Subscription Management ====================

    async def subscribe_fills(self, instrument: str = "BTC_USDT_Perp"):
        """
        Subscribe to fill events for an instrument

        Args:
            instrument: Trading pair (e.g., "BTC_USDT_Perp")
        """
        await self._send_subscribe("v1.fill", instrument)
        self._subscribed_streams.add(("v1.fill", instrument))
        self._subscribed_instruments.add(instrument)
        logger.info(f"Subscribed to GRVT fills: {instrument}")

    async def subscribe_order_states(self, instrument: str = "BTC_USDT_Perp"):
        """
        Subscribe to order state events for an instrument

        Args:
            instrument: Trading pair (e.g., "BTC_USDT_Perp")
        """
        await self._send_subscribe("v1.state", instrument)
        self._subscribed_streams.add(("v1.state", instrument))
        self._subscribed_instruments.add(instrument)
        logger.info(f"Subscribed to GRVT order states: {instrument}")

    async def subscribe_positions(self, instrument: str = "BTC_USDT_Perp"):
        """
        Subscribe to position events for an instrument

        Args:
            instrument: Trading pair (e.g., "BTC_USDT_Perp")
        """
        await self._send_subscribe("v1.position", instrument)
        self._subscribed_streams.add(("v1.position", instrument))
        self._subscribed_instruments.add(instrument)
        logger.info(f"Subscribed to GRVT positions: {instrument}")

    async def _send_subscribe(self, stream: str, instrument: str):
        """Send subscription request"""
        if not self._connected or not self._ws:
            raise Exception("WebSocket not connected")

        self._msg_id += 1

        # Build selector: "subAccountId-instrument"
        selector = f"{self.trading_account_id}-{instrument}"

        message = {
            "jsonrpc": "2.0",
            "method": "subscribe",
            "params": {
                "stream": stream,
                "selectors": [selector]
            },
            "id": self._msg_id
        }

        await self._ws.send_json(message)
        logger.debug(f"Sent subscribe: {stream} selector={selector}")

    async def unsubscribe(self, stream: str, instrument: str):
        """Unsubscribe from a stream"""
        if not self._connected or not self._ws:
            return

        self._msg_id += 1
        selector = f"{self.trading_account_id}-{instrument}"

        message = {
            "jsonrpc": "2.0",
            "method": "unsubscribe",
            "params": {
                "stream": stream,
                "selectors": [selector]
            },
            "id": self._msg_id
        }

        await self._ws.send_json(message)
        self._subscribed_streams.discard((stream, instrument))
        logger.info(f"Unsubscribed from GRVT {stream}: {instrument}")

    # ==================== Message Processing Loop ====================

    async def run(self):
        """Run message processing loop"""
        self._running = True

        while self._running:
            try:
                if not self._connected:
                    success = await self.connect()
                    if not success:
                        await asyncio.sleep(self._current_reconnect_delay)
                        continue

                await self._process_messages()

            except Exception as e:
                logger.error(f"GRVT WebSocket run loop error: {e}")
                if self._running:
                    await self._reconnect()

    async def _process_messages(self):
        """Process incoming WebSocket messages"""
        try:
            async for msg in self._ws:
                if not self._running:
                    break

                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"GRVT WebSocket error: {msg.data}")
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logger.warning("GRVT WebSocket closed")
                    break
                elif msg.type == aiohttp.WSMsgType.PING:
                    await self._ws.pong()

        except asyncio.CancelledError:
            logger.info("GRVT WebSocket message loop cancelled")
        except Exception as e:
            logger.error(f"GRVT WebSocket message processing error: {e}")

        self._connected = False

    async def _handle_message(self, data: str):
        """Handle incoming message"""
        try:
            message = json.loads(data)
            self._message_count += 1
            self._last_message_time = time.time()

            # Check for JSON-RPC response (subscription confirmation)
            if "id" in message and "result" in message:
                logger.debug(f"GRVT subscription confirmed: {message}")
                return

            # Check for JSON-RPC error
            if "error" in message:
                error = message["error"]
                logger.error(f"GRVT WebSocket error: {error}")
                for callback in self._error_callbacks:
                    try:
                        await callback("rpc_error", error)
                    except Exception as e:
                        logger.error(f"Error callback failed: {e}")
                return

            # Handle stream data
            if "params" in message:
                params = message["params"]
                stream = params.get("stream", "")
                feed = params.get("feed", {})

                if stream == "v1.fill":
                    await self._handle_fill(feed)
                elif stream == "v1.state":
                    await self._handle_order_state(feed)
                elif stream == "v1.position":
                    await self._handle_position(feed)
                else:
                    logger.debug(f"Unknown stream: {stream}")

        except json.JSONDecodeError as e:
            logger.error(f"GRVT WebSocket JSON parse error: {e}")
        except Exception as e:
            logger.error(f"GRVT WebSocket message handler error: {e}")

    async def _handle_fill(self, data: Dict[str, Any]):
        """Handle fill event"""
        try:
            # Parse fill data
            # GRVT fill format based on API docs
            timestamp_ns = int(data.get("event_time", 0))

            fill_event = GRVTFillEvent(
                fill_id=data.get("fill_id", ""),
                order_id=data.get("order_id", ""),
                client_order_id=data.get("client_order_id"),
                sub_account_id=data.get("sub_account_id", ""),
                instrument=data.get("instrument", ""),
                is_buyer=data.get("is_buyer", False),
                is_taker=data.get("is_taker", True),  # Default to taker if not specified
                size=Decimal(str(data.get("fill_qty", "0"))),
                price=Decimal(str(data.get("fill_price", "0"))),
                realized_pnl=Decimal(str(data.get("realized_pnl", "0"))),
                fee=Decimal(str(data.get("fee", "0"))),
                fee_currency=data.get("fee_currency", "USDT"),
                trade_id=data.get("trade_id", ""),
                timestamp_ns=timestamp_ns,
                timestamp=datetime.fromtimestamp(timestamp_ns / 1_000_000_000) if timestamp_ns else datetime.now(),
            )

            self._fill_count += 1
            logger.info(
                f"[GRVT WS Fill] {fill_event.side} {fill_event.size} @ {fill_event.price} "
                f"(maker={fill_event.is_maker}, fee={fill_event.fee})"
            )

            # Trigger callbacks
            for callback in self._fill_callbacks:
                try:
                    await callback(fill_event)
                except Exception as e:
                    logger.error(f"Fill callback error: {e}")

        except Exception as e:
            logger.error(f"Error handling fill event: {e}, data={data}")

    async def _handle_order_state(self, data: Dict[str, Any]):
        """Handle order state event"""
        try:
            # Parse order state data
            timestamp_ns = int(data.get("update_time", 0))

            # Extract leg info (GRVT orders have legs)
            legs = data.get("legs", [])
            leg = legs[0] if legs else {}

            order_event = GRVTOrderStateEvent(
                order_id=data.get("order_id", ""),
                client_order_id=data.get("metadata", {}).get("client_order_id"),
                sub_account_id=data.get("sub_account_id", ""),
                instrument=leg.get("instrument", ""),
                is_buying=leg.get("is_buying_asset", False),
                size=Decimal(str(leg.get("size", "0"))),
                limit_price=Decimal(str(leg.get("limit_price", "0"))),
                filled_size=Decimal(str(data.get("filled_size", "0"))),
                remaining_size=Decimal(str(data.get("remaining_size", "0"))),
                state=data.get("state", "UNKNOWN"),
                reject_reason=data.get("reject_reason"),
                timestamp_ns=timestamp_ns,
                timestamp=datetime.fromtimestamp(timestamp_ns / 1_000_000_000) if timestamp_ns else datetime.now(),
            )

            logger.debug(
                f"[GRVT WS Order] {order_event.order_id} {order_event.state} "
                f"filled={order_event.filled_size}/{order_event.size}"
            )

            # Trigger callbacks
            for callback in self._order_state_callbacks:
                try:
                    await callback(order_event)
                except Exception as e:
                    logger.error(f"Order state callback error: {e}")

        except Exception as e:
            logger.error(f"Error handling order state event: {e}, data={data}")

    async def _handle_position(self, data: Dict[str, Any]):
        """Handle position event"""
        try:
            position_event = GRVTPositionEvent(
                sub_account_id=data.get("sub_account_id", ""),
                instrument=data.get("instrument", ""),
                size=Decimal(str(data.get("balance", "0"))),
                notional=Decimal(str(data.get("notional", "0"))),
                entry_price=Decimal(str(data.get("entry_price", "0"))),
                exit_price=Decimal(str(data.get("exit_price", "0"))),
                mark_price=Decimal(str(data.get("mark_price", "0"))),
                unrealized_pnl=Decimal(str(data.get("unrealized_pnl", "0"))),
                realized_pnl=Decimal(str(data.get("realized_pnl", "0"))),
                total_pnl=Decimal(str(data.get("total_pnl", "0"))),
                roi=Decimal(str(data.get("roi", "0"))),
                timestamp=datetime.now(),
            )

            logger.debug(
                f"[GRVT WS Position] {position_event.instrument} "
                f"size={position_event.size} entry={position_event.entry_price}"
            )

            # Trigger callbacks
            for callback in self._position_callbacks:
                try:
                    await callback(position_event)
                except Exception as e:
                    logger.error(f"Position callback error: {e}")

        except Exception as e:
            logger.error(f"Error handling position event: {e}, data={data}")

    # ==================== Status ====================

    @property
    def is_connected(self) -> bool:
        """Whether WebSocket is connected"""
        return self._connected

    @property
    def is_running(self) -> bool:
        """Whether the client is running"""
        return self._running

    def get_stats(self) -> Dict[str, Any]:
        """Get client statistics"""
        return {
            "connected": self._connected,
            "running": self._running,
            "testnet": self.testnet,
            "message_count": self._message_count,
            "fill_count": self._fill_count,
            "reconnect_count": self._reconnect_count,
            "subscribed_instruments": list(self._subscribed_instruments),
            "subscribed_streams": [(s, i) for s, i in self._subscribed_streams],
            "last_message_time": self._last_message_time,
            "uptime_seconds": time.time() - self._connect_time if self._connect_time else 0,
        }
