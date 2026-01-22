"""
StandX → StandX 對沖引擎
StandX Hedge Engine

同平台多帳戶對沖，交易對相同
- 主帳戶成交 → 對沖帳戶執行反向市價單
- 交易對直接映射（BTC-USD → BTC-USD）
"""
import asyncio
import logging
import time
from decimal import Decimal
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime

from .base_hedge_engine import (
    BaseHedgeEngine,
    BaseHedgeConfig,
    HedgeResult,
    HedgeStatus,
)

logger = logging.getLogger(__name__)

# 獲取 mm_trades 日誌（與做市策略共用同一個日誌文件）
trade_log = logging.getLogger("mm_trade")


@dataclass
class StandXHedgeConfig(BaseHedgeConfig):
    """StandX 對沖配置"""
    hedge_type: str = "standx"

    # StandX 特有配置
    use_same_symbol: bool = True  # 使用相同交易對


class StandXHedgeEngine(BaseHedgeEngine):
    """
    StandX 對沖引擎

    職責:
    1. 在另一個 StandX 帳戶執行對沖訂單
    2. 交易對直接映射（相同交易對）
    3. 風控模式（失敗時暫停或 fallback 到主帳戶平倉）
    """

    def __init__(
        self,
        hedge_adapter,           # 對沖 StandX 適配器
        fallback_adapter,        # 主 StandX 適配器（用於 fallback）
        config: Optional[StandXHedgeConfig] = None,
    ):
        super().__init__(
            hedge_adapter=hedge_adapter,
            fallback_adapter=fallback_adapter,
            config=config or StandXHedgeConfig(),
        )

    def map_symbol(self, source_symbol: str) -> str:
        """
        交易對映射 - StandX→StandX 直接返回相同交易對
        """
        # 檢查是否有自定義映射
        if source_symbol in self.config.symbol_map:
            return self.config.symbol_map[source_symbol]

        # 默認：使用相同交易對
        return source_symbol

    async def execute_hedge(
        self,
        fill_id: str,
        fill_side: str,
        fill_qty: Decimal,
        fill_price: Decimal,
        source_symbol: str,
    ) -> HedgeResult:
        """
        在另一個 StandX 帳戶執行對沖

        source 買入成交 → 對沖帳戶賣出
        source 賣出成交 → 對沖帳戶買入
        """
        start_time = time.time()

        # 對沖方向（反向）
        hedge_side = "sell" if fill_side == "buy" else "buy"

        # 交易對映射
        hedge_symbol = self.map_symbol(source_symbol)

        result = HedgeResult(
            success=False,
            status=HedgeStatus.PENDING,
            source_fill_id=fill_id,
            source_symbol=source_symbol,
            hedge_symbol=hedge_symbol,
            requested_qty=fill_qty,
            normalized_qty=fill_qty,  # StandX 不需要正規化
            hedge_side=hedge_side,
            started_at=datetime.now(),
        )

        # 記錄代理狀態
        proxy_info = ""
        via_proxy = False
        if hasattr(self.hedge_adapter, 'proxy_url') and self.hedge_adapter.proxy_url:
            proxy_info = f" [VIA PROXY: {self.hedge_adapter.proxy_url[:30]}...]"
            via_proxy = True

        logger.info(
            f"[StandX Hedge] Starting: {source_symbol} → {hedge_symbol}, "
            f"{hedge_side} {fill_qty} (fill_price: {fill_price}){proxy_info}"
        )

        # 寫入 mm_trades 日誌
        trade_log.info(
            f"HEDGE_START | exchange=standx_hedge | side={hedge_side} | qty={fill_qty} | "
            f"source_price={fill_price} | symbol={hedge_symbol} | via_proxy={via_proxy}"
        )

        # 重試執行
        for attempt in range(1, self.config.max_retries + 1):
            self._total_attempts += 1
            result.attempts = attempt

            try:
                # 執行對沖訂單
                order = await asyncio.wait_for(
                    self.hedge_adapter.place_order(
                        symbol=hedge_symbol,
                        side=hedge_side,
                        order_type="market",
                        quantity=fill_qty,
                    ),
                    timeout=self.config.timeout_ms / 1000
                )

                if order:
                    # 對沖成功
                    result.success = True
                    result.status = HedgeStatus.FILLED
                    result.order_id = getattr(order, "order_id", None) or getattr(order, "client_order_id", None)
                    result.fill_qty = fill_qty

                    # 嘗試獲取成交價格
                    result.fill_price = getattr(order, "price", None) or fill_price
                    result.execution_price = result.fill_price

                    # 計算滑點
                    result.slippage_bps = self._calculate_slippage(
                        fill_price,
                        result.fill_price,
                        hedge_side
                    )

                    # 統計
                    latency = (time.time() - start_time) * 1000
                    result.latency_ms = latency
                    result.completed_at = datetime.now()

                    self._total_success += 1
                    self._total_latency_ms += latency

                    logger.info(
                        f"[StandX Hedge] Success: {hedge_side} {fill_qty} @ {result.fill_price} "
                        f"(slippage: {result.slippage_bps:.1f} bps, latency: {latency:.0f}ms)"
                    )

                    # 寫入 mm_trades 日誌
                    trade_log.info(
                        f"HEDGE_SUCCESS | exchange=standx_hedge | side={hedge_side} | qty={fill_qty} | "
                        f"price={result.fill_price} | slippage_bps={result.slippage_bps:.1f} | "
                        f"latency_ms={latency:.0f} | attempts={attempt} | order_id={result.order_id}"
                    )
                    return result
                else:
                    result.error_message = "Order returned None"
                    logger.warning(f"[StandX Hedge] Attempt {attempt}: Order returned None")

            except asyncio.TimeoutError:
                result.error_message = "Timeout"
                result.status = HedgeStatus.TIMEOUT
                logger.warning(f"[StandX Hedge] Attempt {attempt}: Timeout")

            except Exception as e:
                result.error_message = str(e)
                logger.warning(f"[StandX Hedge] Attempt {attempt} failed: {e}")

            # 重試前等待
            if attempt < self.config.max_retries:
                await asyncio.sleep(self.config.retry_delay_ms / 1000)

        # 所有重試失敗，進入風控模式
        logger.error(f"[StandX Hedge] All {self.config.max_retries} attempts failed")
        result.status = HedgeStatus.FAILED
        self._total_failed += 1

        # 寫入 mm_trades 日誌
        trade_log.info(
            f"HEDGE_FAILED | exchange=standx_hedge | side={hedge_side} | qty={fill_qty} | "
            f"symbol={hedge_symbol} | attempts={self.config.max_retries} | error={result.error_message}"
        )

        # 風控處理
        return await self._handle_hedge_failure(result, fill_side, fill_qty, source_symbol)

    async def _handle_hedge_failure(
        self,
        result: HedgeResult,
        fill_side: str,
        fill_qty: Decimal,
        source_symbol: str,
    ) -> HedgeResult:
        """
        對沖失敗風控處理

        策略：
        1. 檢查倉位是否超過 hard limit
        2. 超過才在主帳戶平倉，否則等待恢復
        """
        result.status = HedgeStatus.RISK_CONTROL

        # 獲取當前主帳戶倉位
        try:
            positions = await self.fallback_adapter.get_positions(source_symbol)
            current_position = Decimal("0")
            for pos in positions:
                if pos.symbol == source_symbol:
                    current_position = pos.size if pos.side == "long" else -pos.size
        except Exception as e:
            logger.error(f"[StandX Hedge] Failed to get positions: {e}")
            result.status = HedgeStatus.FALLBACK_FAILED
            result.completed_at = datetime.now()
            return result

        hard_limit = self.config.max_unhedged_position

        if abs(current_position) > hard_limit:
            # 超過 hard limit，在主帳戶平倉
            soft_limit = hard_limit * Decimal("0.5")
            reduce_qty = abs(current_position) - soft_limit

            logger.warning(
                f"[StandX Hedge] Position {current_position} exceeds hard limit {hard_limit}, "
                f"reducing by {reduce_qty}"
            )

            fallback_result = await self.execute_fallback(
                side=fill_side,
                qty=reduce_qty,
                symbol=source_symbol,
            )

            if fallback_result["success"]:
                result.status = HedgeStatus.PARTIAL_FALLBACK
                self._total_fallback += 1
                logger.info(f"[StandX Hedge] Fallback success: order_id={fallback_result.get('order_id')}")

                # 寫入 mm_trades 日誌
                trade_log.info(
                    f"HEDGE_FALLBACK | exchange=standx_main | status=success | side={fill_side} | "
                    f"qty={reduce_qty} | symbol={source_symbol} | position_before={current_position} | "
                    f"order_id={fallback_result.get('order_id')}"
                )
            else:
                result.status = HedgeStatus.FALLBACK_FAILED
                logger.error(f"[StandX Hedge] Fallback failed: {fallback_result.get('error')}")

                # 寫入 mm_trades 日誌
                trade_log.info(
                    f"HEDGE_FALLBACK | exchange=standx_main | status=failed | side={fill_side} | "
                    f"qty={reduce_qty} | symbol={source_symbol} | error={fallback_result.get('error')}"
                )
        else:
            # 倉位在可接受範圍，等待恢復
            logger.info(
                f"[StandX Hedge] Position {current_position} within limit {hard_limit}, "
                "waiting for recovery"
            )
            result.status = HedgeStatus.WAITING_RECOVERY

            # 寫入 mm_trades 日誌
            trade_log.info(
                f"HEDGE_WAIT | exchange=standx_hedge | status=waiting_recovery | "
                f"position={current_position} | hard_limit={hard_limit} | symbol={source_symbol}"
            )

        result.completed_at = datetime.now()
        return result

    async def check_recovery(self) -> bool:
        """
        檢查對沖帳戶是否恢復

        測試：
        1. 查詢餘額
        2. 查詢市場信息
        """
        now = time.time()

        # 頻率節流
        if (self._last_recovery_check_ts is not None and
            now - self._last_recovery_check_ts < self.RECOVERY_CHECK_INTERVAL_SEC):
            return False

        self._last_recovery_check_ts = now

        try:
            # 測試 1：查詢餘額
            balance = await self.hedge_adapter.get_balance()
            if balance is None:
                self._recovery_success_count = 0
                return False

            # 測試 2：查詢市場信息（可選）
            if hasattr(self.hedge_adapter, 'get_symbol_info'):
                await self.hedge_adapter.get_symbol_info("BTC-USD")

            self._recovery_success_count += 1
            logger.info(
                f"[StandX Hedge] Recovery check passed "
                f"({self._recovery_success_count}/{self.RECOVERY_SUCCESS_REQUIRED})"
            )

            if self._recovery_success_count >= self.RECOVERY_SUCCESS_REQUIRED:
                self._recovery_success_count = 0
                logger.info("[StandX Hedge] Recovery complete, resuming normal operation")
                return True

            return False

        except Exception as e:
            logger.warning(f"[StandX Hedge] Recovery check failed: {e}")
            self._recovery_success_count = 0
            return False
