"""
訂單驗證與正規化模組

提供統一的訂單參數驗證和正規化邏輯，可被所有交易所適配器共用。
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
from typing import Optional, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from src.adapters.base_adapter import SymbolInfo

logger = logging.getLogger(__name__)


@dataclass
class OrderValidationResult:
    """訂單驗證結果"""
    ok: bool
    normalized_qty: Optional[Decimal] = None
    normalized_price: Optional[Decimal] = None
    reason: Optional[str] = None
    spec: Optional["SymbolInfo"] = None
    estimated_notional: Optional[Decimal] = None


def validate_and_normalize_order(
    symbol: str,
    side: str,
    quantity: Decimal,
    price: Optional[Decimal],
    spec: Optional["SymbolInfo"],
    best_bid: Optional[Decimal] = None,
    best_ask: Optional[Decimal] = None,
) -> OrderValidationResult:
    """
    驗證並正規化訂單參數

    Args:
        symbol: 交易對
        side: buy/sell/long/short
        quantity: 原始數量
        price: 原始價格（市價單可為 None）
        spec: 交易對規格
        best_bid: 當前最佳買價（用於市價單估算 notional）
        best_ask: 當前最佳賣價（用於市價單估算 notional）

    Returns:
        OrderValidationResult: 驗證結果
    """
    if spec is None:
        # 沒有規格，直接通過（但記錄警告）
        logger.warning(f"No spec for {symbol}, skipping validation")
        return OrderValidationResult(
            ok=True,
            normalized_qty=quantity,
            normalized_price=price,
            reason="no_spec",
        )

    result = OrderValidationResult(ok=False, spec=spec)

    # 1. 正規化數量
    normalized_qty = _normalize_quantity(quantity, spec)
    if normalized_qty is None:
        result.reason = f"qty_below_min: {quantity} < {spec.min_qty}"
        return result
    result.normalized_qty = normalized_qty

    # 2. 正規化價格
    if price is not None:
        result.normalized_price = _normalize_price(price, spec, side)
    else:
        result.normalized_price = None

    # 3. 估算 notional
    price_for_notional = result.normalized_price
    if price_for_notional is None:
        # 市價單用 orderbook 估算
        if side.lower() in ["buy", "long"] and best_ask:
            price_for_notional = best_ask
        elif best_bid:
            price_for_notional = best_bid

    if price_for_notional:
        result.estimated_notional = normalized_qty * price_for_notional

        # 4. 檢查 min_notional
        if spec.min_notional and result.estimated_notional < spec.min_notional:
            result.reason = f"notional_below_min: {result.estimated_notional:.2f} < {spec.min_notional}"
            return result

    result.ok = True
    return result


def _normalize_quantity(qty: Decimal, spec: "SymbolInfo") -> Optional[Decimal]:
    """
    正規化數量（向下取整到 qty_step）

    Args:
        qty: 原始數量
        spec: 交易對規格

    Returns:
        Optional[Decimal]: 正規化後的數量，如果低於最小值則返回 None
    """
    try:
        steps = (qty / spec.qty_step).to_integral_value(rounding=ROUND_FLOOR)
        normalized = steps * spec.qty_step

        if normalized < spec.min_qty:
            logger.debug(f"Quantity {qty} -> {normalized} below min {spec.min_qty}")
            return None

        return normalized
    except Exception as e:
        logger.error(f"Error normalizing quantity: {e}")
        return None


def _normalize_price(price: Decimal, spec: "SymbolInfo", side: str) -> Decimal:
    """
    正規化價格（依 side 調整取整方向）

    策略：保守做市（更難被成交）
    - 買單：向下取整（出價更低，更難買到）
    - 賣單：向上取整（要價更高，更難賣出）

    Args:
        price: 原始價格
        spec: 交易對規格
        side: 訂單方向

    Returns:
        Decimal: 正規化後的價格
    """
    try:
        if side.lower() in ["buy", "long"]:
            # 買單向下取整（更保守）
            rounding = ROUND_FLOOR
        else:
            # 賣單向上取整（更保守）
            rounding = ROUND_CEILING

        steps = (price / spec.price_tick).to_integral_value(rounding=rounding)
        return steps * spec.price_tick
    except Exception as e:
        logger.error(f"Error normalizing price: {e}")
        return price
