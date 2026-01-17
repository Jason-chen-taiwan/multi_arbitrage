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

    @router.post("/start")
    async def start_market_maker(request: Request):
        """啟動做市商"""
        try:
            data = await request.json()
            dry_run = data.get('dry_run', True)

            # 從保存的配置讀取參數
            config_manager = get_mm_config()
            saved_config = config_manager.get_dict()
            quote_cfg = saved_config.get('quote', {})
            position_cfg = saved_config.get('position', {})

            # 使用保存的配置，如果沒有則使用默認值
            order_size = Decimal(str(data.get('order_size', position_cfg.get('order_size_btc', 0.001))))
            order_distance = int(data.get('order_distance', quote_cfg.get('order_distance_bps', 8)))
            cancel_distance = int(quote_cfg.get('cancel_distance_bps', 3))
            rebalance_distance = int(quote_cfg.get('rebalance_distance_bps', 12))
            max_position = Decimal(str(position_cfg.get('max_position_btc', 0.01)))

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
                dry_run=dry_run,
            )

            logger.info(f"做市商配置: order_dist={order_distance}bps, cancel_dist={cancel_distance}bps, rebal_dist={rebalance_distance}bps")

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

    @router.post("/stop")
    async def stop_market_maker():
        """停止做市商"""
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

    @router.get("/status")
    async def get_mm_status():
        """獲取做市商狀態"""
        try:
            result = mm_status.copy()
            mm_executor = mm_executor_getter()
            if mm_executor:
                result['executor'] = serialize_for_json(mm_executor.to_dict())
            return JSONResponse(result)
        except Exception as e:
            return JSONResponse({'error': str(e)})

    @router.get("/positions")
    async def get_mm_positions():
        """獲取做市商實時倉位"""
        try:
            adapters = adapters_getter()
            positions = {
                'standx': {'btc': 0, 'equity': 0},
                'grvt': {'btc': 0, 'usdt': 0},
            }

            # 查詢 StandX 倉位
            if 'STANDX' in adapters:
                try:
                    standx = adapters['STANDX']
                    standx_positions = await standx.get_positions('BTC-USD')
                    for pos in standx_positions:
                        if 'BTC' in pos.symbol:
                            qty = float(pos.size)
                            if pos.side == 'short':
                                qty = -qty
                            positions['standx']['btc'] = qty

                    # 查詢餘額
                    balance = await standx.get_balance()
                    positions['standx']['equity'] = float(balance.equity)
                except Exception as e:
                    logger.warning(f"查詢 StandX 倉位失敗: {e}")

            # 查詢 GRVT 倉位
            if 'GRVT' in adapters:
                try:
                    grvt = adapters['GRVT']
                    grvt_positions = await grvt.get_positions('BTC_USDT_Perp')
                    for pos in grvt_positions:
                        if 'BTC' in pos.symbol:
                            qty = float(pos.size)
                            if pos.side == 'short':
                                qty = -qty
                            positions['grvt']['btc'] = qty

                    # 查詢餘額
                    balance = await grvt.get_balance()
                    positions['grvt']['usdt'] = float(balance.available_balance) if balance else 0
                except Exception as e:
                    logger.warning(f"查詢 GRVT 倉位失敗: {e}")

            # 計算淨敞口
            positions['net_btc'] = positions['standx']['btc'] + positions['grvt']['btc']
            positions['is_hedged'] = abs(positions['net_btc']) < 0.0001

            return JSONResponse(serialize_for_json(positions))
        except Exception as e:
            return JSONResponse({'error': str(e)})

    @router.get("/config")
    async def get_mm_config_api():
        """獲取做市商配置"""
        try:
            config_manager = get_mm_config()
            return JSONResponse(config_manager.get_dict())
        except Exception as e:
            return JSONResponse({'error': str(e)}, status_code=500)

    @router.post("/config")
    async def update_mm_config_api(request: Request):
        """更新做市商配置"""
        try:
            data = await request.json()
            config_manager = get_mm_config()
            config_manager.update(data, save=True)
            return JSONResponse({'success': True, 'config': config_manager.get_dict()})
        except Exception as e:
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    @router.post("/config/reload")
    async def reload_mm_config_api():
        """重新加載做市商配置"""
        try:
            config_manager = get_mm_config()
            config_manager.reload()
            return JSONResponse({'success': True, 'config': config_manager.get_dict()})
        except Exception as e:
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    app.include_router(router)
