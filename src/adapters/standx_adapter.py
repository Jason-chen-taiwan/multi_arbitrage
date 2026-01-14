"""
StandX Exchange Adapter Implementation

This module implements BasePerpAdapter for StandX exchange.
"""
import json
import time
from typing import Dict, Any, Optional, List
from decimal import Decimal
from datetime import datetime
from uuid import uuid4

import aiohttp
from eth_account import Account

from .base_adapter import BasePerpAdapter, Balance, Position, Order, OrderSide, OrderType, OrderStatus, Orderbook
from ..auth import AsyncStandXAuth


class StandXAdapter(BasePerpAdapter):
    """
    StandX 交易所適配器實現

    Symbol 映射由 SymbolManager 統一管理 (config/symbols.yaml)
    """

    def __init__(self, config: Dict[str, Any]):
        """
        初始化 StandX 適配器
        
        Args:
            config: 配置字典，必須包含：
                - exchange_name: "standx"
                - private_key: 錢包私鑰
                - chain: 鏈名稱，如 "bsc" 或 "solana"
                - base_url: API 基礎 URL（可選，默認 https://api.standx.com）
                - perps_url: Perps API URL（可選，默認 https://perps.standx.com）
        """
        super().__init__(config)
        
        self.chain = config.get("chain", "bsc")
        self.base_url = config.get("base_url", "https://api.standx.com")
        self.perps_url = config.get("perps_url", "https://perps.standx.com")
        
        # Initialize wallet
        private_key = config.get("private_key") or config.get("wallet_private_key")
        if not private_key:
            raise ValueError("配置中必須包含 private_key 或 wallet_private_key")
        
        self.account = Account.from_key(private_key)
        self.wallet_address = self.account.address
        
        # Initialize auth manager
        self.auth = AsyncStandXAuth(base_url=self.base_url)
        
        # Session management
        self.session: Optional[aiohttp.ClientSession] = None
        self.session_id = str(uuid4())
    
    async def connect(self) -> bool:
        """連接到 StandX 並完成認證"""
        try:
            # Create HTTP session
            self.session = aiohttp.ClientSession()
            
            # Authenticate with wallet signature
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
            if self.session:
                await self.session.close()
                self.session = None
            return True
        except Exception as e:
            print(f"❌ Failed to disconnect from StandX: {e}")
            return False
    
    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        sign_body: bool = False
    ) -> Dict:
        """Make authenticated API request."""
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
        """下單"""
        if order_type == "limit" and price is None:
            raise ValueError("限價單必須指定價格")
        
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
    
    async def get_orderbook(
        self,
        symbol: str,
        depth: int = 20,
        limit: int = None,  # 兼容性參數
    ) -> Orderbook:
        """查詢訂單簿"""
        # 如果提供了 limit 參數，使用它而不是 depth
        if limit is not None:
            depth = limit

        try:
            result = await self._request(
                'GET', '/api/query_depth_book',
                params={'symbol': symbol}
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
