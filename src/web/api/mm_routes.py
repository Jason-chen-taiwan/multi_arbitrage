"""
做市商 API 路由

包含:
- POST /api/mm/start - 啟動做市商
- POST /api/mm/stop - 停止做市商
- GET /api/mm/status - 獲取狀態
- GET /api/mm/positions - 獲取倉位
- GET /api/mm/config - 獲取配置
- POST /api/mm/config - 更新配置
- POST /api/mm/config/reload - 重新載入配置
"""

from decimal import Decimal
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.strategy.market_maker_executor import MarketMakerExecutor, MMConfig, ExecutorStatus
from src.strategy.hedge_engine import HedgeEngine
from src.utils.mm_config_manager import get_mm_config
from src.web.schemas import (
    MMStartRequest,
    MMStatusResponse,
    MMPositionResponse,
    MMConfigResponse,
    MMConfigUpdateRequest,
    SuccessResponse,
    ErrorResponse,
)


router = APIRouter(prefix="/api/mm", tags=["market_maker"])


def register_mm_routes(app, dependencies):
    """
    註冊做市商相關路由

    Args:
        app: FastAPI 應用實例
        dependencies: 依賴項字典
    """
    adapters_getter = dependencies['adapters_getter']
    mm_executor_getter = dependencies['mm_executor_getter']
    mm_executor_setter = dependencies['mm_executor_setter']
    mm_status = dependencies['mm_status']
    serialize_for_json = dependencies['serialize_for_json']
    logger = dependencies['logger']

    @router.post("/start", response_model=SuccessResponse, responses={500: {"model": ErrorResponse}})
    async def start_market_maker(request_data: MMStartRequest):
        """
        啟動做市商

        啟動 StandX 做市商執行器。如果已有執行器運行，會先停止它。

        - **dry_run**: 是否為模擬模式（不會實際下單）
        - **order_size**: 訂單大小（BTC），使用配置預設值如未指定
        - **order_distance**: 訂單距離（基點），使用配置預設值如未指定
        """
        try:
            # 先停止現有的執行器（防止重複啟動導致多個執行器同時運行）
            existing_executor = mm_executor_getter()
            if existing_executor:
                logger.info("停止現有的 StandX 做市商執行器...")
                try:
                    await existing_executor.stop()
                except Exception as e:
                    logger.warning(f"停止現有執行器時發生錯誤: {e}")
                mm_executor_setter(None)

            dry_run = request_data.dry_run

            # 從保存的配置讀取參數
            config_manager = get_mm_config()
            saved_config = config_manager.get_dict()
            quote_cfg = saved_config.get('quote', {})
            position_cfg = saved_config.get('position', {})
            volatility_cfg = saved_config.get('volatility', {})

            # 使用保存的配置，如果沒有則使用默認值
            order_size = Decimal(str(request_data.order_size or position_cfg.get('order_size_btc', 0.001)))
            order_distance = int(request_data.order_distance or quote_cfg.get('order_distance_bps', 8))
            cancel_distance = int(quote_cfg.get('cancel_distance_bps', 3))
            rebalance_distance = int(quote_cfg.get('rebalance_distance_bps', 12))
            max_position = Decimal(str(position_cfg.get('max_position_btc', 0.01)))

            # 硬停參數：根據 max_position 動態計算
            # hard_stop = max_position * 0.7 (70% 時硬停)
            # resume_position = max_position * 0.45 (45% 時恢復)
            hard_stop_position = max_position * Decimal("0.7")
            resume_position = max_position * Decimal("0.45")

            # 波動率參數
            volatility_window = int(volatility_cfg.get('window_sec', 2))
            volatility_threshold = float(volatility_cfg.get('threshold_bps', 5.0))
            volatility_resume = float(volatility_cfg.get('resume_threshold_bps', 4.0))
            volatility_stable = float(volatility_cfg.get('stable_seconds', 2.0))

            adapters = adapters_getter()

            # 檢查是否有 StandX
            if 'STANDX' not in adapters:
                return JSONResponse({'success': False, 'error': 'StandX 未連接'})

            standx = adapters['STANDX']
            grvt = adapters.get('GRVT')  # 可選，沒有則不對沖

            # 創建配置（使用保存的報價參數）
            config = MMConfig(
                symbol="BTC-USD",
                hedge_symbol="BTC_USDT_Perp",
                hedge_exchange="grvt",
                order_size_btc=order_size,
                order_distance_bps=order_distance,
                cancel_distance_bps=cancel_distance,
                rebalance_distance_bps=rebalance_distance,
                max_position_btc=max_position,
                # 硬停參數（根據 max_position 動態計算）
                hard_stop_position_btc=hard_stop_position,
                resume_position_btc=resume_position,
                dry_run=dry_run,
                # 波動率參數
                volatility_window_sec=volatility_window,
                volatility_threshold_bps=volatility_threshold,
                volatility_resume_threshold_bps=volatility_resume,
                volatility_stable_seconds=volatility_stable,
            )

            logger.info(
                f"做市商配置: order_size={order_size}, max_pos={max_position}, "
                f"hard_stop={hard_stop_position}, resume_pos={resume_position}"
            )
            logger.info(
                f"做市商配置: order_dist={order_distance}bps, cancel_dist={cancel_distance}bps, "
                f"rebal_dist={rebalance_distance}bps, vol_window={volatility_window}s, "
                f"vol_pause={volatility_threshold}bps, vol_resume={volatility_resume}bps"
            )

            # 創建對沖引擎 (如果有 GRVT)
            hedge_engine = None
            if grvt:
                hedge_engine = HedgeEngine(
                    hedge_adapter=grvt,
                    standx_adapter=standx,
                )

            # 創建執行器
            mm_executor = MarketMakerExecutor(
                standx_adapter=standx,
                hedge_adapter=grvt,
                hedge_engine=hedge_engine,
                config=config,
            )

            # 如果沒有 GRVT，警告但繼續
            if not grvt:
                logger.warning("GRVT 未連接，做市商將不會對沖")

            # 設置回調
            async def on_status_change(status: ExecutorStatus):
                mm_status['status'] = status.value

            mm_executor.on_status_change(on_status_change)

            # 啟動
            await mm_executor.start()

            # 更新全局狀態
            mm_executor_setter(mm_executor)
            mm_status['running'] = True
            mm_status['status'] = 'running'
            mm_status['dry_run'] = dry_run
            mm_status['order_size_btc'] = float(order_size)
            mm_status['order_distance_bps'] = order_distance
            mm_status['cancel_distance_bps'] = cancel_distance
            mm_status['rebalance_distance_bps'] = rebalance_distance
            mm_status['max_position_btc'] = float(max_position)

            logger.info(f"做市商已啟動 (dry_run={dry_run}, order_dist={order_distance}bps)")
            return JSONResponse({'success': True})

        except Exception as e:
            logger.error(f"啟動做市商失敗: {e}")
            return JSONResponse({'success': False, 'error': str(e)})

    @router.post("/stop", response_model=SuccessResponse, responses={500: {"model": ErrorResponse}})
    async def stop_market_maker():
        """
        停止做市商

        優雅地停止 StandX 做市商執行器，取消所有掛單。
        """
        try:
            mm_executor = mm_executor_getter()
            if mm_executor:
                await mm_executor.stop()
                mm_executor_setter(None)

            mm_status['running'] = False
            mm_status['status'] = 'stopped'

            logger.info("做市商已停止")
            return JSONResponse({'success': True})

        except Exception as e:
            logger.error(f"停止做市商失敗: {e}")
            return JSONResponse({'success': False, 'error': str(e)})

    @router.get("/status", response_model=MMStatusResponse)
    async def get_mm_status():
        """
        獲取做市商狀態

        返回做市商的當前運行狀態、配置參數和執行器詳細信息。
        """
        try:
            result = mm_status.copy()
            mm_executor = mm_executor_getter()
            if mm_executor:
                result['executor'] = serialize_for_json(mm_executor.to_dict())
            return JSONResponse(result)
        except Exception as e:
            return JSONResponse({'error': str(e)})

    @router.get("/positions", response_model=MMPositionResponse)
    async def get_mm_positions():
        """
        獲取做市商倉位

        從 executor state 讀取，統一資料來源。

        - 如果 executor 未運行：`status: "disconnected"`
        - 如果 executor 運行中：返回 StandX 和 GRVT 的倉位數據
        """
        import time

        try:
            mm_executor = mm_executor_getter()

            # Executor 未運行 → 返回未連接狀態
            if not mm_executor:
                return JSONResponse({
                    'status': 'disconnected',
                    'message': '做市商未啟動'
                })

            # 從 executor state 讀取倉位（統一資料來源）
            state = mm_executor.state
            standx_pos = float(state.get_standx_position())
            hedge_pos = float(state.get_hedge_position())
            last_sync = state.get_last_position_sync()
            seconds_ago = round(time.time() - last_sync, 1) if last_sync > 0 else None

            positions = {
                'status': 'connected',
                'standx': {'btc': standx_pos},
                'grvt': {'btc': hedge_pos},
                'net_btc': standx_pos + hedge_pos,
                'is_hedged': abs(standx_pos + hedge_pos) < 0.0001,
                'last_sync': last_sync,
                'seconds_ago': seconds_ago,
            }

            return JSONResponse(serialize_for_json(positions))
        except Exception as e:
            logger.error(f"獲取倉位失敗: {e}")
            return JSONResponse({'error': str(e)})

    @router.get("/config", response_model=MMConfigResponse)
    async def get_mm_config_api():
        """
        獲取做市商配置

        返回當前的做市商配置，包括報價、倉位、波動率和執行參數。
        """
        try:
            config_manager = get_mm_config()
            return JSONResponse(config_manager.get_dict())
        except Exception as e:
            return JSONResponse({'error': str(e)}, status_code=500)

    @router.post("/config")
    async def update_mm_config_api(request_data: MMConfigUpdateRequest):
        """
        更新做市商配置

        更新做市商配置並保存到檔案。支持部分更新。
        """
        try:
            config_manager = get_mm_config()
            update_data = request_data.model_dump(exclude_none=True)
            config_manager.update(update_data, save=True)
            return JSONResponse({'success': True, 'config': config_manager.get_dict()})
        except Exception as e:
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    @router.post("/config/reload", response_model=SuccessResponse)
    async def reload_mm_config_api():
        """
        重新載入做市商配置

        從檔案重新載入配置，覆蓋當前記憶體中的配置。
        """
        try:
            config_manager = get_mm_config()
            config_manager.reload()
            return JSONResponse({'success': True, 'config': config_manager.get_dict()})
        except Exception as e:
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    app.include_router(router)
