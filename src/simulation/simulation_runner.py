"""
Simulation Runner

Orchestrates multiple parameter set simulations in parallel.
All simulations receive the same market data for fair comparison.
"""

import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime
from uuid import uuid4
import logging

from .param_set_manager import ParamSet, ParamSetManager
from .simulation_executor import SimulationExecutor
from .simulation_state import SimulationState
from .shared_market_feed import SharedMarketFeed, MarketTick
from .result_logger import ResultLogger

logger = logging.getLogger(__name__)


class SimulationRunner:
    """
    Orchestrates multiple parameter set simulations in parallel.

    Features:
    - Shared market feed ensures all simulators see identical data
    - Each simulator has isolated state
    - Results logged to JSON for comparison
    """

    def __init__(
        self,
        adapter: Any,  # BasePerpAdapter
        param_set_manager: ParamSetManager,
        result_logger: ResultLogger,
        symbol: str = "BTC-USD",
        tick_interval_ms: int = 100
    ):
        self.adapter = adapter
        self.param_set_manager = param_set_manager
        self.result_logger = result_logger
        self.symbol = symbol
        self.tick_interval_ms = tick_interval_ms

        # Market feed
        self._market_feed: Optional[SharedMarketFeed] = None

        # Simulators
        self._executors: Dict[str, SimulationExecutor] = {}

        # Run state
        self._running = False
        self._current_run_id: Optional[str] = None
        self._started_at: Optional[datetime] = None
        self._duration_minutes: int = 60

        # Auto-stop task
        self._auto_stop_task: Optional[asyncio.Task] = None

    async def start(
        self,
        param_set_ids: List[str],
        duration_minutes: int = 60,
        run_id: str = None
    ) -> str:
        """
        Start simulations for the specified parameter sets.

        Args:
            param_set_ids: List of parameter set IDs to simulate
            duration_minutes: How long to run (0 = indefinite)
            run_id: Optional custom run ID

        Returns:
            Run ID
        """
        if self._running:
            raise RuntimeError("Simulation already running. Stop it first.")

        # Generate run ID
        self._current_run_id = run_id or f"run_{uuid4().hex[:8]}"
        self._started_at = datetime.now()
        self._duration_minutes = duration_minutes

        logger.info(f"Starting simulation run: {self._current_run_id}")
        logger.info(f"Parameter sets: {param_set_ids}")
        logger.info(f"Duration: {duration_minutes} minutes")

        # Create market feed
        self._market_feed = SharedMarketFeed(
            adapter=self.adapter,
            symbol=self.symbol,
            tick_interval_ms=self.tick_interval_ms
        )

        # Create simulators for each param set
        self._executors = {}
        for ps_id in param_set_ids:
            param_set = self.param_set_manager.get_param_set(ps_id)
            if param_set is None:
                logger.warning(f"Parameter set not found: {ps_id}")
                continue

            executor = SimulationExecutor(param_set)
            self._executors[ps_id] = executor

            # Subscribe to market feed
            self._market_feed.subscribe(executor.on_market_tick)

        if not self._executors:
            raise ValueError("No valid parameter sets to simulate")

        # Log run metadata
        self.result_logger.create_run_directory(self._current_run_id)
        self.result_logger.log_run_metadata(self._current_run_id, {
            'run_id': self._current_run_id,
            'started_at': self._started_at.isoformat(),
            'duration_minutes': duration_minutes,
            'param_set_ids': list(self._executors.keys()),
            'symbol': self.symbol,
            'tick_interval_ms': self.tick_interval_ms,
            'base_config': self.param_set_manager.get_base_config()
        })

        # Start all simulators
        for executor in self._executors.values():
            await executor.start()

        # Start market feed
        await self._market_feed.start()

        self._running = True

        # Schedule auto-stop if duration > 0
        if duration_minutes > 0:
            self._auto_stop_task = asyncio.create_task(
                self._auto_stop_after(duration_minutes * 60)
            )

        logger.info(f"Simulation running with {len(self._executors)} parameter sets")
        return self._current_run_id

    async def _auto_stop_after(self, seconds: float):
        """Automatically stop after specified duration."""
        await asyncio.sleep(seconds)
        logger.info(f"Auto-stopping simulation after {seconds/60} minutes")
        await self.stop()

    async def stop(self) -> Dict:
        """
        Stop all simulations and save results.

        Returns:
            Comparison summary
        """
        if not self._running:
            return {}

        self._running = False

        # Cancel auto-stop task
        if self._auto_stop_task:
            self._auto_stop_task.cancel()
            try:
                await self._auto_stop_task
            except asyncio.CancelledError:
                pass

        logger.info("Stopping simulation run...")

        # Stop market feed first
        if self._market_feed:
            await self._market_feed.stop()

        # Stop all executors
        for executor in self._executors.values():
            await executor.stop()

        # Save results
        results = await self._save_results()

        # Clear state
        ended_at = datetime.now()
        run_id = self._current_run_id

        self._executors = {}
        self._market_feed = None
        self._current_run_id = None
        self._started_at = None

        logger.info(f"Simulation run {run_id} completed")
        return results

    async def _save_results(self) -> Dict:
        """Save simulation results to JSON files."""
        if not self._current_run_id:
            return {}

        ended_at = datetime.now()
        results = []

        # Save each param set result
        for ps_id, executor in self._executors.items():
            status = executor.get_status()
            result = {
                'param_set_id': ps_id,
                'param_set_name': executor.param_set.name,
                'description': executor.param_set.description,
                'config': executor.param_set.config,
                'metrics': status['state']['metrics'],
                'final_state': status['state']
            }
            results.append(result)

            # Log individual result
            self.result_logger.log_param_set_result(
                self._current_run_id,
                ps_id,
                result
            )

        # Create comparison summary
        comparison = self._create_comparison_summary(results)

        # Log comparison
        self.result_logger.log_comparison_summary(
            self._current_run_id,
            {
                'run_id': self._current_run_id,
                'started_at': self._started_at.isoformat() if self._started_at else None,
                'ended_at': ended_at.isoformat(),
                'duration_seconds': (ended_at - self._started_at).total_seconds() if self._started_at else 0,
                'comparison': comparison
            }
        )

        return comparison

    def _create_comparison_summary(self, results: List[Dict]) -> Dict:
        """
        Create comparison summary with rankings.

        Uses StandX tier metrics:
        - effective_points_pct: Weighted score (100%*boosted + 50%*standard + 10%*basic)
        - boosted_time_pct: Time at 0-10 bps (100% points)
        - standard_time_pct: Time at 10-30 bps (50% points)
        - basic_time_pct: Time at 30-100 bps (10% points)
        """
        if not results:
            return {}

        # Extract metrics for ranking
        metrics_list = []
        for r in results:
            m = r['metrics']
            metrics_list.append({
                'param_set_id': r['param_set_id'],
                'param_set_name': r['param_set_name'],
                # Tier metrics
                'effective_points_pct': m.get('effective_points_pct', 0),
                'boosted_time_pct': m.get('boosted_time_pct', 0),
                'standard_time_pct': m.get('standard_time_pct', 0),
                'basic_time_pct': m.get('basic_time_pct', 0),
                'uptime_percentage': m.get('uptime_percentage', 0),
                # Trading metrics
                'simulated_fills': m.get('simulated_fills', 0),
                'simulated_pnl_usd': m.get('simulated_pnl_usd', 0),
                'avg_spread_captured_bps': m.get('avg_spread_captured_bps', 0),
                'orders_cancelled': m.get('orders_cancelled', 0),
                'cancel_by_distance': m.get('cancel_by_distance', 0),
                'cancel_by_queue': m.get('cancel_by_queue', 0),
                'rebalance_count': m.get('rebalance_count', 0),
            })

        # Create rankings
        rankings = {
            'by_effective_points': sorted(metrics_list, key=lambda x: x['effective_points_pct'], reverse=True),
            'by_boosted_time': sorted(metrics_list, key=lambda x: x['boosted_time_pct'], reverse=True),
            'by_pnl': sorted(metrics_list, key=lambda x: x['simulated_pnl_usd'], reverse=True),
            'by_fills': sorted(metrics_list, key=lambda x: x['simulated_fills'], reverse=True),
        }

        # Determine recommendation based on effective_points_pct
        best = rankings['by_effective_points'][0] if rankings['by_effective_points'] else None

        return {
            'comparison_table': metrics_list,
            'rankings': {
                'by_effective_points': [m['param_set_id'] for m in rankings['by_effective_points']],
                'by_boosted_time': [m['param_set_id'] for m in rankings['by_boosted_time']],
                'by_pnl': [m['param_set_id'] for m in rankings['by_pnl']],
                'by_fills': [m['param_set_id'] for m in rankings['by_fills']],
            },
            'recommendation': {
                'param_set_id': best['param_set_id'] if best else None,
                'param_set_name': best['param_set_name'] if best else None,
                'reason': f"最高有效積分 {best['effective_points_pct']:.1f}% (100%檔: {best['boosted_time_pct']:.1f}%)" if best else '',
                'metrics': best
            }
        }

    def is_running(self) -> bool:
        """Check if simulation is running."""
        return self._running

    def get_current_run_id(self) -> Optional[str]:
        """Get current run ID."""
        return self._current_run_id

    def get_live_status(self) -> Dict:
        """Get live status for all running simulations."""
        if not self._running:
            return {'running': False}

        elapsed = 0
        remaining = 0
        if self._started_at:
            elapsed = (datetime.now() - self._started_at).total_seconds()
            if self._duration_minutes > 0:
                remaining = max(0, self._duration_minutes * 60 - elapsed)

        executor_statuses = {}
        for ps_id, executor in self._executors.items():
            executor_statuses[ps_id] = executor.get_status()

        market_stats = {}
        if self._market_feed:
            market_stats = self._market_feed.get_stats()

        progress_pct = 0
        if self._duration_minutes > 0:
            progress_pct = min(100, (elapsed / (self._duration_minutes * 60)) * 100)

        return {
            'running': True,
            'run_id': self._current_run_id,
            'started_at': self._started_at.isoformat() if self._started_at else None,
            'elapsed_seconds': elapsed,
            'remaining_seconds': remaining,
            'duration_minutes': self._duration_minutes,
            'progress_pct': progress_pct,
            'param_set_count': len(self._executors),
            'executors': executor_statuses,
            'market_feed': market_stats
        }

    def get_live_comparison(self) -> List[Dict]:
        """Get live comparison table for all running simulations."""
        if not self._running:
            return []

        comparison = []
        for ps_id, executor in self._executors.items():
            status = executor.get_status()
            metrics = status['state']['metrics']
            comparison.append({
                'param_set_id': ps_id,
                'param_set_name': executor.param_set.name,
                # Tier percentages (StandX scoring)
                'boosted_time_pct': metrics.get('boosted_time_pct', 0),    # 0-10 bps: 100%
                'standard_time_pct': metrics.get('standard_time_pct', 0),  # 10-30 bps: 50%
                'basic_time_pct': metrics.get('basic_time_pct', 0),        # 30-100 bps: 10%
                'effective_points_pct': metrics.get('effective_points_pct', 0),  # Weighted score
                'uptime_percentage': metrics.get('uptime_percentage', 0),  # Any points earned
                # Trading metrics
                'simulated_fills': metrics.get('simulated_fills', 0),
                'simulated_pnl_usd': metrics.get('simulated_pnl_usd', 0),
                'rolling_uptime': status['state'].get('rolling_uptime', 0),
                'has_orders': status['state'].get('has_bid', False) or status['state'].get('has_ask', False),
                # Cancel and rebalance counts
                'price_cancel_count': metrics.get('cancel_by_distance', 0),
                'queue_cancel_count': metrics.get('cancel_by_queue', 0),
                'rebalance_count': metrics.get('rebalance_count', 0),
            })

        # Sort by effective points percentage (weighted score)
        comparison.sort(key=lambda x: x['effective_points_pct'], reverse=True)
        return comparison
