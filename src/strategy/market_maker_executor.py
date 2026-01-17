"""
做市商執行器
Market Maker Executor

參考 frozen-cherry/standx-mm 的 maker.py 設計
- 事件驅動報價
- 波動率控制
- 即時對沖

流程:
1. 連接 → 同步狀態
2. 收到價格 → 檢查波動率 → 撤單/掛單
3. 收到成交 → 取消另一邊 → 觸發對沖
4. 對沖完成 → 重新掛單
"""
import asyncio
import logging
from typing import Optional, Callable, Awaitable
from decimal import Decimal
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .mm_state import MMState, OrderInfo, FillEvent
from .hedge_engine import HedgeEngine, HedgeResult, HedgeStatus

logger = logging.getLogger(__name__)


class ExecutorStatus(Enum):
    """執行器狀態"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"         # 波動率過高暫停
    HEDGING = "hedging"       # 正在對沖
    ERROR = "error"


@dataclass
class MMConfig:
    """
    做市商配置

    參數說明：
    - order_distance_bps: 掛單距離 mark price，需要 < 10 bps 才符合 uptime
    - cancel_distance_bps: 價格接近訂單時撤單，防止成交
    - rebalance_distance_bps: 價格遠離訂單時撤單重掛，獲得更好價格

    Uptime 策略：
    - 掛單距離 8 bps（留 2 bps 緩衝）
    - 價格靠近 3 bps 時撤單（避免成交）
    - 價格遠離 12 bps 時重掛（超出 10 bps uptime 要求後再 2 bps）
    """
    # 交易對（通用）
    symbol: str = "BTC-USD"              # 主交易對
    hedge_symbol: str = "BTC_USDT_Perp"  # 對沖交易對
    hedge_exchange: str = "grvt"         # 對沖交易所 ("grvt", "standx", "binance")

    # 報價參數 (優化版：8 bps 掛單距離，留緩衝給 uptime)
    order_distance_bps: int = 8          # 掛單距離 mark price (< 10 bps 符合 uptime)
    cancel_distance_bps: int = 3         # 價格靠近時撤單（防止成交）
    rebalance_distance_bps: int = 12     # 價格遠離時撤單重掛 (超出 10 bps 後)

    # 倉位參數
    order_size_btc: Decimal = Decimal("0.001")   # 單邊訂單量
    max_position_btc: Decimal = Decimal("0.01")  # 最大持倉

    # 波動率控制 (frozen-cherry 默認值)
    volatility_window_sec: int = 5       # 波動率窗口
    volatility_threshold_bps: float = 5.0  # 超過則暫停（更保守）

    # 訂單參數
    order_type: str = "limit"            # 使用 limit 單
    time_in_force: str = "gtc"           # good-til-cancel

    # 執行參數
    tick_interval_ms: int = 100          # 主循環間隔
    dry_run: bool = False                # 模擬模式
    disappear_time_sec: float = 2.0      # 訂單消失判定時間（秒）


class MarketMakerExecutor:
    """
    做市商執行器

    職責:
    1. 管理雙邊報價 (bid/ask)
    2. 響應價格更新 (撤單/重掛)
    3. 處理成交事件 (觸發對沖)
    4. 對沖完成後重新報價
    """

    def __init__(
        self,
        standx_adapter,         # StandXAdapter
        hedge_adapter=None,     # GRVT 適配器 (用於對沖)
        hedge_engine: Optional[HedgeEngine] = None,  # 可選，沒有則不對沖
        config: Optional[MMConfig] = None,
        state: Optional[MMState] = None,
    ):
        self.standx = standx_adapter
        self.hedge_adapter = hedge_adapter
        self.hedge_engine = hedge_engine
        self.config = config or MMConfig()
        self.state = state or MMState(volatility_window_sec=self.config.volatility_window_sec)

        # 執行器狀態
        self._status = ExecutorStatus.STOPPED
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # 最新價格
        self._last_mid_price: Optional[Decimal] = None
        self._last_best_bid: Optional[Decimal] = None
        self._last_best_ask: Optional[Decimal] = None

        # 回調
        self._on_status_change: Optional[Callable[[ExecutorStatus], Awaitable[None]]] = None
        self._on_fill: Optional[Callable[[FillEvent], Awaitable[None]]] = None
        self._on_hedge: Optional[Callable[[HedgeResult], Awaitable[None]]] = None

        # 統計
        self._total_quotes = 0
        self._total_cancels = 0
        self._started_at: Optional[datetime] = None

        # 重入保護鎖
        self._fill_lock = asyncio.Lock()

    # ==================== 生命週期 ====================

    async def start(self):
        """啟動做市"""
        if self._running:
            logger.warning("Executor already running")
            return

        logger.info("Starting Market Maker Executor...")
        self._status = ExecutorStatus.STARTING

        try:
            # 初始化：同步狀態
            await self._initialize()

            # 啟動主循環
            self._running = True
            self._status = ExecutorStatus.RUNNING
            self._started_at = datetime.now()

            if self._on_status_change:
                await self._on_status_change(self._status)

            logger.info("Market Maker Executor started")

            # 如果使用 WebSocket，等待事件
            # 否則使用輪詢模式
            self._task = asyncio.create_task(self._run_loop())

        except Exception as e:
            self._status = ExecutorStatus.ERROR
            logger.error(f"Failed to start executor: {e}")
            raise

    async def stop(self):
        """停止做市"""
        if not self._running:
            return

        logger.info("Stopping Market Maker Executor...")
        self._running = False

        # 取消主循環
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # 撤銷所有訂單
        await self._cancel_all_orders(reason="stop")

        self._status = ExecutorStatus.STOPPED
        if self._on_status_change:
            await self._on_status_change(self._status)

        logger.info("Market Maker Executor stopped")

    async def _initialize(self):
        """初始化：同步狀態"""
        logger.info("Initializing executor state...")

        # 同步 StandX 倉位
        await self._sync_standx_position()

        # 同步對沖倉位 (如果有 hedge adapter)
        if self.hedge_adapter:
            await self._sync_hedge_position()

        # 取消現有訂單
        if not self.config.dry_run:
            logger.info(f"[Init] Checking existing orders (dry_run={self.config.dry_run})")
            await self._cancel_all_existing_orders()
        else:
            logger.info(f"[Init] Skipping order cancel in dry_run mode")

        logger.info("Executor initialized")

    async def _cancel_all_existing_orders(self):
        """取消交易所上的所有現有訂單"""
        logger.info(f"[Cancel] Querying open orders for {self.config.symbol}")
        try:
            open_orders = await self.standx.get_open_orders(self.config.symbol)
            logger.info(f"[Cancel] Found {len(open_orders)} open orders")
            if open_orders:
                logger.info(f"Cancelling {len(open_orders)} existing orders on StandX")
                for order in open_orders:
                    try:
                        logger.info(f"[Cancel] Cancelling order: {order.client_order_id} (order_id={order.order_id}) @ {order.price}")
                        # 使用 client_order_id 作為關鍵字參數
                        await self.standx.cancel_order(
                            symbol=self.config.symbol,
                            client_order_id=order.client_order_id
                        )
                        logger.info(f"Cancelled existing order: {order.client_order_id}")
                    except Exception as e:
                        logger.warning(f"Failed to cancel order {order.client_order_id}: {e}")
            else:
                logger.info("No existing orders to cancel")
        except Exception as e:
            logger.error(f"Failed to get existing orders: {e}", exc_info=True)

    # ==================== 主循環 ====================

    async def _run_loop(self):
        """主循環 (輪詢模式)"""
        while self._running:
            try:
                await self._tick()
                await asyncio.sleep(self.config.tick_interval_ms / 1000)

            except asyncio.CancelledError:
                break

            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                await asyncio.sleep(1)  # 錯誤後等待

    async def _tick(self):
        """單次執行"""
        # 如果正在對沖，跳過
        if self._status == ExecutorStatus.HEDGING:
            return

        # 如果在 PAUSED 狀態（風控模式），檢查是否可以恢復
        if self._status == ExecutorStatus.PAUSED and self.hedge_engine:
            if await self.hedge_engine.check_recovery():
                logger.info("GRVT recovered, resuming market making")
                self._status = ExecutorStatus.RUNNING
                if self._on_status_change:
                    await self._on_status_change(self._status)

        # 獲取最新價格
        try:
            orderbook = await self.standx.get_orderbook(self.config.symbol)
            if not orderbook or not orderbook.bids or not orderbook.asks:
                return

            best_bid = orderbook.bids[0][0]
            best_ask = orderbook.asks[0][0]
            mid_price = (best_bid + best_ask) / 2

            self._last_mid_price = mid_price
            self._last_best_bid = best_bid
            self._last_best_ask = best_ask
            self.state.update_price(mid_price)

            # 更新 uptime 統計
            bid_order = self.state.get_bid_order()
            ask_order = self.state.get_ask_order()
            bid_price = bid_order.price if bid_order else None
            ask_price = ask_order.price if ask_order else None
            self.state.update_uptime(mid_price, bid_price, ask_price)

        except Exception as e:
            logger.error(f"Failed to get orderbook: {e}")
            return

        # 檢查訂單狀態 (輪詢模式：檢測成交)
        if not self.config.dry_run:
            await self._check_order_status()
            # 如果成交後進入對沖狀態，不繼續下單
            if self._status == ExecutorStatus.HEDGING:
                return

        # 檢查波動率
        volatility = self.state.get_volatility_bps()
        if volatility > self.config.volatility_threshold_bps:
            if self._status != ExecutorStatus.PAUSED:
                logger.warning(f"High volatility: {volatility:.1f} bps, pausing")
                self._status = ExecutorStatus.PAUSED
                self.state.record_volatility_pause()  # 記錄波動率暫停
                await self._cancel_all_orders(reason="high volatility")
                if self._on_status_change:
                    await self._on_status_change(self._status)
            return
        elif self._status == ExecutorStatus.PAUSED:
            logger.info(f"Volatility normalized: {volatility:.1f} bps, resuming")
            self._status = ExecutorStatus.RUNNING
            if self._on_status_change:
                await self._on_status_change(self._status)

        # 檢查是否需要撤單 (價格太近)
        orders_to_cancel = self.state.get_orders_to_cancel(
            mid_price,
            self.config.cancel_distance_bps
        )
        for client_order_id in orders_to_cancel:
            # 判斷是買單還是賣單
            bid = self.state.get_bid_order()
            ask = self.state.get_ask_order()
            if bid and bid.client_order_id == client_order_id:
                self.state.record_cancel("buy", "price")
            elif ask and ask.client_order_id == client_order_id:
                self.state.record_cancel("sell", "price")
            await self._cancel_order(client_order_id, reason="price too close")

        # 檢查是否需要重掛 (價格太遠)
        should_rebalance = self.state.should_rebalance_orders(
            mid_price,
            self.config.rebalance_distance_bps
        )
        if should_rebalance:
            # 記錄重掛
            if self.state.has_bid_order():
                self.state.record_rebalance("buy")
            if self.state.has_ask_order():
                self.state.record_rebalance("sell")
            await self._cancel_all_orders(reason="rebalance")

        # 掛單（傳遞 best_bid/best_ask 以確保不穿透價差）
        await self._place_orders(mid_price, best_bid, best_ask)

    # ==================== 訂單管理 ====================

    async def _place_orders(self, mid_price: Decimal, best_bid: Optional[Decimal] = None, best_ask: Optional[Decimal] = None):
        """掛雙邊訂單"""
        # 防禦性檢查：只在 RUNNING 狀態下掛單
        if self._status != ExecutorStatus.RUNNING:
            logger.debug(f"Skipping order placement, status={self._status}")
            return

        # 獲取當前倉位 (正=long, 負=short)
        current_position = self.state.get_standx_position()
        max_pos = self.config.max_position_btc

        # 計算報價
        bid_price, ask_price = self._calculate_prices(mid_price, best_bid, best_ask)

        # 掛買單 - 如果已經 long 太多，不再買入
        if current_position >= max_pos:
            logger.debug(f"Position too long ({current_position}), skipping bid")
        elif self.state.has_bid_order():
            logger.debug("Already have bid order, skipping")
        else:
            await self._place_bid(bid_price)

        # 掛賣單 - 如果已經 short 太多，不再賣出
        if current_position <= -max_pos:
            logger.debug(f"Position too short ({current_position}), skipping ask")
        elif self.state.has_ask_order():
            logger.debug("Already have ask order, skipping")
        else:
            await self._place_ask(ask_price)

    def _calculate_prices(
        self,
        mid_price: Decimal,
        best_bid: Optional[Decimal] = None,
        best_ask: Optional[Decimal] = None
    ) -> tuple[Decimal, Decimal]:
        """
        計算報價

        正確策略：
        - bid_price = best_bid * (1 - order_distance_bps / 10000)
        - ask_price = best_ask * (1 + order_distance_bps / 10000)

        從 best_bid/best_ask 計算，而非從 mid_price 計算
        """
        distance_ratio = Decimal(self.config.order_distance_bps) / Decimal("10000")

        # 從 best_bid/best_ask 計算報價（而非 mid_price）
        bid_price = best_bid * (Decimal("1") - distance_ratio)
        ask_price = best_ask * (Decimal("1") + distance_ratio)

        # 對齊到 tick size (floor for buy, ceil for sell)
        import math
        tick_size = Decimal("0.01")

        # Floor for buy (更保守的買價)
        bid_price = Decimal(str(math.floor(float(bid_price) / float(tick_size)) * float(tick_size)))
        # Ceil for sell (更保守的賣價)
        ask_price = Decimal(str(math.ceil(float(ask_price) / float(tick_size)) * float(tick_size)))

        logger.debug(
            f"Quote prices: bid={bid_price} (from best_bid={best_bid}), "
            f"ask={ask_price} (from best_ask={best_ask}), "
            f"distance={self.config.order_distance_bps}bps"
        )

        return bid_price, ask_price

    async def _place_bid(self, price: Decimal):
        """掛買單"""
        if self.config.dry_run:
            logger.info(f"[DRY RUN] Would place bid: {self.config.order_size_btc} @ {price}")
            return

        try:
            order = await self.standx.place_order(
                symbol=self.config.symbol,
                side="buy",
                order_type=self.config.order_type,
                quantity=self.config.order_size_btc,
                price=price,
                time_in_force=self.config.time_in_force,
            )

            order_info = OrderInfo(
                order_id=order.order_id,
                client_order_id=order.client_order_id,
                side="buy",
                price=price,
                qty=self.config.order_size_btc,
                status="pending",
            )
            self.state.set_bid_order(order_info)
            self._total_quotes += 1

            # 記錄操作歷史
            self.state.record_operation(
                action="place",
                side="buy",
                order_price=price,
                best_bid=self._last_best_bid,
                best_ask=self._last_best_ask,
                reason="new order",
            )

            logger.info(f"Bid placed: {self.config.order_size_btc} @ {price}")

        except Exception as e:
            logger.error(f"Failed to place bid: {e}")

    async def _place_ask(self, price: Decimal):
        """掛賣單"""
        if self.config.dry_run:
            logger.info(f"[DRY RUN] Would place ask: {self.config.order_size_btc} @ {price}")
            return

        try:
            order = await self.standx.place_order(
                symbol=self.config.symbol,
                side="sell",
                order_type=self.config.order_type,
                quantity=self.config.order_size_btc,
                price=price,
                time_in_force=self.config.time_in_force,
            )

            order_info = OrderInfo(
                order_id=order.order_id,
                client_order_id=order.client_order_id,
                side="sell",
                price=price,
                qty=self.config.order_size_btc,
                status="pending",
            )
            self.state.set_ask_order(order_info)
            self._total_quotes += 1

            # 記錄操作歷史
            self.state.record_operation(
                action="place",
                side="sell",
                order_price=price,
                best_bid=self._last_best_bid,
                best_ask=self._last_best_ask,
                reason="new order",
            )

            logger.info(f"Ask placed: {self.config.order_size_btc} @ {price}")

        except Exception as e:
            logger.error(f"Failed to place ask: {e}")

    async def _cancel_order(self, client_order_id: str, reason: str = ""):
        """撤銷單個訂單（帶容錯處理）"""
        # 先獲取訂單信息以記錄操作歷史
        bid = self.state.get_bid_order()
        ask = self.state.get_ask_order()
        order_side = None
        order_price = Decimal("0")
        if bid and bid.client_order_id == client_order_id:
            order_side = "buy"
            order_price = bid.price
        elif ask and ask.client_order_id == client_order_id:
            order_side = "sell"
            order_price = ask.price

        if self.config.dry_run:
            logger.info(f"[DRY RUN] Would cancel order: {client_order_id}")
            return

        try:
            await self.standx.cancel_order(
                symbol=self.config.symbol,
                client_order_id=client_order_id,
            )
            self._total_cancels += 1

            # 記錄操作歷史
            if order_side:
                self.state.record_operation(
                    action="cancel",
                    side=order_side,
                    order_price=order_price,
                    best_bid=self._last_best_bid,
                    best_ask=self._last_best_ask,
                    reason=reason or "manual cancel",
                )

            logger.info(f"Order cancelled: {client_order_id}")

        except Exception as e:
            # 優先用 error code
            error_code = getattr(e, 'code', None) or getattr(e, 'error_code', None)
            error_msg = str(e).lower()

            # 這些情況視為正常（訂單已經不存在）
            ok_codes = ['ORDER_NOT_FOUND', 'ALREADY_FILLED', 'ALREADY_CANCELED']
            ok_keywords = ['not found', 'already', 'filled', 'canceled', 'cancelled', 'does not exist']

            if error_code in ok_codes or any(kw in error_msg for kw in ok_keywords):
                logger.info(f"Order already gone: {client_order_id} (code={error_code})")
            else:
                logger.error(f"Failed to cancel order {client_order_id}: {e}")

        # 無論如何都清除本地狀態
        self._clear_order_by_id(client_order_id)

    def _clear_order_by_id(self, client_order_id: str):
        """根據 client_order_id 清除本地訂單狀態"""
        bid = self.state.get_bid_order()
        ask = self.state.get_ask_order()

        if bid and bid.client_order_id == client_order_id:
            self.state.clear_bid_order()
        elif ask and ask.client_order_id == client_order_id:
            self.state.clear_ask_order()

    async def _cancel_all_orders(self, reason: str = ""):
        """撤銷所有訂單"""
        bid = self.state.get_bid_order()
        ask = self.state.get_ask_order()

        tasks = []
        if bid and bid.status in ["pending", "open"]:
            tasks.append(self._cancel_order(bid.client_order_id, reason=reason))
        if ask and ask.status in ["pending", "open"]:
            tasks.append(self._cancel_order(ask.client_order_id, reason=reason))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        self.state.clear_all_orders()

    async def _check_order_status(self):
        """
        改進的訂單狀態檢測

        功能：
        1. 檢測部分成交（通過 remaining_qty 變化）
        2. 檢測訂單消失（等待時間閾值後處理）
        3. API 失敗時不推進 disappeared_since_ts
        """
        import time

        bid = self.state.get_bid_order()
        ask = self.state.get_ask_order()

        if not bid and not ask:
            return  # 沒有訂單需要檢查

        # API 調用可能失敗，需要容錯
        try:
            open_orders = await self.standx.get_open_orders(self.config.symbol)
        except Exception as e:
            logger.warning(f"Failed to get open orders: {e}")
            # API 失敗時，不推進 disappeared_since_ts
            return

        open_order_map = {o.client_order_id: o for o in open_orders}

        # 收集消失的訂單（統一處理）
        disappeared_orders = []

        for order in [bid, ask]:
            if not order:
                continue

            if order.client_order_id in open_order_map:
                # 訂單仍存在
                remote = open_order_map[order.client_order_id]
                order.disappeared_since_ts = None  # 重置

                # 部分成交檢測（用 delta）
                if hasattr(remote, 'remaining_qty') and remote.remaining_qty is not None:
                    # 容忍 remote 可能回傳 float
                    remote_remaining = Decimal(str(remote.remaining_qty))
                    filled_delta = order.last_remaining_qty - remote_remaining

                    # filled_delta 非負保護
                    if filled_delta < Decimal("0"):
                        logger.warning(
                            f"Negative filled_delta detected: {filled_delta}, "
                            f"local={order.last_remaining_qty}, remote={remote_remaining}"
                        )
                        # 可能是 API 延遲或數據不一致，用 remote 校正本地
                        order.last_remaining_qty = remote_remaining
                        filled_delta = Decimal("0")

                    if filled_delta > Decimal("0"):
                        logger.info(f"Partial fill detected: {order.client_order_id}, delta={filled_delta}")
                        order.cum_filled_qty += filled_delta
                        order.last_remaining_qty = remote_remaining
                        order.status = "partially_filled"
                        await self._handle_partial_fill(order, filled_delta)

            else:
                # 訂單消失
                now = time.time()
                if order.disappeared_since_ts is None:
                    order.disappeared_since_ts = now
                    logger.debug(f"Order disappeared: {order.client_order_id}")
                elif now - order.disappeared_since_ts >= self.config.disappear_time_sec:
                    # 消失超過時間閾值
                    disappeared_orders.append(order)

        # 統一處理消失的訂單
        if disappeared_orders:
            await self._handle_disappeared_orders(disappeared_orders)

    async def _handle_partial_fill(self, order: OrderInfo, filled_delta: Decimal):
        """
        處理部分成交

        策略：
        - 記錄部分成交事件
        - 不立刻撤銷另一邊訂單（避免自我打斷）
        - 讓正常的訂單管理流程在下一個 tick 處理價格調整
        """
        logger.info(
            f"Partial fill: {order.client_order_id}, "
            f"filled={filled_delta}, cum_filled={order.cum_filled_qty}, "
            f"remaining={order.last_remaining_qty}"
        )

        # 記錄部分成交事件（可用於統計和監控）
        self.state.record_partial_fill()

        # 【重要】不在這裡 cancel 另一邊
        # 原因：
        # 1. 避免在快速連續成交時造成不必要的撤單
        # 2. 讓 _place_orders() 在下一個 tick 根據倉位和價格決定是否需要調整
        # 3. 如果需要對沖，會由 on_fill_event() 處理

        # 注意：部分成交不會立即觸發對沖，等完全成交或消失後再處理

    async def _handle_disappeared_orders(self, orders: list):
        """
        統一處理消失的訂單

        策略：
        - 單張消失：用倉位變化推斷，delta=0 需多輪確認
        - 多張消失：先 sync position，若 delta!=0 記 unknown_fill
        """
        # 先同步倉位（無論單張多張）
        old_position = self.state.get_standx_position()
        await self._sync_standx_position()
        new_position = self.state.get_standx_position()
        position_delta = new_position - old_position

        if len(orders) > 1:
            # 【保險絲 1】多張同時消失
            logger.warning(f"Multiple orders disappeared simultaneously: {[o.client_order_id for o in orders]}")

            if position_delta != Decimal("0"):
                # 倉位有變化 → 可能是雙邊都成交，記錄 unknown_fill
                logger.warning(
                    f"Position changed while multiple orders disappeared: "
                    f"delta={position_delta}, recording unknown_fill_detected"
                )
                self.state.record_unknown_fill_detected()

            # 清除所有消失的訂單
            for order in orders:
                order.status = "canceled_or_unknown"
                order.disappeared_since_ts = None
                order.unknown_pending_checks = 0
                self.state.record_order_canceled_or_unknown()
                self._clear_order(order.side)
            return

        # 單張消失，用倉位變化判斷
        order = orders[0]

        # 用 remaining_qty 而不是 orig_qty
        remaining_qty = order.last_remaining_qty
        expected_delta = remaining_qty if order.side == "buy" else -remaining_qty

        tolerance = Decimal("0.0001")

        if abs(position_delta - expected_delta) < tolerance:
            # 倉位變化符合預期 → 完全成交
            logger.info(f"Order filled (position confirmed): {order.client_order_id}")
            await self._on_fill_confirmed(order, remaining_qty)
            # 更新本地狀態
            order.status = "filled"
            order.cum_filled_qty += remaining_qty
            order.last_remaining_qty = Decimal("0")
            order.disappeared_since_ts = None
            order.unknown_pending_checks = 0
            self.state.record_order_filled()
            self._clear_order(order.side)

        elif position_delta != Decimal("0") and abs(position_delta) < abs(expected_delta):
            # 部分成交後消失（可能是剩餘被取消）
            filled_qty = abs(position_delta)
            logger.info(f"Order partially filled then disappeared: {order.client_order_id}, qty={filled_qty}")
            await self._on_fill_confirmed(order, filled_qty)
            # 更新本地狀態
            order.status = "filled"  # 部分成交後消失，視為已結束
            order.cum_filled_qty += filled_qty
            order.last_remaining_qty = Decimal("0")
            order.disappeared_since_ts = None
            order.unknown_pending_checks = 0
            self.state.record_order_filled()
            self._clear_order(order.side)

        else:
            # 【保險絲 2】倉位無預期變化 → 先標 unknown_pending，多輪確認
            order.unknown_pending_checks += 1
            CONFIRM_THRESHOLD = 2  # 需要連續 2 次確認

            if order.unknown_pending_checks >= CONFIRM_THRESHOLD:
                # 多次確認倉位都沒變化 → 確定是 canceled
                logger.info(
                    f"Order disappeared confirmed (no position change after {CONFIRM_THRESHOLD} checks): "
                    f"{order.client_order_id}"
                )
                order.status = "canceled_or_unknown"
                order.disappeared_since_ts = None
                order.unknown_pending_checks = 0
                self.state.record_order_canceled_or_unknown()
                self._clear_order(order.side)
            else:
                # 還需要再確認
                logger.info(
                    f"Order disappeared but position unchanged, pending confirmation "
                    f"({order.unknown_pending_checks}/{CONFIRM_THRESHOLD}): {order.client_order_id}"
                )

    def _clear_order(self, side: str):
        """清除指定邊的訂單"""
        if side == "buy":
            self.state.clear_bid_order()
        else:
            self.state.clear_ask_order()

    async def _on_fill_confirmed(self, order: OrderInfo, fill_qty: Decimal):
        """成交確認處理（帶 Lock 保護，不會丟失事件）"""
        async with self._fill_lock:
            # 優先用真實成交價，沒有則用掛單價並標記
            fill_price = order.price  # fallback，目前無法獲取真實成交價
            logger.debug(f"Using order price as fill price: {fill_price}")

            fill_event = FillEvent(
                order_id=order.order_id,
                client_order_id=order.client_order_id,
                symbol=self.config.symbol,
                side=order.side,
                fill_qty=fill_qty,
                fill_price=fill_price,
                remaining_qty=order.last_remaining_qty,
                is_fully_filled=(order.last_remaining_qty == Decimal("0")),
                timestamp=datetime.now(),
            )

            await self.on_fill_event(fill_event)

    # ==================== 成交處理 ====================

    async def _sync_standx_position(self) -> Decimal:
        """從 StandX 同步實際倉位"""
        try:
            positions = await self.standx.get_positions(self.config.symbol)
            for pos in positions:
                if pos.symbol == self.config.symbol:
                    position_qty = Decimal(str(pos.size)) if pos.side == "long" else -Decimal(str(pos.size))
                    self.state.set_standx_position(position_qty)
                    logger.info(f"[Sync] StandX position: {position_qty}")
                    return position_qty
            # 沒有找到倉位，設為 0
            self.state.set_standx_position(Decimal("0"))
            logger.info("[Sync] StandX position: 0 (no position found)")
            return Decimal("0")
        except Exception as e:
            logger.error(f"Failed to sync StandX position: {e}")
            return self.state.get_standx_position()

    async def _sync_hedge_position(self) -> Decimal:
        """從對沖交易所 (GRVT) 同步實際倉位"""
        if not self.hedge_adapter:
            return Decimal("0")
        try:
            # 自動匹配交易對
            hedge_symbol = self.config.hedge_symbol
            if self.hedge_engine:
                hedge_symbol = self.hedge_engine._match_hedge_symbol(
                    self.config.symbol
                ) or hedge_symbol

            positions = await self.hedge_adapter.get_positions(hedge_symbol)
            for pos in positions:
                if hedge_symbol in pos.symbol or pos.symbol == hedge_symbol:
                    position_qty = Decimal(str(pos.size)) if pos.side == "long" else -Decimal(str(pos.size))
                    self.state.set_hedge_position(position_qty)
                    logger.info(f"[Sync] Hedge (GRVT) position: {position_qty}")
                    return position_qty
            # 沒有找到倉位，設為 0
            self.state.set_hedge_position(Decimal("0"))
            logger.info("[Sync] Hedge (GRVT) position: 0 (no position found)")
            return Decimal("0")
        except Exception as e:
            logger.error(f"Failed to sync hedge position: {e}")
            return self.state.get_hedge_position()

    async def on_fill_event(self, fill: FillEvent):
        """
        處理成交事件 (由 WebSocket 回調觸發)

        流程:
        1. 同步倉位（從交易所查詢實際倉位）
        2. 取消另一邊訂單
        3. 執行對沖（如果有 hedge_engine）
        4. 對沖完成後同步倉位並重新掛單

        【保險絲 3】使用 try/finally 確保狀態回復
        """
        logger.info(f"Fill received: {fill.side} {fill.fill_qty} @ {fill.fill_price}")

        # 更新狀態
        self.state.record_fill()

        # 記錄操作歷史
        self.state.record_operation(
            action="fill",
            side=fill.side,
            order_price=fill.fill_price,
            best_bid=self._last_best_bid,
            best_ask=self._last_best_ask,
            reason=f"qty={fill.fill_qty}",
        )

        # 同步 StandX 實際倉位（而不是本地計算）
        await self._sync_standx_position()

        # 取消另一邊訂單（成交後取消對手方）
        await self._cancel_all_orders(reason="fill received")

        # 【保險絲 3】只有在有 hedge_engine 時才進入 HEDGING 狀態
        # 避免監控誤判系統在對沖
        should_hedge = self.hedge_engine is not None

        if should_hedge:
            self._status = ExecutorStatus.HEDGING
            if self._on_status_change:
                await self._on_status_change(self._status)

        try:
            # 觸發回調
            if self._on_fill:
                await self._on_fill(fill)

            # 執行對沖 (如果有對沖引擎)
            if should_hedge:
                hedge_result = await self.hedge_engine.execute_hedge(
                    fill_id=fill.order_id,
                    fill_side=fill.side,
                    fill_qty=fill.fill_qty,
                    fill_price=fill.fill_price,
                    standx_symbol=self.config.symbol,
                )

                # 記錄對沖結果
                self.state.record_hedge(hedge_result.success)

                # 對沖完成後，同步對沖交易所實際倉位
                await self._sync_hedge_position()

                # 如果對沖回退，重新同步 StandX 倉位
                if hedge_result.status in [HedgeStatus.FALLBACK, HedgeStatus.PARTIAL_FALLBACK]:
                    await self._sync_standx_position()

                # 根據對沖結果決定狀態（風控模式）
                if hedge_result.status in [
                    HedgeStatus.RISK_CONTROL,
                    HedgeStatus.WAITING_RECOVERY,
                    HedgeStatus.PARTIAL_FALLBACK,
                    HedgeStatus.FALLBACK_FAILED,
                ]:
                    # 進入 PAUSED 狀態，停止掛單
                    self._status = ExecutorStatus.PAUSED
                    logger.warning(f"Entering PAUSED due to hedge failure: {hedge_result.status.value}")
                    # 撤銷所有訂單
                    await self._cancel_all_orders(reason="hedge failure")
                    if self._on_status_change:
                        await self._on_status_change(self._status)
                    # 不恢復 RUNNING，等待 check_recovery
                    return

                # 觸發對沖回調
                if self._on_hedge:
                    await self._on_hedge(hedge_result)

                logger.info(
                    f"Hedge completed: {hedge_result.status.value}, "
                    f"latency: {hedge_result.latency_ms:.0f}ms"
                )
            else:
                logger.warning(f"No hedge engine, position unhedged")

        except Exception as e:
            logger.error(f"Error during fill processing: {e}", exc_info=True)

        finally:
            # 【保險絲 3】無論如何都恢復報價狀態
            if should_hedge or self._status == ExecutorStatus.HEDGING:
                self._status = ExecutorStatus.RUNNING
                if self._on_status_change:
                    await self._on_status_change(self._status)

    # ==================== 回調註冊 ====================

    def on_status_change(self, callback: Callable[[ExecutorStatus], Awaitable[None]]):
        """註冊狀態變化回調"""
        self._on_status_change = callback

    def set_on_fill_callback(self, callback: Callable[[FillEvent], Awaitable[None]]):
        """註冊成交回調"""
        self._on_fill = callback

    def set_on_hedge_callback(self, callback: Callable[[HedgeResult], Awaitable[None]]):
        """註冊對沖回調"""
        self._on_hedge = callback

    # ==================== 狀態和統計 ====================

    @property
    def status(self) -> ExecutorStatus:
        """獲取狀態"""
        return self._status

    @property
    def is_running(self) -> bool:
        """是否運行中"""
        return self._running

    def get_stats(self) -> dict:
        """獲取統計"""
        uptime = None
        if self._started_at:
            uptime = (datetime.now() - self._started_at).total_seconds()

        return {
            "status": self._status.value,
            "uptime_seconds": uptime,
            "total_quotes": self._total_quotes,
            "total_cancels": self._total_cancels,
            "last_mid_price": float(self._last_mid_price) if self._last_mid_price else None,
            "volatility_bps": self.state.get_volatility_bps(),
            **self.state.get_stats(),
            "hedge_stats": self.hedge_engine.get_stats() if self.hedge_engine else None,
        }

    def to_dict(self) -> dict:
        """序列化"""
        return {
            "config": {
                "symbol": self.config.symbol,
                "hedge_symbol": self.config.hedge_symbol,
                "order_distance_bps": self.config.order_distance_bps,
                "order_size_btc": float(self.config.order_size_btc),
                "max_position_btc": float(self.config.max_position_btc),
                "volatility_threshold_bps": self.config.volatility_threshold_bps,
                "dry_run": self.config.dry_run,
            },
            "state": self.state.to_dict(),
            "stats": self.get_stats(),
        }
