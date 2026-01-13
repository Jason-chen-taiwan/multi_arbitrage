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

    參數說明 (參考 frozen-cherry/standx-mm)：
    - order_distance_bps: 掛單距離 mark price，需要在 10 bps 內才符合 uptime
    - cancel_distance_bps: 價格接近訂單時撤單，防止成交
    - rebalance_distance_bps: 價格遠離訂單時撤單重掛，獲得更好價格
    """
    # 交易對
    standx_symbol: str = "BTC-USD"
    binance_symbol: str = "BTC/USDT:USDT"

    # 報價參數 (frozen-cherry 默認值)
    order_distance_bps: int = 10         # 掛單距離 mark price (需 ≤10 bps 符合 uptime)
    cancel_distance_bps: int = 5         # 價格靠近時撤單（防止成交）
    rebalance_distance_bps: int = 20     # 價格遠離時撤單重掛

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
        binance_adapter,        # CCXTAdapter
        hedge_engine: HedgeEngine,
        config: Optional[MMConfig] = None,
        state: Optional[MMState] = None,
    ):
        self.standx = standx_adapter
        self.binance = binance_adapter
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
        await self._cancel_all_orders()

        self._status = ExecutorStatus.STOPPED
        if self._on_status_change:
            await self._on_status_change(self._status)

        logger.info("Market Maker Executor stopped")

    async def _initialize(self):
        """初始化：同步狀態"""
        logger.info("Initializing executor state...")

        # 查詢 StandX 倉位
        try:
            positions = await self.standx.get_positions(self.config.standx_symbol)
            for pos in positions:
                if pos.symbol == self.config.standx_symbol:
                    # 根據 side 設置正負
                    position_qty = pos.size if pos.side == "long" else -pos.size
                    self.state.set_standx_position(position_qty)
                    logger.info(f"StandX position: {position_qty}")
                    break
        except Exception as e:
            logger.warning(f"Failed to get StandX positions: {e}")

        # 查詢 Binance 倉位
        try:
            positions = await self.binance.get_positions(self.config.binance_symbol)
            for pos in positions:
                if self.config.binance_symbol in pos.symbol:
                    position_qty = pos.size if pos.side == "long" else -pos.size
                    self.state.set_binance_position(position_qty)
                    logger.info(f"Binance position: {position_qty}")
                    break
        except Exception as e:
            logger.warning(f"Failed to get Binance positions: {e}")

        # 取消現有訂單
        await self._cancel_all_orders()

        logger.info("Executor initialized")

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

        # 獲取最新價格
        try:
            orderbook = await self.standx.get_orderbook(self.config.standx_symbol)
            if not orderbook or not orderbook.bids or not orderbook.asks:
                return

            best_bid = orderbook.bids[0][0]
            best_ask = orderbook.asks[0][0]
            mid_price = (best_bid + best_ask) / 2

            self._last_mid_price = mid_price
            self._last_best_bid = best_bid
            self._last_best_ask = best_ask
            self.state.update_price(mid_price)

        except Exception as e:
            logger.error(f"Failed to get orderbook: {e}")
            return

        # 檢查波動率
        volatility = self.state.get_volatility_bps()
        if volatility > self.config.volatility_threshold_bps:
            if self._status != ExecutorStatus.PAUSED:
                logger.warning(f"High volatility: {volatility:.1f} bps, pausing")
                self._status = ExecutorStatus.PAUSED
                await self._cancel_all_orders()
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
            await self._cancel_order(client_order_id)

        # 檢查是否需要重掛 (價格太遠)
        should_rebalance = self.state.should_rebalance_orders(
            mid_price,
            self.config.rebalance_distance_bps
        )
        if should_rebalance:
            await self._cancel_all_orders()

        # 掛單（傳遞 best_bid/best_ask 以確保不穿透價差）
        await self._place_orders(mid_price, best_bid, best_ask)

    # ==================== 訂單管理 ====================

    async def _place_orders(self, mid_price: Decimal, best_bid: Optional[Decimal] = None, best_ask: Optional[Decimal] = None):
        """掛雙邊訂單"""
        # 檢查倉位限制
        current_position = abs(self.state.get_standx_position())
        if current_position >= self.config.max_position_btc:
            logger.warning(f"Position limit reached: {current_position}")
            return

        # 計算報價
        bid_price, ask_price = self._calculate_prices(mid_price, best_bid, best_ask)

        # 掛買單
        if not self.state.has_bid_order():
            await self._place_bid(bid_price)

        # 掛賣單
        if not self.state.has_ask_order():
            await self._place_ask(ask_price)

    def _calculate_prices(
        self,
        mid_price: Decimal,
        best_bid: Optional[Decimal] = None,
        best_ask: Optional[Decimal] = None
    ) -> tuple[Decimal, Decimal]:
        """
        計算報價

        策略 (參考 frozen-cherry/standx-mm)：
        1. 從 mark price (mid_price) 計算固定距離的報價
        2. 使用 order_distance_bps 參數（默認 10 bps = 0.1%）
        3. 依靠 cancel_distance_bps 在價格接近時撤單來避免成交

        計算公式：
        - buy_price = mid_price * (1 - order_distance_bps / 10000)
        - sell_price = mid_price * (1 + order_distance_bps / 10000)
        """
        # 從 mark price 計算報價
        distance_ratio = Decimal(self.config.order_distance_bps) / Decimal("10000")

        bid_price = mid_price * (Decimal("1") - distance_ratio)
        ask_price = mid_price * (Decimal("1") + distance_ratio)

        # 對齊到 tick size (floor for buy, ceil for sell)
        import math
        tick_size = Decimal("0.01")

        # Floor for buy (更保守的買價)
        bid_price = Decimal(str(math.floor(float(bid_price) / float(tick_size)) * float(tick_size)))
        # Ceil for sell (更保守的賣價)
        ask_price = Decimal(str(math.ceil(float(ask_price) / float(tick_size)) * float(tick_size)))

        logger.debug(
            f"Quote prices: bid={bid_price}, ask={ask_price}, "
            f"mid={mid_price}, distance={self.config.order_distance_bps}bps"
        )

        return bid_price, ask_price

    async def _place_bid(self, price: Decimal):
        """掛買單"""
        if self.config.dry_run:
            logger.info(f"[DRY RUN] Would place bid: {self.config.order_size_btc} @ {price}")
            return

        try:
            order = await self.standx.place_order(
                symbol=self.config.standx_symbol,
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
                symbol=self.config.standx_symbol,
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

            logger.info(f"Ask placed: {self.config.order_size_btc} @ {price}")

        except Exception as e:
            logger.error(f"Failed to place ask: {e}")

    async def _cancel_order(self, client_order_id: str):
        """撤銷單個訂單"""
        if self.config.dry_run:
            logger.info(f"[DRY RUN] Would cancel order: {client_order_id}")
            return

        try:
            await self.standx.cancel_order(
                symbol=self.config.standx_symbol,
                client_order_id=client_order_id,
            )
            self._total_cancels += 1

            # 更新狀態
            bid = self.state.get_bid_order()
            ask = self.state.get_ask_order()

            if bid and bid.client_order_id == client_order_id:
                self.state.clear_bid_order()
            elif ask and ask.client_order_id == client_order_id:
                self.state.clear_ask_order()

            logger.info(f"Order cancelled: {client_order_id}")

        except Exception as e:
            logger.error(f"Failed to cancel order {client_order_id}: {e}")

    async def _cancel_all_orders(self):
        """撤銷所有訂單"""
        bid = self.state.get_bid_order()
        ask = self.state.get_ask_order()

        tasks = []
        if bid and bid.status in ["pending", "open"]:
            tasks.append(self._cancel_order(bid.client_order_id))
        if ask and ask.status in ["pending", "open"]:
            tasks.append(self._cancel_order(ask.client_order_id))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        self.state.clear_all_orders()

    # ==================== 成交處理 ====================

    async def on_fill_event(self, fill: FillEvent):
        """
        處理成交事件 (由 WebSocket 回調觸發)

        流程:
        1. 更新倉位
        2. 取消另一邊訂單
        3. 執行對沖
        4. 對沖完成後重新掛單
        """
        logger.info(f"Fill received: {fill.side} {fill.fill_qty} @ {fill.fill_price}")

        # 更新狀態
        self.state.record_fill()

        # 更新 StandX 倉位
        delta = fill.fill_qty if fill.side == "buy" else -fill.fill_qty
        self.state.update_standx_position(delta)

        # 取消另一邊訂單
        await self._cancel_all_orders()

        # 進入對沖狀態
        self._status = ExecutorStatus.HEDGING
        if self._on_status_change:
            await self._on_status_change(self._status)

        # 觸發回調
        if self._on_fill:
            await self._on_fill(fill)

        # 執行對沖
        hedge_result = await self.hedge_engine.execute_hedge(
            fill_id=fill.order_id,
            fill_side=fill.side,
            fill_qty=fill.fill_qty,
            fill_price=fill.fill_price,
            standx_symbol=self.config.standx_symbol,
        )

        # 記錄對沖結果
        self.state.record_hedge(hedge_result.success)

        # 更新 Binance 倉位
        if hedge_result.success and hedge_result.status == HedgeStatus.FILLED:
            # 對沖成功，Binance 倉位反向
            hedge_delta = -delta
            self.state.update_binance_position(hedge_delta)
        elif hedge_result.status == HedgeStatus.FALLBACK:
            # 回退成功，StandX 倉位回滾
            self.state.update_standx_position(-delta)

        # 觸發對沖回調
        if self._on_hedge:
            await self._on_hedge(hedge_result)

        logger.info(
            f"Hedge completed: {hedge_result.status.value}, "
            f"latency: {hedge_result.latency_ms:.0f}ms"
        )

        # 恢復報價狀態
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
            "hedge_stats": self.hedge_engine.get_stats(),
        }

    def to_dict(self) -> dict:
        """序列化"""
        return {
            "config": {
                "standx_symbol": self.config.standx_symbol,
                "binance_symbol": self.config.binance_symbol,
                "order_distance_bps": self.config.order_distance_bps,
                "order_size_btc": float(self.config.order_size_btc),
                "max_position_btc": float(self.config.max_position_btc),
                "volatility_threshold_bps": self.config.volatility_threshold_bps,
                "dry_run": self.config.dry_run,
            },
            "state": self.state.to_dict(),
            "stats": self.get_stats(),
        }
