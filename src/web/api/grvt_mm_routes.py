"""
GRVT 做市商 API 路由

包含:
- POST /api/grvt-mm/start - 啟動做市商
- POST /api/grvt-mm/stop - 停止做市商
- GET /api/grvt-mm/status - 獲取狀態
- GET /api/grvt-mm/positions - 獲取倉位
- GET /api/grvt-mm/config - 獲取配置
- POST /api/grvt-mm/config - 更新配置
- POST /api/grvt-mm/config/reload - 重新載入配置
"""

from decimal import Decimal
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.strategy.market_maker_executor import MarketMakerExecutor, MMConfig, ExecutorStatus
from src.strategy.hedge_engine import HedgeEngine
from src.utils.grvt_mm_config_manager import get_grvt_mm_config


router = APIRouter(prefix="/api/grvt-mm", tags=["grvt_market_maker"])


def register_grvt_mm_routes(app, dependencies):
    """
    註冊 GRVT 做市商相關路由

    Args:
        app: FastAPI 應用實例
        dependencies: 依賴項字典
    """
    adapters_getter = dependencies['adapters_getter']
    grvt_mm_executor_getter = dependencies.get('grvt_mm_executor_getter')
    grvt_mm_executor_setter = dependencies.get('grvt_mm_executor_setter')
    grvt_mm_status = dependencies.get('grvt_mm_status')
    serialize_for_json = dependencies['serialize_for_json']
    logger = dependencies['logger']

    # 如果沒有提供 GRVT 專用的 getter/setter，使用默認
    if not grvt_mm_executor_getter:
        _grvt_mm_executor = {'instance': None}

        def grvt_mm_executor_getter():
            return _grvt_mm_executor['instance']

        def grvt_mm_executor_setter(executor):
            _grvt_mm_executor['instance'] = executor

    if not grvt_mm_status:
        grvt_mm_status = {
            'running': False,
            'status': 'stopped',
            'order_size_btc': 0.01,
            'order_distance_bps': 8,
            'cancel_distance_bps': 3,
            'rebalance_distance_bps': 12,
            'max_position_btc': 1.0,
            # 策略模式 (從配置讀取預設值)
            'strategy_mode': 'rebate',
            'aggressiveness': 'aggressive',
            'post_only': True,
        }
        dependencies['grvt_mm_status'] = grvt_mm_status

    @router.post("/start")
    async def start_grvt_market_maker(request: Request):
        """啟動 GRVT 做市商"""
        try:
            # 先停止現有的執行器（防止重複啟動導致多個執行器同時運行）
            existing_executor = grvt_mm_executor_getter()
            if existing_executor:
                logger.info("停止現有的 GRVT 做市商執行器...")
                try:
                    await existing_executor.stop()
                except Exception as e:
                    logger.warning(f"停止現有執行器時發生錯誤: {e}")
                grvt_mm_executor_setter(None)

            data = await request.json()

            # 從保存的配置讀取參數（強制重新載入以確保讀取最新配置）
            config_manager = get_grvt_mm_config()
            config_manager.reload()  # 確保每次啟動都讀取最新的 YAML 配置
            saved_config = config_manager.get_dict()

            # 診斷：打印讀取的配置
            logger.info(f"[Routes] saved_config keys: {list(saved_config.keys())}")
            logger.info(f"[Routes] strategy in saved_config: {saved_config.get('strategy', 'NOT FOUND')}")

            strategy_cfg = saved_config.get('strategy', {})
            quote_cfg = saved_config.get('quote', {})
            position_cfg = saved_config.get('position', {})
            execution_cfg = saved_config.get('execution', {})
            fees_cfg = saved_config.get('fees', {})

            # 策略模式參數
            strategy_mode = strategy_cfg.get('mode', 'uptime')  # "uptime" | "rebate"
            aggressiveness = strategy_cfg.get('aggressiveness', 'moderate')  # "aggressive" | "moderate" | "conservative"

            logger.info(f"[Routes] Final: strategy_mode={strategy_mode}, aggressiveness={aggressiveness}")

            # 報價參數
            order_size = Decimal(str(data.get('order_size', position_cfg.get('order_size_btc', 0.01))))
            order_distance = int(data.get('order_distance', quote_cfg.get('order_distance_bps', 8)))
            cancel_distance = int(quote_cfg.get('cancel_distance_bps', 3))
            cancel_on_approach = quote_cfg.get('cancel_on_approach', True)
            rebalance_distance = int(quote_cfg.get('rebalance_distance_bps', 12))
            post_only = quote_cfg.get('post_only', False)
            min_spread_ticks = int(quote_cfg.get('min_spread_ticks', 2))
            max_position = Decimal(str(position_cfg.get('max_position_btc', 1.0)))
            tick_interval = int(execution_cfg.get('tick_interval_ms', 500))

            # 費率參數 (負數=收rebate, 正數=付fee)
            maker_fee_bps = Decimal(str(fees_cfg.get('maker_bps', -1)))
            taker_fee_bps = Decimal(str(fees_cfg.get('taker_bps', 3)))
            hedge_fee_bps = Decimal(str(fees_cfg.get('hedge_bps', 2)))

            adapters = adapters_getter()

            # 檢查是否有 GRVT
            if 'GRVT' not in adapters:
                return JSONResponse({'success': False, 'error': 'GRVT 未連接'})

            grvt = adapters['GRVT']
            standx = adapters.get('STANDX')  # 可選，用於對沖

            # 創建配置（GRVT 作為主交易所）
            config = MMConfig(
                symbol="BTC_USDT_Perp",       # GRVT 交易對
                hedge_symbol="BTC-USD",        # StandX 對沖交易對
                hedge_exchange="standx",       # 對沖到 StandX
                order_size_btc=order_size,
                order_distance_bps=order_distance,
                cancel_distance_bps=cancel_distance,
                rebalance_distance_bps=rebalance_distance,
                max_position_btc=max_position,
                tick_interval_ms=tick_interval,
                dry_run=False,
                # 新增：rebate 策略參數
                strategy_mode=strategy_mode,
                aggressiveness=aggressiveness,
                cancel_on_approach=cancel_on_approach,
                post_only=post_only,
                min_spread_ticks=min_spread_ticks,
                maker_fee_bps=maker_fee_bps,
                taker_fee_bps=taker_fee_bps,
                hedge_fee_bps=hedge_fee_bps,
            )

            logger.info(f"GRVT 做市商配置: strategy_mode={strategy_mode}, aggressiveness={aggressiveness}, post_only={post_only}")

            # 創建對沖引擎 (如果有 StandX)
            hedge_engine = None
            if standx:
                hedge_engine = HedgeEngine(
                    hedge_adapter=standx,  # StandX 作為對沖目標
                    standx_adapter=grvt,   # GRVT 作為來源（雖然名稱是 standx_adapter，但實際上是來源）
                )

            # 創建執行器（GRVT 作為主交易所）
            grvt_mm_executor = MarketMakerExecutor(
                standx_adapter=grvt,       # 這裡傳入 GRVT 作為主交易所
                hedge_adapter=standx,      # StandX 作為對沖交易所
                hedge_engine=hedge_engine,
                config=config,
            )

            # 如果沒有 StandX，警告但繼續
            if not standx:
                logger.warning("StandX 未連接，GRVT 做市商將不會對沖")

            # 設置回調
            async def on_status_change(status: ExecutorStatus):
                grvt_mm_status['status'] = status.value

            grvt_mm_executor.on_status_change(on_status_change)

            # 啟動
            await grvt_mm_executor.start()

            # 更新全局狀態
            grvt_mm_executor_setter(grvt_mm_executor)
            grvt_mm_status['running'] = True
            grvt_mm_status['status'] = 'running'
            grvt_mm_status['order_size_btc'] = float(order_size)
            grvt_mm_status['order_distance_bps'] = order_distance
            grvt_mm_status['cancel_distance_bps'] = cancel_distance
            grvt_mm_status['rebalance_distance_bps'] = rebalance_distance
            grvt_mm_status['max_position_btc'] = float(max_position)
            # 新增策略狀態
            grvt_mm_status['strategy_mode'] = strategy_mode
            grvt_mm_status['aggressiveness'] = aggressiveness
            grvt_mm_status['post_only'] = post_only

            logger.info(
                f"GRVT 做市商已啟動: strategy_mode={strategy_mode}, "
                f"aggressiveness={aggressiveness}, post_only={post_only}"
            )
            return JSONResponse({'success': True})

        except Exception as e:
            logger.error(f"啟動 GRVT 做市商失敗: {e}")
            return JSONResponse({'success': False, 'error': str(e)})

    @router.post("/stop")
    async def stop_grvt_market_maker():
        """停止 GRVT 做市商"""
        try:
            grvt_mm_executor = grvt_mm_executor_getter()
            if grvt_mm_executor:
                await grvt_mm_executor.stop()
                grvt_mm_executor_setter(None)

            grvt_mm_status['running'] = False
            grvt_mm_status['status'] = 'stopped'

            logger.info("GRVT 做市商已停止")
            return JSONResponse({'success': True})

        except Exception as e:
            logger.error(f"停止 GRVT 做市商失敗: {e}")
            return JSONResponse({'success': False, 'error': str(e)})

    @router.get("/status")
    async def get_grvt_mm_status():
        """獲取 GRVT 做市商狀態"""
        try:
            result = grvt_mm_status.copy()
            grvt_mm_executor = grvt_mm_executor_getter()
            if grvt_mm_executor:
                result['executor'] = serialize_for_json(grvt_mm_executor.to_dict())
            return JSONResponse(result)
        except Exception as e:
            return JSONResponse({'error': str(e)})

    @router.get("/positions")
    async def get_grvt_mm_positions():
        """獲取 GRVT 做市商實時倉位"""
        try:
            adapters = adapters_getter()
            positions = {
                'grvt': {'btc': 0, 'usdt': 0},
                'standx': {'btc': 0, 'equity': 0},
            }

            # 查詢 GRVT 倉位（主交易所）
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

            # 查詢 StandX 倉位（對沖交易所）
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

            # 計算淨敞口
            positions['net_btc'] = positions['grvt']['btc'] + positions['standx']['btc']
            positions['is_hedged'] = abs(positions['net_btc']) < 0.0001

            return JSONResponse(serialize_for_json(positions))
        except Exception as e:
            return JSONResponse({'error': str(e)})

    @router.get("/rebate-stats")
    async def get_grvt_mm_rebate_stats():
        """
        獲取 GRVT 做市商 rebate 統計 (含淨收益)

        返回：
        - maker_volume_usdt: Maker 成交額
        - taker_volume_usdt: Taker 成交額
        - rebates_received_usdt: 收到的 rebate
        - fees_paid_usdt: 付出的手續費
        - hedge_fees_usdt: 對沖手續費
        - hedge_slippage_usdt: 對沖滑點損失
        - net_profit_usdt: 淨收益 (rebate - 成本)
        - maker_ratio_pct: Maker 成交佔比
        - unknown_ratio_pct: Unknown 成交佔比 (應為 0%)
        - post_only_rejects: Post-only 被拒次數
        """
        try:
            grvt_mm_executor = grvt_mm_executor_getter()
            if not grvt_mm_executor:
                return JSONResponse({
                    'success': False,
                    'error': 'GRVT 做市商未啟動'
                })

            rebate_stats = grvt_mm_executor.state.get_rebate_stats()
            return JSONResponse({
                'success': True,
                **serialize_for_json(rebate_stats)
            })
        except Exception as e:
            logger.error(f"獲取 rebate 統計失敗: {e}")
            return JSONResponse({'success': False, 'error': str(e)})

    @router.get("/config")
    async def get_grvt_mm_config_api():
        """獲取 GRVT 做市商配置"""
        try:
            config_manager = get_grvt_mm_config()
            return JSONResponse(config_manager.get_dict())
        except Exception as e:
            return JSONResponse({'error': str(e)}, status_code=500)

    @router.post("/config")
    async def update_grvt_mm_config_api(request: Request):
        """更新 GRVT 做市商配置"""
        try:
            data = await request.json()
            config_manager = get_grvt_mm_config()
            config_manager.update(data, save=True)
            return JSONResponse({'success': True, 'config': config_manager.get_dict()})
        except Exception as e:
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    @router.post("/config/reload")
    async def reload_grvt_mm_config_api():
        """重新加載 GRVT 做市商配置"""
        try:
            config_manager = get_grvt_mm_config()
            config_manager.reload()
            return JSONResponse({'success': True, 'config': config_manager.get_dict()})
        except Exception as e:
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    app.include_router(router)
