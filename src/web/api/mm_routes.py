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

import os

from src.strategy.market_maker_executor import MarketMakerExecutor, MMConfig, ExecutorStatus
from src.strategy.hedge_engine import HedgeEngine
from src.strategy.standx_hedge_engine import StandXHedgeEngine
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
        所有交易均為實盤交易。

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

            # 根據 HEDGE_TARGET 決定對沖適配器和交易對
            hedge_target = os.getenv('HEDGE_TARGET', 'grvt')
            hedge_adapter = None
            hedge_symbol = "BTC_USDT_Perp"
            hedge_exchange = "grvt"

            if hedge_target == 'standx_hedge':
                hedge_adapter = adapters.get('STANDX_HEDGE')
                hedge_symbol = "BTC-USD"  # StandX 使用相同交易對
                hedge_exchange = "standx_hedge"
            elif hedge_target == 'grvt':
                hedge_adapter = adapters.get('GRVT')
                hedge_symbol = "BTC_USDT_Perp"
                hedge_exchange = "grvt"
            # hedge_target == 'none' 時 hedge_adapter 保持 None

            # 創建配置（使用保存的報價參數）- 全部實盤交易
            config = MMConfig(
                symbol="BTC-USD",
                hedge_symbol=hedge_symbol,
                hedge_exchange=hedge_exchange,
                order_size_btc=order_size,
                order_distance_bps=order_distance,
                cancel_distance_bps=cancel_distance,
                rebalance_distance_bps=rebalance_distance,
                max_position_btc=max_position,
                # 硬停參數（根據 max_position 動態計算）
                hard_stop_position_btc=hard_stop_position,
                resume_position_btc=resume_position,
                dry_run=False,  # 全部實盤交易
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

            # 根據 HEDGE_TARGET 創建對沖引擎
            hedge_engine = None
            if hedge_target == 'standx_hedge' and hedge_adapter:
                # StandX → StandX 對沖
                hedge_engine = StandXHedgeEngine(
                    hedge_adapter=hedge_adapter,
                    fallback_adapter=standx,  # 主帳戶作為 fallback
                )
                logger.info("使用 StandX 對沖帳戶對沖")
            elif hedge_target == 'grvt' and hedge_adapter:
                # StandX → GRVT 對沖
                hedge_engine = HedgeEngine(
                    hedge_adapter=hedge_adapter,
                    standx_adapter=standx,
                )
                logger.info("使用 GRVT 對沖")
            elif hedge_target == 'none':
                logger.info("對沖已禁用 (HEDGE_TARGET=none)")

            # 創建執行器
            mm_executor = MarketMakerExecutor(
                standx_adapter=standx,
                hedge_adapter=hedge_adapter,
                hedge_engine=hedge_engine,
                config=config,
            )

            # 如果沒有對沖適配器，警告但繼續
            if not hedge_adapter and hedge_target != 'none':
                logger.warning(f"對沖目標 {hedge_target} 未連接，做市商將不會對沖")

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
            mm_status['hedge_target'] = hedge_target
            mm_status['order_size_btc'] = float(order_size)
            mm_status['order_distance_bps'] = order_distance
            mm_status['cancel_distance_bps'] = cancel_distance
            mm_status['rebalance_distance_bps'] = rebalance_distance
            mm_status['max_position_btc'] = float(max_position)

            logger.info(f"做市商已啟動 (實盤交易, hedge_target={hedge_target}, order_dist={order_distance}bps)")
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

    @router.post("/runtime/hedge", response_model=SuccessResponse, responses={500: {"model": ErrorResponse}})
    async def set_hedge_enabled(request: Request):
        """
        運行時切換對沖開關

        Body:
        - enabled: bool - 是否啟用對沖
        """
        try:
            data = await request.json()
            enabled = data.get('enabled', True)

            mm_executor = mm_executor_getter()
            if not mm_executor:
                return JSONResponse({'success': False, 'error': '做市商未啟動'})

            mm_executor.set_hedge_enabled(enabled)
            logger.info(f"對沖開關已設置為: {enabled}")
            return JSONResponse({
                'success': True,
                'hedge_enabled': enabled
            })
        except Exception as e:
            logger.error(f"設置對沖開關失敗: {e}")
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    @router.post("/runtime/instant-close", response_model=SuccessResponse, responses={500: {"model": ErrorResponse}})
    async def set_instant_close_enabled(request: Request):
        """
        運行時切換即時平倉開關

        Body:
        - enabled: bool - 是否啟用即時平倉（成交後立即市價平倉）
        """
        try:
            data = await request.json()
            enabled = data.get('enabled', False)

            mm_executor = mm_executor_getter()
            if not mm_executor:
                return JSONResponse({'success': False, 'error': '做市商未啟動'})

            mm_executor.set_instant_close_enabled(enabled)
            logger.info(f"即時平倉開關已設置為: {enabled}")
            return JSONResponse({
                'success': True,
                'instant_close_enabled': enabled
            })
        except Exception as e:
            logger.error(f"設置即時平倉開關失敗: {e}")
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    @router.get("/runtime/controls")
    async def get_runtime_controls():
        """
        獲取運行時控制開關狀態
        """
        try:
            mm_executor = mm_executor_getter()
            if not mm_executor:
                return JSONResponse({
                    'running': False,
                    'hedge_enabled': False,
                    'instant_close_enabled': False
                })

            return JSONResponse({
                'running': True,
                'hedge_enabled': mm_executor.is_hedge_enabled(),
                'instant_close_enabled': mm_executor.is_instant_close_enabled()
            })
        except Exception as e:
            logger.error(f"獲取運行時控制失敗: {e}")
            return JSONResponse({'error': str(e)}, status_code=500)

    @router.post("/close-positions", response_model=SuccessResponse, responses={500: {"model": ErrorResponse}})
    async def close_all_positions(request: Request):
        """
        即時市價平倉

        使用市價單平掉指定帳戶的所有倉位。

        Body:
        - account: "main" | "hedge" | "both"
        """
        try:
            data = await request.json()
            account = data.get('account', 'both')
            adapters = adapters_getter()

            results = {}
            symbol = "BTC-USD"

            # 平掉主帳戶倉位
            if account in ('main', 'both') and 'STANDX' in adapters:
                standx = adapters['STANDX']
                try:
                    positions = await standx.get_positions(symbol)
                    for pos in positions:
                        if pos.symbol == symbol and pos.size > 0:
                            close_side = "sell" if pos.side == "long" else "buy"
                            order = await standx.place_order(
                                symbol=symbol,
                                side=close_side,
                                order_type="market",
                                quantity=pos.size,
                            )
                            results['main'] = {
                                'success': True,
                                'closed_size': float(pos.size),
                                'side': close_side,
                                'order_id': getattr(order, 'order_id', None)
                            }
                            logger.info(f"主帳戶平倉: {close_side} {pos.size} BTC")
                            break
                    else:
                        results['main'] = {'success': True, 'closed_size': 0, 'message': '無倉位'}
                except Exception as e:
                    results['main'] = {'success': False, 'error': str(e)}
                    logger.error(f"主帳戶平倉失敗: {e}")

            # 平掉對沖帳戶倉位
            hedge_target = os.getenv('HEDGE_TARGET', 'grvt')
            hedge_key = 'STANDX_HEDGE' if hedge_target == 'standx_hedge' else 'GRVT'

            if account in ('hedge', 'both') and hedge_key in adapters:
                hedge_adapter = adapters[hedge_key]
                hedge_symbol = symbol if hedge_target == 'standx_hedge' else "BTC_USDT_Perp"
                try:
                    positions = await hedge_adapter.get_positions(hedge_symbol)
                    for pos in positions:
                        if pos.symbol == hedge_symbol and pos.size > 0:
                            close_side = "sell" if pos.side == "long" else "buy"
                            order = await hedge_adapter.place_order(
                                symbol=hedge_symbol,
                                side=close_side,
                                order_type="market",
                                quantity=pos.size,
                            )
                            results['hedge'] = {
                                'success': True,
                                'closed_size': float(pos.size),
                                'side': close_side,
                                'order_id': getattr(order, 'order_id', None)
                            }
                            logger.info(f"對沖帳戶平倉: {close_side} {pos.size}")
                            break
                    else:
                        results['hedge'] = {'success': True, 'closed_size': 0, 'message': '無倉位'}
                except Exception as e:
                    results['hedge'] = {'success': False, 'error': str(e)}
                    logger.error(f"對沖帳戶平倉失敗: {e}")

            success = all(r.get('success', False) for r in results.values()) if results else False
            return JSONResponse({
                'success': success,
                'results': results
            })
        except Exception as e:
            logger.error(f"平倉失敗: {e}")
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    app.include_router(router)
