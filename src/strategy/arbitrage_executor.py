"""
自動套利執行器
Automated Arbitrage Executor

自動執行跨交易所套利交易
"""
import asyncio
from typing import Dict, Optional
from decimal import Decimal
from datetime import datetime
import logging
from dataclasses import dataclass

from src.adapters.base_adapter import BasePerpAdapter, OrderSide
from src.monitor.multi_exchange_monitor import (
    MultiExchangeMonitor,
    ArbitrageOpportunity
)


@dataclass
class ExecutionResult:
    """執行結果"""
    success: bool
    opportunity: ArbitrageOpportunity
    buy_order_id: Optional[str] = None
    sell_order_id: Optional[str] = None
    actual_profit: Optional[Decimal] = None
    error_message: Optional[str] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


class ArbitrageExecutor:
    """套利執行器"""

    def __init__(
        self,
        monitor: MultiExchangeMonitor,
        adapters: Dict[str, BasePerpAdapter],
        max_position_size: Decimal = Decimal("0.1"),  # 最大倉位
        min_profit_usd: Decimal = Decimal("5.0"),     # 最小利潤 USD
        execution_timeout: float = 5.0,                # 執行超時（秒）
        enable_auto_execute: bool = False,             # 是否自動執行
        dry_run: bool = True                           # 模擬模式
    ):
        """
        初始化套利執行器

        Args:
            monitor: 市場監控器
            adapters: 交易所適配器字典
            max_position_size: 單次最大交易量
            min_profit_usd: 最小利潤閾值（USD）
            execution_timeout: 訂單執行超時時間
            enable_auto_execute: 是否啟用自動執行
            dry_run: 模擬模式（不實際下單）
        """
        self.monitor = monitor
        self.adapters = adapters
        self.max_position_size = max_position_size
        self.min_profit_usd = min_profit_usd
        self.execution_timeout = execution_timeout
        self.enable_auto_execute = enable_auto_execute
        self.dry_run = dry_run

        # 執行歷史
        self.execution_history = []

        # 統計
        self.stats = {
            'total_attempts': 0,
            'successful_executions': 0,
            'failed_executions': 0,
            'total_profit': Decimal('0'),
            'total_loss': Decimal('0')
        }

        # 日誌
        self.logger = logging.getLogger(__name__)

        # 運行狀態
        self._running = False
        self._task = None

        print(f"\n{'='*80}")
        print(f"🤖 Arbitrage Executor Initialized")
        print(f"{'='*80}")
        print(f"  Max Position Size: {max_position_size}")
        print(f"  Min Profit (USD): ${min_profit_usd}")
        print(f"  Execution Timeout: {execution_timeout}s")
        print(f"  Auto Execute: {'✅ ENABLED' if enable_auto_execute else '❌ DISABLED'}")
        print(f"  Dry Run Mode: {'✅ ON (No Real Orders)' if dry_run else '❌ OFF (Real Trading!)'}")
        print(f"{'='*80}\n")

    async def start(self):
        """啟動執行器"""
        if self._running:
            print("⚠️  Executor is already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._execution_loop())
        print("🚀 Arbitrage Executor started")

    async def stop(self):
        """停止執行器"""
        print("\n🛑 Stopping executor...")
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        print("✅ Executor stopped")
        self._print_summary()

    async def _execution_loop(self):
        """執行循環"""
        while self._running:
            try:
                # 檢查是否有套利機會
                opportunities = self.monitor.arbitrage_opportunities

                if opportunities and self.enable_auto_execute:
                    # 選擇最佳機會
                    best_opp = max(opportunities, key=lambda o: o.profit)

                    # 檢查是否值得執行
                    if await self._should_execute(best_opp):
                        result = await self.execute_arbitrage(best_opp)

                        if result.success:
                            print(f"\n✅ Arbitrage executed successfully!")
                            print(f"   Profit: ${result.actual_profit:.2f}")
                        else:
                            print(f"\n❌ Arbitrage execution failed: {result.error_message}")

                await asyncio.sleep(0.5)  # 檢查頻率

            except Exception as e:
                self.logger.error(f"Execution loop error: {e}")
                await asyncio.sleep(1)

    async def _should_execute(self, opportunity: ArbitrageOpportunity) -> bool:
        """判斷是否應該執行套利"""
        # 1. 檢查利潤是否足夠
        potential_profit = opportunity.profit * opportunity.max_quantity
        if potential_profit < self.min_profit_usd:
            return False

        # 2. 檢查交易量是否足夠
        if opportunity.max_quantity <= 0:
            return False

        # 3. 檢查交易量是否超過限制
        execution_qty = min(opportunity.max_quantity, self.max_position_size)
        if execution_qty <= 0:
            return False

        return True

    async def execute_arbitrage(
        self,
        opportunity: ArbitrageOpportunity
    ) -> ExecutionResult:
        """
        執行套利交易

        Args:
            opportunity: 套利機會

        Returns:
            ExecutionResult: 執行結果
        """
        self.stats['total_attempts'] += 1

        print(f"\n{'='*80}")
        print(f"⚡ Executing Arbitrage")
        print(f"{'='*80}")
        print(f"  Symbol: {opportunity.symbol}")
        print(f"  Buy:  {opportunity.buy_exchange.upper()} @ ${opportunity.buy_price}")
        print(f"  Sell: {opportunity.sell_exchange.upper()} @ ${opportunity.sell_price}")
        print(f"  Expected Profit: ${opportunity.profit * opportunity.max_quantity:.2f}")
        print(f"{'='*80}\n")

        # 計算執行數量
        execution_qty = min(opportunity.max_quantity, self.max_position_size)

        # 模擬模式
        if self.dry_run:
            print("  🔵 DRY RUN MODE - No real orders placed")
            simulated_profit = opportunity.profit * execution_qty
            result = ExecutionResult(
                success=True,
                opportunity=opportunity,
                buy_order_id="DRY_RUN_BUY",
                sell_order_id="DRY_RUN_SELL",
                actual_profit=simulated_profit
            )
            self.stats['successful_executions'] += 1
            self.stats['total_profit'] += simulated_profit
            self.execution_history.append(result)
            return result

        # 實際執行
        try:
            buy_adapter = self.adapters[opportunity.buy_exchange.lower()]
            sell_adapter = self.adapters[opportunity.sell_exchange.lower()]

            # 並行下單（買入和賣出）
            buy_task = buy_adapter.place_order(
                symbol=opportunity.symbol,
                side=OrderSide.BUY,
                order_type="market",
                quantity=execution_qty
            )

            sell_task = sell_adapter.place_order(
                symbol=opportunity.symbol,
                side=OrderSide.SELL,
                order_type="market",
                quantity=execution_qty
            )

            # 等待訂單執行
            buy_order, sell_order = await asyncio.wait_for(
                asyncio.gather(buy_task, sell_task),
                timeout=self.execution_timeout
            )

            # 計算實際利潤
            actual_buy_price = Decimal(str(buy_order.get('avg_price', opportunity.buy_price)))
            actual_sell_price = Decimal(str(sell_order.get('avg_price', opportunity.sell_price)))
            actual_profit = (actual_sell_price - actual_buy_price) * execution_qty

            result = ExecutionResult(
                success=True,
                opportunity=opportunity,
                buy_order_id=buy_order['order_id'],
                sell_order_id=sell_order['order_id'],
                actual_profit=actual_profit
            )

            self.stats['successful_executions'] += 1
            if actual_profit > 0:
                self.stats['total_profit'] += actual_profit
            else:
                self.stats['total_loss'] += abs(actual_profit)

            self.execution_history.append(result)
            return result

        except asyncio.TimeoutError:
            error_msg = "Order execution timeout"
            self.logger.error(error_msg)
            self.stats['failed_executions'] += 1
            return ExecutionResult(
                success=False,
                opportunity=opportunity,
                error_message=error_msg
            )

        except Exception as e:
            error_msg = f"Execution error: {str(e)}"
            self.logger.error(error_msg)
            self.stats['failed_executions'] += 1
            return ExecutionResult(
                success=False,
                opportunity=opportunity,
                error_message=error_msg
            )

    def _print_summary(self):
        """打印執行摘要"""
        print(f"\n{'='*80}")
        print(f"📊 ARBITRAGE EXECUTOR SUMMARY")
        print(f"{'='*80}")
        print(f"  Total Attempts: {self.stats['total_attempts']}")
        print(f"  Successful: {self.stats['successful_executions']}")
        print(f"  Failed: {self.stats['failed_executions']}")
        print(f"  Total Profit: ${self.stats['total_profit']:.2f}")
        print(f"  Total Loss: ${self.stats['total_loss']:.2f}")
        print(f"  Net P&L: ${self.stats['total_profit'] - self.stats['total_loss']:.2f}")

        if self.stats['successful_executions'] > 0:
            avg_profit = self.stats['total_profit'] / self.stats['successful_executions']
            print(f"  Avg Profit/Trade: ${avg_profit:.2f}")

        print(f"{'='*80}\n")

    def get_execution_history(self):
        """獲取執行歷史"""
        return self.execution_history

    def get_stats(self):
        """獲取統計數據"""
        return self.stats
