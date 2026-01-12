"""
Exchange Adapters Package

統一入口：通過配置創建適配器，無需關心具體實現

使用示例:
    from adapters import create_adapter
    
    # 只需要更改配置即可切換交易所
    config = {
        "exchange_name": "standx",  # 或 "nado", "grvt" 等
        "private_key": "0x...",
        "chain": "bsc"
    }
    
    adapter = create_adapter(config)
    await adapter.connect()
    balance = await adapter.get_balance()
"""
from .base_adapter import (
    BasePerpAdapter,
    OrderSide,
    OrderType,
    TimeInForce,
    OrderStatus,
    Position,
    Balance,
    Order,
)
from .factory import (
    create_adapter,
    register_adapter,
    get_available_exchanges,
)

__all__ = [
    # 基類和接口
    "BasePerpAdapter",
    "create_adapter",
    
    # 數據模型
    "Position",
    "Balance",
    "Order",
    
    # 枚舉類型
    "OrderSide",
    "OrderType",
    "TimeInForce",
    "OrderStatus",
    
    # 工具函數
    "register_adapter",
    "get_available_exchanges",
]
