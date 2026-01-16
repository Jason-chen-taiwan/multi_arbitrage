"""
Adapter Factory

This module provides a factory function to create exchange adapters based on configuration.
"""
from typing import Dict, Any, Type
from .base_adapter import BasePerpAdapter
from .standx_adapter import StandXAdapter
from .grvt_adapter import GRVTAdapter
from .ccxt_adapter import CCXTAdapter

# DEX 交易所（需要自定義適配器）
DEX_EXCHANGES = ["standx", "grvt"]

# CEX 交易所（使用 CCXT 統一適配器）
CEX_EXCHANGES = [
    "binance", "okx", "bitget", "bybit", "gateio",
    "huobi", "kucoin", "mexc", "coinbase", "kraken"
]

# 注冊 DEX 適配器
_ADAPTER_REGISTRY: Dict[str, Type[BasePerpAdapter]] = {
    "standx": StandXAdapter,
    "grvt": GRVTAdapter,
    # 未來可以添加更多 DEX 適配器
    # "var": VARAdapter,
    # "paradex": ParadexAdapter,
}


def create_adapter(config: Dict[str, Any]) -> BasePerpAdapter:
    """
    根據配置創建適配器實例

    Args:
        config: 配置字典，必須包含 "exchange_name" 字段

    Returns:
        BasePerpAdapter: 適配器實例

    Raises:
        ValueError: 如果交易所名稱不支持或配置無效

    Example:
        >>> # StandX - Token 模式 (推薦)
        >>> config = {
        ...     "exchange_name": "standx",
        ...     "api_token": "eyJhbGci...",
        ...     "ed25519_private_key": "3cqUwpXqkE9gA5..."
        ... }
        >>> adapter = create_adapter(config)
        >>> await adapter.connect()

        >>> # StandX - 錢包簽名模式 (舊方式)
        >>> config = {
        ...     "exchange_name": "standx",
        ...     "private_key": "0x...",
        ...     "chain": "bsc"
        ... }
        >>> adapter = create_adapter(config)
        >>> await adapter.connect()

        >>> # CEX 示例（Binance）
        >>> config = {
        ...     "exchange_name": "binance",
        ...     "api_key": "your_api_key",
        ...     "api_secret": "your_api_secret"
        ... }
        >>> adapter = create_adapter(config)
        >>> await adapter.connect()
    """
    exchange_name = config.get("exchange_name")

    if not exchange_name:
        raise ValueError("配置中必須包含 'exchange_name' 字段")

    exchange_name = exchange_name.lower()

    # 檢查是否是 DEX（使用自定義適配器）
    if exchange_name in _ADAPTER_REGISTRY:
        adapter_class = _ADAPTER_REGISTRY[exchange_name]
        return adapter_class(config)

    # 檢查是否是 CEX（使用 CCXT 適配器）
    elif exchange_name in CEX_EXCHANGES:
        return CCXTAdapter(config)

    # 不支持的交易所
    else:
        all_exchanges = list(_ADAPTER_REGISTRY.keys()) + CEX_EXCHANGES
        available = ", ".join(sorted(all_exchanges))
        raise ValueError(
            f"不支持的交易所: {exchange_name}。\n"
            f"可用的 DEX: {', '.join(DEX_EXCHANGES)}\n"
            f"可用的 CEX: {', '.join(CEX_EXCHANGES)}"
        )


def register_adapter(exchange_name: str, adapter_class: Type[BasePerpAdapter]):
    """
    註冊新的適配器類
    
    Args:
        exchange_name: 交易所名稱（小寫）
        adapter_class: 適配器類，必須繼承自 BasePerpAdapter
        
    Example:
        >>> from adapters.base_adapter import BasePerpAdapter
        >>> class MyExchangeAdapter(BasePerpAdapter):
        ...     pass
        >>> register_adapter("myexchange", MyExchangeAdapter)
    """
    if not issubclass(adapter_class, BasePerpAdapter):
        raise ValueError(f"適配器類必須繼承自 BasePerpAdapter")
    
    _ADAPTER_REGISTRY[exchange_name.lower()] = adapter_class


def get_available_exchanges() -> Dict[str, list]:
    """
    獲取所有可用的交易所列表

    Returns:
        Dict[str, list]: 包含 DEX 和 CEX 列表的字典
            - "dex": DEX 交易所列表
            - "cex": CEX 交易所列表
            - "all": 所有交易所列表
    """
    all_exchanges = list(_ADAPTER_REGISTRY.keys()) + CEX_EXCHANGES
    return {
        "dex": list(_ADAPTER_REGISTRY.keys()),
        "cex": CEX_EXCHANGES,
        "all": sorted(all_exchanges)
    }
