"""
Parameter Set Manager

Loads and manages multiple parameter sets for simulation comparison.
"""

import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from copy import deepcopy


@dataclass
class ParamSet:
    """A single parameter set configuration."""
    id: str
    name: str
    description: str
    config: Dict[str, Any]  # Full merged config


@dataclass
class SimulationConfig:
    """Simulation run settings."""
    duration_minutes: int = 60
    tick_interval_ms: int = 100


class ParamSetManager:
    """
    Manages parameter sets for multi-simulation comparison.
    Loads from config/param_sets.yaml and handles merging with base config.
    """

    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = Path(__file__).parent.parent.parent / "config" / "param_sets.yaml"
        self.config_path = Path(config_path)
        self._raw_config: Dict = {}
        self._param_sets: Dict[str, ParamSet] = {}
        self._simulation_config: SimulationConfig = SimulationConfig()
        self._base_config: Dict = {}
        self._load_config()

    def _load_config(self):
        """Load configuration from YAML file."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        with open(self.config_path, 'r', encoding='utf-8') as f:
            self._raw_config = yaml.safe_load(f)

        # Load simulation settings
        sim_config = self._raw_config.get('simulation', {})
        self._simulation_config = SimulationConfig(
            duration_minutes=sim_config.get('duration_minutes', 60),
            tick_interval_ms=sim_config.get('tick_interval_ms', 100)
        )

        # Load base config
        self._base_config = self._raw_config.get('base_config', {})

        # Load and merge param sets
        self._param_sets = {}
        for ps_data in self._raw_config.get('param_sets', []):
            param_set = self._create_param_set(ps_data)
            self._param_sets[param_set.id] = param_set

    def _create_param_set(self, ps_data: Dict) -> ParamSet:
        """Create a ParamSet by merging overrides with base config."""
        # Deep copy base config
        merged_config = deepcopy(self._base_config)

        # Merge overrides
        overrides = ps_data.get('overrides', {})
        self._deep_merge(merged_config, overrides)

        return ParamSet(
            id=ps_data['id'],
            name=ps_data.get('name', ps_data['id']),
            description=ps_data.get('description', ''),
            config=merged_config
        )

    def _deep_merge(self, base: Dict, override: Dict):
        """Deep merge override into base dict."""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = deepcopy(value)

    def reload(self):
        """Reload configuration from file."""
        self._load_config()

    def get_param_sets(self) -> List[ParamSet]:
        """Get all available parameter sets."""
        return list(self._param_sets.values())

    def get_param_set(self, param_set_id: str) -> Optional[ParamSet]:
        """Get a specific parameter set by ID."""
        return self._param_sets.get(param_set_id)

    def get_param_set_ids(self) -> List[str]:
        """Get list of all parameter set IDs."""
        return list(self._param_sets.keys())

    def get_simulation_config(self) -> SimulationConfig:
        """Get simulation run settings."""
        return self._simulation_config

    def get_base_config(self) -> Dict:
        """Get the base configuration."""
        return deepcopy(self._base_config)

    def add_param_set(self, ps_data: Dict, save: bool = False) -> ParamSet:
        """
        Add a new parameter set dynamically.

        Args:
            ps_data: Dict with id, name, description, overrides
            save: Whether to persist to YAML file
        """
        if 'id' not in ps_data:
            raise ValueError("Parameter set must have an 'id'")

        param_set = self._create_param_set(ps_data)
        self._param_sets[param_set.id] = param_set

        if save:
            self._save_config()

        return param_set

    def remove_param_set(self, param_set_id: str, save: bool = False) -> bool:
        """Remove a parameter set."""
        if param_set_id not in self._param_sets:
            return False

        del self._param_sets[param_set_id]

        if save:
            self._save_config()

        return True

    def _save_config(self):
        """Save current configuration to YAML file."""
        # Rebuild param_sets list from current state
        param_sets_list = []
        for ps in self._param_sets.values():
            ps_data = {
                'id': ps.id,
                'name': ps.name,
                'description': ps.description,
                'overrides': self._extract_overrides(ps.config)
            }
            param_sets_list.append(ps_data)

        self._raw_config['param_sets'] = param_sets_list

        with open(self.config_path, 'w', encoding='utf-8') as f:
            yaml.dump(self._raw_config, f, allow_unicode=True, default_flow_style=False)

    def _extract_overrides(self, config: Dict) -> Dict:
        """Extract overrides by comparing with base config."""
        overrides = {}
        for key, value in config.items():
            if key not in self._base_config:
                overrides[key] = value
            elif isinstance(value, dict) and isinstance(self._base_config.get(key), dict):
                nested = self._extract_overrides_nested(value, self._base_config[key])
                if nested:
                    overrides[key] = nested
            elif value != self._base_config.get(key):
                overrides[key] = value
        return overrides

    def _extract_overrides_nested(self, config: Dict, base: Dict) -> Dict:
        """Extract nested overrides."""
        overrides = {}
        for key, value in config.items():
            if key not in base:
                overrides[key] = value
            elif value != base.get(key):
                overrides[key] = value
        return overrides

    def to_dict(self) -> Dict:
        """Export all param sets as dict for API response."""
        return {
            'simulation': {
                'duration_minutes': self._simulation_config.duration_minutes,
                'tick_interval_ms': self._simulation_config.tick_interval_ms
            },
            'base_config': self._base_config,
            'param_sets': [
                {
                    'id': ps.id,
                    'name': ps.name,
                    'description': ps.description,
                    'config': ps.config
                }
                for ps in self._param_sets.values()
            ]
        }


# Global instance
_manager_instance: Optional[ParamSetManager] = None


def get_param_set_manager() -> ParamSetManager:
    """Get global ParamSetManager instance."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = ParamSetManager()
    return _manager_instance
