"""
StandX Exchange Connector

Implements the BaseExchange interface for StandX Perps API.
"""

import json
import time
import asyncio
from typing import Dict, List, Optional
from decimal import Decimal
from uuid import uuid4

import aiohttp
from eth_account import Account

from .base import (
    BaseExchange, OrderBook, Order, Position, Balance, Trade,
    OrderSide, OrderType, TimeInForce, OrderStatus
)
from ..auth import AsyncStandXAuth


class StandXExchange(BaseExchange):
    """
    StandX Perps Exchange Connector.
    
    Provides full trading functionality for StandX perpetual contracts.
    """
    
    def __init__(self, config: Dict):
        """
        Initialize StandX connector.
        
        Args:
            config: Configuration dictionary with keys:
                - chain: Blockchain network ('bsc' or 'solana')
                - wallet_private_key: Wallet private key
                - base_url: API base URL (default: https://api.standx.com)
                - perps_url: Perps API URL (default: https://perps.standx.com)
        """
        super().__init__(config)
        
        self.chain = config.get('chain', 'bsc')
        self.base_url = config.get('base_url', 'https://api.standx.com')
        self.perps_url = config.get('perps_url', 'https://perps.standx.com')
        
        # Initialize wallet
        private_key = config.get('wallet_private_key')
        if not private_key:
            raise ValueError("wallet_private_key is required")
        
        self.account = Account.from_key(private_key)
        self.wallet_address = self.account.address
        
        # Initialize auth manager
        self.auth = AsyncStandXAuth(base_url=self.base_url)
        
        # Session management
        self.session: Optional[aiohttp.ClientSession] = None
        self.session_id = str(uuid4())
        
        # Cache
        self._symbol_info_cache: Dict[str, Dict] = {}
    
    async def connect(self) -> bool:
        """Establish connection and authenticate."""
        try:
            # Create HTTP session
            self.session = aiohttp.ClientSession()
            
            # Authenticate with wallet signature
            async def sign_message(message: str) -> str:
                """Sign message with wallet."""
                signed_message = self.account.sign_message(
                    Account.encode_defunct(text=message)
                )
                return signed_message.signature.hex()
            
            # Perform authentication
            login_response = await self.auth.authenticate(
                chain=self.chain,
                wallet_address=self.wallet_address,
                sign_message_fn=sign_message
            )
            
            print(f"✅ Connected to StandX as {login_response.get('alias', 'Unknown')}")
            return True
            
        except Exception as e:
            print(f"❌ Failed to connect: {e}")
            return False
    
    async def disconnect(self) -> bool:
        """Close connection."""
        try:
            if self.session:
                await self.session.close()
                self.session = None
            return True
        except Exception as e:
            print(f"❌ Failed to disconnect: {e}")
            return False
    
    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        sign_body: bool = False
    ) -> Dict:
        """
        Make authenticated API request.
        
        Args:
            method: HTTP method
            endpoint: API endpoint
            params: Query parameters
            data: Request body
            sign_body: Whether to sign request body
            
        Returns:
            Response JSON
        """
        if not self.session:
            raise Exception("Not connected. Call connect() first.")
        
        url = f"{self.perps_url}{endpoint}"
        
        # Prepare headers
        payload_str = json.dumps(data) if data else None
        headers = self.auth.get_auth_headers(
            payload=payload_str if sign_body else None
        )
        
        # Add session ID for order operations
        if '/order' in endpoint:
            headers['x-session-id'] = self.session_id
        
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
    
    async def get_orderbook(self, symbol: str) -> OrderBook:
        """Get current order book."""
        result = await self._request('GET', '/api/query_depth_book', params={'symbol': symbol})
        
        bids = [(Decimal(price), Decimal(size)) for price, size in result['bids']]
        asks = [(Decimal(price), Decimal(size)) for price, size in result['asks']]
        
        return OrderBook(
            symbol=symbol,
            bids=bids,
            asks=asks,
            timestamp=int(time.time() * 1000)
        )
    
    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        qty: Decimal,
        price: Optional[Decimal] = None,
        time_in_force: TimeInForce = TimeInForce.GTC,
        client_order_id: Optional[str] = None,
        reduce_only: bool = False
    ) -> Order:
        """Place new order."""
        
        # Prepare order data
        order_data = {
            "symbol": symbol,
            "side": side.value,
            "order_type": order_type.value if order_type != OrderType.POST_ONLY else "limit",
            "qty": str(qty),
            "time_in_force": time_in_force.value,
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
        
        # Return order (note: actual order details come via WebSocket)
        return Order(
            order_id=None,  # Will be updated via WebSocket
            cl_ord_id=order_data["cl_ord_id"],
            symbol=symbol,
            side=side,
            order_type=order_type,
            price=price,
            qty=qty,
            filled_qty=Decimal('0'),
            status=OrderStatus.NEW,
            time_in_force=time_in_force,
            created_at=int(time.time() * 1000),
            updated_at=int(time.time() * 1000)
        )
    
    async def cancel_order(
        self,
        symbol: str,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None
    ) -> bool:
        """Cancel existing order."""
        
        cancel_data = {}
        
        if order_id:
            cancel_data["order_id"] = int(order_id)
        elif client_order_id:
            cancel_data["cl_ord_id"] = client_order_id
        else:
            raise ValueError("Either order_id or client_order_id is required")
        
        try:
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
        """Cancel all open orders for symbol."""
        
        # Get all open orders
        open_orders = await self.get_open_orders(symbol)
        
        if not open_orders:
            return 0
        
        # Prepare batch cancel
        order_ids = [int(order.order_id) for order in open_orders if order.order_id]
        
        if not order_ids:
            return 0
        
        try:
            await self._request(
                'POST', '/api/cancel_orders',
                data={"order_id_list": order_ids},
                sign_body=True
            )
            return len(order_ids)
        except Exception as e:
            print(f"❌ Failed to cancel all orders: {e}")
            return 0
    
    async def get_open_orders(self, symbol: str) -> List[Order]:
        """Get all open orders for symbol."""
        
        result = await self._request(
            'GET', '/api/query_open_orders',
            params={'symbol': symbol, 'limit': 500}
        )
        
        orders = []
        for order_data in result.get('result', []):
            orders.append(self._parse_order(order_data))
        
        return orders
    
    async def get_order(
        self,
        symbol: str,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None
    ) -> Optional[Order]:
        """Get specific order details."""
        
        params = {'symbol': symbol}
        
        if order_id:
            params['order_id'] = int(order_id)
        elif client_order_id:
            params['cl_ord_id'] = client_order_id
        else:
            raise ValueError("Either order_id or client_order_id is required")
        
        try:
            result = await self._request('GET', '/api/query_order', params=params)
            return self._parse_order(result)
        except Exception:
            return None
    
    async def get_position(self, symbol: str) -> Optional[Position]:
        """Get current position for symbol."""
        
        result = await self._request(
            'GET', '/api/query_positions',
            params={'symbol': symbol}
        )
        
        if not result:
            return None
        
        position_data = result[0] if isinstance(result, list) else result
        
        qty = Decimal(position_data['qty'])
        if qty == 0:
            return None
        
        return Position(
            symbol=symbol,
            side=OrderSide.BUY if qty > 0 else OrderSide.SELL,
            qty=abs(qty),
            entry_price=Decimal(position_data['entry_price']),
            mark_price=Decimal(position_data['mark_price']),
            leverage=int(position_data['leverage']),
            unrealized_pnl=Decimal(position_data['upnl']),
            realized_pnl=Decimal(position_data['realized_pnl']),
            margin=Decimal(position_data['holding_margin']),
            liquidation_price=Decimal(position_data['liq_price']) if position_data.get('liq_price') else None
        )
    
    async def get_balance(self) -> Balance:
        """Get account balance."""
        
        result = await self._request('GET', '/api/query_balance')
        
        return Balance(
            total_balance=Decimal(result['balance']),
            available_balance=Decimal(result['cross_available']),
            used_margin=Decimal(result['cross_margin']),
            unrealized_pnl=Decimal(result['upnl']),
            equity=Decimal(result['equity'])
        )
    
    async def get_trades(
        self,
        symbol: str,
        limit: int = 100,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None
    ) -> List[Trade]:
        """Get recent trades."""
        
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
                trade_id=str(trade_data['id']),
                order_id=str(trade_data['order_id']),
                symbol=symbol,
                side=OrderSide(trade_data['side']),
                price=Decimal(trade_data['price']),
                qty=Decimal(trade_data['qty']),
                fee=Decimal(trade_data['fee_qty']),
                realized_pnl=Decimal(trade_data['pnl']),
                timestamp=int(trade_data['created_at'])
            ))
        
        return trades
    
    async def get_symbol_info(self, symbol: str) -> Dict:
        """Get symbol trading information and limits."""
        
        # Check cache
        if symbol in self._symbol_info_cache:
            return self._symbol_info_cache[symbol]
        
        # Fetch from API
        result = await self._request(
            'GET', '/api/query_symbol_info',
            params={'symbol': symbol}
        )
        
        info = result[0] if isinstance(result, list) else result
        
        # Cache result
        self._symbol_info_cache[symbol] = info
        
        return info
    
    def _parse_order(self, data: Dict) -> Order:
        """Parse order data from API response."""
        
        return Order(
            order_id=str(data['id']) if data.get('id') else None,
            cl_ord_id=data.get('cl_ord_id'),
            symbol=data['symbol'],
            side=OrderSide(data['side']),
            order_type=OrderType(data['order_type']),
            price=Decimal(data['price']) if data.get('price') else None,
            qty=Decimal(data['qty']),
            filled_qty=Decimal(data.get('fill_qty', '0')),
            status=self._parse_order_status(data['status']),
            time_in_force=TimeInForce(data['time_in_force']),
            created_at=int(data['created_at']),
            updated_at=int(data['updated_at'])
        )
    
    @staticmethod
    def _parse_order_status(status_str: str) -> OrderStatus:
        """Parse order status string."""
        status_map = {
            'new': OrderStatus.NEW,
            'open': OrderStatus.OPEN,
            'partially_filled': OrderStatus.PARTIALLY_FILLED,
            'filled': OrderStatus.FILLED,
            'cancelled': OrderStatus.CANCELLED,
            'rejected': OrderStatus.REJECTED
        }
        return status_map.get(status_str, OrderStatus.NEW)
