"""
Binance 對沖引擎
Hedge Engine for Binance

成交後立即在 Binance 執行對沖訂單
- 1 秒內完成
- 重試 3 次
- 失敗後回退到 StandX 平倉
"""
import asyncio
import logging
import time
from typing import Optional
from decimal import Decimal
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class HedgeStatus(Enum):
    """對沖狀態"""
    PENDING = "pending"
    EXECUTING = "executing"
    FILLED = "filled"
    PARTIAL = "partial"
    FAILED = "failed"
    TIMEOUT = "timeout"
    FALLBACK = "fallback"  # 回退到 StandX 平倉


@dataclass
class HedgeConfig:
    """對沖配置"""
    symbol: str = "BTC/USDT:USDT"    # Binance 交易對
    timeout_ms: int = 1000            # 超時時間 (1秒)
    max_retries: int = 3              # 最大重試次數
    retry_delay_ms: int = 100         # 重試間隔
    use_market_order: bool = True     # 使用市價單
    max_slippage_bps: int = 20        # 最大允許滑點


@dataclass
class HedgeResult:
    """對沖結果"""
    success: bool
    status: HedgeStatus
    source_fill_id: str              # 觸發對沖的成交 ID

    # 執行信息
    order_id: Optional[str] = None
    fill_price: Optional[Decimal] = None
    fill_qty: Optional[Decimal] = None
    slippage_bps: Optional[float] = None

    # 重試信息
    attempts: int = 0
    latency_ms: float = 0.0

    # 錯誤信息
    error_message: Optional[str] = None

    # 時間戳
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None


class HedgeEngine:
    """
    對沖引擎

    職責:
    1. 在 Binance 執行對沖訂單 (市價單)
    2. 實現重試機制 (最多 3 次)
    3. 超時處理 (1 秒)
    4. 失敗時回退到 StandX 平倉
    """

    def __init__(
        self,
        binance_adapter,       # CCXTAdapter
        standx_adapter,        # StandXAdapter (用於回退平倉)
        config: Optional[HedgeConfig] = None,
    ):
        self.binance = binance_adapter
        self.standx = standx_adapter
        self.config = config or HedgeConfig()

        # 統計
        self._total_attempts = 0
        self._total_success = 0
        self._total_failed = 0
        self._total_fallback = 0
        self._total_latency_ms = 0.0

    async def execute_hedge(
        self,
        fill_id: str,
        fill_side: str,           # "buy" or "sell" (StandX 成交方向)
        fill_qty: Decimal,
        fill_price: Decimal,
        standx_symbol: str = "BTC-USD",
    ) -> HedgeResult:
        """
        執行對沖

        StandX 買入成交 → Binance 賣出
        StandX 賣出成交 → Binance 買入

        Args:
            fill_id: 觸發對沖的成交 ID
            fill_side: StandX 成交方向 ("buy" or "sell")
            fill_qty: 成交數量
            fill_price: 成交價格 (用於計算滑點)
            standx_symbol: StandX 交易對 (用於回退平倉)

        Returns:
            HedgeResult: 對沖結果
        """
        start_time = time.time()

        # 對沖方向 (反向)
        hedge_side = "sell" if fill_side == "buy" else "buy"

        result = HedgeResult(
            success=False,
            status=HedgeStatus.PENDING,
            source_fill_id=fill_id,
            started_at=datetime.now(),
        )

        logger.info(f"Starting hedge: {hedge_side} {fill_qty} BTC (source fill: {fill_id})")

        # 重試執行
        for attempt in range(1, self.config.max_retries + 1):
            self._total_attempts += 1
            result.attempts = attempt

            try:
                # 執行對沖
                hedge_result = await self._execute_single_hedge(
                    side=hedge_side,
                    qty=fill_qty,
                    reference_price=fill_price,
                    timeout_ms=self.config.timeout_ms,
                )

                if hedge_result["success"]:
                    # 對沖成功
                    result.success = True
                    result.status = HedgeStatus.FILLED
                    result.order_id = hedge_result.get("order_id")
                    result.fill_price = hedge_result.get("fill_price")
                    result.fill_qty = hedge_result.get("fill_qty")
                    result.slippage_bps = self._calculate_slippage(
                        fill_price,
                        hedge_result.get("fill_price"),
                        hedge_side
                    )

                    latency = (time.time() - start_time) * 1000
                    result.latency_ms = latency
                    result.completed_at = datetime.now()

                    self._total_success += 1
                    self._total_latency_ms += latency

                    logger.info(
                        f"Hedge success: {hedge_side} {fill_qty} @ {result.fill_price} "
                        f"(slippage: {result.slippage_bps:.1f} bps, latency: {latency:.0f}ms)"
                    )
                    return result

                else:
                    # 執行失敗，記錄錯誤
                    result.error_message = hedge_result.get("error", "Unknown error")
                    logger.warning(
                        f"Hedge attempt {attempt} failed: {result.error_message}"
                    )

            except asyncio.TimeoutError:
                result.error_message = "Timeout"
                result.status = HedgeStatus.TIMEOUT
                logger.warning(f"Hedge attempt {attempt} timeout")

            except Exception as e:
                result.error_message = str(e)
                logger.error(f"Hedge attempt {attempt} error: {e}")

            # 重試前等待
            if attempt < self.config.max_retries:
                await asyncio.sleep(self.config.retry_delay_ms / 1000)

        # 所有重試失敗，執行回退
        logger.error(f"All {self.config.max_retries} hedge attempts failed, executing fallback")
        result.status = HedgeStatus.FAILED
        self._total_failed += 1

        # 回退: 在 StandX 平倉
        fallback_result = await self._execute_fallback(
            side=fill_side,  # 原始成交方向
            qty=fill_qty,
            symbol=standx_symbol,
        )

        if fallback_result["success"]:
            result.status = HedgeStatus.FALLBACK
            self._total_fallback += 1
            logger.info(f"Fallback success: closed position on StandX")
        else:
            logger.error(f"Fallback also failed: {fallback_result.get('error')}")
            result.error_message = f"Hedge and fallback failed: {result.error_message}"

        result.latency_ms = (time.time() - start_time) * 1000
        result.completed_at = datetime.now()
        return result

    async def _execute_single_hedge(
        self,
        side: str,
        qty: Decimal,
        reference_price: Decimal,
        timeout_ms: int,
    ) -> dict:
        """執行單次對沖"""
        try:
            # 使用 asyncio.wait_for 設置超時
            order = await asyncio.wait_for(
                self.binance.place_order(
                    symbol=self.config.symbol,
                    side=side,
                    order_type="market",
                    quantity=qty,
                ),
                timeout=timeout_ms / 1000
            )

            # 市價單應該立即成交
            if order:
                return {
                    "success": True,
                    "order_id": getattr(order, "order_id", None) or str(order),
                    "fill_price": getattr(order, "price", reference_price),
                    "fill_qty": qty,
                }
            else:
                return {
                    "success": False,
                    "error": "Order returned None"
                }

        except asyncio.TimeoutError:
            raise

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    async def _execute_fallback(
        self,
        side: str,
        qty: Decimal,
        symbol: str,
    ) -> dict:
        """
        回退: 在 StandX 平倉

        如果買入成交後對沖失敗，在 StandX 賣出平倉
        如果賣出成交後對沖失敗，在 StandX 買入平倉
        """
        try:
            # 平倉方向 (反向)
            close_side = "sell" if side == "buy" else "buy"

            logger.info(f"Executing fallback: {close_side} {qty} on StandX")

            order = await self.standx.place_order(
                symbol=symbol,
                side=close_side,
                order_type="market",
                quantity=qty,
                reduce_only=True,  # 只減倉
            )

            if order:
                return {
                    "success": True,
                    "order_id": order.client_order_id,
                }
            else:
                return {
                    "success": False,
                    "error": "StandX order returned None"
                }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def _calculate_slippage(
        self,
        expected_price: Decimal,
        actual_price: Optional[Decimal],
        side: str,
    ) -> float:
        """
        計算滑點 (basis points)

        買入: 實際價格 > 預期價格 = 負滑點 (不利)
        賣出: 實際價格 < 預期價格 = 負滑點 (不利)
        """
        if actual_price is None or expected_price == 0:
            return 0.0

        diff = actual_price - expected_price
        if side == "buy":
            # 買入時，價格越高越不利
            slippage = -float(diff / expected_price * 10000)
        else:
            # 賣出時，價格越低越不利
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
