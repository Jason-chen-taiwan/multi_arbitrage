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


# ==================== 事件去重器 ====================
class EventDeduplicator:
    """
    WebSocket 事件去重器

    用於過濾重複的成交事件，防止同一成交被處理多次
    """

    def __init__(self, ttl_sec: float = 60.0):
        """
        Args:
            ttl_sec: 事件記錄過期時間（秒）
        """
        self._seen: Dict[str, float] = {}
        self._ttl = ttl_sec
        self._lock = Lock()

    def is_duplicate(self, order_id: str, filled_qty: Decimal) -> bool:
        """
        檢查事件是否重複

        Args:
            order_id: 訂單 ID
            filled_qty: 成交數量

        Returns:
            True 如果是重複事件
        """
        key = f"{order_id}:{filled_qty}"
        now = time.time()

        with self._lock:
            # 清理過期記錄
            cutoff = now - self._ttl
            self._seen = {k: t for k, t in self._seen.items() if t > cutoff}

            # 檢查是否已處理
            if key in self._seen:
                return True

            # 標記為已處理
            self._seen[key] = now
            return False

    def clear(self):
        """清除所有記錄"""
        with self._lock:
            self._seen.clear()


# ==================== 下單節流器 ====================
class OrderThrottle:
    """
    下單節流器

    防止在短時間內對同一方向重複下單
    """

    def __init__(self, cooldown_sec: float = 2.0):
        """
        Args:
            cooldown_sec: 下單冷卻時間（秒）
        """
        self._last_order: Dict[str, float] = {}  # side -> timestamp
        self._cooldown = cooldown_sec
        self._lock = Lock()

    def can_place(self, side: str) -> bool:
        """
        檢查是否可以下單（僅檢查，不記錄）

        Args:
            side: 訂單方向 ("buy" or "sell")

        Returns:
            True 如果可以下單
        """
        now = time.time()

        with self._lock:
            last = self._last_order.get(side, 0)
            if now - last < self._cooldown:
                return False
            return True

    def try_acquire(self, side: str) -> bool:
        """
        原子性地檢查並獲取下單權限

        這是推薦使用的方法，可以避免 can_place + record_order 之間的競爭條件。

        Args:
            side: 訂單方向 ("buy" or "sell")

        Returns:
            True 如果獲取成功（同時已記錄時間）
        """
        now = time.time()

        with self._lock:
            last = self._last_order.get(side, 0)
            if now - last < self._cooldown:
                return False
            # 原子性地記錄時間
            self._last_order[side] = now
            return True

    def record_order(self, side: str):
        """
        記錄下單時間（已廢棄，建議使用 try_acquire）

        Args:
            side: 訂單方向 ("buy" or "sell")
        """
        with self._lock:
            self._last_order[side] = time.time()

    def reset(self, side: str = None):
        """
        重置節流器

        Args:
            side: 如果指定，只重置該方向；否則重置全部
        """
        with self._lock:
            if side:
                self._last_order.pop(side, None)
            else:
                self._last_order.clear()


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

    # Maker/Taker 狀態 (rebate 追蹤用)
    # None = unknown (adapter 未實作), True = maker, False = taker
    is_maker: Optional[bool] = None


@dataclass
class OperationRecord:
    """操作歷史記錄"""
    time: str                           # ISO 格式時間
    action: str                         # 'place', 'cancel', 'rebalance', 'fill'
    side: str                           # 'buy' or 'sell'
    order_price: Decimal                # 訂單價格
    best_bid: Optional[Decimal] = None  # 當時最佳買價
    best_ask: Optional[Decimal] = None  # 當時最佳賣價
    reason: str = ""                    # 操作原因

    def to_dict(self) -> Dict:
        """序列化為字典"""
        return {
            "time": self.time,
            "action": self.action,
            "side": self.side,
            "order_price": float(self.order_price) if self.order_price else 0,
            "best_bid": float(self.best_bid) if self.best_bid else None,
            "best_ask": float(self.best_ask) if self.best_ask else None,
            "reason": self.reason,
        }


class MMState:
    """
    做市商狀態管理 (線程安全)

    追蹤:
    - 雙邊訂單 (bid/ask)
    - 倉位 (StandX / GRVT / 通用)
    - 價格歷史 (波動率計算)
    """

    def __init__(self, volatility_window_sec: int = 5):
        self._lock = Lock()

        # 訂單追蹤
        self._bid_order: Optional[OrderInfo] = None
        self._ask_order: Optional[OrderInfo] = None

        # 【新增】通用倉位 map: (exchange, symbol) -> Decimal
        self._positions: Dict[Tuple[str, str], Decimal] = {}

        # 倉位追蹤 (保留舊欄位作為 fallback)
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

        # 操作歷史記錄 (最多保留 50 筆)
        self._operation_history: List[OperationRecord] = []
        self._max_history_size = 50

        # ==================== Rebate 追蹤 (GRVT rebate 模式) ====================
        self._maker_volume: Decimal = Decimal("0")       # Maker 成交額
        self._taker_volume: Decimal = Decimal("0")       # Taker 成交額
        self._rebates_received: Decimal = Decimal("0")   # 收到的 rebate
        self._fees_paid: Decimal = Decimal("0")          # 付出的手續費
        self._hedge_fees: Decimal = Decimal("0")         # 對沖手續費
        self._hedge_slippage: Decimal = Decimal("0")     # 對沖滑點損失
        self._maker_fill_count: int = 0
        self._taker_fill_count: int = 0
        self._unknown_fill_count: int = 0                # adapter 未實作 is_maker
        self._post_only_rejects: int = 0                 # post_only 被拒次數
        self._raw_fee_sum: Decimal = Decimal("0")        # 原始符號費用總和（對帳用）

        # ==================== 保本回補追蹤 ====================
        self._entry_price: Optional[Decimal] = None      # 建倉價格
        self._entry_side: Optional[str] = None           # 建倉方向 ("buy" or "sell")
        self._entry_time: Optional[float] = None         # 建倉時間

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

    # ==================== 倉位管理 (通用) ====================

    def get_position(self, exchange: str, symbol: str) -> Decimal:
        """
        通用倉位獲取 - 必須明確傳 exchange 和 symbol

        Args:
            exchange: 交易所名稱 ("standx", "grvt", etc.)
            symbol: 交易對 ("BTC-USD", "BTC_USDT_Perp", etc.)

        Returns:
            倉位數量 (正=long, 負=short)
        """
        with self._lock:
            return self._positions.get((exchange, symbol), Decimal("0"))

    def set_position(self, exchange: str, symbol: str, pos: Decimal):
        """
        通用倉位設定 - 必須明確傳 exchange 和 symbol

        Args:
            exchange: 交易所名稱 ("standx", "grvt", etc.)
            symbol: 交易對
            pos: 倉位數量 (正=long, 負=short)
        """
        with self._lock:
            self._positions[(exchange, symbol)] = pos
            logger.debug(f"Position set: {exchange}/{symbol} = {pos}")

    # ==================== 保本回補：Entry Price 管理 ====================

    def set_entry_price(self, price: Decimal, side: str):
        """
        記錄建倉價格（用於保本回補）

        Args:
            price: 成交價格
            side: 成交方向 ("buy" or "sell")
        """
        with self._lock:
            self._entry_price = price
            self._entry_side = side
            self._entry_time = time.time()
            logger.info(f"[Breakeven] Entry recorded: {side} @ {price}")

    def get_entry_price(self) -> Optional[Decimal]:
        """獲取建倉價格"""
        with self._lock:
            return self._entry_price

    def get_entry_side(self) -> Optional[str]:
        """獲取建倉方向"""
        with self._lock:
            return self._entry_side

    def get_entry_time(self) -> Optional[float]:
        """獲取建倉時間"""
        with self._lock:
            return self._entry_time

    def clear_entry(self):
        """清除建倉記錄（倉位歸零時調用）"""
        with self._lock:
            self._entry_price = None
            self._entry_side = None
            self._entry_time = None
            logger.info("[Breakeven] Entry cleared")

    def has_entry(self) -> bool:
        """是否有建倉記錄"""
        with self._lock:
            return self._entry_price is not None

    # ==================== 倉位管理 (舊版 - 保留作 fallback) ====================

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

    # ==================== Rebate 追蹤方法 ====================

    def record_rebate_fill(
        self,
        fill_qty: Decimal,
        fill_price: Decimal,
        is_maker: Optional[bool],
        fee_bps: Decimal
    ):
        """
        記錄成交 (rebate 模式) - 保持原始符號

        Args:
            fill_qty: 成交數量
            fill_price: 成交價格
            is_maker: True=maker, False=taker, None=unknown
            fee_bps: 費率 (負數=rebate, 正數=fee)
        """
        notional = fill_qty * fill_price

        # 計算 fee (正=付錢, 負=收錢)
        fee = notional * fee_bps / Decimal("10000")

        with self._lock:
            self._raw_fee_sum += fee  # 保留原始符號方便對帳

            # 記錄 maker/taker/unknown
            if is_maker is True:
                self._maker_volume += notional
                self._maker_fill_count += 1
            elif is_maker is False:
                self._taker_volume += notional
                self._taker_fill_count += 1
            else:
                # is_maker is None → unknown
                self._unknown_fill_count += 1
                logger.warning("Fill without is_maker flag - adapter needs update")

            # 分開記錄收入和支出
            if fee < 0:
                self._rebates_received += abs(fee)
            else:
                self._fees_paid += fee

    def record_hedge_cost(
        self,
        fee_paid: Decimal,
        slippage_loss: Decimal
    ):
        """
        記錄對沖成本 - 拆分手續費和滑點

        Args:
            fee_paid: 對沖手續費
            slippage_loss: 滑點損失 (正數=損失, 負數=獲利)
        """
        with self._lock:
            self._hedge_fees += fee_paid
            self._hedge_slippage += slippage_loss

    def record_post_only_reject(self):
        """記錄 post_only 被拒"""
        with self._lock:
            self._post_only_rejects += 1

    def get_rebate_stats(self) -> Dict:
        """
        獲取 rebate 統計 (含淨收益)

        Returns:
            dict: rebate 相關統計數據
        """
        with self._lock:
            total_costs = self._fees_paid + self._hedge_fees + self._hedge_slippage
            net_profit = self._rebates_received - total_costs
            total_fills = self._maker_fill_count + self._taker_fill_count + self._unknown_fill_count
            maker_ratio = (
                self._maker_fill_count / total_fills * 100
                if total_fills > 0 else 0
            )
            unknown_ratio = (
                self._unknown_fill_count / total_fills * 100
                if total_fills > 0 else 0
            )
            return {
                "maker_volume_usdt": float(self._maker_volume),
                "taker_volume_usdt": float(self._taker_volume),
                "rebates_received_usdt": float(self._rebates_received),
                "fees_paid_usdt": float(self._fees_paid),
                "hedge_fees_usdt": float(self._hedge_fees),
                "hedge_slippage_usdt": float(self._hedge_slippage),
                "raw_fee_sum_usdt": float(self._raw_fee_sum),
                "net_profit_usdt": float(net_profit),
                "total_fills": total_fills,
                "maker_fill_count": self._maker_fill_count,
                "taker_fill_count": self._taker_fill_count,
                "unknown_fill_count": self._unknown_fill_count,
                "maker_ratio_pct": maker_ratio,
                "unknown_ratio_pct": unknown_ratio,
                "post_only_rejects": self._post_only_rejects,
            }

    def record_operation(
        self,
        action: str,
        side: str,
        order_price: Decimal,
        best_bid: Optional[Decimal] = None,
        best_ask: Optional[Decimal] = None,
        reason: str = ""
    ):
        """
        記錄操作到歷史

        Args:
            action: 操作類型 ('place', 'cancel', 'rebalance', 'fill')
            side: 訂單方向 ('buy' or 'sell')
            order_price: 訂單價格
            best_bid: 當時最佳買價
            best_ask: 當時最佳賣價
            reason: 操作原因
        """
        record = OperationRecord(
            time=datetime.now().isoformat(),
            action=action,
            side=side,
            order_price=order_price,
            best_bid=best_bid,
            best_ask=best_ask,
            reason=reason,
        )
        with self._lock:
            self._operation_history.append(record)
            # 保留最近 50 筆
            if len(self._operation_history) > self._max_history_size:
                self._operation_history = self._operation_history[-self._max_history_size:]
        logger.debug(f"Operation recorded: {action} {side} @ {order_price} ({reason})")

    def get_operation_history(self) -> List[Dict]:
        """獲取操作歷史列表"""
        with self._lock:
            return [r.to_dict() for r in self._operation_history]

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

            # StandX Uptime Program 要求雙邊都有訂單才算 qualified
            # 如果缺少任一邊訂單，算作 out of range
            if bid_price is None or ask_price is None:
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
                "uptime_pct": boosted_pct,  # StandX Uptime Program: boosted tier = qualified uptime
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
                "uptime_pct": self._boosted_time_ms / total_time * 100,  # StandX Uptime = boosted tier
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
                "uptime_pct": self._boosted_time_ms / total_time * 100,  # StandX Uptime = boosted tier
                "boosted_pct": self._boosted_time_ms / total_time * 100,
                "standard_pct": self._standard_time_ms / total_time * 100,
                "basic_pct": self._basic_time_ms / total_time * 100,
                "out_of_range_pct": self._out_of_range_time_ms / total_time * 100,
                "effective_pts_pct": (
                    (self._boosted_time_ms * 1.0 + self._standard_time_ms * 0.5 + self._basic_time_ms * 0.1)
                    / total_time * 100
                ),
            }

        # 獲取操作歷史 (需要在鎖外調用以避免死鎖)
        operation_history = [r.to_dict() for r in self._operation_history]

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
            "operation_history": operation_history,
        }
