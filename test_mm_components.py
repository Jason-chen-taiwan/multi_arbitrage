#!/usr/bin/env python3
"""測試做市商組件"""
import sys
sys.path.insert(0, '.')

from decimal import Decimal

# 導入組件
from src.strategy.mm_state import MMState, OrderInfo, FillEvent
from src.strategy.hedge_engine import HedgeConfig, HedgeStatus
from src.strategy.market_maker_executor import MMConfig, ExecutorStatus

print('=' * 60)
print('測試 MM 組件')
print('=' * 60)

# 1. 測試 MMState
print('\n1. MMState 測試')
state = MMState(volatility_window_sec=5)
print(f'   初始狀態: {state.to_dict()}')

# 更新價格
state.update_price(Decimal('94000'))
state.update_price(Decimal('94010'))
state.update_price(Decimal('93990'))
print(f'   波動率: {state.get_volatility_bps():.2f} bps')

# 設置訂單
order = OrderInfo(
    client_order_id='test_bid_001',
    side='buy',
    price=Decimal('93900'),
    qty=Decimal('0.001'),
    status='open'
)
state.set_bid_order(order)
print(f'   有買單: {state.has_bid_order()}')

# 2. 測試 HedgeConfig
print('\n2. HedgeConfig 默認值')
config = HedgeConfig()
print(f'   symbol: {config.symbol}')
print(f'   timeout_ms: {config.timeout_ms}')
print(f'   max_retries: {config.max_retries}')

# 3. 測試 MMConfig
print('\n3. MMConfig 默認值')
mm_config = MMConfig()
print(f'   standx_symbol: {mm_config.standx_symbol}')
print(f'   binance_symbol: {mm_config.binance_symbol}')
print(f'   order_distance_bps: {mm_config.order_distance_bps}')
print(f'   order_size_btc: {mm_config.order_size_btc}')
print(f'   volatility_threshold_bps: {mm_config.volatility_threshold_bps}')
print(f'   dry_run: {mm_config.dry_run}')

# 4. 測試 ExecutorStatus
print('\n4. ExecutorStatus 枚舉')
for status in ExecutorStatus:
    print(f'   {status.name}: {status.value}')

# 5. 測試 HedgeStatus
print('\n5. HedgeStatus 枚舉')
for status in HedgeStatus:
    print(f'   {status.name}: {status.value}')

# 6. 測試訂單距離檢查
print('\n6. 訂單距離檢查')
current_price = Decimal('94000')
# 撤單距離 3 bps = 94000 * 0.0003 = 28.2
orders_to_cancel = state.get_orders_to_cancel(current_price, cancel_distance_bps=3)
print(f'   當前價格: ${current_price}')
print(f'   買單價格: ${order.price}')
print(f'   需要撤銷: {orders_to_cancel}')

# 7. 測試重掛檢查
print('\n7. 重掛檢查')
should_rebalance = state.should_rebalance_orders(current_price, rebalance_distance_bps=15)
print(f'   需要重掛: {should_rebalance}')

# 8. 測試倉位管理
print('\n8. 倉位管理')
state.update_standx_position(Decimal('0.001'))
state.update_binance_position(Decimal('-0.001'))
print(f'   StandX 倉位: {state.get_standx_position()}')
print(f'   Binance 倉位: {state.get_binance_position()}')
print(f'   淨敞口: {state.get_net_position()}')
print(f'   倉位平衡: {state.is_position_balanced()}')

print('\n' + '=' * 60)
print('所有組件測試通過!')
print('=' * 60)
