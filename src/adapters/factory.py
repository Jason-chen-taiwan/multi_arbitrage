"""
Adapter Factory

This module provides a factory function to create exchange adapters based on configuration.
"""
from typing import Dict, Any, Type
from .base_adapter import BasePerpAdapter
from .standx_adapter import StandXAdapter

# 注冊所有可用的適配器
_ADAPTER_REGISTRY: Dict[str, Type[BasePerpAdapter]] = {
    "standx": StandXAdapter,
    # 未來可以添加更多交易所適配器
    # "nado": NadoAdapter,
    # "grvt": GrvtAdapter,
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
        >>> config = {
        ...     "exchange_name": "standx",
        ...     "private_key": "0x...",
        ...     "chain": "bsc"
        ... }
        >>> adapter = create_adapter(config)
        >>> await adapter.connect()
    """
    exchange_name = config.get("exchange_name")
    
    if not exchange_name:
        raise ValueError("配置中必須包含 'exchange_name' 字段")
    
    exchange_name = exchange_name.lower()
    
    if exchange_name not in _ADAPTER_REGISTRY:
        available = ", ".join(_ADAPTER_REGISTRY.keys())
        raise ValueError(
            f"不支持的交易所: {exchange_name}。"
            f"可用的交易所: {available}"
        )
    
    adapter_class = _ADAPTER_REGISTRY[exchange_name]
    return adapter_class(config)


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


def get_available_exchanges() -> list:
    """
    獲取所有可用的交易所列表
    
    Returns:
        list: 交易所名稱列表
    """
    return list(_ADAPTER_REGISTRY.keys())
