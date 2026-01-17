"""
GRVT Market Maker Config Manager

統一管理 GRVT 做市商配置，支持：
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
class GRVTStrategyConfig:
    """策略模式配置"""
    mode: str = "uptime"  # "uptime" | "rebate"
    aggressiveness: str = "moderate"  # "aggressive" | "moderate" | "conservative"


@dataclass
class GRVTQuoteConfig:
    """報價配置"""
    order_distance_bps: int = 8
    cancel_distance_bps: int = 3
    rebalance_distance_bps: int = 12
    cancel_on_approach: bool = True  # rebate 模式設為 False
    post_only: bool = False  # rebate 模式設為 True
    min_spread_ticks: int = 2  # 最小 spread 保護


@dataclass
class GRVTFeesConfig:
    """費率配置 (負數=收rebate, 正數=付fee)"""
    maker_bps: float = -1.0  # GRVT maker rebate
    taker_bps: float = 3.0   # GRVT taker fee
    hedge_bps: float = 2.0   # StandX hedge fee
    track_enabled: bool = True


@dataclass
class GRVTPositionConfig:
    """倉位配置"""
    order_size_btc: float = 0.01
    max_position_btc: float = 1.0


@dataclass
class GRVTVolatilityConfig:
    """波動率配置"""
    window_sec: int = 5
    threshold_bps: float = 5.0


@dataclass
class GRVTOrderConfig:
    """訂單配置"""
    type: str = "limit"
    time_in_force: str = "gtc"


@dataclass
class GRVTExecutionConfig:
    """執行配置"""
    tick_interval_ms: int = 100
    disappear_time_sec: float = 2.0


@dataclass
class GRVTHedgeConfig:
    """對沖配置"""
    exchange: str = "standx"
    auto_match_symbol: bool = True
    symbol_map: Dict[str, str] = field(default_factory=lambda: {
        "BTC_USDT_Perp": "BTC-USD",
        "ETH_USDT_Perp": "ETH-USD",
        "SOL_USDT_Perp": "SOL-USD",
    })
    timeout_ms: int = 1000
    retry_count: int = 3
    retry_delay_ms: int = 100
    max_unhedged_position: float = 0.01


@dataclass
class GRVTMMConfigData:
    """GRVT 做市商完整配置"""
    symbols: Dict[str, str] = field(default_factory=lambda: {
        "primary": "BTC_USDT_Perp",
        "hedge": "BTC-USD"
    })
    strategy: GRVTStrategyConfig = field(default_factory=GRVTStrategyConfig)
    quote: GRVTQuoteConfig = field(default_factory=GRVTQuoteConfig)
    position: GRVTPositionConfig = field(default_factory=GRVTPositionConfig)
    fees: GRVTFeesConfig = field(default_factory=GRVTFeesConfig)
    volatility: GRVTVolatilityConfig = field(default_factory=GRVTVolatilityConfig)
    order: GRVTOrderConfig = field(default_factory=GRVTOrderConfig)
    execution: GRVTExecutionConfig = field(default_factory=GRVTExecutionConfig)
    hedge: GRVTHedgeConfig = field(default_factory=GRVTHedgeConfig)

    def to_dict(self) -> Dict[str, Any]:
        """轉換為字典"""
        return {
            "symbols": self.symbols,
            "strategy": asdict(self.strategy),
            "quote": asdict(self.quote),
            "position": asdict(self.position),
            "fees": asdict(self.fees),
            "volatility": asdict(self.volatility),
            "order": asdict(self.order),
            "execution": asdict(self.execution),
            "hedge": {
                "exchange": self.hedge.exchange,
                "auto_match_symbol": self.hedge.auto_match_symbol,
                "symbol_map": self.hedge.symbol_map,
                "timeout_ms": self.hedge.timeout_ms,
                "retry_count": self.hedge.retry_count,
                "retry_delay_ms": self.hedge.retry_delay_ms,
                "max_unhedged_position": self.hedge.max_unhedged_position,
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GRVTMMConfigData':
        """從字典創建"""
        hedge_data = data.get("hedge", {})
        strategy_data = data.get("strategy", {})
        quote_data = data.get("quote", {})
        fees_data = data.get("fees", {})

        return cls(
            symbols=data.get("symbols", {}),
            strategy=GRVTStrategyConfig(
                mode=strategy_data.get("mode", "uptime"),
                aggressiveness=strategy_data.get("aggressiveness", "moderate"),
            ),
            quote=GRVTQuoteConfig(
                order_distance_bps=quote_data.get("order_distance_bps", 8),
                cancel_distance_bps=quote_data.get("cancel_distance_bps", 3),
                rebalance_distance_bps=quote_data.get("rebalance_distance_bps", 12),
                cancel_on_approach=quote_data.get("cancel_on_approach", True),
                post_only=quote_data.get("post_only", False),
                min_spread_ticks=quote_data.get("min_spread_ticks", 2),
            ),
            position=GRVTPositionConfig(**data.get("position", {})),
            fees=GRVTFeesConfig(
                maker_bps=fees_data.get("maker_bps", -1.0),
                taker_bps=fees_data.get("taker_bps", 3.0),
                hedge_bps=fees_data.get("hedge_bps", 2.0),
                track_enabled=fees_data.get("track_enabled", True),
            ),
            volatility=GRVTVolatilityConfig(**data.get("volatility", {})),
            order=GRVTOrderConfig(**data.get("order", {})),
            execution=GRVTExecutionConfig(**data.get("execution", {})),
            hedge=GRVTHedgeConfig(
                exchange=hedge_data.get("exchange", "standx"),
                auto_match_symbol=hedge_data.get("auto_match_symbol", True),
                symbol_map=hedge_data.get("symbol_map", {}),
                timeout_ms=hedge_data.get("timeout_ms", 1000),
                retry_count=hedge_data.get("retry_count", 3),
                retry_delay_ms=hedge_data.get("retry_delay_ms", 100),
                max_unhedged_position=hedge_data.get("max_unhedged_position", 0.01),
            ),
        )


class GRVTMMConfigManager:
    """GRVT 做市商配置管理器 (單例)"""

    _instance: Optional['GRVTMMConfigManager'] = None

    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置管理器

        Args:
            config_path: 配置文件路徑，默認為 config/grvt_mm_config.yaml
        """
        if config_path is None:
            project_root = Path(__file__).parent.parent.parent
            config_path = project_root / "config" / "grvt_mm_config.yaml"

        self._config_path = Path(config_path)
        self._config: GRVTMMConfigData = GRVTMMConfigData()
        self._load_config()

    @classmethod
    def get_instance(cls, config_path: Optional[str] = None) -> 'GRVTMMConfigManager':
        """獲取單例實例"""
        if cls._instance is None:
            cls._instance = cls(config_path)
        return cls._instance

    @classmethod
    def reset(cls):
        """重置單例 (用於測試)"""
        cls._instance = None

    def _to_plain_dict(self, data) -> Dict[str, Any]:
        """遞歸轉換 ruamel.yaml CommentedMap 為普通 dict"""
        if hasattr(data, 'items'):
            return {k: self._to_plain_dict(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._to_plain_dict(item) for item in data]
        else:
            return data

    def _load_config(self):
        """從文件加載配置"""
        if not self._config_path.exists():
            print(f"Warning: GRVT MM config not found at {self._config_path}, using defaults")
            return

        try:
            yaml = YAML()
            yaml.preserve_quotes = True

            with open(self._config_path, 'r', encoding='utf-8') as f:
                data = yaml.load(f)

            if data:
                self._raw_yaml = data
                # 遞歸轉換為普通 dict（重要：ruamel.yaml 返回的是 CommentedMap）
                plain_data = self._to_plain_dict(data)

                # 診斷：打印原始 YAML 中的 strategy 區段
                strategy_raw = plain_data.get("strategy", {})
                print(f"[ConfigManager] Raw strategy from YAML: {strategy_raw}")

                self._config = GRVTMMConfigData.from_dict(plain_data)

                # 診斷：打印解析後的配置
                print(f"[ConfigManager] Parsed config: strategy.mode={self._config.strategy.mode}, strategy.aggressiveness={self._config.strategy.aggressiveness}")
                print(f"[ConfigManager] Loaded GRVT MM config from {self._config_path}")

        except Exception as e:
            print(f"Error loading GRVT MM config: {e}, using defaults")
            import traceback
            traceback.print_exc()

    def reload(self):
        """重新加載配置"""
        self._load_config()

    def save(self):
        """保存配置到文件 (保留註釋和格式)"""
        try:
            yaml = YAML()
            yaml.preserve_quotes = True
            yaml.indent(mapping=2, sequence=4, offset=2)

            if hasattr(self, '_raw_yaml') and self._raw_yaml:
                self._update_raw_yaml(self._config.to_dict())
                data_to_save = self._raw_yaml
            else:
                data_to_save = self._config.to_dict()

            with open(self._config_path, 'w', encoding='utf-8') as f:
                yaml.dump(data_to_save, f)
            print(f"Saved GRVT MM config to {self._config_path}")
        except Exception as e:
            print(f"Error saving GRVT MM config: {e}")

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
    def config(self) -> GRVTMMConfigData:
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

        for key, value in updates.items():
            if key in current and isinstance(current[key], dict) and isinstance(value, dict):
                current[key].update(value)
            else:
                current[key] = value

        self._config = GRVTMMConfigData.from_dict(current)

        if save:
            self.save()

    # 便捷屬性
    @property
    def primary_symbol(self) -> str:
        return self._config.symbols.get("primary", "BTC_USDT_Perp")

    @property
    def hedge_symbol(self) -> str:
        return self._config.symbols.get("hedge", "BTC-USD")

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

    def __repr__(self) -> str:
        return f"<GRVTMMConfigManager symbol={self.primary_symbol} order_dist={self.order_distance_bps}bps>"


# 便捷函數
def get_grvt_mm_config() -> GRVTMMConfigManager:
    """獲取 GRVTMMConfigManager 單例"""
    return GRVTMMConfigManager.get_instance()
