"""
系統控制 API 路由

包含:
- POST /api/system/reinit - 重新初始化系統
- POST /api/control/auto-execute - 控制自動執行
- POST /api/control/live-trade - 控制實際交易
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse


router = APIRouter(tags=["control"])


def register_control_routes(app, dependencies):
    """
    註冊控制相關路由

    Args:
        app: FastAPI 應用實例
        dependencies: 依賴項字典
    """
    adapters_getter = dependencies['adapters_getter']
    executor_getter = dependencies['executor_getter']
    monitor_getter = dependencies['monitor_getter']
    system_status = dependencies['system_status']
    init_system = dependencies['init_system']
    logger = dependencies['logger']
    system_manager_getter = dependencies.get('system_manager_getter')

    @router.post("/api/system/reinit")
    async def reinit_system_api():
        """重新初始化系統 - 重新連接所有已配置的交易所"""
        try:
            logger.info("🔄 重新初始化系統...")

            # 優先使用 system_manager 的 reconnect_all 方法
            if system_manager_getter:
                system_manager = system_manager_getter()
                if system_manager and hasattr(system_manager, 'reconnect_all'):
                    result = await system_manager.reconnect_all()

                    # 構建成功/失敗訊息
                    success_exchanges = [k for k, v in result.get('results', {}).items() if v.get('success')]
                    failed_exchanges = [k for k, v in result.get('results', {}).items() if not v.get('success')]

                    if result.get('success'):
                        return JSONResponse({
                            'success': True,
                            'message': f'已連接 {len(success_exchanges)} 個交易所: {", ".join(success_exchanges)}',
                            'ready_for_trading': result.get('ready_for_trading', False),
                            'hedging_available': result.get('hedging_available', False),
                            'details': result.get('results', {})
                        })
                    else:
                        return JSONResponse({
                            'success': False,
                            'error': f'部分交易所連接失敗: {", ".join(failed_exchanges)}',
                            'connected': success_exchanges,
                            'failed': failed_exchanges,
                            'ready_for_trading': result.get('ready_for_trading', False),
                            'hedging_available': result.get('hedging_available', False),
                            'details': result.get('results', {})
                        })

            # 回退：使用舊方法
            adapters = adapters_getter()
            monitor = monitor_getter()
            executor = executor_getter()

            # 停止現有監控
            if monitor:
                await monitor.stop()
            if executor:
                await executor.stop()

            # 斷開所有現有連接
            for name, adapter in list(adapters.items()):
                if hasattr(adapter, 'disconnect'):
                    try:
                        await adapter.disconnect()
                    except:
                        pass

            # 重新初始化
            await init_system()

            adapters = adapters_getter()  # 獲取更新後的 adapters
            connected_count = len(adapters)
            if connected_count > 0:
                return JSONResponse({
                    'success': True,
                    'message': f'已連接 {connected_count} 個交易所: {", ".join(adapters.keys())}'
                })
            else:
                return JSONResponse({
                    'success': False,
                    'error': '沒有可連接的交易所，請先配置交易所'
                })

        except Exception as e:
            logger.error(f"重新初始化失敗: {e}")
            return JSONResponse({'success': False, 'error': str(e)})

    @router.post("/api/control/auto-execute")
    async def control_auto_execute(request: Request):
        """控制自動執行"""
        try:
            data = await request.json()
            enabled = data['enabled']

            executor = executor_getter()
            if executor:
                executor.enable_auto_execute = enabled
                system_status['auto_execute'] = enabled

            return JSONResponse({'success': True})
        except Exception as e:
            return JSONResponse({'success': False, 'error': str(e)})

    @router.post("/api/control/live-trade")
    async def control_live_trade(request: Request):
        """控制實際交易"""
        try:
            data = await request.json()
            enabled = data['enabled']

            executor = executor_getter()
            if executor:
                executor.dry_run = not enabled
                system_status['dry_run'] = not enabled

            return JSONResponse({'success': True})
        except Exception as e:
            return JSONResponse({'success': False, 'error': str(e)})

    app.include_router(router)
