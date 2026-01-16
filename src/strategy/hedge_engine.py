"""
GRVT 對沖引擎
Hedge Engine for GRVT (DEX)

成交後在 GRVT 執行對沖訂單
- 自動匹配交易對（StandX BTC-USD → GRVT BTC_USDT_Perp）
- 兩段式對沖（送單 + 等待成交）
- 風控模式（失敗時不立即平倉，而是暫停等待恢復）
- 合約規格對齊（qty_step, min_qty）
"""
import asyncio
import logging
import time
from typing import Optional, Dict, Any, Set
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
    FALLBACK = "fallback"

    # 風控狀態
    RISK_CONTROL = "risk_control"           # 進入風控模式
    WAITING_RECOVERY = "waiting_recovery"   # 等待恢復
    PARTIAL_FALLBACK = "partial_fallback"   # 部分平倉
    FALLBACK_FAILED = "fallback_failed"     # 平倉也失敗


@dataclass
class HedgeConfig:
    """對沖配置"""
    # 交易對
    symbol: str = "BTC_USDT_Perp"           # 對沖交易對（GRVT 格式）
    standx_symbol: str = "BTC-USD"          # StandX 交易對

    # 自動匹配
    auto_match_symbol: bool = True          # 是否自動匹配

    # 交易對映射（優先使用）
    symbol_map: Dict[str, str] = field(default_factory=lambda: {
        "BTC-USD": "BTC_USDT_Perp",
        "ETH-USD": "ETH_USDT_Perp",
        "SOL-USD": "SOL_USDT_Perp",
    })

    # 超時和重試
    timeout_ms: int = 1000                  # 總超時時間 (1秒)
    max_retries: int = 3                    # 最大重試次數
    retry_delay_ms: int = 100               # 重試間隔

    # 訂單類型
    use_market_order: bool = True           # 使用市價單
    max_slippage_bps: int = 20              # 最大允許滑點

    # 風控參數
    max_unhedged_position: Decimal = Decimal("0.01")  # 最大未對沖倉位 (BTC)


@dataclass
class HedgeResult:
    """對沖結果（增強版）"""
    success: bool
    status: HedgeStatus
    source_fill_id: str                     # 觸發對沖的成交 ID

    # 交易對信息（調試用）
    standx_symbol: str = ""                 # 原始 StandX 交易對
    hedge_symbol: str = ""                  # 匹配的對沖交易對

    # 數量信息（調試用）
    requested_qty: Decimal = Decimal("0")   # 請求的對沖量
    normalized_qty: Decimal = Decimal("0")  # 正規化後的對沖量

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
    對沖引擎 (GRVT)

    職責:
    1. 在 GRVT 執行對沖訂單 (市價單)
    2. 自動匹配交易對（symbol_map 或自動拼接）
    3. 合約規格對齊（qty_step, min_qty）
    4. 兩段式對沖（送單 + 等待成交）
    5. 風控模式（失敗時暫停，超過 hard limit 才部分平倉）
    6. 恢復檢測（連續 N 次成功才恢復）
    """

    # 快取 TTL
    VALID_SYMBOLS_TTL_SEC = 300             # 5 分鐘

    # 恢復條件
    RECOVERY_SUCCESS_REQUIRED = 3           # 連續成功次數
    RECOVERY_CHECK_INTERVAL_SEC = 2.0       # 恢復檢查間隔

    def __init__(
        self,
        hedge_adapter,                      # GRVT 適配器
        standx_adapter,                     # StandX 適配器 (用於 fallback)
        config: Optional[HedgeConfig] = None,
    ):
        self.hedge_adapter = hedge_adapter
        self.standx = standx_adapter
        self.config = config or HedgeConfig()

        # 交易對驗證快取
        self._valid_symbols: Optional[Set[str]] = None
        self._valid_symbols_ts: Optional[float] = None

        # 恢復狀態
        self._recovery_success_count = 0
        self._last_recovery_check_ts: Optional[float] = None

        # 統計
        self._total_attempts = 0
        self._total_success = 0
        self._total_failed = 0
        self._total_fallback = 0
        self._total_latency_ms = 0.0

    # ==================== 交易對匹配 ====================

    def _match_hedge_symbol(self, standx_symbol: str) -> Optional[str]:
        """
        匹配對沖交易對

        優先順序:
        1. symbol_map 中的映射
        2. 自動拼接（如果啟用）
        """
        # 1. 優先使用配置的 symbol_map
        if standx_symbol in self.config.symbol_map:
            return self.config.symbol_map[standx_symbol]

        # 2. 自動拼接
        if self.config.auto_match_symbol:
            base = standx_symbol.split('-')[0].upper()
            return f"{base}_USDT_Perp"

        return None

    async def _validate_hedge_symbol(self, hedge_symbol: str) -> bool:
        """驗證對沖交易對（帶 TTL 快取）"""
        now = time.time()

        # 檢查快取是否過期
        if (self._valid_symbols is not None and
            self._valid_symbols_ts is not None and
            now - self._valid_symbols_ts < self.VALID_SYMBOLS_TTL_SEC):
            return hedge_symbol in self._valid_symbols

        # 重新獲取（失敗時不覆蓋舊快取）
        try:
            markets = await self.hedge_adapter.get_markets()
            self._valid_symbols = {
                m.get("symbol") if isinstance(m, dict) else getattr(m, "symbol", None)
                for m in markets
            }
            self._valid_symbols.discard(None)
            self._valid_symbols_ts = now
        except Exception as e:
            logger.warning(f"Failed to fetch markets, using cached: {e}")
            # 失敗時仍使用舊快取（如果有）
            if self._valid_symbols is None:
                return False

        return hedge_symbol in self._valid_symbols

    def invalidate_caches(self):
        """手動清除快取（熱更新用）"""
        self._valid_symbols = None
        self._valid_symbols_ts = None
        logger.info("HedgeEngine caches invalidated")

    # ==================== 主對沖流程 ====================

    async def execute_hedge(
        self,
        fill_id: str,
        fill_side: str,                     # "buy" or "sell" (StandX 成交方向)
        fill_qty: Decimal,
        fill_price: Decimal,
        standx_symbol: str = "BTC-USD",
    ) -> HedgeResult:
        """
        執行對沖

        StandX 買入成交 → GRVT 賣出
        StandX 賣出成交 → GRVT 買入
        """
        start_time = time.time()

        # 對沖方向 (反向)
        hedge_side = "sell" if fill_side == "buy" else "buy"

        # 匹配對沖交易對
        hedge_symbol = self._match_hedge_symbol(standx_symbol)

        result = HedgeResult(
            success=False,
            status=HedgeStatus.PENDING,
            source_fill_id=fill_id,
            started_at=datetime.now(),
            standx_symbol=standx_symbol,
            hedge_symbol=hedge_symbol or "",
            requested_qty=fill_qty,
        )

        # 驗證交易對匹配
        if not hedge_symbol:
            result.status = HedgeStatus.FAILED
            result.error_message = f"No hedge symbol mapping for {standx_symbol}"
            logger.error(result.error_message)
            return result

        # 驗證交易對存在
        if not await self._validate_hedge_symbol(hedge_symbol):
            result.status = HedgeStatus.FAILED
            result.error_message = f"Hedge symbol {hedge_symbol} not found on GRVT"
            logger.error(result.error_message)
            return result

        # 獲取合約規格並正規化數量
        spec = await self.hedge_adapter.get_contract_spec(hedge_symbol)
        if spec:
            normalized_qty = self.hedge_adapter.normalize_quantity(fill_qty, spec)
            if normalized_qty is None:
                result.status = HedgeStatus.FAILED
                result.error_message = f"Quantity {fill_qty} below minimum for {hedge_symbol}"
                logger.error(result.error_message)
                return result
            result.normalized_qty = normalized_qty
        else:
            normalized_qty = fill_qty
            result.normalized_qty = fill_qty

        logger.info(f"Starting hedge: {standx_symbol} → {hedge_symbol}, {hedge_side} {normalized_qty}")

        # 重試執行
        for attempt in range(1, self.config.max_retries + 1):
            self._total_attempts += 1
            result.attempts = attempt

            try:
                # 兩段式對沖
                hedge_result = await self._execute_two_phase_hedge(
                    side=hedge_side,
                    qty=normalized_qty,
                    reference_price=fill_price,
                    timeout_ms=self.config.timeout_ms,
                    hedge_symbol=hedge_symbol,
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
                        f"Hedge success: {hedge_side} {normalized_qty} @ {result.fill_price} "
                        f"(slippage: {result.slippage_bps:.1f} bps, latency: {latency:.0f}ms)"
                    )
                    return result

                else:
                    result.error_message = hedge_result.get("error", "Unknown error")
                    logger.warning(f"Hedge attempt {attempt} failed: {result.error_message}")

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

        # 所有重試失敗，進入風控模式
        logger.error(f"All {self.config.max_retries} hedge attempts failed")
        result.status = HedgeStatus.FAILED
        self._total_failed += 1

        # 風控處理
        return await self._handle_hedge_failure(result, fill_side, fill_qty, standx_symbol)

    # ==================== 兩段式對沖 ====================

    async def _execute_two_phase_hedge(
        self,
        side: str,
        qty: Decimal,
        reference_price: Decimal,
        timeout_ms: int,
        hedge_symbol: str,
    ) -> dict:
        """
        兩段式對沖（送單 + 等待成交）

        Phase 1: 送單（30% 時間）
        Phase 2: 等待成交（70% 時間）
        """
        # 送單最多用 30% 時間（但至少 500ms）
        place_timeout = max(timeout_ms * 0.3, 500) / 1000
        wait_timeout = (timeout_ms / 1000) - place_timeout

        # 第一段：送單
        try:
            order = await asyncio.wait_for(
                self.hedge_adapter.place_order(
                    symbol=hedge_symbol,
                    side=side,
                    order_type="market",
                    quantity=qty,
                ),
                timeout=place_timeout
            )

            if not order or not order.order_id:
                return {"success": False, "error": "Order placement failed"}

            logger.info(f"Hedge order placed: {order.order_id}")

        except asyncio.TimeoutError:
            return {"success": False, "error": "Order placement timeout"}
        except Exception as e:
            return {"success": False, "error": str(e)}

        # 第二段：等待成交
        wait_start = time.time()

        while time.time() - wait_start < wait_timeout:
            try:
                order_status = await self.hedge_adapter.get_order(order.order_id, hedge_symbol)

                if order_status is None:
                    # 訂單查不到，額外驗證 open_orders
                    open_orders = await self.hedge_adapter.get_open_orders(hedge_symbol)
                    order_ids = {o.order_id for o in open_orders}

                    if order.order_id not in order_ids:
                        # 確實不在 open_orders 中，可能已成交
                        logger.info(f"Order {order.order_id} not in open orders, likely filled")
                        break
                    else:
                        # 還在 open_orders，可能是 get_order 暫時失敗
                        logger.warning(f"get_order returned None but order in open_orders")
                        await asyncio.sleep(0.1)
                        continue

                status_str = str(order_status.status).upper()

                if status_str in ["FILLED", "COMPLETE", "CLOSED"]:
                    return {
                        "success": True,
                        "order_id": order.order_id,
                        "fill_price": order_status.price or reference_price,
                        "fill_qty": order_status.filled_quantity or qty,
                    }

                if "PARTIAL" in status_str:
                    logger.info(f"Hedge order partially filled: {order_status.filled_quantity}/{qty}")
                    # 繼續等待

                if status_str in ["CANCELLED", "CANCELED", "REJECTED", "EXPIRED"]:
                    return {"success": False, "error": f"Order {status_str}"}

            except Exception as e:
                logger.warning(f"Error checking order status: {e}")

            await asyncio.sleep(0.1)  # 100ms 輪詢

        # 超時，檢查最終狀態
        try:
            final_status = await self.hedge_adapter.get_order(order.order_id, hedge_symbol)
            if final_status and final_status.filled_quantity and final_status.filled_quantity > Decimal("0"):
                return {
                    "success": True,
                    "order_id": order.order_id,
                    "fill_price": final_status.price or reference_price,
                    "fill_qty": final_status.filled_quantity,
                    "partial": final_status.filled_quantity < qty,
                }
        except Exception:
            pass

        return {"success": False, "error": "Order status unknown after timeout"}

    # ==================== 風控處理 ====================

    async def _handle_hedge_failure(
        self,
        result: HedgeResult,
        fill_side: str,
        fill_qty: Decimal,
        standx_symbol: str,
    ) -> HedgeResult:
        """
        對沖失敗風控處理

        策略：
        1. 檢查倉位是否超過 hard limit
        2. 超過才部分平倉，否則等待恢復
        """
        result.status = HedgeStatus.RISK_CONTROL

        # 獲取當前 StandX 倉位
        try:
            positions = await self.standx.get_positions(standx_symbol)
            current_position = Decimal("0")
            for pos in positions:
                if pos.symbol == standx_symbol:
                    current_position = pos.size if pos.side == "long" else -pos.size
        except Exception as e:
            logger.error(f"Failed to get StandX positions: {e}")
            result.status = HedgeStatus.FALLBACK_FAILED
            return result

        hard_limit = self.config.max_unhedged_position

        if abs(current_position) > hard_limit:
            # 超過 hard limit，部分平倉到 soft limit
            soft_limit = hard_limit * Decimal("0.5")
            reduce_qty = abs(current_position) - soft_limit

            logger.warning(f"Position {current_position} exceeds hard limit, reducing by {reduce_qty}")

            fallback_result = await self._execute_fallback(
                side=fill_side,
                qty=reduce_qty,
                symbol=standx_symbol,
            )

            if fallback_result["success"]:
                result.status = HedgeStatus.PARTIAL_FALLBACK
                self._total_fallback += 1
            else:
                result.status = HedgeStatus.FALLBACK_FAILED
        else:
            # 倉位在可接受範圍，等待 GRVT 恢復
            logger.info(f"Position {current_position} within limit, waiting for GRVT recovery")
            result.status = HedgeStatus.WAITING_RECOVERY

        result.completed_at = datetime.now()
        return result

    async def _execute_fallback(
        self,
        side: str,
        qty: Decimal,
        symbol: str,
    ) -> dict:
        """在 StandX 部分平倉"""
        try:
            close_side = "sell" if side == "buy" else "buy"

            logger.info(f"Executing fallback: {close_side} {qty} on StandX")

            order = await self.standx.place_order(
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
                return {"success": False, "error": "StandX order returned None"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    # ==================== 恢復檢測 ====================

    async def check_recovery(self) -> bool:
        """
        檢查是否可以從 WAITING_RECOVERY 恢復

        條件：連續 N 次成功（帶頻率節流）
        """
        now = time.time()

        # 頻率節流：每 2 秒最多檢查一次
        if (self._last_recovery_check_ts is not None and
            now - self._last_recovery_check_ts < self.RECOVERY_CHECK_INTERVAL_SEC):
            return False

        self._last_recovery_check_ts = now

        try:
            # 測試 1：獲取市場列表
            markets = await self.hedge_adapter.get_markets()
            if not markets:
                self._recovery_success_count = 0
                return False

            # 測試 2：只查單一 hedge_symbol 的倉位（不是全量）
            hedge_symbol = self._match_hedge_symbol(self.config.standx_symbol)
            if hedge_symbol:
                await self.hedge_adapter.get_positions(hedge_symbol)

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

    # ==================== 輔助方法 ====================

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
