"""
Web API 路由模組

將 auto_dashboard.py 中的 API 端點拆分到獨立文件：
- config_routes.py: /api/config/* 端點
- control_routes.py: /api/control/* 和 /api/system/* 端點
- mm_routes.py: /api/mm/* 端點 (StandX)
- simulation_routes.py: /api/simulation/* 端點
- referral_routes.py: /api/referral/* 端點
"""

from .config_routes import register_config_routes
from .control_routes import register_control_routes
from .mm_routes import register_mm_routes
from .simulation_routes import register_simulation_routes
from .referral_routes import register_referral_routes
from .accounts_routes import register_accounts_routes


def register_all_routes(app, dependencies):
    """
    註冊所有 API 路由

    Args:
        app: FastAPI 應用實例
        dependencies: 依賴項字典，包含:
            - config_manager: ConfigManager 實例
            - adapters_getter: 返回 adapters 字典的函數
            - executor_getter: 返回 executor 的函數
            - mm_executor_getter: 返回 mm_executor 的函數
            - monitor_getter: 返回 monitor 的函數
            - system_status: 系統狀態字典
            - mm_status: 做市商狀態字典
            - init_system: 初始化系統的異步函數
            - add_exchange: 添加交易所的異步函數
            - remove_exchange: 移除交易所的異步函數
            - serialize_for_json: JSON 序列化函數
            - logger: 日誌記錄器
            - system_manager_getter: 返回 SystemManager 的函數
    """
    register_config_routes(app, dependencies)
    register_control_routes(app, dependencies)
    register_mm_routes(app, dependencies)
    register_simulation_routes(app, dependencies)
    register_referral_routes(app, dependencies)
    register_accounts_routes(app, dependencies)
