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
import time
import os
from typing import Optional, Callable, Awaitable, Dict
from decimal import Decimal
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from logging.handlers import RotatingFileHandler

from .mm_state import MMState, OrderInfo, FillEvent, EventDeduplicator, OrderThrottle
from .hedge_engine import HedgeEngine, HedgeResult, HedgeStatus

# WebSocket types (conditional import)
try:
    from ..adapters.grvt_ws_client import GRVTFillEvent, GRVTOrderStateEvent
except ImportError:
    GRVTFillEvent = None
    GRVTOrderStateEvent = None

logger = logging.getLogger(__name__)

# ==================== 交易日誌設置 ====================
# 專門記錄掛單、撤單、成交等操作的日誌
# 每次 executor 啟動建立新的 log 檔案，方便追蹤各 session
# 注意：模組載入時不建立檔案，只有 executor.start() 呼叫時才建立

# 全域變數：當前 session 的 log 檔案路徑
_current_trade_log_file: Optional[Path] = None

def _setup_trade_logger(exchange: str = "mm", create_file: bool = False):
    """
    設置交易日誌

    Args:
        exchange: 交易所名稱，用於檔案命名 (mm, grvt, standx)
        create_file: 是否建立新的 log 檔案（只有 executor.start() 時設為 True）
    """
    global _current_trade_log_file

    trade_logger = logging.getLogger("mm_trade")

    # 模組載入時：只設定 logger，不建立檔案
    if not create_file:
        if not trade_logger.handlers:
            trade_logger.setLevel(logging.INFO)
            trade_logger.propagate = False
            # 加一個 NullHandler 避免 "No handlers" 警告
            trade_logger.addHandler(logging.NullHandler())
        return trade_logger

    # ==================== Executor 啟動時：建立新的 log 檔案 ====================
    # 清除舊 handlers
    for handler in trade_logger.handlers[:]:
        handler.close()
        trade_logger.removeHandler(handler)

    trade_logger.setLevel(logging.INFO)
    trade_logger.propagate = False

    # 創建 logs 目錄
    log_dir = Path(__file__).parent.parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)

    # 依時間戳建立新檔案
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"mm_trades_{timestamp}.log"
    _current_trade_log_file = log_file

    # 使用 FileHandler
    file_handler = logging.FileHandler(
        log_file,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)

    # 格式
    formatter = logging.Formatter(
        '%(asctime)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)

    trade_logger.addHandler(file_handler)

    # 清理舊 log 檔案（保留最近 20 個）
    _cleanup_old_logs(log_dir, keep_count=20)

    return trade_logger


def _cleanup_old_logs(log_dir: Path, keep_count: int = 20):
    """清理舊的 log 檔案，只保留最近 N 個"""
    try:
        # 找出所有 mm_trades_*.log 檔案
        log_files = sorted(
            log_dir.glob("mm_trades_*.log"),
            key=lambda f: f.stat().st_mtime,
            reverse=True  # 最新的在前
        )

        # 刪除超過數量的舊檔案
        for old_file in log_files[keep_count:]:
            try:
                old_file.unlink()
                logger.debug(f"Cleaned up old log: {old_file.name}")
            except Exception as e:
                logger.warning(f"Failed to delete old log {old_file.name}: {e}")
    except Exception as e:
        logger.warning(f"Failed to cleanup old logs: {e}")


def get_current_trade_log_file() -> Optional[Path]:
    """獲取當前 session 的 log 檔案路徑"""
    return _current_trade_log_file


# 初始化 trade_log（模組載入時建立第一個檔案）
trade_log = _setup_trade_logger()


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

    策略模式：
    - uptime: StandX uptime 獎勵模式（避免成交，掛單距離 8 bps，價格靠近時撤單）
    - rebate: GRVT maker rebate 模式（追求成交，貼近 best 報價，不撤單）
    """
    # 交易對（通用）
    symbol: str = "BTC-USD"              # 主交易對
    hedge_symbol: str = "BTC_USDT_Perp"  # 對沖交易對
    hedge_exchange: str = "grvt"         # 對沖交易所 ("grvt", "standx", "binance")

    # ==================== 主交易所路由 ====================
    primary_exchange: str = "standx"     # 主做市交易所 ("standx" | "grvt")

    # ==================== 策略模式 ====================
    strategy_mode: str = "uptime"        # "uptime" (StandX) | "rebate" (GRVT)

    # 報價激進度 (rebate 模式用)
    # - aggressive: 貼 best_bid/best_ask（最高成交率）
    # - moderate: 離 best 1 bps（外側，較安全）
    # - conservative: 離 best 2 bps（外側）
    aggressiveness: str = "moderate"

    # 是否在價格接近時取消訂單 (rebate 模式設為 False)
    cancel_on_approach: bool = True

    # 強制 post_only (預設開啟，確保 maker，避免意外成交)
    post_only: bool = True

    # 最小 spread 保護 (tick 數，spread < 此值時只掛一邊)
    min_spread_ticks: int = 2

    # ==================== 費率設定 ====================
    # 負數 = 收 rebate, 正數 = 付 fee
    maker_fee_bps: Decimal = Decimal("-1")   # GRVT maker rebate
    taker_fee_bps: Decimal = Decimal("3")    # GRVT taker fee
    hedge_fee_bps: Decimal = Decimal("2")    # StandX hedge fee (備用)

    # ==================== 報價參數 (uptime 模式) ====================
    order_distance_bps: int = 12         # 掛單距離 mark price (保守模式，犧牲 uptime tier 換取安全)
    cancel_distance_bps: int = 5         # 價格靠近時撤單（防止成交，~$46 緩衝）
    rebalance_distance_bps: int = 18     # 價格遠離時撤單重掛

    # ==================== Inventory Skew 參數 ====================
    inventory_skew_enabled: bool = True
    inventory_skew_max_bps: Decimal = Decimal("6")     # 偏倉方向拉遠 6 bps
    inventory_skew_pull_bps: Decimal = Decimal("4.5")  # 回補方向拉近 4.5 bps
    min_quote_bps: Decimal = Decimal("0.5")            # 最小報價距離 (防止貼盤太近)
    min_reversion_quote_bps: Decimal = Decimal("0")    # 回補方向最小距離 (允許貼盤)

    # ==================== 倉位參數 ====================
    order_size_btc: Decimal = Decimal("0.001")   # 單邊訂單量
    max_position_btc: Decimal = Decimal("0.01")  # 最大持倉 (軟停)

    # 硬停參數 (帶 hysteresis)
    hard_stop_position_btc: Decimal = Decimal("0.007")   # 硬停倉位 (超過全停)
    resume_position_btc: Decimal = Decimal("0.0045")     # 恢復倉位 (留 buffer)
    hard_stop_cooldown_sec: int = 30                     # 硬停後冷卻時間
    resume_check_count: int = 3                          # 連續 N 次滿足才恢復
    min_effective_max_pos_btc: Decimal = Decimal("0.001")  # effective_max_pos 下限

    # ==================== 成交後行為 ====================
    # "all": 撤銷雙邊（有對沖時用）
    # "opposite": 只撤對手邊（通用）
    # "none": 不撤銷（無對沖回補模式）
    fill_cancel_policy: str = "none"

    # Stale order reprice 參數 (避免洗單)
    stale_order_timeout_sec: int = 30           # 回補訂單過期時間
    stale_reprice_bps: Decimal = Decimal("2")   # 距離 best 超過此值才 reprice
    min_reprice_interval_sec: int = 5           # reprice 最小間隔

    # ==================== 保本回補參數 ====================
    # 成交後，回補訂單直接掛在建倉價，確保價格回來時不虧損
    breakeven_reversion_enabled: bool = True    # 是否啟用保本回補
    breakeven_offset_bps: Decimal = Decimal("0")  # 回補價格偏移 (正=更保守, 負=更激進吃rebate)

    # ==================== 波動率控制 ====================
    volatility_window_sec: int = 2       # 波動率窗口（2 秒反應更快）
    volatility_threshold_bps: float = 5.0  # 超過則暫停
    volatility_resume_threshold_bps: float = 4.0  # 低於此值才考慮恢復 (hysteresis)
    volatility_stable_seconds: float = 2.0  # 需持續低於恢復閾值多少秒才真正恢復
    volatility_distance_multiplier: Decimal = Decimal("2")  # 高波動時距離倍數

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
        grvt_adapter=None,      # GRVT 適配器 (用於做市)
    ):
        self.standx = standx_adapter
        self.hedge_adapter = hedge_adapter
        self.hedge_engine = hedge_engine
        self.config = config or MMConfig()
        self.state = state or MMState(volatility_window_sec=self.config.volatility_window_sec)

        # 【新增】GRVT adapter 引用
        self.grvt = grvt_adapter

        # 【新增】Primary adapter 路由 - 依 config.primary_exchange 決定
        if self.config.primary_exchange == "grvt" and self.grvt:
            self.primary = self.grvt
            logger.info(f"[Init] Primary adapter set to GRVT")
        else:
            self.primary = self.standx
            logger.info(f"[Init] Primary adapter set to StandX")

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
        self._placing_lock = asyncio.Lock()  # 下單鎖，防止重複下單

        # 下單中標記（防止競態條件）
        self._placing_bid = False
        self._placing_ask = False

        # 【新增】硬停追蹤
        self._hard_stop_time: Optional[float] = None   # 硬停觸發時間
        self._resume_ok_count: int = 0                 # 連續滿足恢復條件的次數

        # 【新增】波動率恢復追蹤 (hysteresis + stable period)
        self._volatility_stable_since: Optional[float] = None  # 波動率首次低於恢復閾值的時間

        # 【新增】Stale order reprice 追蹤
        self._last_reprice_time: Dict[str, float] = {}  # side -> last reprice timestamp

        # 交易對規格（啟動時從 adapter 獲取）
        self._tick_size: Decimal = Decimal("0.01")  # 默認值，會在初始化時更新

        # WebSocket support (for real-time fill detection)
        self._use_websocket = False  # Will be set to True if WebSocket is available
        self._ws_connected = False

        # 【新增】Skew 日誌去重（只在值變化時記錄）
        self._last_skew_log: Optional[tuple] = None  # (pos_ratio, bid_bps, ask_bps)

        # 【新增】事件去重器 - 防止 WebSocket 重複成交事件
        self._event_deduplicator = EventDeduplicator(ttl_sec=60.0)

        # 【新增】下單節流器 - 防止快速重複下單
        # 增加冷卻時間到 5 秒，適應 StandX API 延遲
        self._order_throttle = OrderThrottle(cooldown_sec=5.0)

        # 【新增】REST Gate 失敗計數器
        self._rest_gate_failures = 0

        # 【新增】倉位同步節流（風控用）
        self._last_position_sync: float = 0  # 上次同步時間
        self._position_sync_interval: float = 2.0  # 同步間隔（秒）

    # ==================== 生命週期 ====================

    async def start(self):
        """啟動做市"""
        global trade_log

        if self._running:
            logger.warning("Executor already running")
            return

        # ==================== 建立新的 log 檔案 ====================
        # 每次 executor 啟動都建立新的 session log
        trade_log = _setup_trade_logger(
            exchange=self.config.primary_exchange,
            create_file=True
        )
        log_file = get_current_trade_log_file()
        logger.info(f"Trade log file: {log_file}")

        # 【診斷】啟動時打印完整配置
        logger.info(f"Starting Market Maker Executor with config:")
        logger.info(f"  symbol={self.config.symbol}")
        logger.info(f"  hedge_symbol={self.config.hedge_symbol}")
        logger.info(f"  strategy_mode={self.config.strategy_mode}")
        logger.info(f"  aggressiveness={self.config.aggressiveness}")
        logger.info(f"  order_size_btc={self.config.order_size_btc}")
        logger.info(f"  max_position_btc={self.config.max_position_btc}")

        # 交易日誌 - 啟動配置
        trade_log.info("=" * 80)
        trade_log.info(f"EXECUTOR_START | exchange={self.config.primary_exchange} | symbol={self.config.symbol}")
        trade_log.info(
            f"CONFIG | exchange={self.config.primary_exchange} | "
            f"strategy_mode={self.config.strategy_mode} | aggressiveness={self.config.aggressiveness} | "
            f"order_size={self.config.order_size_btc} | max_pos={self.config.max_position_btc}"
        )
        trade_log.info(
            f"CONFIG | skew_enabled={self.config.inventory_skew_enabled} | "
            f"push_bps={self.config.inventory_skew_max_bps} | "
            f"pull_bps={self.config.inventory_skew_pull_bps}"
        )
        trade_log.info(
            f"CONFIG | hard_stop={self.config.hard_stop_position_btc} | "
            f"resume_pos={self.config.resume_position_btc} | "
            f"fill_policy={self.config.fill_cancel_policy}"
        )
        trade_log.info(
            f"CONFIG | breakeven_enabled={self.config.breakeven_reversion_enabled} | "
            f"breakeven_offset={self.config.breakeven_offset_bps}"
        )
        trade_log.info("=" * 80)

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

        # 交易日誌 - 停止
        pos = self._get_primary_position()
        trade_log.info("=" * 80)
        trade_log.info(f"EXECUTOR_STOP | exchange={self.config.primary_exchange} | final_pos={pos}")
        trade_log.info("=" * 80)
        self._running = False

        # Stop WebSocket if running
        if self._use_websocket and hasattr(self.standx, 'stop_websocket'):
            try:
                await self.primary.stop_websocket()
                self._ws_connected = False
                logger.info("[WebSocket] Stopped")
            except Exception as e:
                logger.warning(f"[WebSocket] Error stopping: {e}")

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

        # 獲取交易對規格（tick size）
        try:
            symbol_info = await self.primary.get_symbol_info(self.config.symbol)
            if symbol_info and symbol_info.price_tick:
                self._tick_size = symbol_info.price_tick
                logger.info(f"[Init] Symbol {self.config.symbol} tick_size={self._tick_size}")
            else:
                logger.warning(f"[Init] Could not get tick_size for {self.config.symbol}, using default {self._tick_size}")
        except Exception as e:
            logger.warning(f"[Init] Failed to get symbol info: {e}, using default tick_size={self._tick_size}")

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

        # Initialize WebSocket for real-time fill detection (if adapter supports it)
        await self._init_websocket()

        logger.info("Executor initialized")

    async def _cancel_all_existing_orders(self):
        """取消交易所上的所有現有訂單"""
        logger.info(f"[Cancel] Querying open orders for {self.config.symbol}")
        try:
            open_orders = await self.primary.get_open_orders(self.config.symbol)
            logger.info(f"[Cancel] Found {len(open_orders)} open orders")
            if open_orders:
                logger.info(f"Cancelling {len(open_orders)} existing orders")
                for order in open_orders:
                    try:
                        logger.info(f"[Cancel] Cancelling order: order_id={order.order_id}, client_order_id={order.client_order_id} @ {order.price}")
                        # 傳遞 order_id 和 client_order_id，讓 adapter 決定使用哪個
                        await self.primary.cancel_order(
                            symbol=self.config.symbol,
                            order_id=order.order_id,
                            client_order_id=order.client_order_id
                        )
                        logger.info(f"Cancelled existing order: {order.order_id}")
                    except Exception as e:
                        logger.warning(f"Failed to cancel order {order.order_id}: {e}")
            else:
                logger.info("No existing orders to cancel")
        except Exception as e:
            logger.error(f"Failed to get existing orders: {e}", exc_info=True)

    async def _init_websocket(self):
        """
        Initialize WebSocket for real-time fill detection

        If the adapter supports WebSocket (has start_websocket method),
        use it for real-time fill detection instead of polling.
        """
        logger.info("=" * 60)
        logger.info("[WebSocket] Initializing WebSocket for real-time fill detection")
        logger.info(f"[WebSocket] Adapter type: {type(self.standx).__name__}")

        # Check if adapter has WebSocket support
        if not hasattr(self.standx, 'start_websocket'):
            logger.info("[WebSocket] Adapter does not support WebSocket (no start_websocket method)")
            logger.info("[WebSocket] Using POLLING mode for fill detection")
            self._use_websocket = False
            return

        logger.info("[WebSocket] Adapter supports WebSocket, attempting to start...")

        try:
            # Register fill callback
            if hasattr(self.standx, 'on_fill'):
                self.primary.on_fill(self._on_ws_fill)
                logger.info("[WebSocket] Registered fill callback")
            else:
                logger.warning("[WebSocket] Adapter has no on_fill method")

            # Register order state callback (optional)
            if hasattr(self.standx, 'on_order_state'):
                self.primary.on_order_state(self._on_ws_order_state)
                logger.info("[WebSocket] Registered order state callback")

            # Start WebSocket with the trading symbol
            # Use appropriate symbol format based on adapter type
            adapter_type = type(self.standx).__name__
            if adapter_type == "StandXAdapter":
                # StandX uses BTC-USD format
                ws_symbol = self._normalize_to_standx_symbol(self.config.symbol)
            else:
                # GRVT uses BTC_USDT_Perp format
                ws_symbol = self._normalize_to_grvt_symbol(self.config.symbol)
            logger.info(f"[WebSocket] Starting WebSocket for symbol: {ws_symbol} (adapter: {adapter_type})")

            success = await self.primary.start_websocket(instruments=[ws_symbol])

            if success:
                self._use_websocket = True
                self._ws_connected = True
                logger.info(f"[WebSocket] SUCCESS - Using WEBSOCKET mode for fill detection")
                logger.info(f"[WebSocket] Subscribed to: {ws_symbol}")
            else:
                logger.warning("[WebSocket] FAILED - Falling back to POLLING mode")
                self._use_websocket = False

        except Exception as e:
            logger.error(f"[WebSocket] Initialization error: {e}", exc_info=True)
            logger.warning("[WebSocket] FAILED - Falling back to POLLING mode")
            self._use_websocket = False

        logger.info(f"[WebSocket] Final mode: {'WEBSOCKET' if self._use_websocket else 'POLLING'}")
        logger.info("=" * 60)

    def _normalize_to_grvt_symbol(self, symbol: str) -> str:
        """Convert generic symbol to GRVT format (BTC_USDT_Perp)"""
        if '_Perp' in symbol:
            return symbol

        # Normalize separators
        normalized = symbol.upper().replace('-', '_').replace('/', '_')

        # Common conversions
        conversions = {
            'BTC_USD': 'BTC_USDT_Perp',
            'BTCUSD': 'BTC_USDT_Perp',
            'BTC_USDT': 'BTC_USDT_Perp',
            'BTCUSDT': 'BTC_USDT_Perp',
            'ETH_USD': 'ETH_USDT_Perp',
            'ETHUSD': 'ETH_USDT_Perp',
            'ETH_USDT': 'ETH_USDT_Perp',
            'ETHUSDT': 'ETH_USDT_Perp',
        }

        if normalized in conversions:
            return conversions[normalized]

        # Default: add _USDT_Perp
        if normalized.endswith('USDT'):
            base = normalized[:-4]
            return f'{base}_USDT_Perp'
        elif normalized.endswith('_USDT'):
            return normalized + '_Perp'

        return f'{normalized}_USDT_Perp'

    def _normalize_to_standx_symbol(self, symbol: str) -> str:
        """Convert generic symbol to StandX format (BTC-USD)"""
        if '-USD' in symbol and '_Perp' not in symbol:
            return symbol

        # Normalize: remove _Perp suffix if present
        normalized = symbol.replace('_Perp', '').upper()

        # Convert underscore format to dash format
        # BTC_USDT -> BTC-USD
        # BTC_USDT_Perp -> BTC-USD
        conversions = {
            'BTC_USDT': 'BTC-USD',
            'BTCUSDT': 'BTC-USD',
            'BTC_USD': 'BTC-USD',
            'ETH_USDT': 'ETH-USD',
            'ETHUSDT': 'ETH-USD',
            'ETH_USD': 'ETH-USD',
        }

        if normalized in conversions:
            return conversions[normalized]

        # Default: replace underscore with dash, remove T from USDT
        base = normalized.replace('_USDT', '').replace('USDT', '').replace('_', '')
        return f'{base}-USD'

    async def _on_ws_fill(self, fill_event):
        """
        Handle fill event from WebSocket

        This provides real-time fill detection, much faster than polling.
        Supports both GRVT (GRVTFillEvent) and StandX (OrderUpdate) formats.
        """
        # Detect event type and extract common fields
        adapter_type = type(self.standx).__name__

        if adapter_type == "StandXAdapter":
            # StandX OrderUpdate format
            side = fill_event.side  # "buy" or "sell"
            fill_qty = fill_event.filled_qty
            fill_price = fill_event.avg_fill_price or fill_event.price
            order_id = fill_event.order_id
            client_order_id = fill_event.client_order_id or ""
            symbol = fill_event.symbol
            timestamp = fill_event.timestamp
            is_maker = None  # StandX doesn't provide is_maker in WebSocket

            logger.info(
                f"[WebSocket Fill] StandX: {side} {fill_qty} @ {fill_price} "
                f"(order_id={order_id}, status={fill_event.status})"
            )
        else:
            # GRVT GRVTFillEvent format
            if GRVTFillEvent is None:
                logger.warning("[WebSocket] GRVTFillEvent type not available")
                return

            side = fill_event.side
            fill_qty = fill_event.size
            fill_price = fill_event.price
            order_id = fill_event.order_id
            client_order_id = fill_event.client_order_id or ""
            symbol = fill_event.instrument
            timestamp = fill_event.timestamp
            is_maker = fill_event.is_maker

            logger.info(
                f"[WebSocket Fill] GRVT: {side} {fill_qty} @ {fill_price} "
                f"(maker={is_maker}, fee={fill_event.fee})"
            )

        # ==================== 關鍵修復：qty=0 過濾 ====================
        # qty=0 的事件是訂單狀態更新，不是實際成交，必須跳過
        if fill_qty is None or fill_qty <= Decimal("0"):
            logger.debug(
                f"[WS Dedup] Skipping qty=0 event: order_id={order_id}, "
                f"fill_qty={fill_qty}"
            )
            return

        # ==================== 關鍵修復：事件去重 ====================
        # 同一 order_id + fill_qty 的事件只處理一次
        if self._event_deduplicator.is_duplicate(str(order_id), fill_qty):
            logger.info(
                f"[WS Dedup] Duplicate fill ignored: order_id={order_id}, "
                f"fill_qty={fill_qty}"
            )
            return

        # Convert WebSocket fill event to internal FillEvent
        internal_fill = FillEvent(
            order_id=order_id,
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            fill_qty=fill_qty,
            fill_price=fill_price,
            remaining_qty=Decimal("0"),  # WebSocket fill events are per-fill, not remaining
            is_fully_filled=True,  # Each WS event is a complete fill notification
            timestamp=timestamp,
            is_maker=is_maker,
        )

        # Clear the corresponding order from local state
        if side == "buy":
            self.state.clear_bid_order()
        else:
            self.state.clear_ask_order()

        # Process the fill event
        await self.on_fill_event(internal_fill)

    async def _on_ws_order_state(self, order_event):
        """
        Handle order state event from WebSocket

        Updates local order state based on exchange notifications.
        Supports both GRVT (GRVTOrderStateEvent) and StandX (OrderUpdate) formats.
        """
        adapter_type = type(self.standx).__name__

        if adapter_type == "StandXAdapter":
            # StandX OrderUpdate format
            order_id = order_event.order_id
            client_order_id = order_event.client_order_id
            status = order_event.status  # "open", "filled", "cancelled", "rejected"
            filled_qty = order_event.filled_qty
            total_qty = order_event.qty

            logger.debug(
                f"[WebSocket Order] StandX: {order_id} {status} "
                f"filled={filled_qty}/{total_qty}"
            )

            # Normalize status for comparison
            state = status.upper()
        else:
            # GRVT GRVTOrderStateEvent format
            if GRVTOrderStateEvent is None:
                logger.warning("[WebSocket] GRVTOrderStateEvent type not available")
                return

            order_id = order_event.order_id
            client_order_id = getattr(order_event, 'client_order_id', None)
            state = order_event.state
            filled_qty = order_event.filled_size
            total_qty = order_event.size

            logger.debug(
                f"[WebSocket Order] GRVT: {order_id} {state} "
                f"filled={filled_qty}/{total_qty}"
            )

        # Handle different states
        if state == "FILLED":
            # Order fully filled - this is also covered by fill events
            pass
        elif state == "CANCELLED":
            # Order was cancelled
            logger.info(f"[WebSocket] Order cancelled: {order_id}")
            # Clear from local state by order_id or client_order_id
            self._clear_order_from_state(order_id, client_order_id)
        elif state == "REJECTED":
            # Order was rejected
            reject_reason = getattr(order_event, 'reject_reason', 'unknown')
            logger.warning(f"[WebSocket] Order rejected: {order_id}, reason={reject_reason}")
            # Clear from local state
            self._clear_order_from_state(order_id, client_order_id, record_post_only=True)

    def _clear_order_from_state(self, order_id: str, client_order_id: str = None, record_post_only: bool = False):
        """Helper to clear order from local state by order_id or client_order_id"""
        bid = self.state.get_bid_order()
        ask = self.state.get_ask_order()

        # Try matching by order_id first, then by client_order_id
        matched_bid = False
        matched_ask = False

        if bid:
            if bid.order_id == order_id or (client_order_id and bid.client_order_id == client_order_id):
                matched_bid = True
        if ask:
            if ask.order_id == order_id or (client_order_id and ask.client_order_id == client_order_id):
                matched_ask = True

        if matched_bid:
            self.state.clear_bid_order()
            if record_post_only:
                self.state.record_post_only_reject()
        elif matched_ask:
            self.state.clear_ask_order()
            if record_post_only:
                self.state.record_post_only_reject()

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
        """單次執行 - 含硬停自動恢復"""
        # 如果正在對沖，跳過
        if self._status == ExecutorStatus.HEDGING:
            return

        # 每 10 個 tick 記錄一次 WebSocket 狀態（診斷用）
        self._tick_count = getattr(self, '_tick_count', 0) + 1
        if self._tick_count % 10 == 1:
            logger.debug(f"[Tick] ws_enabled={self._use_websocket}, ws_connected={self._ws_connected}")

        # ==================== 硬停自動恢復（帶 hysteresis） ====================
        if self._status == ExecutorStatus.PAUSED and self._hard_stop_time:
            time_since_stop = time.time() - self._hard_stop_time
            cooldown = self.config.hard_stop_cooldown_sec

            # 只有過了冷卻時間才檢查恢復
            if time_since_stop > cooldown:
                # 【優化】WebSocket 模式：用本地倉位檢查，不調 API
                # 非 WebSocket 模式：每 30 秒同步一次（更保守）
                if self._use_websocket:
                    # WebSocket 模式：直接用本地追蹤的倉位
                    current_pos = self._get_primary_position()
                else:
                    # 輪詢模式：需要 sync，但限制頻率
                    last_recovery_sync = getattr(self, '_last_recovery_sync', 0)
                    if time.time() - last_recovery_sync > 30:
                        await self._sync_primary_position()
                        self._last_recovery_sync = time.time()
                    current_pos = self._get_primary_position()

                resume_pos = self.config.resume_position_btc
                required_count = self.config.resume_check_count

                # 檢查恢復條件
                if abs(current_pos) < resume_pos:
                    self._resume_ok_count += 1
                    logger.debug(f"[Recovery] Check passed ({self._resume_ok_count}/{required_count}), pos={current_pos}")

                    if self._resume_ok_count >= required_count:
                        logger.info(
                            f"[Recovery] pos={current_pos} < resume={resume_pos}, "
                            f"count={self._resume_ok_count}/{required_count}, resuming"
                        )
                        self._status = ExecutorStatus.RUNNING
                        self._hard_stop_time = None
                        self._resume_ok_count = 0
                        if self._on_status_change:
                            await self._on_status_change(self._status)
                else:
                    # 不滿足條件，重置計數器
                    self._resume_ok_count = 0

        # 如果在 PAUSED 狀態（hedge engine 風控模式），檢查是否可以恢復
        if self._status == ExecutorStatus.PAUSED and self.hedge_engine and not self._hard_stop_time:
            if await self.hedge_engine.check_recovery():
                logger.info("GRVT recovered, resuming market making")
                self._status = ExecutorStatus.RUNNING
                if self._on_status_change:
                    await self._on_status_change(self._status)

        # 獲取最新價格 (使用 primary adapter)
        try:
            orderbook = await self.primary.get_orderbook(self.config.symbol)
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
            # 如果使用 WebSocket，不需要用倉位變化檢測成交（WebSocket 提供即時推送）
            if not self._use_websocket:
                # 【關鍵】每個 tick 都同步倉位，用倉位變化偵測成交（輪詢模式 fallback）
                await self._check_position_and_fill()
                # 如果成交後進入對沖狀態，不繼續下單
                if self._status == ExecutorStatus.HEDGING:
                    return

                # 輪詢模式：每個 tick 都檢查訂單狀態
                await self._check_order_status()
            else:
                # WebSocket 模式：只每 15 個 tick 檢查一次訂單狀態（作為 fallback）
                # tick_interval_ms=2000 → 每 30 秒檢查一次
                if self._tick_count % 15 == 0:
                    await self._check_order_status()

            # 再次檢查（可能在 _check_order_status 中觸發成交）
            if self._status == ExecutorStatus.HEDGING:
                return

        # ==================== 訂單同步已移至 REST Gate ====================
        # _place_orders() 現在每次都會查詢交易所訂單並同步 state
        # 所以不再需要固定間隔同步，避免重複查詢浪費 rate limit
        # 舊代碼：if self._tick_count % 5 == 0: await self._sync_open_orders()

        # 檢查波動率 (使用 hysteresis + stable period)
        volatility = self.state.get_volatility_bps()
        pause_threshold = self.config.volatility_threshold_bps
        resume_threshold = self.config.volatility_resume_threshold_bps
        stable_seconds = self.config.volatility_stable_seconds

        if volatility > pause_threshold:
            # 超過暫停閾值 → 暫停
            if self._status != ExecutorStatus.PAUSED:
                logger.warning(f"High volatility: {volatility:.1f} bps > {pause_threshold} bps, pausing")
                self._status = ExecutorStatus.PAUSED
                self.state.record_volatility_pause()
                await self._cancel_all_orders(reason="high volatility")
                if self._on_status_change:
                    await self._on_status_change(self._status)
            # 重置穩定計時器
            self._volatility_stable_since = None
            return

        elif self._status == ExecutorStatus.PAUSED:
            # 已暫停，檢查是否可以恢復
            if volatility > resume_threshold:
                # 仍高於恢復閾值，重置穩定計時器
                self._volatility_stable_since = None
                return
            else:
                # 低於恢復閾值，開始或繼續計算穩定期
                now = time.time()
                if self._volatility_stable_since is None:
                    # 首次低於恢復閾值，開始計時
                    self._volatility_stable_since = now
                    logger.info(
                        f"Volatility {volatility:.1f} bps < {resume_threshold} bps, "
                        f"waiting {stable_seconds}s stable period..."
                    )
                    return

                # 檢查是否已持續足夠時間
                stable_duration = now - self._volatility_stable_since
                if stable_duration >= stable_seconds:
                    # 穩定期達標，恢復運行
                    logger.info(
                        f"Volatility stable for {stable_duration:.1f}s "
                        f"({volatility:.1f} bps < {resume_threshold} bps), resuming"
                    )
                    self._status = ExecutorStatus.RUNNING
                    self._volatility_stable_since = None
                    if self._on_status_change:
                        await self._on_status_change(self._status)
                else:
                    # 仍在等待穩定期
                    return

        # 檢查是否需要撤單 (價格太近)
        # 只在 uptime 模式或 cancel_on_approach=True 時執行
        # rebate 模式不撤單 - 讓訂單成交以獲得 maker rebate
        if self.config.cancel_on_approach and self.config.strategy_mode == "uptime":
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

        # ==================== 保本回補訂單過期檢查 ====================
        # 如果保本訂單卡太久，可能需要認賠離場
        if self.config.breakeven_reversion_enabled and self.state.has_entry():
            entry_time = self.state.get_entry_time()
            entry_side = self.state.get_entry_side()
            timeout = self.config.stale_order_timeout_sec
            min_interval = self.config.min_reprice_interval_sec

            if entry_time and entry_side:
                time_since_entry = time.time() - entry_time

                # 超過 timeout，檢查是否需要 reprice
                if time_since_entry > timeout:
                    # 獲取回補訂單
                    if entry_side == "buy":
                        # 回補方向是 ask
                        reversion_order = self.state.get_ask_order()
                        reversion_side = "ask"
                        best_price = best_ask
                    else:
                        # 回補方向是 bid
                        reversion_order = self.state.get_bid_order()
                        reversion_side = "bid"
                        best_price = best_bid

                    if reversion_order and best_price:
                        # 計算距離 best 的 bps
                        if reversion_side == "ask":
                            distance_bps = (reversion_order.price - best_price) / best_price * Decimal("10000")
                        else:
                            distance_bps = (best_price - reversion_order.price) / best_price * Decimal("10000")

                        # 如果距離 best 超過閾值，考慮 reprice
                        if distance_bps > self.config.stale_reprice_bps:
                            # 檢查 reprice 間隔
                            last_reprice = self._last_reprice_time.get(reversion_side, 0)
                            if time.time() - last_reprice > min_interval:
                                logger.warning(
                                    f"[StaleBreakeven] Order stale for {time_since_entry:.0f}s, "
                                    f"distance={float(distance_bps):.1f} bps > threshold={self.config.stale_reprice_bps}, "
                                    f"clearing entry and repricing"
                                )
                                # 清除 entry，讓下一個 tick 用 skew 重新報價
                                self.state.clear_entry()
                                self._last_reprice_time[reversion_side] = time.time()
                                # 撤銷舊訂單
                                await self._cancel_order(
                                    reversion_order.client_order_id,
                                    reason=f"stale breakeven ({time_since_entry:.0f}s)"
                                )

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
        """掛雙邊訂單 - 含 REST gate、spread 保護、hard stop、soft stop 和 post_only 支援"""
        # 防禦性檢查：只在 RUNNING 狀態下掛單
        if self._status != ExecutorStatus.RUNNING:
            logger.debug(f"Skipping order placement, status={self._status}")
            return

        # ==================== REST Gate: 下單前查交易所 ====================
        # 每次下單前都查詢交易所實際訂單，用交易所結果作為判斷依據
        # 這是防止重複訂單的核心機制
        #
        # WebSocket 模式優化：
        # - 如果 WebSocket 連接正常，只在需要下單時才查詢（每 10 個 tick 或本地沒有訂單時）
        # - 這樣可以大幅減少 REST API 調用，避免 429 錯誤
        exchange_bids = []
        exchange_asks = []
        rest_gate_ok = False

        # 決定是否需要 REST Gate 查詢
        need_rest_gate = True
        if self._use_websocket and self._ws_connected:
            # WebSocket 模式：只在以下情況查詢
            # 1. 本地沒有訂單（需要下單）
            # 2. 每 10 個 tick 做一次同步（約 1 秒，tick_interval=100ms）
            has_local_orders = self.state.has_bid_order() or self.state.has_ask_order()
            if has_local_orders and self._tick_count % 10 != 0:
                # 有訂單且不是同步週期，跳過 REST Gate
                need_rest_gate = False
                rest_gate_ok = True
                # 使用本地 state
                if self.state.has_bid_order():
                    exchange_bids = [self.state.get_bid_order()]
                if self.state.has_ask_order():
                    exchange_asks = [self.state.get_ask_order()]

        if need_rest_gate:
            try:
                open_orders = await self.primary.get_open_orders(self.config.symbol)
                logger.debug(f"[REST Gate] Got {len(open_orders)} open orders from exchange")

                # 分類訂單
                for order in open_orders:
                    if order.status not in ["open", "partially_filled", "new"]:
                        continue
                    if order.side.lower() == "buy":
                        exchange_bids.append(order)
                    else:
                        exchange_asks.append(order)

                # ==================== 同步本地 state（REST 為準）====================
                # 交易所沒有 bid 但本地有 → 清除本地
                if not exchange_bids and self.state.has_bid_order():
                    logger.info("[REST Gate] Exchange has no bid, clearing local bid state")
                    self.state.clear_bid_order()

                # 交易所沒有 ask 但本地有 → 清除本地
                if not exchange_asks and self.state.has_ask_order():
                    logger.info("[REST Gate] Exchange has no ask, clearing local ask state")
                    self.state.clear_ask_order()

                # 交易所有 bid 但本地沒有 → 取消孤兒訂單（避免重複下單）
                if exchange_bids and not self.state.has_bid_order():
                    logger.warning(f"[REST Gate] Exchange has {len(exchange_bids)} orphan bids, cancelling")
                    for order in exchange_bids:
                        try:
                            await self.primary.cancel_order(
                                symbol=self.config.symbol,
                                order_id=order.order_id,
                                client_order_id=getattr(order, 'client_order_id', None)
                            )
                            trade_log.info(
                                f"REST_GATE_CANCEL | exchange={self.config.primary_exchange} | side=buy | "
                                f"order_id={order.order_id} | reason=orphan_order"
                            )
                        except Exception as e:
                            logger.error(f"[REST Gate] Failed to cancel orphan bid: {e}")
                    exchange_bids = []  # 已取消，視為沒有

                if exchange_asks and not self.state.has_ask_order():
                    logger.warning(f"[REST Gate] Exchange has {len(exchange_asks)} orphan asks, cancelling")
                    for order in exchange_asks:
                        try:
                            await self.primary.cancel_order(
                                symbol=self.config.symbol,
                                order_id=order.order_id,
                                client_order_id=getattr(order, 'client_order_id', None)
                            )
                            trade_log.info(
                                f"REST_GATE_CANCEL | exchange={self.config.primary_exchange} | side=sell | "
                                f"order_id={order.order_id} | reason=orphan_order"
                            )
                        except Exception as e:
                            logger.error(f"[REST Gate] Failed to cancel orphan ask: {e}")
                    exchange_asks = []

                # 交易所有多個同方向訂單 → 取消多餘的
                if len(exchange_bids) > 1:
                    logger.warning(f"[REST Gate] Multiple bids ({len(exchange_bids)}), cancelling extras")
                    sorted_bids = sorted(exchange_bids, key=lambda o: getattr(o, 'created_at', 0), reverse=True)
                    for order in sorted_bids[1:]:
                        try:
                            await self.primary.cancel_order(
                                symbol=self.config.symbol,
                                order_id=order.order_id,
                                client_order_id=getattr(order, 'client_order_id', None)
                            )
                            trade_log.info(
                                f"REST_GATE_CANCEL | exchange={self.config.primary_exchange} | side=buy | "
                                f"order_id={order.order_id} | reason=duplicate"
                            )
                        except Exception as e:
                            logger.error(f"[REST Gate] Failed to cancel duplicate bid: {e}")
                    exchange_bids = [sorted_bids[0]]  # 只保留最新的

                if len(exchange_asks) > 1:
                    logger.warning(f"[REST Gate] Multiple asks ({len(exchange_asks)}), cancelling extras")
                    sorted_asks = sorted(exchange_asks, key=lambda o: getattr(o, 'created_at', 0), reverse=True)
                    for order in sorted_asks[1:]:
                        try:
                            await self.primary.cancel_order(
                                symbol=self.config.symbol,
                                order_id=order.order_id,
                                client_order_id=getattr(order, 'client_order_id', None)
                            )
                            trade_log.info(
                                f"REST_GATE_CANCEL | exchange={self.config.primary_exchange} | side=sell | "
                                f"order_id={order.order_id} | reason=duplicate"
                            )
                        except Exception as e:
                            logger.error(f"[REST Gate] Failed to cancel duplicate ask: {e}")
                    exchange_asks = [sorted_asks[0]]

                rest_gate_ok = True

            except Exception as e:
                logger.error(f"[REST Gate] Failed to query open orders: {e}")
                self._rest_gate_failures += 1

                # ==================== 關鍵修復：REST 失敗時進入安全模式 ====================
                # 不回退到本地 state，直接返回不下單
                if self._rest_gate_failures >= 3:
                    logger.warning(
                        f"[REST Gate] {self._rest_gate_failures} consecutive failures, "
                        f"entering safe mode - skipping order placement"
                    )
                trade_log.info(
                    f"REST_GATE_SAFE_MODE | exchange={self.config.primary_exchange} | "
                    f"failures={self._rest_gate_failures} | error={str(e)[:100]}"
                )
                return  # 直接返回，不下單

            # REST 查詢成功，重置失敗計數
            self._rest_gate_failures = 0

        # ==================== 用 REST 結果決定是否可下單 ====================
        # 關鍵：用交易所查詢結果，而不是本地 state
        has_bid_on_exchange = len(exchange_bids) > 0
        has_ask_on_exchange = len(exchange_asks) > 0

        # ==================== 倉位同步（風控關鍵）====================
        # 在 hard stop 檢查前同步倉位，確保風控準確
        # 這是防止漏接成交導致風控失效的關鍵機制
        # 節流：每 2 秒最多同步一次，避免 API 過載
        now = time.time()
        if now - self._last_position_sync >= self._position_sync_interval:
            await self._sync_primary_position()
            self._last_position_sync = now
        current_position = self._get_primary_position()
        max_pos = self.config.max_position_btc
        hard_stop = self.config.hard_stop_position_btc

        # ==================== 硬停檢查 ====================
        # 超過 hard_stop 全部停掛，記錄時間以便自動恢復
        if abs(current_position) >= hard_stop:
            logger.warning(
                f"[RiskControl] Position {current_position} >= hard_stop {hard_stop}, "
                f"pausing ALL orders"
            )
            await self._cancel_all_orders(reason="hard stop")
            self._status = ExecutorStatus.PAUSED
            self._hard_stop_time = time.time()  # 記錄觸發時間
            if self._on_status_change:
                await self._on_status_change(self._status)
            return

        # ==================== Spread 保護 (rebate 模式) ====================
        if self.config.strategy_mode == "rebate":
            spread = best_ask - best_bid
            min_spread = self._tick_size * Decimal(self.config.min_spread_ticks)

            if spread < min_spread:
                # Spread 太窄：根據庫存只掛一邊，避免 post_only reject 或自成交
                logger.warning(f"Spread too narrow: {spread}, min_spread={min_spread}, placing one side only")

                if current_position > 0:
                    # 多頭庫存 → 只掛 ask（想賣出）
                    # 用 REST 結果判斷，而不是本地 state
                    if not has_ask_on_exchange and not self._placing_ask:
                        await self._place_ask(best_ask, post_only=True)
                else:
                    # 空頭或中性庫存 → 只掛 bid（想買入）
                    if not has_bid_on_exchange and not self._placing_bid:
                        await self._place_bid(best_bid, post_only=True)
                return

        # 診斷日誌：下單決策（使用 DEBUG 級別減少噪音）
        logger.debug(
            f"[PlaceOrders] position={current_position}, max_pos={max_pos}, "
            f"hard_stop={hard_stop}, has_bid_exchange={has_bid_on_exchange}, has_ask_exchange={has_ask_on_exchange}"
        )

        # 計算報價
        bid_price, ask_price = self._calculate_prices(mid_price, best_bid, best_ask)

        # 決定是否使用 post_only
        use_post_only = self.config.post_only or self.config.strategy_mode == "rebate"

        # ==================== 軟停：超過 max_pos 只掛回補方向 ====================
        can_place_bid = current_position < max_pos   # 還沒 long 到上限
        can_place_ask = current_position > -max_pos  # 還沒 short 到下限

        # ==================== 掛買單（用 REST 結果 + 本地狀態判斷）====================
        local_bid = self.state.get_bid_order()
        if not can_place_bid:
            logger.debug(f"[Limit] Skipping bid: pos {current_position} >= max {max_pos}")
        elif has_bid_on_exchange:
            # 交易所已有 bid，不再下單（REST gate 核心邏輯）
            logger.debug("Exchange already has bid order, skipping")
        elif self._placing_bid:
            logger.debug("Bid order already being placed, skipping")
        elif local_bid and not has_bid_on_exchange:
            # 【新增】本地有 bid 但 REST 沒查到 → 可能是 API 延遲，等待確認
            logger.debug(f"[Local Guard] Local bid exists but not on exchange yet, waiting for confirmation")
        else:
            await self._place_bid(bid_price, post_only=use_post_only)

        # ==================== 掛賣單（用 REST 結果 + 本地狀態判斷）====================
        local_ask = self.state.get_ask_order()
        if not can_place_ask:
            logger.debug(f"[Limit] Skipping ask: pos {current_position} <= -{max_pos}")
        elif has_ask_on_exchange:
            # 交易所已有 ask，不再下單（REST gate 核心邏輯）
            logger.debug("Exchange already has ask order, skipping")
        elif self._placing_ask:
            logger.debug("Ask order already being placed, skipping")
        elif local_ask and not has_ask_on_exchange:
            # 【新增】本地有 ask 但 REST 沒查到 → 可能是 API 延遲，等待確認
            logger.debug(f"[Local Guard] Local ask exists but not on exchange yet, waiting for confirmation")
        else:
            await self._place_ask(ask_price, post_only=use_post_only)

    def _calculate_prices(
        self,
        mid_price: Decimal,
        best_bid: Optional[Decimal] = None,
        best_ask: Optional[Decimal] = None
    ) -> tuple[Decimal, Decimal]:
        """
        計算報價 - 加入 Inventory Skew 和波動率調整

        策略模式：
        - uptime: 從 best_bid/best_ask 往外 order_distance_bps
        - rebate: 根據 aggressiveness 靠近市場（但永遠在外側）

        Inventory Skew：
        - long 偏多 → bid 更遠（push）、ask 更近（pull）
        - short 偏多 → bid 更近（pull）、ask 更遠（push）

        關鍵：rebate 模式下報價永遠在 best 的「外側」
        - bid 永遠 <= best_bid
        - ask 永遠 >= best_ask
        """
        import math
        tick_size = self._tick_size

        # ==================== Step 1: 計算基礎距離 ====================
        if self.config.strategy_mode == "rebate":
            if self.config.aggressiveness == "aggressive":
                base_bps = Decimal("0")
            elif self.config.aggressiveness == "moderate":
                base_bps = Decimal("1")
            else:  # conservative
                base_bps = Decimal("2")
        else:
            # Uptime 模式
            base_bps = Decimal(self.config.order_distance_bps)

        # ==================== Step 2: Inventory Skew 計算 ====================
        current_pos = self._get_primary_position()
        max_pos = self.config.max_position_btc
        order_size = self.config.order_size_btc

        # 防止 max_pos 太小導致 ratio 飽和
        effective_max_pos = max(
            max_pos,
            order_size * Decimal("3"),
            self.config.min_effective_max_pos_btc
        )

        # 【診斷】打印 skew 計算輸入（改為 debug 減少噪音）
        logger.debug(
            f"[Skew Input] current_pos={current_pos}, max_pos={max_pos}, "
            f"effective_max_pos={effective_max_pos}, base_bps={base_bps}"
        )

        if self.config.inventory_skew_enabled and effective_max_pos > 0:
            # pos_ratio: -1 (max short) ~ +1 (max long)
            pos_ratio = current_pos / effective_max_pos
            pos_ratio = max(Decimal("-1"), min(Decimal("1"), pos_ratio))

            # 雙向 skew：一邊拉遠、另一邊拉近
            push_bps = self.config.inventory_skew_max_bps   # 偏倉方向拉遠
            pull_bps = self.config.inventory_skew_pull_bps  # 回補方向拉近

            # 限制 pull 生效範圍，避免極端庫存時被 adverse selection 打穿
            max_pull_ratio = Decimal("0.7")  # pull 只在 70% 庫存內生效
            effective_ratio_for_pull = min(abs(pos_ratio), max_pull_ratio)

            if pos_ratio > 0:  # long 偏多
                bid_bps = base_bps + (pos_ratio * push_bps)                    # bid 更遠（用完整 ratio）
                ask_bps = base_bps - (effective_ratio_for_pull * pull_bps)    # ask 更近（用限制 ratio）
            else:  # short 偏多 (pos_ratio <= 0)
                bid_bps = base_bps - (effective_ratio_for_pull * pull_bps)    # bid 更近（用限制 ratio）
                ask_bps = base_bps + (abs(pos_ratio) * push_bps)              # ask 更遠（用完整 ratio）

            # 確保不低於最小距離（回補方向可用更近的 min）
            min_bps = self.config.min_quote_bps
            min_reversion_bps = self.config.min_reversion_quote_bps

            if pos_ratio > 0:  # long → ask 是回補方向
                bid_bps = max(min_bps, bid_bps)
                ask_bps = max(min_reversion_bps, ask_bps)
            else:  # short → bid 是回補方向
                bid_bps = max(min_reversion_bps, bid_bps)
                ask_bps = max(min_bps, ask_bps)

            # ==================== Skew 日誌去重（只在值變化時記錄）====================
            # 四捨五入以避免微小變化導致大量日誌
            rounded_ratio = round(float(pos_ratio), 2)
            rounded_bid_bps = round(float(bid_bps), 1)
            rounded_ask_bps = round(float(ask_bps), 1)
            current_skew = (rounded_ratio, rounded_bid_bps, rounded_ask_bps)

            if self._last_skew_log != current_skew:
                self._last_skew_log = current_skew

                logger.info(
                    f"[Skew Result] pos={current_pos}, ratio={rounded_ratio:.2f}, "
                    f"bid_bps={rounded_bid_bps:.1f}, ask_bps={rounded_ask_bps:.1f}, "
                    f"push={self.config.inventory_skew_max_bps}, pull={self.config.inventory_skew_pull_bps}"
                )

                # 交易日誌 - Skew 計算（只在變化時記錄）
                trade_log.info(
                    f"SKEW | exchange={self.config.primary_exchange} | pos={current_pos} | max_pos={max_pos} | ratio={rounded_ratio:.3f} | "
                    f"bid_bps={rounded_bid_bps:.2f} | ask_bps={rounded_ask_bps:.2f} | "
                    f"base_bps={float(base_bps):.1f}"
                )
        else:
            bid_bps = base_bps
            ask_bps = base_bps

        # ==================== Step 3: 保本回補覆蓋 ====================
        # 如果啟用保本回補且有建倉記錄，回補方向直接用 entry price
        breakeven_applied = False

        # 【診斷】打印保本回補狀態（改為 debug 減少噪音）
        logger.debug(
            f"[Breakeven Check] enabled={self.config.breakeven_reversion_enabled}, "
            f"has_entry={self.state.has_entry()}, "
            f"entry_price={self.state.get_entry_price()}, "
            f"entry_side={self.state.get_entry_side()}"
        )

        if self.config.breakeven_reversion_enabled and self.state.has_entry():
            entry_price = self.state.get_entry_price()
            entry_side = self.state.get_entry_side()
            offset_bps = self.config.breakeven_offset_bps

            if entry_price and entry_side:
                # 計算帶偏移的保本價格
                # offset > 0 = 更保守 (遠離 best)
                # offset < 0 = 更激進 (吃 rebate)
                if entry_side == "buy":
                    # 之前買入 → ask 用 entry price 賣出（確保不虧）
                    # ask_price = entry_price * (1 + offset_bps / 10000)
                    ask_price = entry_price * (Decimal("1") + offset_bps / Decimal("10000"))
                    # bid 仍用 skew 計算，不變
                    breakeven_applied = True
                    logger.info(
                        f"[Breakeven Applied] Entry buy @ {entry_price}, "
                        f"ask_price set to {ask_price} (offset={offset_bps} bps)"
                    )
                    # 交易日誌
                    trade_log.info(
                        f"BREAKEVEN | exchange={self.config.primary_exchange} | entry_side=buy | entry_price={entry_price} | "
                        f"ask_price={ask_price} | offset_bps={offset_bps}"
                    )
                else:  # entry_side == "sell"
                    # 之前賣出 → bid 用 entry price 買回（確保不虧）
                    # bid_price = entry_price * (1 - offset_bps / 10000)
                    bid_price = entry_price * (Decimal("1") - offset_bps / Decimal("10000"))
                    # ask 仍用 skew 計算，不變
                    breakeven_applied = True
                    logger.info(
                        f"[Breakeven Applied] Entry sell @ {entry_price}, "
                        f"bid_price set to {bid_price} (offset={offset_bps} bps)"
                    )
                    # 交易日誌
                    trade_log.info(
                        f"BREAKEVEN | exchange={self.config.primary_exchange} | entry_side=sell | entry_price={entry_price} | "
                        f"bid_price={bid_price} | offset_bps={offset_bps}"
                    )

        # ==================== Step 4: 波動率動態調整 ====================
        vol_raw = self.state.get_volatility_bps()
        volatility = Decimal(str(vol_raw)) if isinstance(vol_raw, float) else Decimal(vol_raw)
        vol_threshold = Decimal(str(self.config.volatility_threshold_bps))

        trigger_threshold = vol_threshold * Decimal("0.7")  # 70% 開始調整

        if volatility > trigger_threshold and vol_threshold > 0:
            # 線性增加：從 70% 閾值開始，到 100% 閾值達到 max multiplier
            ratio = (volatility - trigger_threshold) / (vol_threshold - trigger_threshold)
            ratio = min(Decimal("1"), ratio)  # 封頂

            vol_multiplier = Decimal("1") + (
                ratio * (self.config.volatility_distance_multiplier - Decimal("1"))
            )

            bid_bps = (bid_bps * vol_multiplier).quantize(Decimal("0.1"))
            ask_bps = (ask_bps * vol_multiplier).quantize(Decimal("0.1"))

            logger.debug(
                f"[Volatility] {float(volatility):.1f} bps (threshold={vol_threshold}), "
                f"multiplier={float(vol_multiplier):.2f}"
            )

        # ==================== Step 5: 計算最終價格 ====================
        # 保本回補側已在 Step 3 設定，這裡只計算非保本側
        if not breakeven_applied:
            # 沒有保本回補，兩邊都用 bps 計算
            bid_price = best_bid * (Decimal("1") - bid_bps / Decimal("10000"))
            ask_price = best_ask * (Decimal("1") + ask_bps / Decimal("10000"))
        else:
            # 有保本回補，只計算非保本側
            entry_side = self.state.get_entry_side()
            if entry_side == "buy":
                # ask 已設定保本價，只計算 bid
                bid_price = best_bid * (Decimal("1") - bid_bps / Decimal("10000"))
                # ask_price 已在 Step 3 設定
            else:  # entry_side == "sell"
                # bid 已設定保本價，只計算 ask
                ask_price = best_ask * (Decimal("1") + ask_bps / Decimal("10000"))
                # bid_price 已在 Step 3 設定

        # 確保不跨價（保本回補側允許在 best 內側）
        if not breakeven_applied:
            bid_price = min(bid_price, best_bid)
            ask_price = max(ask_price, best_ask)
        else:
            entry_side = self.state.get_entry_side()
            if entry_side == "buy":
                # bid 不跨價，ask 保本價可能在 best 內側（允許，能賺錢）
                bid_price = min(bid_price, best_bid)
            else:
                # ask 不跨價，bid 保本價可能在 best 內側（允許，能賺錢）
                ask_price = max(ask_price, best_ask)

        # ==================== Step 6: 對齊 tick ====================
        bid_price = Decimal(str(math.floor(float(bid_price) / float(tick_size)) * float(tick_size)))
        ask_price = Decimal(str(math.ceil(float(ask_price) / float(tick_size)) * float(tick_size)))

        # 日誌
        if breakeven_applied:
            entry_side = self.state.get_entry_side()
            entry_price = self.state.get_entry_price()
            logger.debug(
                f"[Quote] Final (breakeven={entry_side} @ {entry_price}): "
                f"bid={bid_price}, ask={ask_price}"
            )
        else:
            logger.debug(
                f"[Quote] Final: bid={bid_price} (bps={float(bid_bps):.1f}), "
                f"ask={ask_price} (bps={float(ask_bps):.1f})"
            )

        return bid_price, ask_price

    def _generate_client_order_id(self) -> str:
        """
        生成 client_order_id - 使用策略模式區分範圍

        - uptime 模式: 0 ~ 1B
        - rebate 模式: 1B ~ 2B

        這樣可以在日誌和交易所後台識別訂單來源
        """
        import random
        if self.config.strategy_mode == "rebate":
            # Rebate 模式: 1,000,000,000 ~ 1,999,999,999
            return str(random.randint(1_000_000_000, 1_999_999_999))
        else:
            # Uptime 模式: 0 ~ 999,999,999
            return str(random.randint(0, 999_999_999))

    async def _place_bid(self, price: Decimal, post_only: bool = False):
        """掛買單"""
        if self.config.dry_run:
            logger.info(f"[DRY RUN] Would place bid: {self.config.order_size_btc} @ {price} (post_only={post_only})")
            return

        # 【修復】原子性節流檢查 - 同時檢查並記錄，防止競爭條件
        if not self._order_throttle.try_acquire("buy"):
            logger.debug("[Throttle] Bid order throttled, cooldown active")
            return

        # 設置下單中標記，防止重複下單
        self._placing_bid = True
        try:
            # 生成策略專用的 client_order_id
            client_order_id = self._generate_client_order_id()

            order = await self.primary.place_order(
                symbol=self.config.symbol,
                side="buy",
                order_type=self.config.order_type,
                quantity=self.config.order_size_btc,
                price=price,
                time_in_force=self.config.time_in_force,
                post_only=post_only,
                client_order_id=client_order_id,
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

            logger.info(f"Bid placed: {self.config.order_size_btc} @ {price} (order_id={order.order_id}, client_order_id={order.client_order_id})")

            # 交易日誌
            pos = self._get_primary_position()
            trade_log.info(
                f"PLACE_BID | exchange={self.config.primary_exchange} | price={price} | qty={self.config.order_size_btc} | "
                f"best_bid={self._last_best_bid} | best_ask={self._last_best_ask} | "
                f"pos={pos} | order_id={order.order_id} | post_only={post_only}"
            )

        except Exception as e:
            logger.error(f"Failed to place bid: {e}")
            trade_log.info(f"PLACE_BID_FAIL | exchange={self.config.primary_exchange} | price={price} | error={e}")
        finally:
            self._placing_bid = False

    async def _place_ask(self, price: Decimal, post_only: bool = False):
        """掛賣單"""
        if self.config.dry_run:
            logger.info(f"[DRY RUN] Would place ask: {self.config.order_size_btc} @ {price} (post_only={post_only})")
            return

        # 【修復】原子性節流檢查 - 同時檢查並記錄，防止競爭條件
        if not self._order_throttle.try_acquire("sell"):
            logger.debug("[Throttle] Ask order throttled, cooldown active")
            return

        # 設置下單中標記，防止重複下單
        self._placing_ask = True
        try:
            # 生成策略專用的 client_order_id
            client_order_id = self._generate_client_order_id()

            order = await self.primary.place_order(
                symbol=self.config.symbol,
                side="sell",
                order_type=self.config.order_type,
                quantity=self.config.order_size_btc,
                price=price,
                time_in_force=self.config.time_in_force,
                post_only=post_only,
                client_order_id=client_order_id,
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

            logger.info(f"Ask placed: {self.config.order_size_btc} @ {price} (order_id={order.order_id}, client_order_id={order.client_order_id})")

            # 交易日誌
            pos = self._get_primary_position()
            trade_log.info(
                f"PLACE_ASK | exchange={self.config.primary_exchange} | price={price} | qty={self.config.order_size_btc} | "
                f"best_bid={self._last_best_bid} | best_ask={self._last_best_ask} | "
                f"pos={pos} | order_id={order.order_id} | post_only={post_only}"
            )

        except Exception as e:
            logger.error(f"Failed to place ask: {e}")
            trade_log.info(f"PLACE_ASK_FAIL | exchange={self.config.primary_exchange} | price={price} | error={e}")
        finally:
            self._placing_ask = False

    async def _cancel_order(self, client_order_id: str, reason: str = ""):
        """
        撤銷單個訂單（帶 REST 確認機制）

        流程：
        1. 發送取消請求
        2. 短暫等待讓交易所處理
        3. REST 確認訂單是否真的取消了
        4. 根據確認結果決定是否清除本地 state
        """
        # 先獲取訂單信息以記錄操作歷史
        bid = self.state.get_bid_order()
        ask = self.state.get_ask_order()
        order_side = None
        order_price = Decimal("0")
        order_qty = Decimal("0")
        order_id = None
        if bid and bid.client_order_id == client_order_id:
            order_side = "buy"
            order_price = bid.price
            order_qty = bid.qty
            order_id = bid.order_id
        elif ask and ask.client_order_id == client_order_id:
            order_side = "sell"
            order_price = ask.price
            order_qty = ask.qty
            order_id = ask.order_id

        if self.config.dry_run:
            logger.info(f"[DRY RUN] Would cancel order: {client_order_id}")
            return

        cancel_confirmed = False

        try:
            await self.primary.cancel_order(
                symbol=self.config.symbol,
                order_id=order_id,
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

            logger.info(f"Cancel request sent: {client_order_id}")

            # 交易日誌
            trade_log.info(
                f"CANCEL | exchange={self.config.primary_exchange} | side={order_side} | price={order_price} | "
                f"client_order_id={client_order_id} | reason={reason}"
            )

            # ==================== REST 確認取消成功 ====================
            # 短暫等待讓交易所處理取消請求
            await asyncio.sleep(0.3)

            # 查詢交易所確認訂單是否真的取消了
            try:
                open_orders = await self.primary.get_open_orders(self.config.symbol)
                # 檢查訂單是否還在 open orders 中
                order_still_exists = any(
                    getattr(o, 'client_order_id', None) == client_order_id or
                    getattr(o, 'order_id', None) == order_id
                    for o in open_orders
                )

                if order_still_exists:
                    logger.warning(f"[Cancel Confirm] Order {client_order_id} still exists after cancel request!")
                    trade_log.info(
                        f"CANCEL_NOT_CONFIRMED | exchange={self.config.primary_exchange} | "
                        f"client_order_id={client_order_id} | reason=order_still_exists"
                    )
                    # 訂單還在，不清除本地 state
                    cancel_confirmed = False
                else:
                    logger.info(f"[Cancel Confirm] Order {client_order_id} confirmed cancelled")
                    cancel_confirmed = True

            except Exception as confirm_error:
                logger.warning(f"[Cancel Confirm] Failed to confirm cancel: {confirm_error}")
                # 確認失敗時，假設取消成功（讓下一次 REST gate 處理）
                cancel_confirmed = True

        except Exception as e:
            # 優先用 error code
            error_code = getattr(e, 'code', None) or getattr(e, 'error_code', None)
            error_msg = str(e).lower()

            # 檢測是否為 ALREADY_FILLED（訂單已成交）
            fill_codes = ['ALREADY_FILLED']
            fill_keywords = ['already filled', 'order filled', 'has been filled']
            is_filled = error_code in fill_codes or any(kw in error_msg for kw in fill_keywords)

            # 這些情況視為正常（訂單已經不存在）
            ok_codes = ['ORDER_NOT_FOUND', 'ALREADY_FILLED', 'ALREADY_CANCELED']
            ok_keywords = ['not found', 'already', 'filled', 'canceled', 'cancelled', 'does not exist']

            if error_code in ok_codes or any(kw in error_msg for kw in ok_keywords):
                if is_filled:
                    # ==================== 訂單已成交，記錄 FILL 事件 ====================
                    logger.warning(f"[Cancel->Fill] Order {client_order_id} was FILLED during cancel!")
                    trade_log.info(
                        f"FILL_ON_CANCEL | exchange={self.config.primary_exchange} | "
                        f"side={order_side} | price={order_price} | qty={order_qty} | "
                        f"client_order_id={client_order_id} | reason=cancel_returned_filled"
                    )
                    # 記錄成交統計（不觸發對沖，僅記錄）
                    self.state.record_fill()
                    # 記錄成交事件（供前端顯示）
                    if order_side and order_price and order_qty:
                        self.state.record_fill_event(
                            side=order_side,
                            price=order_price,
                            qty=order_qty,
                            is_maker=True,  # 撤單時成交通常是 maker
                            order_id=client_order_id,
                        )
                else:
                    logger.info(f"Order already gone: {client_order_id} (code={error_code})")
                    trade_log.info(f"CANCEL_GONE | exchange={self.config.primary_exchange} | client_order_id={client_order_id} | code={error_code}")
                cancel_confirmed = True  # 訂單不存在，視為取消成功
            else:
                logger.error(f"Failed to cancel order {client_order_id}: {e}")
                trade_log.info(f"CANCEL_FAIL | exchange={self.config.primary_exchange} | client_order_id={client_order_id} | error={e}")
                cancel_confirmed = False  # 取消失敗，不清除本地 state

        # ==================== 根據確認結果清除本地狀態 ====================
        if cancel_confirmed:
            self._clear_order_by_id(client_order_id)
        else:
            logger.warning(f"[Cancel] Not clearing local state for {client_order_id} - cancel not confirmed")

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

        # 額外安全措施：撤銷交易所上該 symbol 的所有訂單
        # 避免因狀態不同步導致遺漏訂單
        if reason == "stop":
            try:
                open_orders = await self.primary.get_open_orders(self.config.symbol)
                if open_orders:
                    logger.warning(f"[Stop] Found {len(open_orders)} untracked orders, canceling...")
                    for order in open_orders:
                        try:
                            await self.primary.cancel_order(self.config.symbol, order.order_id)
                            logger.info(f"[Stop] Canceled untracked order {order.order_id}")
                        except Exception as e:
                            logger.warning(f"[Stop] Failed to cancel {order.order_id}: {e}")
            except Exception as e:
                logger.warning(f"[Stop] Failed to query open orders: {e}")

    async def _check_order_status(self):
        """
        改進的訂單狀態檢測

        功能：
        1. 檢測部分成交（通過 remaining_qty 變化）
        2. 檢測訂單消失（等待時間閾值後處理）
        3. API 失敗時不推進 disappeared_since_ts

        WebSocket 模式：
        - 跳過訂單消失檢測（由 WebSocket 處理成交）
        - 仍檢測部分成交（更新 remaining_qty）
        """
        import time

        bid = self.state.get_bid_order()
        ask = self.state.get_ask_order()

        if not bid and not ask:
            return  # 沒有訂單需要檢查

        # WebSocket 模式：減少 API 調用頻率
        if self._use_websocket:
            # 只做輕量級檢查，不處理訂單消失
            return

        # 診斷日誌：本地追蹤的訂單
        tracked_ids = []
        if bid:
            tracked_ids.append(f"bid:{bid.client_order_id}")
        if ask:
            tracked_ids.append(f"ask:{ask.client_order_id}")
        logger.debug(f"[OrderCheck] Tracking orders: {tracked_ids}")

        # API 調用可能失敗，需要容錯
        try:
            open_orders = await self.primary.get_open_orders(self.config.symbol)
        except Exception as e:
            logger.warning(f"Failed to get open orders: {e}")
            # API 失敗時，不推進 disappeared_since_ts
            return

        # 診斷日誌：交易所返回的訂單
        logger.debug(f"[OrderCheck] Exchange returned {len(open_orders)} open orders")
        for o in open_orders:
            logger.debug(f"[OrderCheck] Remote order: client_order_id={o.client_order_id}, order_id={o.order_id}, status={o.status}")

        # 構建 open_order_map（同時用 client_order_id 和 order_id 匹配）
        open_order_map = {}
        for o in open_orders:
            if o.client_order_id:
                open_order_map[o.client_order_id] = o
            # 同時用 order_id 作為 key（備用匹配）
            if o.order_id:
                open_order_map[f"oid:{o.order_id}"] = o

        # 收集消失的訂單（統一處理）
        disappeared_orders = []

        for order in [bid, ask]:
            if not order:
                continue

            # 嘗試匹配：優先 client_order_id，其次 order_id
            remote_order = open_order_map.get(order.client_order_id)
            if not remote_order and order.order_id:
                remote_order = open_order_map.get(f"oid:{order.order_id}")

            if remote_order:
                # 訂單仍存在
                logger.debug(f"[OrderCheck] Order {order.client_order_id} still open (matched via {'client_order_id' if open_order_map.get(order.client_order_id) else 'order_id'})")
                order.disappeared_since_ts = None  # 重置

                # 部分成交檢測（用 delta）
                if hasattr(remote_order, 'remaining_qty') and remote_order.remaining_qty is not None:
                    # 容忍 remote 可能回傳 float
                    remote_remaining = Decimal(str(remote_order.remaining_qty))
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
                    logger.info(f"[OrderCheck] Order disappeared: {order.side} client_order_id={order.client_order_id}, order_id={order.order_id}")
                elif now - order.disappeared_since_ts >= self.config.disappear_time_sec:
                    # 消失超過時間閾值
                    logger.info(f"[OrderCheck] Order confirmed disappeared (>{self.config.disappear_time_sec}s): {order.client_order_id}")
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
        logger.info(f"[FillDetect] Handling {len(orders)} disappeared order(s): {[o.client_order_id for o in orders]}")

        # 先同步倉位（無論單張多張）
        old_position = self.state.get_standx_position()
        await self._sync_standx_position()
        new_position = self.state.get_standx_position()
        position_delta = new_position - old_position

        logger.info(f"[FillDetect] Position sync: old={old_position}, new={new_position}, delta={position_delta}")

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

    async def _check_position_and_fill(self):
        """
        【關鍵】用倉位變化偵測成交

        這比「訂單消失」更可靠，因為：
        1. 訂單可能被 rebalance 取消，但倉位不會說謊
        2. 即使 tick_interval 較長，倉位變化還是能偵測到
        """
        old_position = self.state.get_standx_position()
        new_position = await self._sync_standx_position()
        position_delta = new_position - old_position

        # 檢測倉位變化（容忍微小誤差）
        if abs(position_delta) > Decimal("0.0001"):
            logger.info(f"[PositionFill] Position changed: {old_position} → {new_position}, delta={position_delta}")

            # 推斷成交方向和數量
            if position_delta > 0:
                # 倉位增加 = 買入成交
                fill_side = "buy"
                fill_qty = position_delta
            else:
                # 倉位減少 = 賣出成交
                fill_side = "sell"
                fill_qty = abs(position_delta)

            # 創建成交事件
            fill_event = FillEvent(
                order_id="position_inferred",
                client_order_id="position_inferred",
                symbol=self.config.symbol,
                side=fill_side,
                fill_qty=fill_qty,
                fill_price=self._last_mid_price or Decimal("0"),  # 用中間價估算
                remaining_qty=Decimal("0"),
                is_fully_filled=True,
                timestamp=datetime.now(),
            )

            # 清除對應方向的訂單（因為已經成交了）
            if fill_side == "buy":
                self.state.clear_bid_order()
            else:
                self.state.clear_ask_order()

            # 觸發成交處理流程
            await self.on_fill_event(fill_event)

    def _get_primary_position(self) -> Decimal:
        """
        統一倉位獲取入口 - 依 primary_exchange 路由

        Returns:
            當前主做市交易所的倉位 (正=long, 負=short)
        """
        return self.state.get_position(
            self.config.primary_exchange,
            self.config.symbol
        )

    async def _sync_primary_position(self) -> Decimal:
        """
        同步主做市交易所的倉位 (使用 self.primary adapter)

        會同時更新：
        1. 通用倉位 map: state.set_position(exchange, symbol, pos)
        2. 舊版倉位欄位: state.set_standx_position (for backward compat)

        Returns:
            同步後的倉位
        """
        try:
            positions = await self.primary.get_positions(self.config.symbol)
            logger.debug(f"[Sync] Got {len(positions)} positions for {self.config.symbol}")

            # 提取 base asset 用於匹配 (BTC, ETH, etc.)
            symbol_base = self.config.symbol.upper().replace("-", "_").replace("/", "_").split("_")[0]

            for pos in positions:
                # 智能匹配：只要 base asset 相同就算匹配
                # 統一處理各種分隔符 (-, /, _)
                pos_base = pos.symbol.upper().replace("-", "_").replace("/", "_").split("_")[0]
                if pos_base == symbol_base:
                    position_qty = Decimal(str(pos.size)) if pos.side == "long" else -Decimal(str(pos.size))

                    # 更新通用倉位 map
                    self.state.set_position(
                        self.config.primary_exchange,
                        self.config.symbol,
                        position_qty
                    )
                    # 同時更新舊版欄位 (for backward compat)
                    self.state.set_standx_position(position_qty)

                    logger.debug(
                        f"[Sync] Primary ({self.config.primary_exchange}) position: {position_qty} "
                        f"(symbol={pos.symbol}, matched base={symbol_base})"
                    )
                    return position_qty

            # 沒有找到倉位，設為 0
            self.state.set_position(self.config.primary_exchange, self.config.symbol, Decimal("0"))
            self.state.set_standx_position(Decimal("0"))
            logger.debug(f"[Sync] Primary ({self.config.primary_exchange}) position: 0 (no {symbol_base} position found)")
            return Decimal("0")
        except Exception as e:
            logger.error(f"Failed to sync primary exchange position: {e}")
            return self._get_primary_position()

    async def _sync_standx_position(self) -> Decimal:
        """
        @deprecated - 使用 _sync_primary_position() 代替

        保留作為 backward compat
        """
        return await self._sync_primary_position()

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
                    logger.debug(f"[Sync] Hedge (GRVT) position: {position_qty}")
                    return position_qty
            # 沒有找到倉位，設為 0
            self.state.set_hedge_position(Decimal("0"))
            logger.debug("[Sync] Hedge (GRVT) position: 0 (no position found)")
            return Decimal("0")
        except Exception as e:
            logger.error(f"Failed to sync hedge position: {e}")
            return self.state.get_hedge_position()

    async def _sync_open_orders(self) -> bool:
        """
        同步本地訂單狀態和交易所實際訂單

        用 REST API 查詢交易所的 open orders，與 local state 比對：
        - 如果 local state 有訂單但交易所沒有 → 清除 local state
        - 如果交易所有訂單但 local state 沒有 → 記錄警告（可能是手動下的單）
        - 如果交易所有多個同方向訂單 → 取消多餘的（保留最新的）

        Returns:
            True if sync successful, False otherwise
        """
        try:
            # 查詢交易所實際 open orders
            open_orders = await self.primary.get_open_orders(self.config.symbol)
            logger.debug(f"[SyncOrders] Got {len(open_orders)} open orders from exchange")

            # 分類訂單
            exchange_bids = []  # 交易所上的買單
            exchange_asks = []  # 交易所上的賣單

            for order in open_orders:
                # 只處理 open 狀態的訂單
                if order.status not in ["open", "partially_filled", "new"]:
                    continue

                if order.side.lower() == "buy":
                    exchange_bids.append(order)
                else:
                    exchange_asks.append(order)

            # 獲取 local state
            local_bid = self.state.get_bid_order()
            local_ask = self.state.get_ask_order()

            corrections_made = False

            # ==================== 檢查買單 ====================
            if local_bid and not exchange_bids:
                # Local 有買單但交易所沒有 → 清除 local state
                logger.warning(
                    f"[SyncOrders] BID desync: local has order {local_bid.client_order_id} "
                    f"but exchange has none, clearing local state"
                )
                trade_log.info(
                    f"SYNC_CORRECTION | exchange={self.config.primary_exchange} | side=buy | action=clear_local | "
                    f"client_order_id={local_bid.client_order_id} | reason=not_on_exchange"
                )
                self.state.clear_bid_order()
                corrections_made = True

            elif not local_bid and exchange_bids:
                # 交易所有買單但 local 沒有 → 可能是手動下的或 state 漏了
                logger.warning(
                    f"[SyncOrders] BID desync: exchange has {len(exchange_bids)} orders "
                    f"but local has none (orphan orders)"
                )
                # 取消這些孤兒訂單
                for order in exchange_bids:
                    logger.warning(f"[SyncOrders] Cancelling orphan bid: {order.order_id}")
                    trade_log.info(
                        f"SYNC_CORRECTION | exchange={self.config.primary_exchange} | side=buy | action=cancel_orphan | "
                        f"order_id={order.order_id} | price={order.price}"
                    )
                    try:
                        await self.primary.cancel_order(
                            symbol=self.config.symbol,
                            order_id=order.order_id,
                            client_order_id=getattr(order, 'client_order_id', None)
                        )
                    except Exception as e:
                        logger.error(f"[SyncOrders] Failed to cancel orphan bid: {e}")
                corrections_made = True

            elif len(exchange_bids) > 1:
                # 交易所有多個買單 → 取消多餘的（保留最新的）
                logger.warning(f"[SyncOrders] Multiple bids on exchange: {len(exchange_bids)}, keeping newest")
                # 按創建時間排序，保留最新的
                sorted_bids = sorted(exchange_bids, key=lambda o: getattr(o, 'created_at', 0), reverse=True)
                for order in sorted_bids[1:]:  # 跳過第一個（最新的）
                    logger.warning(f"[SyncOrders] Cancelling duplicate bid: {order.order_id}")
                    trade_log.info(
                        f"SYNC_CORRECTION | exchange={self.config.primary_exchange} | side=buy | action=cancel_duplicate | "
                        f"order_id={order.order_id} | price={order.price}"
                    )
                    try:
                        await self.primary.cancel_order(
                            symbol=self.config.symbol,
                            order_id=order.order_id,
                            client_order_id=getattr(order, 'client_order_id', None)
                        )
                    except Exception as e:
                        logger.error(f"[SyncOrders] Failed to cancel duplicate bid: {e}")
                corrections_made = True

            # ==================== 檢查賣單 ====================
            if local_ask and not exchange_asks:
                # Local 有賣單但交易所沒有 → 清除 local state
                logger.warning(
                    f"[SyncOrders] ASK desync: local has order {local_ask.client_order_id} "
                    f"but exchange has none, clearing local state"
                )
                trade_log.info(
                    f"SYNC_CORRECTION | exchange={self.config.primary_exchange} | side=sell | action=clear_local | "
                    f"client_order_id={local_ask.client_order_id} | reason=not_on_exchange"
                )
                self.state.clear_ask_order()
                corrections_made = True

            elif not local_ask and exchange_asks:
                # 交易所有賣單但 local 沒有 → 可能是手動下的或 state 漏了
                logger.warning(
                    f"[SyncOrders] ASK desync: exchange has {len(exchange_asks)} orders "
                    f"but local has none (orphan orders)"
                )
                # 取消這些孤兒訂單
                for order in exchange_asks:
                    logger.warning(f"[SyncOrders] Cancelling orphan ask: {order.order_id}")
                    trade_log.info(
                        f"SYNC_CORRECTION | exchange={self.config.primary_exchange} | side=sell | action=cancel_orphan | "
                        f"order_id={order.order_id} | price={order.price}"
                    )
                    try:
                        await self.primary.cancel_order(
                            symbol=self.config.symbol,
                            order_id=order.order_id,
                            client_order_id=getattr(order, 'client_order_id', None)
                        )
                    except Exception as e:
                        logger.error(f"[SyncOrders] Failed to cancel orphan ask: {e}")
                corrections_made = True

            elif len(exchange_asks) > 1:
                # 交易所有多個賣單 → 取消多餘的（保留最新的）
                logger.warning(f"[SyncOrders] Multiple asks on exchange: {len(exchange_asks)}, keeping newest")
                sorted_asks = sorted(exchange_asks, key=lambda o: getattr(o, 'created_at', 0), reverse=True)
                for order in sorted_asks[1:]:
                    logger.warning(f"[SyncOrders] Cancelling duplicate ask: {order.order_id}")
                    trade_log.info(
                        f"SYNC_CORRECTION | exchange={self.config.primary_exchange} | side=sell | action=cancel_duplicate | "
                        f"order_id={order.order_id} | price={order.price}"
                    )
                    try:
                        await self.primary.cancel_order(
                            symbol=self.config.symbol,
                            order_id=order.order_id,
                            client_order_id=getattr(order, 'client_order_id', None)
                        )
                    except Exception as e:
                        logger.error(f"[SyncOrders] Failed to cancel duplicate ask: {e}")
                corrections_made = True

            if corrections_made:
                logger.info("[SyncOrders] State corrections applied")

            return True

        except Exception as e:
            logger.error(f"[SyncOrders] Failed to sync open orders: {e}")
            return False

    async def on_fill_event(self, fill: FillEvent):
        """
        處理成交事件 - 三段式撤單策略 + partial fill 處理

        流程:
        1. 同步倉位（從交易所查詢實際倉位）
        2. 檢查 partial fill（用 API 查詢作為真相來源）
        3. 根據 fill_cancel_policy 決定是否撤單
        4. 執行對沖（如果有 hedge_engine）
        5. 對沖完成後同步倉位並重新掛單

        fill_cancel_policy:
        - "all": 撤銷雙邊（有對沖時用）
        - "opposite": 只撤對手邊（通用）
        - "none": 不撤銷（無對沖回補模式）

        【保險絲 3】使用 try/finally 確保狀態回復
        """
        logger.info(
            f"Fill received: {fill.side} {fill.fill_qty} @ {fill.fill_price}, "
            f"is_maker={fill.is_maker}, order_id={fill.order_id}"
        )

        # 交易日誌 - 成交
        pos_before = self._get_primary_position()
        trade_log.info(
            f"FILL | exchange={self.config.primary_exchange} | side={fill.side} | price={fill.fill_price} | qty={fill.fill_qty} | "
            f"is_maker={fill.is_maker} | pos_before={pos_before} | "
            f"order_id={fill.order_id} | client_order_id={fill.client_order_id}"
        )

        # 更新狀態
        self.state.record_fill()

        # 記錄成交事件（含詳細資訊，供前端顯示）
        self.state.record_fill_event(
            side=fill.side,
            price=fill.fill_price,
            qty=fill.fill_qty,
            is_maker=fill.is_maker,
            order_id=fill.client_order_id or fill.order_id,
        )

        # ==================== Rebate 追蹤 (rebate 模式) ====================
        if self.config.strategy_mode == "rebate":
            is_maker = fill.is_maker  # 可能是 True/False/None

            # 根據 is_maker 選擇費率
            if is_maker is True:
                fee_bps = self.config.maker_fee_bps   # 負數 = rebate
            elif is_maker is False:
                fee_bps = self.config.taker_fee_bps   # 正數 = 付費
            else:
                # Unknown - 保守估計用 taker fee
                fee_bps = self.config.taker_fee_bps

            self.state.record_rebate_fill(
                fill.fill_qty,
                fill.fill_price,
                is_maker=is_maker,
                fee_bps=fee_bps
            )

        # 記錄操作歷史
        self.state.record_operation(
            action="fill",
            side=fill.side,
            order_price=fill.fill_price,
            best_bid=self._last_best_bid,
            best_ask=self._last_best_ask,
            reason=f"qty={fill.fill_qty}",
        )

        # 只用一個同步方法，避免重複/混亂
        await self._sync_primary_position()

        # ==================== 保本回補：記錄建倉價格 ====================
        if self.config.breakeven_reversion_enabled:
            current_pos = self._get_primary_position()

            logger.info(
                f"[Breakeven on_fill] current_pos={current_pos}, has_entry={self.state.has_entry()}, "
                f"fill_side={fill.side}, fill_price={fill.fill_price}"
            )

            # 檢查是否已有 entry，或者倉位歸零/翻轉
            if not self.state.has_entry():
                # 新建倉：記錄 entry price
                if abs(current_pos) > Decimal("0"):
                    logger.info(f"[Breakeven] Recording new entry: {fill.side} @ {fill.fill_price}")
                    self.state.set_entry_price(fill.fill_price, fill.side)
            else:
                # 已有 entry：檢查是否應該清除
                entry_side = self.state.get_entry_side()

                # 倉位歸零：清除 entry
                if abs(current_pos) < Decimal("0.0001"):
                    self.state.clear_entry()
                # 倉位翻轉（例如原本 long，現在變 short）：更新 entry
                elif (entry_side == "buy" and current_pos < 0) or \
                     (entry_side == "sell" and current_pos > 0):
                    self.state.set_entry_price(fill.fill_price, fill.side)

        # ==================== Partial Fill 處理 ====================
        # 用 API 查詢作為真相來源
        is_fully_filled = True
        remaining_qty = Decimal("0")

        try:
            # 查詢該訂單 - 用 self.primary（不是 self.standx）
            order = await self.primary.get_order(fill.order_id)
            if order is None and hasattr(fill, 'client_order_id') and fill.client_order_id:
                # Fallback: 用 client_order_id 查
                if hasattr(self.primary, 'get_order_by_client_id'):
                    order = await self.primary.get_order_by_client_id(fill.client_order_id)

            if order and order.status not in ["filled", "canceled", "expired", "FILLED", "CANCELLED"]:
                # 訂單還在 → partial fill
                remaining_qty = Decimal(str(order.qty)) - Decimal(str(order.filled_qty))
                is_fully_filled = (remaining_qty <= 0)
            # order 查不到 → 視為 fully filled 或 canceled
        except Exception as e:
            # API 失敗時 fallback 到 fill event 的 remaining_qty
            logger.warning(f"[PartialFill] Query failed, using event data: {e}")
            remaining_qty = getattr(fill, 'remaining_qty', None) or Decimal("0")
            is_fully_filled = (remaining_qty <= 0)

        if not is_fully_filled:
            logger.info(f"[PartialFill] Order {fill.order_id} still has {remaining_qty} remaining")

        # 更新本地訂單狀態
        if is_fully_filled:
            # 全部成交 → 清除該邊
            if fill.side == "buy":
                self.state.clear_bid_order()
            else:
                self.state.clear_ask_order()
        else:
            # Partial fill → 更新剩餘數量
            if fill.side == "buy" and self.state.get_bid_order():
                self.state.get_bid_order().last_remaining_qty = remaining_qty
            elif fill.side == "sell" and self.state.get_ask_order():
                self.state.get_ask_order().last_remaining_qty = remaining_qty

        # ==================== 三段式撤單策略 ====================
        policy = self.config.fill_cancel_policy

        if policy == "all":
            # 有對沖模式：撤銷雙邊，準備重新報價
            await self._cancel_all_orders(reason="fill received (policy=all)")

        elif policy == "opposite":
            # 通用模式：只撤對手邊
            if fill.side == "buy":
                ask = self.state.get_ask_order()
                if ask:
                    await self._cancel_order(ask.client_order_id, reason="fill opposite cancel")
            else:
                bid = self.state.get_bid_order()
                if bid:
                    await self._cancel_order(bid.client_order_id, reason="fill opposite cancel")

        else:  # policy == "none"
            # 無對沖回補模式：保留另一邊等回補
            other_side = "ask" if fill.side == "buy" else "bid"
            logger.info(f"[NoHedge] Keeping {other_side} for reversion (policy=none)")

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

                # ==================== 記錄對沖成本 (rebate 模式) ====================
                if self.config.strategy_mode == "rebate" and hedge_result.success:
                    # 計算滑點損失
                    if hedge_result.execution_price and hedge_result.hedge_side:
                        # 用 hedge_side 決定 sign
                        side_sign = Decimal("1") if hedge_result.hedge_side == "buy" else Decimal("-1")
                        slippage_loss = (hedge_result.execution_price - fill.fill_price) * fill.fill_qty * side_sign
                    else:
                        # 回退：用 fill_price 估算
                        slippage_loss = Decimal("0")

                    self.state.record_hedge_cost(
                        fee_paid=hedge_result.fee_paid,
                        slippage_loss=slippage_loss
                    )

                # 對沖完成後，同步對沖交易所實際倉位
                await self._sync_hedge_position()

                # 如果對沖回退，重新同步主做市交易所倉位
                if hedge_result.status in [HedgeStatus.FALLBACK, HedgeStatus.PARTIAL_FALLBACK]:
                    await self._sync_primary_position()

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

        stats = {
            "status": self._status.value,
            "uptime_seconds": uptime,
            "total_quotes": self._total_quotes,
            "total_cancels": self._total_cancels,
            "last_mid_price": float(self._last_mid_price) if self._last_mid_price else None,
            "volatility_bps": self.state.get_volatility_bps(),
            **self.state.get_stats(),
            "hedge_stats": self.hedge_engine.get_stats() if self.hedge_engine else None,
            # WebSocket status
            "websocket_enabled": self._use_websocket,
            "websocket_connected": self._ws_connected,
        }

        # Add WebSocket stats if available
        if self._use_websocket and hasattr(self.standx, 'get_ws_stats'):
            stats["websocket_stats"] = self.primary.get_ws_stats()

        return stats

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
                "volatility_resume_threshold_bps": self.config.volatility_resume_threshold_bps,
                "volatility_stable_seconds": self.config.volatility_stable_seconds,
                "dry_run": self.config.dry_run,
                # 策略模式參數
                "strategy_mode": self.config.strategy_mode,
                "aggressiveness": self.config.aggressiveness,
                "post_only": self.config.post_only,
                "cancel_on_approach": self.config.cancel_on_approach,
                "min_spread_ticks": self.config.min_spread_ticks,
                # 止血策略參數
                "primary_exchange": self.config.primary_exchange,
                "inventory_skew_enabled": self.config.inventory_skew_enabled,
                "inventory_skew_max_bps": float(self.config.inventory_skew_max_bps),
                "inventory_skew_pull_bps": float(self.config.inventory_skew_pull_bps),
                "min_quote_bps": float(self.config.min_quote_bps),
                "hard_stop_position_btc": float(self.config.hard_stop_position_btc),
                "resume_position_btc": float(self.config.resume_position_btc),
                "fill_cancel_policy": self.config.fill_cancel_policy,
            },
            "state": self.state.to_dict(),
            "stats": self.get_stats(),
        }
