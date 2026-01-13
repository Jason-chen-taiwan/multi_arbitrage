"""
Symbol Manager - 統一管理各交易所的 symbol 映射

使用方式:
    from src.utils.symbol_manager import SymbolManager

    # 獲取單例
    sm = SymbolManager.get_instance()

    # 轉換 symbol
    binance_symbol = sm.to_exchange('BTC-USD', 'binance')  # -> 'BTC/USDT:USDT'
    unified_symbol = sm.to_unified('BTC/USDT:USDT', 'binance')  # -> 'BTC-USD'

    # 獲取 tick size
    tick = sm.get_tick_size('BTC-USD')  # -> Decimal('0.01')
"""

import os
from pathlib import Path
from decimal import Decimal
from typing import Dict, Optional, Any
import yaml


class SymbolManager:
    """Symbol 映射管理器 (單例模式)"""

    _instance: Optional['SymbolManager'] = None

    def __init__(self, config_path: Optional[str] = None):
        """
        初始化 (不要直接調用，使用 get_instance())

        Args:
            config_path: 配置文件路徑，默認為 config/symbols.yaml
        """
        if config_path is None:
            # 從項目根目錄查找
            project_root = Path(__file__).parent.parent.parent
            config_path = project_root / "config" / "symbols.yaml"

        self._config_path = Path(config_path)
        self._config: Dict[str, Any] = {}
        self._exchange_maps: Dict[str, Dict[str, str]] = {}
        self._reverse_maps: Dict[str, Dict[str, str]] = {}

        self._load_config()

    @classmethod
    def get_instance(cls, config_path: Optional[str] = None) -> 'SymbolManager':
        """
        獲取單例實例

        Args:
            config_path: 配置文件路徑 (僅首次調用有效)

        Returns:
            SymbolManager 實例
        """
        if cls._instance is None:
            cls._instance = cls(config_path)
        return cls._instance

    @classmethod
    def reset(cls):
        """重置單例 (用於測試)"""
        cls._instance = None

    def _load_config(self):
        """加載配置文件"""
        if not self._config_path.exists():
            print(f"Warning: Symbol config not found at {self._config_path}, using defaults")
            self._use_defaults()
            return

        with open(self._config_path, 'r', encoding='utf-8') as f:
            self._config = yaml.safe_load(f)

        # 構建映射表
        exchanges = self._config.get('exchanges', {})
        for exchange_name, symbol_map in exchanges.items():
            self._exchange_maps[exchange_name.lower()] = symbol_map
            # 反向映射
            self._reverse_maps[exchange_name.lower()] = {
                v: k for k, v in symbol_map.items()
            }

    def _use_defaults(self):
        """使用默認配置"""
        self._config = {
            'symbols': ['BTC-USD', 'ETH-USD', 'SOL-USD'],
            'tick_sizes': {
                'BTC-USD': 0.01,
                'ETH-USD': 0.01,
                'SOL-USD': 0.001,
            },
            'min_quantities': {
                'BTC-USD': 0.001,
                'ETH-USD': 0.01,
                'SOL-USD': 0.1,
            },
            'price_precision': {
                'BTC-USD': 2,
                'ETH-USD': 2,
                'SOL-USD': 3,
            },
            'quantity_precision': {
                'BTC-USD': 3,
                'ETH-USD': 2,
                'SOL-USD': 1,
            },
        }

        # 默認映射
        default_cex_map = {
            'BTC-USD': 'BTC/USDT:USDT',
            'ETH-USD': 'ETH/USDT:USDT',
            'SOL-USD': 'SOL/USDT:USDT',
        }
        default_dex_map = {
            'BTC-USD': 'BTC-USD',
            'ETH-USD': 'ETH-USD',
            'SOL-USD': 'SOL-USD',
        }

        for exchange in ['binance', 'okx', 'bitget', 'bybit']:
            self._exchange_maps[exchange] = default_cex_map.copy()
            self._reverse_maps[exchange] = {v: k for k, v in default_cex_map.items()}

        self._exchange_maps['standx'] = default_dex_map.copy()
        self._reverse_maps['standx'] = {v: k for k, v in default_dex_map.items()}

    def to_exchange(self, unified_symbol: str, exchange: str) -> str:
        """
        將統一格式轉換為交易所格式

        Args:
            unified_symbol: 統一格式 symbol (如 'BTC-USD')
            exchange: 交易所名稱

        Returns:
            交易所格式的 symbol
        """
        exchange = exchange.lower()
        symbol_map = self._exchange_maps.get(exchange, {})
        return symbol_map.get(unified_symbol, unified_symbol)

    def to_unified(self, exchange_symbol: str, exchange: str) -> str:
        """
        將交易所格式轉換為統一格式

        Args:
            exchange_symbol: 交易所格式 symbol
            exchange: 交易所名稱

        Returns:
            統一格式的 symbol (如 'BTC-USD')
        """
        exchange = exchange.lower()
        reverse_map = self._reverse_maps.get(exchange, {})
        return reverse_map.get(exchange_symbol, exchange_symbol)

    def get_tick_size(self, symbol: str) -> Decimal:
        """獲取 tick size"""
        tick_sizes = self._config.get('tick_sizes', {})
        return Decimal(str(tick_sizes.get(symbol, 0.01)))

    def get_min_quantity(self, symbol: str) -> Decimal:
        """獲取最小訂單量"""
        min_qtys = self._config.get('min_quantities', {})
        return Decimal(str(min_qtys.get(symbol, 0.001)))

    def get_price_precision(self, symbol: str) -> int:
        """獲取價格精度"""
        precisions = self._config.get('price_precision', {})
        return precisions.get(symbol, 2)

    def get_quantity_precision(self, symbol: str) -> int:
        """獲取數量精度"""
        precisions = self._config.get('quantity_precision', {})
        return precisions.get(symbol, 3)

    def get_all_symbols(self) -> list:
        """獲取所有支持的 symbols"""
        return self._config.get('symbols', [])

    def get_exchange_map(self, exchange: str) -> Dict[str, str]:
        """
        獲取某交易所的完整映射表

        Args:
            exchange: 交易所名稱

        Returns:
            symbol 映射字典
        """
        return self._exchange_maps.get(exchange.lower(), {})

    def register_exchange(self, exchange: str, symbol_map: Dict[str, str]):
        """
        動態註冊交易所映射

        Args:
            exchange: 交易所名稱
            symbol_map: symbol 映射字典
        """
        exchange = exchange.lower()
        self._exchange_maps[exchange] = symbol_map
        self._reverse_maps[exchange] = {v: k for k, v in symbol_map.items()}

    def __repr__(self) -> str:
        return f"<SymbolManager exchanges={list(self._exchange_maps.keys())}>"


# 便捷函數
def get_symbol_manager() -> SymbolManager:
    """獲取 SymbolManager 單例"""
    return SymbolManager.get_instance()
