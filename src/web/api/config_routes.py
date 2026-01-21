"""
配置 API 路由

包含:
- GET /api/config/list - 獲取所有配置
- POST /api/config/save - 保存配置
- POST /api/config/delete - 刪除配置
- GET /api/config/health - 檢查所有交易所健康狀態
- GET /api/config/health/{exchange} - 檢查單一交易所健康狀態
- POST /api/config/reconnect - 重新連接所有交易所
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.web.schemas import (
    ExchangeListResponse,
    SaveConfigRequest,
    DeleteConfigRequest,
    HealthCheckResponse,
    ExchangeHealthResponse,
    ReconnectResponse,
    SuccessResponse,
    ErrorResponse,
)


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

    @router.get("/list", response_model=ExchangeListResponse)
    async def list_configs():
        """
        獲取所有配置

        返回所有已配置的交易所，按 CEX 和 DEX 分類。
        """
        try:
            configs = config_manager.get_all_configs()
            return JSONResponse(configs)
        except Exception as e:
            return JSONResponse({'error': str(e)})

    @router.post("/save", response_model=SuccessResponse, responses={500: {"model": ErrorResponse}})
    async def save_config(request_data: SaveConfigRequest):
        """
        保存配置並動態添加到監控

        保存交易所 API 配置並立即將其添加到監控系統。
        """
        try:
            # 保存配置
            config_manager.save_config(
                request_data.exchange_name,
                request_data.exchange_type,
                request_data.config
            )

            # 動態添加到監控
            await add_exchange(request_data.exchange_name, request_data.exchange_type)

            return JSONResponse({'success': True})
        except Exception as e:
            return JSONResponse({'success': False, 'error': str(e)})

    @router.post("/delete", response_model=SuccessResponse, responses={500: {"model": ErrorResponse}})
    async def delete_config(request_data: DeleteConfigRequest):
        """
        刪除配置並從監控移除

        從系統中移除交易所配置，同時斷開其連接。
        """
        try:
            # 從監控移除
            await remove_exchange(request_data.exchange_name)

            # 刪除配置
            config_manager.delete_config(request_data.exchange_name, request_data.exchange_type)

            return JSONResponse({'success': True})
        except Exception as e:
            return JSONResponse({'success': False, 'error': str(e)})

    @router.get("/health", response_model=HealthCheckResponse)
    async def check_all_health():
        """
        檢查所有交易所健康狀態

        返回所有已連接交易所的健康狀態，包括延遲和錯誤信息。
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

    @router.get("/health/{exchange}", response_model=ExchangeHealthResponse, responses={404: {"model": ErrorResponse}})
    async def check_exchange_health(exchange: str):
        """
        檢查單一交易所健康狀態

        返回指定交易所的健康狀態、延遲和詳細信息。

        - **exchange**: 交易所名稱（如 standx, grvt）
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

    @router.get("/hedge")
    async def get_hedge_config():
        """
        獲取對沖配置

        返回當前的對沖目標設定和配置狀態。
        """
        try:
            hedge_config = config_manager.get_hedge_config()
            return JSONResponse(hedge_config)
        except Exception as e:
            return JSONResponse({'error': str(e)}, status_code=500)

    @router.post("/hedge", response_model=SuccessResponse, responses={500: {"model": ErrorResponse}})
    async def save_hedge_config(request: Request):
        """
        保存對沖配置

        設定對沖目標（grvt / standx_hedge / none）和相關憑證。

        Body:
        - hedge_target: 對沖目標 ("grvt" | "standx_hedge" | "none")
        - api_token: StandX 對沖帳戶 API Token（當 hedge_target=standx_hedge 時）
        - ed25519_private_key: StandX 對沖帳戶 Ed25519 Key（當 hedge_target=standx_hedge 時）
        """
        try:
            data = await request.json()
            config_manager.save_hedge_config(data)

            # 如果系統已運行，需要重新連接以載入新的對沖帳戶
            if logger:
                logger.info(f"對沖配置已更新: hedge_target={data.get('hedge_target')}")

            return JSONResponse({
                'success': True,
                'message': '對沖配置已保存。請重新連接交易所以啟用新配置。'
            })
        except Exception as e:
            if logger:
                logger.error(f"保存對沖配置失敗: {e}")
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    @router.post("/reconnect", response_model=ReconnectResponse, responses={500: {"model": ErrorResponse}})
    async def reconnect_all_exchanges():
        """
        重新連接所有已配置的交易所

        斷開現有連接並重新建立連接。
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
