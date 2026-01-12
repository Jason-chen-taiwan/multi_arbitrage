"""
Base Adapter for Perpetual Exchange Integration

This module provides a base adapter interface for integrating different
perpetual futures exchanges. All exchange-specific adapters should inherit
from BasePerpAdapter and implement the required methods.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Tuple
from decimal import Decimal
from datetime import datetime
from dataclasses import dataclass
from enum import Enum


class OrderSide(Enum):
    """訂單方向"""
    BUY = "buy"
    SELL = "sell"
    LONG = "long"  # Alias for buy in perps
    SHORT = "short"  # Alias for sell in perps


class OrderType(Enum):
    """訂單類型"""
    MARKET = "market"
    LIMIT = "limit"
    POST_ONLY = "post_only"
    IOC = "ioc"  # Immediate or Cancel
    FOK = "fok"  # Fill or Kill


class TimeInForce(Enum):
    """訂單有效期"""
    GTC = "gtc"  # Good Till Cancel
    IOC = "ioc"  # Immediate or Cancel
    FOK = "fok"  # Fill or Kill
    PO = "post_only"  # Post Only


class OrderStatus(Enum):
    """訂單狀態"""
    PENDING = "pending"
    OPEN = "open"
    PARTIAL_FILLED = "partial_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class Orderbook:
    """訂單簿數據結構"""
    symbol: str
    bids: List[Tuple[Decimal, Decimal]]  # [(price, size), ...]
    asks: List[Tuple[Decimal, Decimal]]
    timestamp: datetime

    @property
    def best_bid(self) -> Optional[Decimal]:
        """獲取最佳買價"""
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> Optional[Decimal]:
        """獲取最佳賣價"""
        return self.asks[0][0] if self.asks else None

    @property
    def mid_price(self) -> Optional[Decimal]:
        """計算中間價"""
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return None

    @property
    def spread(self) -> Optional[Decimal]:
        """計算價差"""
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None

    @property
    def spread_pct(self) -> Optional[Decimal]:
        """計算價差百分比"""
        if self.spread and self.mid_price and self.mid_price > 0:
            return (self.spread / self.mid_price) * 100
        return None


class Position:
    """持倉信息"""
    def __init__(
        self,
        symbol: str,
        size: Decimal,
        side: str,
        entry_price: Decimal,
        mark_price: Decimal,
        unrealized_pnl: Decimal,
        leverage: Optional[int] = None,
        margin_mode: Optional[str] = None,
        liquidation_price: Optional[Decimal] = None,
    ):
        self.symbol = symbol
        self.size = size  # Always positive
        self.side = side  # "long" or "short"
        self.entry_price = entry_price
        self.mark_price = mark_price
        self.unrealized_pnl = unrealized_pnl
        self.leverage = leverage
        self.margin_mode = margin_mode
        self.liquidation_price = liquidation_price
    
    def __repr__(self) -> str:
        return (
            f"Position(symbol={self.symbol}, side={self.side}, "
            f"size={self.size}, entry={self.entry_price}, "
            f"upnl={self.unrealized_pnl})"
        )


class Balance:
    """賬戶餘額信息"""
    def __init__(
        self,
        total_balance: Decimal,
        available_balance: Decimal,
        used_margin: Decimal = Decimal("0"),
        unrealized_pnl: Decimal = Decimal("0"),
        equity: Optional[Decimal] = None,
    ):
        self.total_balance = total_balance
        self.available_balance = available_balance
        self.used_margin = used_margin
        self.unrealized_pnl = unrealized_pnl
        self.equity = equity or (total_balance + unrealized_pnl)
    
    def __repr__(self) -> str:
        return (
            f"Balance(total={self.total_balance}, available={self.available_balance}, "
            f"used_margin={self.used_margin}, upnl={self.unrealized_pnl})"
        )


class Order:
    """訂單信息"""
    def __init__(
        self,
        order_id: Optional[str],
        client_order_id: Optional[str],
        symbol: str,
        side: str,
        order_type: str,
        price: Optional[Decimal],
        qty: Decimal,
        filled_qty: Decimal = Decimal("0"),
        status: str = "pending",
        time_in_force: str = "gtc",
        reduce_only: bool = False,
        created_at: Optional[int] = None,
        updated_at: Optional[int] = None,
    ):
        self.order_id = order_id
        self.client_order_id = client_order_id
        self.symbol = symbol
        self.side = side
        self.order_type = order_type
        self.price = price
        self.qty = qty
        self.filled_qty = filled_qty
        self.status = status
        self.time_in_force = time_in_force
        self.reduce_only = reduce_only
        self.created_at = created_at
        self.updated_at = updated_at
    
    def __repr__(self) -> str:
        return (
            f"Order(id={self.order_id}, symbol={self.symbol}, "
            f"side={self.side}, type={self.order_type}, "
            f"price={self.price}, qty={self.qty}, status={self.status})"
        )


class BasePerpAdapter(ABC):
    """
    永續合約交易所適配器基類
    
    所有交易所適配器都應該繼承此類並實現所有抽象方法。
    這樣可以確保不同交易所的接口統一，方便策略編寫。
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化適配器
        
        Args:
            config: 交易所配置字典，包含 API key、secret、base_url 等
        """
        self.config = config
        self.exchange_name = config.get("exchange_name", "unknown")
    
    @abstractmethod
    async def connect(self) -> bool:
        """
        連接到交易所並完成認證
        
        Returns:
            bool: 連接是否成功
        """
        pass
    
    @abstractmethod
    async def disconnect(self) -> bool:
        """
        斷開與交易所的連接
        
        Returns:
            bool: 斷開是否成功
        """
        pass
    
    @abstractmethod
    async def get_balance(self) -> Balance:
        """
        查詢賬戶餘額
        
        Returns:
            Balance: 賬戶餘額信息
            
        Raises:
            Exception: 查詢失敗時拋出異常
        """
        pass
    
    @abstractmethod
    async def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """
        查詢持倉
        
        Args:
            symbol: 交易對符號（可選，不傳則返回所有持倉）
            
        Returns:
            List[Position]: 持倉列表
            
        Raises:
            Exception: 查詢失敗時拋出異常
        """
        pass
    
    @abstractmethod
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
        """
        下單
        
        Args:
            symbol: 交易對符號
            side: 訂單方向 ("buy", "sell", "long", "short")
            order_type: 訂單類型 ("market", "limit", "post_only")
            quantity: 訂單數量
            price: 訂單價格（限價單必填）
            time_in_force: 訂單有效期
            reduce_only: 是否只減倉
            client_order_id: 客戶端訂單ID
            **kwargs: 其他參數
            
        Returns:
            Order: 訂單信息
            
        Raises:
            Exception: 下單失敗時拋出異常
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
        取消訂單
        
        Args:
            symbol: 交易對符號
            order_id: 訂單ID（與client_order_id二選一）
            client_order_id: 客戶端訂單ID
            
        Returns:
            bool: 是否取消成功
            
        Raises:
            Exception: 取消失敗時拋出異常
        """
        pass
    
    @abstractmethod
    async def cancel_all_orders(self, symbol: str) -> int:
        """
        取消所有訂單
        
        Args:
            symbol: 交易對符號
            
        Returns:
            int: 取消的訂單數量
            
        Raises:
            Exception: 取消失敗時拋出異常
        """
        pass
    
    @abstractmethod
    async def get_open_orders(self, symbol: str) -> List[Order]:
        """
        查詢未成交訂單
        
        Args:
            symbol: 交易對符號
            
        Returns:
            List[Order]: 未成交訂單列表
            
        Raises:
            Exception: 查詢失敗時拋出異常
        """
        pass
    
    @abstractmethod
    async def get_orderbook(
        self,
        symbol: str,
        limit: int = 20,
    ) -> Orderbook:
        """
        查詢訂單簿

        Args:
            symbol: 交易對符號
            limit: 訂單簿深度

        Returns:
            Orderbook: 訂單簿數據

        Raises:
            Exception: 查詢失敗時拋出異常
        """
        pass
    
    # 便捷方法
    async def place_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
        time_in_force: str = "gtc",
        reduce_only: bool = False,
        client_order_id: Optional[str] = None,
        **kwargs
    ) -> Order:
        """
        下限價單（便捷方法）
        
        Args:
            symbol: 交易對符號
            side: 訂單方向
            quantity: 訂單數量
            price: 訂單價格
            time_in_force: 訂單有效期
            reduce_only: 是否只減倉
            client_order_id: 客戶端訂單ID
            **kwargs: 其他參數
            
        Returns:
            Order: 訂單信息
        """
        return await self.place_order(
            symbol=symbol,
            side=side,
            order_type="limit",
            quantity=quantity,
            price=price,
            time_in_force=time_in_force,
            reduce_only=reduce_only,
            client_order_id=client_order_id,
            **kwargs
        )
    
    async def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        reduce_only: bool = False,
        client_order_id: Optional[str] = None,
        **kwargs
    ) -> Order:
        """
        下市價單（便捷方法）
        
        Args:
            symbol: 交易對符號
            side: 訂單方向
            quantity: 訂單數量
            reduce_only: 是否只減倉
            client_order_id: 客戶端訂單ID
            **kwargs: 其他參數
            
        Returns:
            Order: 訂單信息
        """
        return await self.place_order(
            symbol=symbol,
            side=side,
            order_type="market",
            quantity=quantity,
            price=None,
            time_in_force="ioc",
            reduce_only=reduce_only,
            client_order_id=client_order_id,
            **kwargs
        )
    
    async def get_position(self, symbol: str) -> Optional[Position]:
        """
        查詢單個持倉（便捷方法）
        
        Args:
            symbol: 交易對符號
            
        Returns:
            Optional[Position]: 持倉信息，如果沒有持倉則返回None
        """
        positions = await self.get_positions(symbol=symbol)
        if not positions:
            return None
        return positions[0]
    
    async def close_position(
        self,
        symbol: str,
        order_type: str = "market",
        price: Optional[Decimal] = None,
    ) -> Optional[Order]:
        """
        平倉（便捷方法）
        
        Args:
            symbol: 交易對符號
            order_type: 訂單類型
            price: 訂單價格（限價單必填）
            
        Returns:
            Optional[Order]: 平倉訂單，如果沒有持倉則返回None
        """
        position = await self.get_position(symbol)
        if not position:
            return None
        
        # 確定平倉方向（與持倉方向相反）
        side = "sell" if position.side in ["long", "buy"] else "buy"
        
        return await self.place_order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=position.size,
            price=price,
            reduce_only=True
        )
    
    def __repr__(self) -> str:
        """字符串表示"""
        return f"<{self.__class__.__name__}(exchange={self.exchange_name})>"
