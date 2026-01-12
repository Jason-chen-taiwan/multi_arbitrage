"""
Base Exchange Interface

Defines the abstract interface that all exchange connectors must implement.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
from decimal import Decimal
from dataclasses import dataclass
from enum import Enum


class OrderSide(Enum):
    """Order side enumeration."""
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    """Order type enumeration."""
    LIMIT = "limit"
    MARKET = "market"
    POST_ONLY = "post_only"


class TimeInForce(Enum):
    """Time in force enumeration."""
    GTC = "gtc"  # Good til canceled
    IOC = "ioc"  # Immediate or cancel
    FOK = "fok"  # Fill or kill


class OrderStatus(Enum):
    """Order status enumeration."""
    NEW = "new"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class OrderBook:
    """Order book data structure."""
    symbol: str
    bids: List[Tuple[Decimal, Decimal]]  # [(price, size), ...]
    asks: List[Tuple[Decimal, Decimal]]
    timestamp: int
    
    @property
    def best_bid(self) -> Optional[Decimal]:
        """Get best bid price."""
        return self.bids[0][0] if self.bids else None
    
    @property
    def best_ask(self) -> Optional[Decimal]:
        """Get best ask price."""
        return self.asks[0][0] if self.asks else None
    
    @property
    def mid_price(self) -> Optional[Decimal]:
        """Calculate mid price."""
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return None
    
    @property
    def spread(self) -> Optional[Decimal]:
        """Calculate spread."""
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None
    
    @property
    def spread_bps(self) -> Optional[Decimal]:
        """Calculate spread in basis points."""
        if self.mid_price and self.spread:
            return (self.spread / self.mid_price) * 10000
        return None


@dataclass
class Order:
    """Order data structure."""
    order_id: Optional[str]
    cl_ord_id: Optional[str]
    symbol: str
    side: OrderSide
    order_type: OrderType
    price: Optional[Decimal]
    qty: Decimal
    filled_qty: Decimal
    status: OrderStatus
    time_in_force: TimeInForce
    created_at: int
    updated_at: int
    
    @property
    def remaining_qty(self) -> Decimal:
        """Get remaining quantity."""
        return self.qty - self.filled_qty
    
    @property
    def is_open(self) -> bool:
        """Check if order is open."""
        return self.status in [OrderStatus.NEW, OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED]


@dataclass
class Position:
    """Position data structure."""
    symbol: str
    side: OrderSide
    qty: Decimal
    entry_price: Decimal
    mark_price: Decimal
    leverage: int
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    margin: Decimal
    liquidation_price: Optional[Decimal]
    
    @property
    def position_value(self) -> Decimal:
        """Calculate position value."""
        return self.qty * self.mark_price
    
    @property
    def is_long(self) -> bool:
        """Check if long position."""
        return self.qty > 0
    
    @property
    def is_short(self) -> bool:
        """Check if short position."""
        return self.qty < 0


@dataclass
class Balance:
    """Account balance data structure."""
    total_balance: Decimal
    available_balance: Decimal
    used_margin: Decimal
    unrealized_pnl: Decimal
    equity: Decimal


@dataclass
class Trade:
    """Trade data structure."""
    trade_id: str
    order_id: str
    symbol: str
    side: OrderSide
    price: Decimal
    qty: Decimal
    fee: Decimal
    realized_pnl: Decimal
    timestamp: int


class BaseExchange(ABC):
    """
    Abstract base class for exchange connectors.
    
    All exchange implementations must inherit from this class and
    implement all abstract methods.
    """
    
    def __init__(self, config: Dict):
        """
        Initialize exchange connector.
        
        Args:
            config: Exchange configuration dictionary
        """
        self.config = config
        self.name = config.get('name', 'unknown')
    
    @abstractmethod
    async def connect(self) -> bool:
        """
        Establish connection to exchange.
        
        Returns:
            True if connection successful
        """
        pass
    
    @abstractmethod
    async def disconnect(self) -> bool:
        """
        Close connection to exchange.
        
        Returns:
            True if disconnection successful
        """
        pass
    
    @abstractmethod
    async def get_orderbook(self, symbol: str) -> OrderBook:
        """
        Get current order book for symbol.
        
        Args:
            symbol: Trading pair symbol
            
        Returns:
            OrderBook object
        """
        pass
    
    @abstractmethod
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
        """
        Place new order.
        
        Args:
            symbol: Trading pair symbol
            side: Order side (buy/sell)
            order_type: Order type (limit/market)
            qty: Order quantity
            price: Limit price (required for limit orders)
            time_in_force: Time in force
            client_order_id: Custom client order ID
            reduce_only: Only reduce position
            
        Returns:
            Order object
        """
        pass
    
    @abstractmethod
    async def cancel_order(
        self,
        symbol: str,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None
    ) -> bool:
        """
        Cancel existing order.
        
        Args:
            symbol: Trading pair symbol
            order_id: Exchange order ID
            client_order_id: Client order ID
            
        Returns:
            True if cancellation successful
        """
        pass
    
    @abstractmethod
    async def cancel_all_orders(self, symbol: str) -> int:
        """
        Cancel all open orders for symbol.
        
        Args:
            symbol: Trading pair symbol
            
        Returns:
            Number of orders cancelled
        """
        pass
    
    @abstractmethod
    async def get_open_orders(self, symbol: str) -> List[Order]:
        """
        Get all open orders for symbol.
        
        Args:
            symbol: Trading pair symbol
            
        Returns:
            List of Order objects
        """
        pass
    
    @abstractmethod
    async def get_order(
        self,
        symbol: str,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None
    ) -> Optional[Order]:
        """
        Get specific order details.
        
        Args:
            symbol: Trading pair symbol
            order_id: Exchange order ID
            client_order_id: Client order ID
            
        Returns:
            Order object or None if not found
        """
        pass
    
    @abstractmethod
    async def get_position(self, symbol: str) -> Optional[Position]:
        """
        Get current position for symbol.
        
        Args:
            symbol: Trading pair symbol
            
        Returns:
            Position object or None if no position
        """
        pass
    
    @abstractmethod
    async def get_balance(self) -> Balance:
        """
        Get account balance.
        
        Returns:
            Balance object
        """
        pass
    
    @abstractmethod
    async def get_trades(
        self,
        symbol: str,
        limit: int = 100,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None
    ) -> List[Trade]:
        """
        Get recent trades.
        
        Args:
            symbol: Trading pair symbol
            limit: Maximum number of trades to return
            start_time: Start timestamp
            end_time: End timestamp
            
        Returns:
            List of Trade objects
        """
        pass
    
    @abstractmethod
    async def get_symbol_info(self, symbol: str) -> Dict:
        """
        Get symbol trading information and limits.
        
        Args:
            symbol: Trading pair symbol
            
        Returns:
            Dictionary with symbol info
        """
        pass
