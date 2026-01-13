"""
做市商狀態管理模組
Market Maker State Management

參考 frozen-cherry/standx-mm 的 state.py 設計
- 線程安全的狀態管理
- 波動率計算
- 訂單追蹤
"""
from typing import Dict, Optional, List, Tuple
from decimal import Decimal
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock
import time
import logging

logger = logging.getLogger(__name__)


@dataclass
class OrderInfo:
    """訂單信息"""
    order_id: Optional[str] = None
    client_order_id: Optional[str] = None
    side: str = ""          # "buy" or "sell"
    price: Decimal = Decimal("0")
    qty: Decimal = Decimal("0")
    filled_qty: Decimal = Decimal("0")
    status: str = "pending"  # pending, open, filled, cancelled
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class FillEvent:
    """成交事件"""
    order_id: str
    client_order_id: str
    symbol: str
    side: str               # "buy" or "sell"
    fill_price: Decimal
    fill_qty: Decimal
    remaining_qty: Decimal
    is_fully_filled: bool
    timestamp: datetime = field(default_factory=datetime.now)


class MMState:
    """
    做市商狀態管理 (線程安全)

    追蹤:
    - 雙邊訂單 (bid/ask)
    - 倉位 (StandX / Binance)
    - 價格歷史 (波動率計算)
    """

    def __init__(self, volatility_window_sec: int = 5):
        self._lock = Lock()

        # 訂單追蹤
        self._bid_order: Optional[OrderInfo] = None
        self._ask_order: Optional[OrderInfo] = None

        # 倉位追蹤
        self._standx_position: Decimal = Decimal("0")
        self._binance_position: Decimal = Decimal("0")

        # 價格歷史 (用於波動率計算)
        self._price_history: List[Tuple[float, Decimal]] = []
        self._volatility_window_sec = volatility_window_sec

        # 最新價格
        self._last_price: Optional[Decimal] = None
        self._last_price_time: Optional[float] = None

        # 統計
        self._total_fills = 0
        self._total_hedges = 0
        self._successful_hedges = 0

    # ==================== 訂單管理 ====================

    def set_bid_order(self, order: Optional[OrderInfo]):
        """設置買單"""
        with self._lock:
            self._bid_order = order
            if order:
                logger.debug(f"Bid order set: {order.client_order_id} @ {order.price}")

    def set_ask_order(self, order: Optional[OrderInfo]):
        """設置賣單"""
        with self._lock:
            self._ask_order = order
            if order:
                logger.debug(f"Ask order set: {order.client_order_id} @ {order.price}")

    def get_bid_order(self) -> Optional[OrderInfo]:
        """獲取買單"""
        with self._lock:
            return self._bid_order

    def get_ask_order(self) -> Optional[OrderInfo]:
        """獲取賣單"""
        with self._lock:
            return self._ask_order

    def has_bid_order(self) -> bool:
        """是否有買單"""
        with self._lock:
            return self._bid_order is not None and self._bid_order.status in ["pending", "open"]

    def has_ask_order(self) -> bool:
        """是否有賣單"""
        with self._lock:
            return self._ask_order is not None and self._ask_order.status in ["pending", "open"]

    def clear_bid_order(self):
        """清除買單"""
        with self._lock:
            self._bid_order = None

    def clear_ask_order(self):
        """清除賣單"""
        with self._lock:
            self._ask_order = None

    def clear_all_orders(self):
        """清除所有訂單"""
        with self._lock:
            self._bid_order = None
            self._ask_order = None

    def update_order_status(self, client_order_id: str, status: str, filled_qty: Optional[Decimal] = None):
        """更新訂單狀態"""
        with self._lock:
            if self._bid_order and self._bid_order.client_order_id == client_order_id:
                self._bid_order.status = status
                if filled_qty is not None:
                    self._bid_order.filled_qty = filled_qty
            elif self._ask_order and self._ask_order.client_order_id == client_order_id:
                self._ask_order.status = status
                if filled_qty is not None:
                    self._ask_order.filled_qty = filled_qty

    # ==================== 倉位管理 ====================

    def update_standx_position(self, delta: Decimal):
        """更新 StandX 倉位"""
        with self._lock:
            self._standx_position += delta
            logger.info(f"StandX position: {self._standx_position} (delta: {delta})")

    def set_standx_position(self, position: Decimal):
        """設置 StandX 倉位"""
        with self._lock:
            self._standx_position = position

    def update_binance_position(self, delta: Decimal):
        """更新 Binance 倉位"""
        with self._lock:
            self._binance_position += delta
            logger.info(f"Binance position: {self._binance_position} (delta: {delta})")

    def set_binance_position(self, position: Decimal):
        """設置 Binance 倉位"""
        with self._lock:
            self._binance_position = position

    def get_standx_position(self) -> Decimal:
        """獲取 StandX 倉位"""
        with self._lock:
            return self._standx_position

    def get_binance_position(self) -> Decimal:
        """獲取 Binance 倉位"""
        with self._lock:
            return self._binance_position

    def get_net_position(self) -> Decimal:
        """獲取淨敞口 (StandX + Binance)"""
        with self._lock:
            return self._standx_position + self._binance_position

    def is_position_balanced(self, tolerance: Decimal = Decimal("0.0001")) -> bool:
        """倉位是否平衡"""
        with self._lock:
            net = abs(self._standx_position + self._binance_position)
            return net <= tolerance

    # ==================== 價格和波動率 ====================

    def update_price(self, price: Decimal):
        """更新價格"""
        now = time.time()
        with self._lock:
            self._last_price = price
            self._last_price_time = now

            # 添加到歷史
            self._price_history.append((now, price))

            # 清理過期數據
            cutoff = now - self._volatility_window_sec
            self._price_history = [
                (t, p) for t, p in self._price_history if t > cutoff
            ]

    def get_last_price(self) -> Optional[Decimal]:
        """獲取最新價格"""
        with self._lock:
            return self._last_price

    def get_volatility_bps(self) -> float:
        """
        計算窗口內波動率 (basis points)

        波動率 = (max - min) / avg * 10000
        """
        with self._lock:
            if len(self._price_history) < 2:
                return 0.0

            prices = [p for _, p in self._price_history]
            max_price = max(prices)
            min_price = min(prices)
            avg_price = sum(prices) / len(prices)

            if avg_price == 0:
                return 0.0

            volatility = float((max_price - min_price) / avg_price * 10000)
            return volatility

    # ==================== 訂單距離檢查 ====================

    def get_orders_to_cancel(
        self,
        current_price: Decimal,
        cancel_distance_bps: int
    ) -> List[str]:
        """
        獲取需要撤銷的訂單

        當訂單價格距離當前價格太近時，撤銷以避免成交
        """
        to_cancel = []
        threshold = current_price * Decimal(cancel_distance_bps) / Decimal("10000")

        with self._lock:
            # 檢查買單 - 如果買單價格 >= current - threshold，太近了
            if self._bid_order and self._bid_order.status in ["pending", "open"]:
                if self._bid_order.price >= current_price - threshold:
                    to_cancel.append(self._bid_order.client_order_id)

            # 檢查賣單 - 如果賣單價格 <= current + threshold，太近了
            if self._ask_order and self._ask_order.status in ["pending", "open"]:
                if self._ask_order.price <= current_price + threshold:
                    to_cancel.append(self._ask_order.client_order_id)

        return to_cancel

    def should_rebalance_orders(
        self,
        current_price: Decimal,
        rebalance_distance_bps: int
    ) -> bool:
        """
        是否需要重新掛單

        當訂單價格距離當前價格太遠時，重新掛更優價格
        """
        threshold = current_price * Decimal(rebalance_distance_bps) / Decimal("10000")

        with self._lock:
            # 檢查買單
            if self._bid_order and self._bid_order.status in ["pending", "open"]:
                if current_price - self._bid_order.price > threshold:
                    return True

            # 檢查賣單
            if self._ask_order and self._ask_order.status in ["pending", "open"]:
                if self._ask_order.price - current_price > threshold:
                    return True

        return False

    # ==================== 統計 ====================

    def record_fill(self):
        """記錄成交"""
        with self._lock:
            self._total_fills += 1

    def record_hedge(self, success: bool):
        """記錄對沖"""
        with self._lock:
            self._total_hedges += 1
            if success:
                self._successful_hedges += 1

    def get_stats(self) -> Dict:
        """獲取統計數據"""
        with self._lock:
            standx_pos = float(self._standx_position)
            binance_pos = float(self._binance_position)
            net_pos = standx_pos + binance_pos
            return {
                "total_fills": self._total_fills,
                "total_hedges": self._total_hedges,
                "successful_hedges": self._successful_hedges,
                "hedge_success_rate": (
                    self._successful_hedges / self._total_hedges * 100
                    if self._total_hedges > 0 else 0
                ),
                "standx_position": standx_pos,
                "binance_position": binance_pos,
                "net_position": net_pos,
                "is_balanced": abs(net_pos) <= 0.0001,
            }

    def to_dict(self) -> Dict:
        """序列化為字典"""
        # 先獲取需要鎖的數據
        with self._lock:
            bid_order = self._bid_order
            ask_order = self._ask_order
            standx_pos = float(self._standx_position)
            binance_pos = float(self._binance_position)
            last_price = float(self._last_price) if self._last_price else None

            # 計算波動率 (在鎖內計算避免再次獲取鎖)
            if len(self._price_history) < 2:
                volatility = 0.0
            else:
                prices = [p for _, p in self._price_history]
                max_price = max(prices)
                min_price = min(prices)
                avg_price = sum(prices) / len(prices)
                volatility = float((max_price - min_price) / avg_price * 10000) if avg_price != 0 else 0.0

            # 統計數據
            stats = {
                "total_fills": self._total_fills,
                "total_hedges": self._total_hedges,
                "successful_hedges": self._successful_hedges,
                "hedge_success_rate": (
                    self._successful_hedges / self._total_hedges * 100
                    if self._total_hedges > 0 else 0
                ),
                "standx_position": standx_pos,
                "binance_position": binance_pos,
                "net_position": standx_pos + binance_pos,
                "is_balanced": abs(standx_pos + binance_pos) <= 0.0001,
            }

        return {
            "bid_order": {
                "client_order_id": bid_order.client_order_id,
                "price": float(bid_order.price),
                "qty": float(bid_order.qty),
                "status": bid_order.status,
            } if bid_order else None,
            "ask_order": {
                "client_order_id": ask_order.client_order_id,
                "price": float(ask_order.price),
                "qty": float(ask_order.qty),
                "status": ask_order.status,
            } if ask_order else None,
            "standx_position": standx_pos,
            "binance_position": binance_pos,
            "net_position": standx_pos + binance_pos,
            "last_price": last_price,
            "volatility_bps": volatility,
            "stats": stats,
        }
