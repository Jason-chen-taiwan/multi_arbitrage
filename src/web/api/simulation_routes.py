"""
模擬比較 API 路由

包含:
- GET/POST/PUT/DELETE /api/simulation/param-sets - 參數組 CRUD
- POST /api/simulation/start - 開始模擬
- POST /api/simulation/stop - 停止模擬
- POST /api/simulation/force-stop - 強制停止
- GET /api/simulation/status - 獲取狀態
- GET /api/simulation/comparison - 即時比較
- GET /api/simulation/runs - 列出歷史運行
- GET /api/simulation/runs/{run_id} - 運行詳情
- GET /api/simulation/runs/{run_id}/comparison - 運行比較表
- DELETE /api/simulation/runs/{run_id} - 刪除運行
"""

import asyncio
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.simulation import (
    get_param_set_manager,
    SimulationRunner,
    ResultLogger,
    ComparisonEngine,
)
from src.web.schemas import (
    ParamSetResponse,
    ParamSetCreateRequest,
    ParamSetUpdateRequest,
    SimulationStartRequest,
    SimulationStartResponse,
    SimulationStatusResponse,
    SimulationRunListResponse,
    ComparisonTableResponse,
    SuccessResponse,
    ErrorResponse,
)


router = APIRouter(prefix="/api/simulation", tags=["simulation"])

# 模組級全局變量
_simulation_runner = None
_result_logger = None
_comparison_engine = None


def register_simulation_routes(app, dependencies):
    """
    註冊模擬相關路由

    Args:
        app: FastAPI 應用實例
        dependencies: 依賴項字典
    """
    global _simulation_runner, _result_logger, _comparison_engine

    adapters_getter = dependencies['adapters_getter']
    logger = dependencies['logger']

    @router.get("/param-sets", response_model=ParamSetResponse)
    async def get_simulation_param_sets():
        """
        獲取所有參數組

        返回所有已保存的模擬參數組列表。
        """
        try:
            manager = get_param_set_manager()
            return JSONResponse(manager.to_dict())
        except Exception as e:
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    @router.post("/param-sets")
    async def create_simulation_param_set(request_data: ParamSetCreateRequest):
        """
        創建新參數組

        創建一個新的模擬參數組，包含自定義配置覆蓋。
        """
        try:
            manager = get_param_set_manager()
            param_set = manager.add_param_set(request_data.model_dump(exclude_none=True), save=True)
            return JSONResponse({
                'success': True,
                'param_set': {
                    'id': param_set.id,
                    'name': param_set.name,
                    'description': param_set.description
                }
            })
        except Exception as e:
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    @router.put("/param-sets/{param_set_id}")
    async def update_simulation_param_set(param_set_id: str, request_data: ParamSetUpdateRequest):
        """
        更新參數組

        更新指定 ID 的參數組配置。
        """
        try:
            manager = get_param_set_manager()
            data = request_data.model_dump(exclude_none=True)

            # Remove old and add new with same ID
            manager.remove_param_set(param_set_id, save=False)
            data['id'] = param_set_id  # Ensure ID stays the same
            param_set = manager.add_param_set(data, save=True)

            return JSONResponse({
                'success': True,
                'param_set': {
                    'id': param_set.id,
                    'name': param_set.name,
                    'description': param_set.description
                }
            })
        except Exception as e:
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    @router.delete("/param-sets/{param_set_id}", response_model=SuccessResponse, responses={404: {"model": ErrorResponse}})
    async def delete_simulation_param_set(param_set_id: str):
        """
        刪除參數組

        從系統中刪除指定的參數組。
        """
        try:
            manager = get_param_set_manager()
            success = manager.remove_param_set(param_set_id, save=True)

            if success:
                return JSONResponse({'success': True})
            else:
                return JSONResponse({'success': False, 'error': '參數組不存在'}, status_code=404)
        except Exception as e:
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    @router.post("/start", response_model=SimulationStartResponse)
    async def start_simulation(request_data: SimulationStartRequest):
        """
        開始多參數模擬

        使用選定的參數組開始模擬運行，比較不同配置的性能。
        """
        global _simulation_runner, _result_logger, _comparison_engine

        logger.info("=== /api/simulation/start called ===")

        try:
            param_set_ids = request_data.param_set_ids
            duration_minutes = request_data.duration_minutes
            logger.info(f"Request data: param_set_ids={param_set_ids}, duration={duration_minutes}")

            if not param_set_ids:
                logger.warning("No param_set_ids provided")
                return JSONResponse({'success': False, 'error': '請選擇至少一個參數組'})

            # Check if StandX adapter is available
            adapters = adapters_getter()
            standx_adapter = adapters.get('STANDX')
            logger.info(f"StandX adapter available: {standx_adapter is not None}")
            if not standx_adapter:
                logger.warning("StandX adapter not connected")
                return JSONResponse({'success': False, 'error': 'StandX 未連接，請先連接交易所'})

            # Initialize components if needed
            if _result_logger is None:
                _result_logger = ResultLogger()
            if _comparison_engine is None:
                _comparison_engine = ComparisonEngine(_result_logger)

            # Create simulation runner
            param_set_manager = get_param_set_manager()
            _simulation_runner = SimulationRunner(
                adapter=standx_adapter,
                param_set_manager=param_set_manager,
                result_logger=_result_logger,
                symbol="BTC-USD",
                tick_interval_ms=100
            )

            # Start simulation
            run_id = await _simulation_runner.start(
                param_set_ids=param_set_ids,
                duration_minutes=duration_minutes
            )

            return JSONResponse({
                'success': True,
                'run_id': run_id,
                'param_set_ids': param_set_ids,
                'duration_minutes': duration_minutes
            })

        except Exception as e:
            logger.error(f"Failed to start simulation: {e}")
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    @router.post("/stop", response_model=SuccessResponse)
    async def stop_simulation():
        """
        停止模擬

        優雅地停止當前運行的模擬，保存結果。
        """
        global _simulation_runner

        logger.info("Stop simulation API called")

        try:
            if _simulation_runner is None:
                logger.info("simulation_runner is None")
                return JSONResponse({'success': False, 'error': '沒有模擬運行器'})

            if not _simulation_runner.is_running():
                logger.info("simulation_runner is not running")
                return JSONResponse({'success': False, 'error': '沒有正在運行的模擬'})

            logger.info("Calling simulation_runner.stop() with timeout...")

            # Add timeout to prevent hanging the web service
            try:
                results = await asyncio.wait_for(_simulation_runner.stop(), timeout=10.0)
                logger.info(f"Stop completed normally: {results}")
            except asyncio.TimeoutError:
                logger.warning("Simulation stop timed out, forcing cleanup")
                # Force cleanup
                _simulation_runner._running = False
                _simulation_runner._executors = {}
                _simulation_runner._market_feed = None
                _simulation_runner._current_run_id = None
                _simulation_runner._auto_stop_task = None
                results = {'timeout': True, 'message': '停止超時，已強制清理'}
            except asyncio.CancelledError:
                logger.warning("Simulation stop was cancelled")
                _simulation_runner._running = False
                results = {'cancelled': True}

            return JSONResponse({
                'success': True,
                'results': results
            })

        except Exception as e:
            logger.error(f"Failed to stop simulation: {e}", exc_info=True)
            # Force cleanup on error
            if _simulation_runner:
                _simulation_runner._running = False
                _simulation_runner._executors = {}
                _simulation_runner._market_feed = None
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    @router.post("/force-stop", response_model=SuccessResponse)
    async def force_stop_simulation():
        """
        強制停止模擬

        立即停止模擬，不等待任何操作完成。
        """
        global _simulation_runner

        logger.info("Force stop simulation API called")

        if _simulation_runner is None:
            return JSONResponse({'success': True, 'message': '沒有模擬運行器'})

        # Forcibly clear all state without waiting
        _simulation_runner._running = False

        # Cancel auto-stop task if exists
        if _simulation_runner._auto_stop_task:
            _simulation_runner._auto_stop_task.cancel()
            _simulation_runner._auto_stop_task = None

        # Clear executors and market feed references
        _simulation_runner._executors = {}
        _simulation_runner._market_feed = None
        _simulation_runner._current_run_id = None
        _simulation_runner._started_at = None

        logger.info("Force stop completed")
        return JSONResponse({
            'success': True,
            'message': '已強制停止模擬'
        })

    @router.get("/status", response_model=SimulationStatusResponse)
    async def get_simulation_status():
        """
        獲取模擬狀態

        返回當前模擬的運行狀態，包括進度和各參數組的實時數據。
        """
        global _simulation_runner

        if _simulation_runner is None:
            return JSONResponse({
                'running': False,
                'message': 'No simulation runner initialized'
            })

        # Run in thread pool to avoid blocking event loop (state uses locks)
        try:
            status = await asyncio.wait_for(
                asyncio.to_thread(_simulation_runner.get_live_status),
                timeout=2.0
            )
            return JSONResponse(status)
        except asyncio.TimeoutError:
            logger.warning("get_live_status timed out")
            return JSONResponse({
                'running': True,
                'timeout': True,
                'message': 'Status fetch timed out - simulation may be busy'
            })
        except Exception as e:
            logger.error(f"get_live_status error: {e}")
            return JSONResponse({
                'running': True,
                'error': str(e)
            })

    @router.get("/comparison")
    async def get_live_simulation_comparison():
        """
        獲取即時比較數據

        返回當前運行中模擬的實時參數組比較表。
        """
        global _simulation_runner

        if _simulation_runner is None or not _simulation_runner.is_running():
            return JSONResponse([])

        # Run in thread pool to avoid blocking event loop (state uses locks)
        try:
            comparison = await asyncio.wait_for(
                asyncio.to_thread(_simulation_runner.get_live_comparison),
                timeout=2.0
            )
            return JSONResponse(comparison)
        except asyncio.TimeoutError:
            logger.warning("get_live_comparison timed out")
            return JSONResponse([])
        except Exception as e:
            logger.error(f"get_live_comparison error: {e}")
            return JSONResponse([])

    @router.get("/runs", response_model=SimulationRunListResponse)
    async def list_simulation_runs():
        """
        列出所有歷史運行

        返回所有歷史模擬運行的列表。
        """
        global _comparison_engine, _result_logger

        try:
            if _result_logger is None:
                _result_logger = ResultLogger()
            if _comparison_engine is None:
                _comparison_engine = ComparisonEngine(_result_logger)

            runs = _comparison_engine.get_all_runs()
            return JSONResponse({'runs': runs})

        except Exception as e:
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    @router.get("/runs/{run_id}")
    async def get_simulation_run_details(run_id: str):
        """
        獲取特定運行的詳細結果

        返回指定運行 ID 的完整結果數據。
        """
        global _comparison_engine, _result_logger

        try:
            if _result_logger is None:
                _result_logger = ResultLogger()
            if _comparison_engine is None:
                _comparison_engine = ComparisonEngine(_result_logger)

            results = _comparison_engine.get_run_details(run_id)
            if results is None:
                return JSONResponse({'success': False, 'error': '運行記錄不存在'}, status_code=404)

            return JSONResponse(results)

        except Exception as e:
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    @router.get("/runs/{run_id}/comparison", response_model=ComparisonTableResponse)
    async def get_simulation_run_comparison(run_id: str, sort_by: str = "uptime_percentage"):
        """
        獲取運行比較表

        返回指定運行的參數組比較表和推薦結果。

        - **sort_by**: 排序欄位（uptime_percentage, total_pnl, fill_count）
        """
        global _comparison_engine, _result_logger

        try:
            if _result_logger is None:
                _result_logger = ResultLogger()
            if _comparison_engine is None:
                _comparison_engine = ComparisonEngine(_result_logger)

            table = _comparison_engine.get_comparison_table(run_id, sort_by=sort_by)
            recommendation = _comparison_engine.get_recommendation(run_id)

            return JSONResponse({
                'comparison_table': table,
                'recommendation': {
                    'param_set_id': recommendation.param_set_id,
                    'param_set_name': recommendation.param_set_name,
                    'reason': recommendation.reason,
                    'score': recommendation.score
                } if recommendation else None
            })

        except Exception as e:
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    @router.delete("/runs/{run_id}", response_model=SuccessResponse, responses={404: {"model": ErrorResponse}})
    async def delete_simulation_run(run_id: str):
        """
        刪除運行記錄

        從歷史記錄中刪除指定的運行結果。
        """
        global _result_logger

        try:
            if _result_logger is None:
                _result_logger = ResultLogger()

            success = _result_logger.delete_run(run_id)
            if success:
                return JSONResponse({'success': True})
            else:
                return JSONResponse({'success': False, 'error': '運行記錄不存在'}, status_code=404)

        except Exception as e:
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    app.include_router(router)
