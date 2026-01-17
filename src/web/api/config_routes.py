"""
配置 API 路由

包含:
- GET /api/config/list - 獲取所有配置
- POST /api/config/save - 保存配置
- POST /api/config/delete - 刪除配置
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse


router = APIRouter(prefix="/api/config", tags=["config"])


def register_config_routes(app, dependencies):
    """
    註冊配置相關路由

    Args:
        app: FastAPI 應用實例
        dependencies: 依賴項字典
    """
    config_manager = dependencies['config_manager']
    add_exchange = dependencies['add_exchange']
    remove_exchange = dependencies['remove_exchange']
    adapters_getter = dependencies['adapters_getter']
    system_manager_getter = dependencies.get('system_manager_getter')
    logger = dependencies.get('logger')

    @router.get("/list")
    async def list_configs():
        """獲取所有配置"""
        try:
            configs = config_manager.get_all_configs()
            return JSONResponse(configs)
        except Exception as e:
            return JSONResponse({'error': str(e)})

    @router.post("/save")
    async def save_config(request: Request):
        """保存配置並動態添加到監控"""
        try:
            data = await request.json()
            exchange_name = data['exchange_name']
            exchange_type = data['exchange_type']
            config = data['config']

            # 保存配置
            config_manager.save_config(exchange_name, exchange_type, config)

            # 動態添加到監控
            await add_exchange(exchange_name, exchange_type)

            return JSONResponse({'success': True})
        except Exception as e:
            return JSONResponse({'success': False, 'error': str(e)})

    @router.post("/delete")
    async def delete_config(request: Request):
        """刪除配置並從監控移除"""
        try:
            data = await request.json()
            exchange_name = data['exchange_name']
            exchange_type = data['exchange_type']

            # 從監控移除
            await remove_exchange(exchange_name)

            # 刪除配置
            config_manager.delete_config(exchange_name, exchange_type)

            return JSONResponse({'success': True})
        except Exception as e:
            return JSONResponse({'success': False, 'error': str(e)})

    @router.get("/health")
    async def check_all_health():
        """
        檢查所有交易所健康狀態

        Returns:
            {
                "all_healthy": bool,
                "ready_for_trading": bool,
                "hedging_available": bool,
                "exchanges": {
                    "STANDX": {
                        "healthy": bool,
                        "latency_ms": float,
                        "error": str or null,
                        "details": {...}
                    },
                    ...
                }
            }
        """
        try:
            # 優先使用 system_manager 的方法
            if system_manager_getter:
                system_manager = system_manager_getter()
                if system_manager and hasattr(system_manager, 'check_all_health'):
                    result = await system_manager.check_all_health()
                    return JSONResponse(result)

            # 備選：直接檢查 adapters
            adapters = adapters_getter()
            results = {}

            for name, adapter in adapters.items():
                try:
                    if hasattr(adapter, 'health_check'):
                        health = await adapter.health_check()
                        results[name] = health
                    else:
                        results[name] = {
                            "healthy": True,
                            "latency_ms": 0,
                            "error": None,
                            "details": {"note": "no health_check method"}
                        }
                except Exception as e:
                    results[name] = {
                        "healthy": False,
                        "latency_ms": 0,
                        "error": str(e),
                        "details": {}
                    }

            all_healthy = all(r.get("healthy", False) for r in results.values())

            return JSONResponse({
                "all_healthy": all_healthy,
                "ready_for_trading": all_healthy,  # 簡化邏輯
                "hedging_available": "GRVT" in results and results["GRVT"].get("healthy", False),
                "exchanges": results
            })

        except Exception as e:
            return JSONResponse({
                "all_healthy": False,
                "error": str(e),
                "exchanges": {}
            }, status_code=500)

    @router.get("/health/{exchange}")
    async def check_exchange_health(exchange: str):
        """
        檢查單一交易所健康狀態

        Args:
            exchange: 交易所名稱（如 standx, grvt）

        Returns:
            {
                "healthy": bool,
                "latency_ms": float,
                "error": str or null,
                "details": {...}
            }
        """
        try:
            adapters = adapters_getter()
            exchange_upper = exchange.upper()

            if exchange_upper not in adapters:
                return JSONResponse(
                    {"error": f"交易所 {exchange} 未配置"},
                    status_code=404
                )

            adapter = adapters[exchange_upper]

            if not hasattr(adapter, 'health_check'):
                return JSONResponse({
                    "healthy": True,
                    "latency_ms": 0,
                    "error": None,
                    "details": {"note": "no health_check method"}
                })

            health = await adapter.health_check()
            return JSONResponse(health)

        except Exception as e:
            return JSONResponse({
                "healthy": False,
                "latency_ms": 0,
                "error": str(e),
                "details": {}
            }, status_code=500)

    @router.post("/reconnect")
    async def reconnect_all_exchanges():
        """
        重新連接所有已配置的交易所

        Returns:
            {
                "success": bool,
                "results": {
                    "STANDX": {"success": bool, "error": str or null},
                    "GRVT": {"success": bool, "error": str or null}
                },
                "ready_for_trading": bool,
                "hedging_available": bool
            }
        """
        try:
            if system_manager_getter:
                system_manager = system_manager_getter()
                if system_manager and hasattr(system_manager, 'reconnect_all'):
                    result = await system_manager.reconnect_all()
                    return JSONResponse(result)

            return JSONResponse({
                "success": False,
                "error": "系統管理器不可用"
            }, status_code=500)

        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=500)

    app.include_router(router)
