"""
Multi-Parameter Simulation Module

Provides tools for running multiple parameter set simulations in parallel,
recording results, and comparing performance metrics.
"""

from .param_set_manager import ParamSetManager, ParamSet
from .simulation_state import SimulationState
from .simulation_executor import SimulationExecutor
from .simulation_runner import SimulationRunner
from .result_logger import ResultLogger
from .comparison_engine import ComparisonEngine

# Singleton instance
_param_set_manager = None


def get_param_set_manager() -> ParamSetManager:
    """Get the singleton ParamSetManager instance."""
    global _param_set_manager
    if _param_set_manager is None:
        _param_set_manager = ParamSetManager()
    return _param_set_manager


__all__ = [
    'ParamSetManager',
    'ParamSet',
    'SimulationState',
    'SimulationExecutor',
    'SimulationRunner',
    'ResultLogger',
    'ComparisonEngine',
    'get_param_set_manager',
]
