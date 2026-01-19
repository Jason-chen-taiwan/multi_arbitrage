"""
Market Maker Config Manager

統一管理做市商配置，支持：
1. 從 YAML 文件加載配置
2. 運行時動態更新配置
3. 提供 API 接口供前端讀取
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional
from decimal import Decimal
from dataclasses import dataclass, field, asdict

from ruamel.yaml import YAML


@dataclass
class QuoteConfig:
    """報價配置"""
    order_distance_bps: int = 9
    cancel_distance_bps: int = 5
    rebalance_distance_bps: int = 12
    queue_position_limit: int = 3  # 排在前 N 檔時撤單


@dataclass
class PositionConfig:
    """倉位配置"""
    order_size_btc: float = 0.001
    max_position_btc: float = 0.01


@dataclass
class VolatilityConfig:
    """波動率配置 (hysteresis + stable period)"""
    window_sec: int = 5
    threshold_bps: float = 10.0  # 暫停閾值 (更敏感，避免單向移動吃單)
    resume_threshold_bps: float = 5.0  # 恢復閾值 (低於此才考慮恢復)
    stable_seconds: float = 3.0  # 需持續低於恢復閾值多少秒


@dataclass
class OrderConfig:
    """訂單配置"""
    type: str = "limit"
    time_in_force: str = "gtc"


@dataclass
class ExecutionConfig:
    """執行配置"""
    tick_interval_ms: int = 100
    dry_run: bool = True


@dataclass
class HedgeConfig:
    """對沖配置"""
    timeout_ms: int = 1000
    retry_count: int = 3
    retry_delay_ms: int = 100


@dataclass
class UptimeConfig:
    """Uptime Program 配置 (StandX: 0-10=100%, 10-30=50%, 30-100=10%)"""
    max_distance_bps: int = 30
    boosted_threshold: float = 0.70
    standard_threshold: float = 0.50


@dataclass
class MMConfigData:
    """做市商完整配置"""
    symbols: Dict[str, str] = field(default_factory=lambda: {
        "standx": "BTC-USD",
        "binance": "BTC/USDT:USDT"
    })
    quote: QuoteConfig = field(default_factory=QuoteConfig)
    position: PositionConfig = field(default_factory=PositionConfig)
    volatility: VolatilityConfig = field(default_factory=VolatilityConfig)
    order: OrderConfig = field(default_factory=OrderConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    hedge: HedgeConfig = field(default_factory=HedgeConfig)
    uptime: UptimeConfig = field(default_factory=UptimeConfig)

    def to_dict(self) -> Dict[str, Any]:
        """轉換為字典"""
        return {
            "symbols": self.symbols,
            "quote": asdict(self.quote),
            "position": asdict(self.position),
            "volatility": asdict(self.volatility),
            "order": asdict(self.order),
            "execution": asdict(self.execution),
            "hedge": asdict(self.hedge),
            "uptime": asdict(self.uptime),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MMConfigData':
        """從字典創建"""
        return cls(
            symbols=data.get("symbols", {}),
            quote=QuoteConfig(**data.get("quote", {})),
            position=PositionConfig(**data.get("position", {})),
            volatility=VolatilityConfig(**data.get("volatility", {})),
            order=OrderConfig(**data.get("order", {})),
            execution=ExecutionConfig(**data.get("execution", {})),
            hedge=HedgeConfig(**data.get("hedge", {})),
            uptime=UptimeConfig(**data.get("uptime", {})),
        )


class MMConfigManager:
    """做市商配置管理器 (單例)"""

    _instance: Optional['MMConfigManager'] = None

    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置管理器

        Args:
            config_path: 配置文件路徑，默認為 config/mm_config.yaml
        """
        if config_path is None:
            project_root = Path(__file__).parent.parent.parent
            config_path = project_root / "config" / "mm_config.yaml"

        self._config_path = Path(config_path)
        self._config: MMConfigData = MMConfigData()
        self._load_config()

    @classmethod
    def get_instance(cls, config_path: Optional[str] = None) -> 'MMConfigManager':
        """獲取單例實例"""
        if cls._instance is None:
            cls._instance = cls(config_path)
        return cls._instance

    @classmethod
    def reset(cls):
        """重置單例 (用於測試)"""
        cls._instance = None

    def _load_config(self):
        """從文件加載配置"""
        if not self._config_path.exists():
            print(f"Warning: MM config not found at {self._config_path}, using defaults")
            return

        try:
            yaml = YAML()
            yaml.preserve_quotes = True

            with open(self._config_path, 'r', encoding='utf-8') as f:
                data = yaml.load(f)

            if data:
                # 保存原始 YAML 數據以保留註釋
                self._raw_yaml = data
                # 轉換為普通 dict 給 dataclass
                self._config = MMConfigData.from_dict(dict(data))
                print(f"Loaded MM config from {self._config_path}")

        except Exception as e:
            print(f"Error loading MM config: {e}, using defaults")

    def reload(self):
        """重新加載配置"""
        self._load_config()

    def save(self):
        """保存配置到文件 (保留註釋和格式)"""
        try:
            yaml = YAML()
            yaml.preserve_quotes = True
            yaml.indent(mapping=2, sequence=4, offset=2)

            # 如果有原始 YAML 數據，更新它以保留註釋
            if hasattr(self, '_raw_yaml') and self._raw_yaml:
                self._update_raw_yaml(self._config.to_dict())
                data_to_save = self._raw_yaml
            else:
                data_to_save = self._config.to_dict()

            with open(self._config_path, 'w', encoding='utf-8') as f:
                yaml.dump(data_to_save, f)
            print(f"Saved MM config to {self._config_path}")
        except Exception as e:
            print(f"Error saving MM config: {e}")

    def _update_raw_yaml(self, new_data: Dict[str, Any]):
        """更新原始 YAML 數據，保留結構和註釋"""
        def deep_update(original, updates):
            for key, value in updates.items():
                if key in original:
                    if isinstance(value, dict) and isinstance(original[key], dict):
                        deep_update(original[key], value)
                    else:
                        original[key] = value
                else:
                    original[key] = value

        deep_update(self._raw_yaml, new_data)

    @property
    def config(self) -> MMConfigData:
        """獲取配置"""
        return self._config

    def get_dict(self) -> Dict[str, Any]:
        """獲取配置字典 (用於 API)"""
        return self._config.to_dict()

    def update(self, updates: Dict[str, Any], save: bool = False):
        """
        更新配置

        Args:
            updates: 要更新的配置項
            save: 是否保存到文件
        """
        current = self._config.to_dict()

        # 深度合併
        for key, value in updates.items():
            if key in current and isinstance(current[key], dict) and isinstance(value, dict):
                current[key].update(value)
            else:
                current[key] = value

        self._config = MMConfigData.from_dict(current)

        if save:
            self.save()

    # 便捷屬性
    @property
    def order_distance_bps(self) -> int:
        return self._config.quote.order_distance_bps

    @property
    def cancel_distance_bps(self) -> int:
        return self._config.quote.cancel_distance_bps

    @property
    def rebalance_distance_bps(self) -> int:
        return self._config.quote.rebalance_distance_bps

    @property
    def order_size_btc(self) -> Decimal:
        return Decimal(str(self._config.position.order_size_btc))

    @property
    def max_position_btc(self) -> Decimal:
        return Decimal(str(self._config.position.max_position_btc))

    @property
    def volatility_threshold_bps(self) -> float:
        return self._config.volatility.threshold_bps

    @property
    def volatility_resume_threshold_bps(self) -> float:
        return self._config.volatility.resume_threshold_bps

    @property
    def volatility_stable_seconds(self) -> float:
        return self._config.volatility.stable_seconds

    @property
    def dry_run(self) -> bool:
        return self._config.execution.dry_run

    @property
    def uptime_max_distance_bps(self) -> int:
        return self._config.uptime.max_distance_bps

    def __repr__(self) -> str:
        return f"<MMConfigManager order_dist={self.order_distance_bps}bps dry_run={self.dry_run}>"


# 便捷函數
def get_mm_config() -> MMConfigManager:
    """獲取 MMConfigManager 單例"""
    return MMConfigManager.get_instance()
