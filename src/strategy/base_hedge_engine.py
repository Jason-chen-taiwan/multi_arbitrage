"""
通用對沖引擎基類
Base Hedge Engine

定義對沖引擎的標準介面，支援多種對沖目標：
- StandX → StandX (同平台多帳戶)
- StandX → GRVT (跨 DEX)
- StandX → CEX (未來擴展)
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, Dict, Callable, Awaitable
from datetime import datetime
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class HedgeStatus(Enum):
    """對沖狀態"""
    PENDING = "pending"
    EXECUTING = "executing"
    FILLED = "filled"
    PARTIAL = "partial"
    FAILED = "failed"
    TIMEOUT = "timeout"
    FALLBACK = "fallback"

    # 風控狀態
    RISK_CONTROL = "risk_control"
    WAITING_RECOVERY = "waiting_recovery"
    PARTIAL_FALLBACK = "partial_fallback"
    FALLBACK_FAILED = "fallback_failed"


@dataclass
class BaseHedgeConfig:
    """通用對沖配置"""
    # 對沖目標類型
    hedge_type: str = "standx"  # "standx" | "grvt" | "binance" | "okx"

    # 超時和重試
    timeout_ms: int = 1000
    max_retries: int = 3
    retry_delay_ms: int = 100

    # 訂單類型
    use_market_order: bool = True
    max_slippage_bps: int = 20

    # 風控
    max_unhedged_position: Decimal = Decimal("0.01")

    # 交易對映射（子類可覆寫）
    symbol_map: Dict[str, str] = field(default_factory=dict)


@dataclass
class HedgeResult:
    """對沖結果"""
    success: bool
    status: HedgeStatus
    source_fill_id: str

    # 交易對信息
    source_symbol: str = ""
    hedge_symbol: str = ""

    # 數量信息
    requested_qty: Decimal = Decimal("0")
    normalized_qty: Decimal = Decimal("0")

    # 執行信息
    order_id: Optional[str] = None
    fill_price: Optional[Decimal] = None
    fill_qty: Optional[Decimal] = None
    hedge_side: Optional[str] = None
    slippage_bps: Optional[float] = None

    # 成本追蹤
    execution_price: Optional[Decimal] = None
    fee_paid: Decimal = Decimal("0")

    # 重試信息
    attempts: int = 0
    latency_ms: float = 0.0

    # 錯誤信息
    error_message: Optional[str] = None

    # 時間戳
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None


class BaseHedgeEngine(ABC):
    """
    對沖引擎基類

    職責:
    1. 在對沖目標執行對沖訂單 (市價單)
    2. 交易對映射（子類實現）
    3. 合約規格對齊（如果需要）
    4. 風控模式（失敗時暫停，超過 hard limit 才 fallback）
    5. 恢復檢測（連續 N 次成功才恢復）
    """

    # 恢復條件
    RECOVERY_SUCCESS_REQUIRED = 3
    RECOVERY_CHECK_INTERVAL_SEC = 2.0

    def __init__(
        self,
        hedge_adapter,           # 對沖目標適配器
        fallback_adapter,        # Fallback 適配器（通常是主帳戶）
        config: Optional[BaseHedgeConfig] = None,
    ):
        self.hedge_adapter = hedge_adapter
        self.fallback_adapter = fallback_adapter
        self.config = config or BaseHedgeConfig()

        # 恢復狀態
        self._recovery_success_count = 0
        self._last_recovery_check_ts: Optional[float] = None

        # 統計
        self._total_attempts = 0
        self._total_success = 0
        self._total_failed = 0
        self._total_fallback = 0
        self._total_latency_ms = 0.0

    @abstractmethod
    def map_symbol(self, source_symbol: str) -> str:
        """
        交易對映射

        子類需實現，例如：
        - StandX→StandX: BTC-USD → BTC-USD (直接返回)
        - StandX→GRVT: BTC-USD → BTC_USDT_Perp
        """
        pass

    @abstractmethod
    async def execute_hedge(
        self,
        fill_id: str,
        fill_side: str,
        fill_qty: Decimal,
        fill_price: Decimal,
        source_symbol: str,
    ) -> HedgeResult:
        """
        執行對沖

        source 買入成交 → 對沖目標賣出
        source 賣出成交 → 對沖目標買入
        """
        pass

    async def execute_fallback(
        self,
        side: str,
        qty: Decimal,
        symbol: str,
    ) -> dict:
        """在 Fallback 帳戶平倉"""
        try:
            close_side = "sell" if side == "buy" else "buy"

            logger.info(f"Executing fallback: {close_side} {qty} on fallback adapter")

            order = await self.fallback_adapter.place_order(
                symbol=symbol,
                side=close_side,
                order_type="market",
                quantity=qty,
                reduce_only=True,
            )

            if order:
                return {
                    "success": True,
                    "order_id": getattr(order, "client_order_id", None) or getattr(order, "order_id", None),
                }
            else:
                return {"success": False, "error": "Fallback order returned None"}

        except Exception as e:
            logger.error(f"Fallback failed: {e}")
            return {"success": False, "error": str(e)}

    def _calculate_slippage(
        self,
        expected_price: Decimal,
        actual_price: Optional[Decimal],
        side: str,
    ) -> float:
        """計算滑點 (basis points)"""
        if actual_price is None or expected_price == 0:
            return 0.0

        diff = actual_price - expected_price
        if side == "buy":
            slippage = -float(diff / expected_price * 10000)
        else:
            slippage = float(diff / expected_price * 10000)

        return slippage

    # ==================== 統計 ====================

    @property
    def success_rate(self) -> float:
        """成功率"""
        if self._total_attempts == 0:
            return 0.0
        return self._total_success / self._total_attempts * 100

    @property
    def avg_latency_ms(self) -> float:
        """平均延遲"""
        if self._total_success == 0:
            return 0.0
        return self._total_latency_ms / self._total_success

    def get_stats(self) -> dict:
        """獲取統計"""
        return {
            "hedge_type": self.config.hedge_type,
            "total_attempts": self._total_attempts,
            "total_success": self._total_success,
            "total_failed": self._total_failed,
            "total_fallback": self._total_fallback,
            "success_rate": self.success_rate,
            "avg_latency_ms": self.avg_latency_ms,
        }

    def reset_stats(self):
        """重置統計"""
        self._total_attempts = 0
        self._total_success = 0
        self._total_failed = 0
        self._total_fallback = 0
        self._total_latency_ms = 0.0

    # ==================== 恢復檢測 ====================

    async def check_recovery(self) -> bool:
        """
        檢查是否可以從 WAITING_RECOVERY 恢復

        條件：連續 N 次成功
        """
        import time
        now = time.time()

        # 頻率節流
        if (self._last_recovery_check_ts is not None and
            now - self._last_recovery_check_ts < self.RECOVERY_CHECK_INTERVAL_SEC):
            return False

        self._last_recovery_check_ts = now

        try:
            # 測試連接 - 獲取市場列表
            if hasattr(self.hedge_adapter, 'get_markets'):
                markets = await self.hedge_adapter.get_markets()
                if not markets:
                    self._recovery_success_count = 0
                    return False

            self._recovery_success_count += 1
            logger.info(f"Recovery check passed ({self._recovery_success_count}/{self.RECOVERY_SUCCESS_REQUIRED})")

            if self._recovery_success_count >= self.RECOVERY_SUCCESS_REQUIRED:
                self._recovery_success_count = 0
                return True

            return False

        except Exception as e:
            logger.warning(f"Recovery check failed: {e}")
            self._recovery_success_count = 0
            return False
