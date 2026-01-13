"""
Comparison Engine

Loads and compares simulation results across runs.
Provides rankings, recommendations, and analytics.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path
import logging

from .result_logger import ResultLogger

logger = logging.getLogger(__name__)


@dataclass
class ParamSetRanking:
    """Ranking entry for a parameter set."""
    param_set_id: str
    param_set_name: str
    rank: int
    value: float
    metric_name: str


@dataclass
class Recommendation:
    """Recommendation for best parameter set."""
    param_set_id: str
    param_set_name: str
    reason: str
    score: float
    metrics: Dict


class ComparisonEngine:
    """
    Loads and compares simulation results.
    Provides rankings and recommendations.

    StandX Maker Points tiers:
    - 0-10 bps: 100% points (Boosted)
    - 10-30 bps: 50% points (Standard)
    - 30-100 bps: 10% points (Basic)
    """

    # Weight configuration for recommendation scoring
    # effective_points_pct is the weighted score based on StandX tiers
    DEFAULT_WEIGHTS = {
        'effective_points_pct': 0.50,  # Main metric - weighted tier score
        'boosted_time_pct': 0.20,      # Bonus for 100% tier time
        'simulated_pnl_usd': 0.15,
        'simulated_fills': 0.15,
    }

    def __init__(self, result_logger: ResultLogger = None):
        if result_logger is None:
            result_logger = ResultLogger()
        self.result_logger = result_logger

    def get_all_runs(self) -> List[Dict]:
        """Get list of all historical runs."""
        return self.result_logger.get_all_runs()

    def get_run_details(self, run_id: str) -> Optional[Dict]:
        """Get detailed results for a specific run."""
        return self.result_logger.get_run_results(run_id)

    def get_comparison_table(
        self,
        run_id: str,
        sort_by: str = "uptime_percentage",
        ascending: bool = False
    ) -> List[Dict]:
        """
        Get comparison table for a run, sorted by specified metric.

        Args:
            run_id: Run identifier
            sort_by: Metric to sort by
            ascending: Sort order

        Returns:
            Sorted list of param set metrics
        """
        results = self.result_logger.get_run_results(run_id)
        if results is None or results['comparison'] is None:
            return []

        comparison = results['comparison'].get('comparison', {})
        table = comparison.get('comparison_table', [])

        # Sort by specified metric
        try:
            table.sort(key=lambda x: x.get(sort_by, 0), reverse=not ascending)
        except Exception as e:
            logger.warning(f"Failed to sort by {sort_by}: {e}")

        return table

    def get_rankings(
        self,
        run_id: str,
        metric: str = "uptime_percentage"
    ) -> List[ParamSetRanking]:
        """
        Get rankings for a specific metric.

        Args:
            run_id: Run identifier
            metric: Metric to rank by

        Returns:
            List of ParamSetRanking objects
        """
        table = self.get_comparison_table(run_id, sort_by=metric, ascending=False)

        rankings = []
        for i, entry in enumerate(table, 1):
            rankings.append(ParamSetRanking(
                param_set_id=entry.get('param_set_id', ''),
                param_set_name=entry.get('param_set_name', ''),
                rank=i,
                value=entry.get(metric, 0),
                metric_name=metric
            ))

        return rankings

    def get_recommendation(
        self,
        run_id: str,
        weights: Dict[str, float] = None
    ) -> Optional[Recommendation]:
        """
        Get recommended parameter set based on weighted scoring.

        Args:
            run_id: Run identifier
            weights: Custom weights (defaults to DEFAULT_WEIGHTS)

        Returns:
            Recommendation object or None
        """
        if weights is None:
            weights = self.DEFAULT_WEIGHTS

        results = self.result_logger.get_run_results(run_id)
        if results is None or results['comparison'] is None:
            return None

        comparison = results['comparison'].get('comparison', {})
        table = comparison.get('comparison_table', [])

        if not table:
            return None

        # Calculate weighted scores
        scores = []
        for entry in table:
            score = 0
            for metric, weight in weights.items():
                value = entry.get(metric, 0)
                # Normalize values (0-1 scale)
                if metric in ('uptime_percentage', 'boosted_time_pct', 'standard_time_pct',
                              'basic_time_pct', 'effective_points_pct'):
                    normalized = value / 100
                elif metric == 'simulated_pnl_usd':
                    normalized = min(value / 100, 1.0)  # Cap at 100 USD
                elif metric == 'simulated_fills':
                    normalized = min(value / 50, 1.0)  # Cap at 50 fills
                else:
                    normalized = value

                score += normalized * weight

            scores.append({
                'param_set_id': entry.get('param_set_id'),
                'param_set_name': entry.get('param_set_name'),
                'score': score,
                'metrics': entry
            })

        # Find best
        best = max(scores, key=lambda x: x['score'])

        return Recommendation(
            param_set_id=best['param_set_id'],
            param_set_name=best['param_set_name'],
            reason=f"最高綜合得分 ({best['score']:.3f}) - 有效積分{best['metrics'].get('effective_points_pct', 0):.1f}%",
            score=best['score'],
            metrics=best['metrics']
        )

    def compare_across_runs(
        self,
        run_ids: List[str],
        param_set_id: str
    ) -> List[Dict]:
        """
        Compare the same parameter set across multiple runs.

        Args:
            run_ids: List of run IDs to compare
            param_set_id: Parameter set to track

        Returns:
            List of metrics from each run
        """
        comparison = []

        for run_id in run_ids:
            results = self.result_logger.get_run_results(run_id)
            if results is None:
                continue

            ps_result = results['param_sets'].get(param_set_id)
            if ps_result is None:
                continue

            comparison.append({
                'run_id': run_id,
                'started_at': results['metadata'].get('started_at') if results['metadata'] else None,
                'metrics': ps_result.get('metrics', {})
            })

        return comparison

    def get_metric_trends(
        self,
        run_ids: List[str],
        metric: str = "uptime_percentage"
    ) -> Dict[str, List[Tuple[str, float]]]:
        """
        Get metric trends across runs for all param sets.

        Args:
            run_ids: List of run IDs (in chronological order)
            metric: Metric to track

        Returns:
            Dict mapping param_set_id to list of (run_id, value) tuples
        """
        trends = {}

        for run_id in run_ids:
            results = self.result_logger.get_run_results(run_id)
            if results is None or results['comparison'] is None:
                continue

            comparison = results['comparison'].get('comparison', {})
            table = comparison.get('comparison_table', [])

            for entry in table:
                ps_id = entry.get('param_set_id')
                value = entry.get(metric, 0)

                if ps_id not in trends:
                    trends[ps_id] = []
                trends[ps_id].append((run_id, value))

        return trends

    def export_to_csv(self, run_id: str, output_path: str = None) -> Optional[str]:
        """
        Export comparison results to CSV.

        Args:
            run_id: Run identifier
            output_path: Optional output path

        Returns:
            Path to CSV file or None
        """
        return self.result_logger.export_run_csv(run_id, output_path)

    def get_summary_stats(self, run_id: str) -> Dict:
        """
        Get summary statistics for a run.

        Args:
            run_id: Run identifier

        Returns:
            Summary statistics dict
        """
        results = self.result_logger.get_run_results(run_id)
        if results is None or results['comparison'] is None:
            return {}

        comparison = results['comparison'].get('comparison', {})
        table = comparison.get('comparison_table', [])

        if not table:
            return {}

        # Calculate summary stats
        metrics = ['uptime_percentage', 'simulated_fills', 'simulated_pnl_usd', 'boosted_time_pct']
        stats = {}

        for metric in metrics:
            values = [entry.get(metric, 0) for entry in table]
            if values:
                stats[metric] = {
                    'min': min(values),
                    'max': max(values),
                    'avg': sum(values) / len(values),
                    'range': max(values) - min(values)
                }

        return {
            'run_id': run_id,
            'param_set_count': len(table),
            'duration_seconds': results['comparison'].get('duration_seconds', 0),
            'metric_stats': stats
        }
