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
    qty: Decimal = Decimal("0")  # 向後兼容，等同於 orig_qty
    filled_qty: Decimal = Decimal("0")  # 向後兼容
    status: str = "pending"  # pending, open, partially_filled, filled, canceled_or_unknown
    created_at: datetime = field(default_factory=datetime.now)

    # 數量追蹤（改進版）
    orig_qty: Optional[Decimal] = None          # 原始下單量
    last_remaining_qty: Optional[Decimal] = None  # 上次查詢的剩餘量
    cum_filled_qty: Decimal = Decimal("0")      # 累計成交量

    # 消失追蹤（用時間而非 tick 次數）
    disappeared_since_ts: Optional[float] = None  # 首次消失時間戳
    unknown_pending_checks: int = 0  # 消失+倉位無變化的確認次數

    def __post_init__(self):
        """初始化時設置默認值"""
        # orig_qty 默認等於 qty（向後兼容）
        if self.orig_qty is None:
            self.orig_qty = self.qty
        # last_remaining_qty 初始化 = orig_qty
        if self.last_remaining_qty is None:
            self.last_remaining_qty = self.orig_qty


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
        self._hedge_position: Decimal = Decimal("0")  # GRVT 對沖倉位

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

        # 詳細撤單/重掛統計
        self._bid_cancels = 0
        self._ask_cancels = 0
        self._bid_rebalances = 0
        self._ask_rebalances = 0
        self._bid_queue_cancels = 0  # 因隊列位置撤單
        self._ask_queue_cancels = 0
        self._volatility_pause_count = 0

        # PnL 追蹤
        self._realized_pnl = Decimal("0")
        self._fill_count = 0

        # 訂單消失分類統計
        self._orders_filled = 0              # 確認成交
        self._orders_canceled_or_unknown = 0  # 取消或未知
        self._partial_fills = 0              # 部分成交次數
        self._unknown_fills_detected = 0     # 未知成交（多張消失+倉位變化）

        # Uptime 分層時間追蹤 (毫秒)
        self._boosted_time_ms = 0      # 100% 層 (0-10 bps)
        self._standard_time_ms = 0     # 50% 層 (10-30 bps)
        self._basic_time_ms = 0        # 10% 層 (30-100 bps)
        self._out_of_range_time_ms = 0 # 超出範圍 (>100 bps 或無單)
        self._total_time_ms = 0
        self._last_uptime_check: Optional[float] = None

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

    def update_hedge_position(self, delta: Decimal):
        """更新對沖倉位 (GRVT)"""
        with self._lock:
            self._hedge_position += delta
            logger.info(f"Hedge (GRVT) position: {self._hedge_position} (delta: {delta})")

    def set_hedge_position(self, position: Decimal):
        """設置對沖倉位 (GRVT)"""
        with self._lock:
            self._hedge_position = position

    def get_standx_position(self) -> Decimal:
        """獲取 StandX 倉位"""
        with self._lock:
            return self._standx_position

    def get_hedge_position(self) -> Decimal:
        """獲取對沖倉位 (GRVT)"""
        with self._lock:
            return self._hedge_position

    def get_net_position(self) -> Decimal:
        """獲取淨敞口 (StandX + GRVT)"""
        with self._lock:
            return self._standx_position + self._hedge_position

    def is_position_balanced(self, tolerance: Decimal = Decimal("0.0001")) -> bool:
        """倉位是否平衡"""
        with self._lock:
            net = abs(self._standx_position + self._hedge_position)
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

    def record_fill(self, side: str = None, pnl: Decimal = Decimal("0")):
        """記錄成交"""
        with self._lock:
            self._total_fills += 1
            self._fill_count += 1
            self._realized_pnl += pnl

    def record_hedge(self, success: bool):
        """記錄對沖"""
        with self._lock:
            self._total_hedges += 1
            if success:
                self._successful_hedges += 1

    def record_cancel(self, side: str, reason: str = "price"):
        """記錄撤單"""
        with self._lock:
            if side == "buy":
                if reason == "queue":
                    self._bid_queue_cancels += 1
                else:
                    self._bid_cancels += 1
            else:
                if reason == "queue":
                    self._ask_queue_cancels += 1
                else:
                    self._ask_cancels += 1

    def record_rebalance(self, side: str):
        """記錄重掛"""
        with self._lock:
            if side == "buy":
                self._bid_rebalances += 1
            else:
                self._ask_rebalances += 1

    def record_volatility_pause(self):
        """記錄波動率暫停"""
        with self._lock:
            self._volatility_pause_count += 1

    def record_order_filled(self):
        """記錄訂單成交"""
        with self._lock:
            self._orders_filled += 1

    def record_order_canceled_or_unknown(self):
        """記錄訂單取消或未知"""
        with self._lock:
            self._orders_canceled_or_unknown += 1

    def record_partial_fill(self):
        """記錄部分成交"""
        with self._lock:
            self._partial_fills += 1

    def record_unknown_fill_detected(self):
        """記錄未知成交（多張消失+倉位變化）"""
        with self._lock:
            self._unknown_fills_detected += 1

    def update_uptime(self, mid_price: Decimal, bid_price: Optional[Decimal], ask_price: Optional[Decimal]):
        """
        更新 uptime 分層時間

        根據訂單距離中間價的 bps 分類:
        - Boosted (100%): 0-10 bps
        - Standard (50%): 10-30 bps
        - Basic (10%): 30-100 bps
        - Out of range: >100 bps 或無訂單
        """
        now = time.time()
        with self._lock:
            if self._last_uptime_check is None:
                self._last_uptime_check = now
                return

            delta_ms = int((now - self._last_uptime_check) * 1000)
            self._last_uptime_check = now
            self._total_time_ms += delta_ms

            # 如果沒有訂單，算作 out of range
            if bid_price is None and ask_price is None:
                self._out_of_range_time_ms += delta_ms
                return

            # 計算訂單距離 (取買賣單中較遠的那個)
            max_distance_bps = 0
            if bid_price is not None and mid_price > 0:
                bid_dist = float((mid_price - bid_price) / mid_price * 10000)
                max_distance_bps = max(max_distance_bps, bid_dist)
            if ask_price is not None and mid_price > 0:
                ask_dist = float((ask_price - mid_price) / mid_price * 10000)
                max_distance_bps = max(max_distance_bps, ask_dist)

            # 根據距離分類
            if max_distance_bps <= 10:
                self._boosted_time_ms += delta_ms
            elif max_distance_bps <= 30:
                self._standard_time_ms += delta_ms
            elif max_distance_bps <= 100:
                self._basic_time_ms += delta_ms
            else:
                self._out_of_range_time_ms += delta_ms

    def get_uptime_stats(self) -> Dict:
        """獲取 uptime 統計"""
        with self._lock:
            total = self._total_time_ms or 1
            boosted_pct = self._boosted_time_ms / total * 100
            standard_pct = self._standard_time_ms / total * 100
            basic_pct = self._basic_time_ms / total * 100
            out_of_range_pct = self._out_of_range_time_ms / total * 100

            # 有效積分百分比 (加權計算)
            effective_pts_pct = (
                self._boosted_time_ms * 1.0 +
                self._standard_time_ms * 0.5 +
                self._basic_time_ms * 0.1
            ) / total * 100

            return {
                "boosted_pct": boosted_pct,
                "standard_pct": standard_pct,
                "basic_pct": basic_pct,
                "out_of_range_pct": out_of_range_pct,
                "effective_pts_pct": effective_pts_pct,
                "total_time_ms": self._total_time_ms,
            }

    def get_stats(self) -> Dict:
        """獲取統計數據"""
        with self._lock:
            standx_pos = float(self._standx_position)
            hedge_pos = float(self._hedge_position)
            net_pos = standx_pos + hedge_pos
            total_time = self._total_time_ms or 1
            return {
                "total_fills": self._total_fills,
                "fill_count": self._fill_count,
                "total_hedges": self._total_hedges,
                "successful_hedges": self._successful_hedges,
                "hedge_success_rate": (
                    self._successful_hedges / self._total_hedges * 100
                    if self._total_hedges > 0 else 0
                ),
                "standx_position": standx_pos,
                "hedge_position": hedge_pos,
                "net_position": net_pos,
                "is_balanced": abs(net_pos) <= 0.0001,
                # 詳細統計
                "bid_cancels": self._bid_cancels,
                "ask_cancels": self._ask_cancels,
                "bid_rebalances": self._bid_rebalances,
                "ask_rebalances": self._ask_rebalances,
                "bid_queue_cancels": self._bid_queue_cancels,
                "ask_queue_cancels": self._ask_queue_cancels,
                "volatility_pause_count": self._volatility_pause_count,
                "pnl_usd": float(self._realized_pnl),
                # 訂單消失分類統計
                "orders_filled": self._orders_filled,
                "orders_canceled_or_unknown": self._orders_canceled_or_unknown,
                "partial_fills": self._partial_fills,
                "unknown_fills_detected": self._unknown_fills_detected,
                # Uptime 分層統計
                "boosted_time_ms": self._boosted_time_ms,
                "standard_time_ms": self._standard_time_ms,
                "basic_time_ms": self._basic_time_ms,
                "out_of_range_time_ms": self._out_of_range_time_ms,
                "total_time_ms": self._total_time_ms,
                "boosted_pct": self._boosted_time_ms / total_time * 100,
                "standard_pct": self._standard_time_ms / total_time * 100,
                "basic_pct": self._basic_time_ms / total_time * 100,
                "out_of_range_pct": self._out_of_range_time_ms / total_time * 100,
                "effective_pts_pct": (
                    (self._boosted_time_ms * 1.0 + self._standard_time_ms * 0.5 + self._basic_time_ms * 0.1)
                    / total_time * 100
                ),
            }

    def to_dict(self) -> Dict:
        """序列化為字典"""
        # 先獲取需要鎖的數據
        with self._lock:
            bid_order = self._bid_order
            ask_order = self._ask_order
            standx_pos = float(self._standx_position)
            hedge_pos = float(self._hedge_position)
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

            # 統計數據 (包含 uptime 分層統計)
            total_time = self._total_time_ms or 1  # 避免除以 0
            stats = {
                "total_fills": self._total_fills,
                "fill_count": self._fill_count,
                "total_hedges": self._total_hedges,
                "successful_hedges": self._successful_hedges,
                "hedge_success_rate": (
                    self._successful_hedges / self._total_hedges * 100
                    if self._total_hedges > 0 else 0
                ),
                "standx_position": standx_pos,
                "hedge_position": hedge_pos,
                "net_position": standx_pos + hedge_pos,
                "is_balanced": abs(standx_pos + hedge_pos) <= 0.0001,
                # 詳細統計
                "bid_cancels": self._bid_cancels,
                "ask_cancels": self._ask_cancels,
                "bid_rebalances": self._bid_rebalances,
                "ask_rebalances": self._ask_rebalances,
                "bid_queue_cancels": self._bid_queue_cancels,
                "ask_queue_cancels": self._ask_queue_cancels,
                "volatility_pause_count": self._volatility_pause_count,
                "pnl_usd": float(self._realized_pnl),
                # 訂單消失分類統計
                "orders_filled": self._orders_filled,
                "orders_canceled_or_unknown": self._orders_canceled_or_unknown,
                "partial_fills": self._partial_fills,
                "unknown_fills_detected": self._unknown_fills_detected,
                # Uptime 分層統計
                "boosted_time_ms": self._boosted_time_ms,
                "standard_time_ms": self._standard_time_ms,
                "basic_time_ms": self._basic_time_ms,
                "out_of_range_time_ms": self._out_of_range_time_ms,
                "total_time_ms": self._total_time_ms,
                "boosted_pct": self._boosted_time_ms / total_time * 100,
                "standard_pct": self._standard_time_ms / total_time * 100,
                "basic_pct": self._basic_time_ms / total_time * 100,
                "out_of_range_pct": self._out_of_range_time_ms / total_time * 100,
                "effective_pts_pct": (
                    (self._boosted_time_ms * 1.0 + self._standard_time_ms * 0.5 + self._basic_time_ms * 0.1)
                    / total_time * 100
                ),
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
            "hedge_position": hedge_pos,
            "net_position": standx_pos + hedge_pos,
            "last_price": last_price,
            "volatility_bps": volatility,
            "fill_count": self._fill_count,
            "pnl_usd": float(self._realized_pnl),
            "stats": stats,
        }
