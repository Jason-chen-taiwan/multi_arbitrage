"""
帳號池 + 策略 API 路由 (v2)

分為兩組獨立的 API：

帳號池管理 (Account Pool):
- GET    /api/accounts                    - 列出所有帳號
- POST   /api/accounts                    - 新增帳號
- PUT    /api/accounts/{account_id}       - 更新帳號
- DELETE /api/accounts/{account_id}       - 刪除帳號

策略管理 (Strategies):
- GET    /api/strategies                  - 列出所有策略
- POST   /api/strategies                  - 新增策略
- PUT    /api/strategies/{strategy_id}    - 更新策略
- DELETE /api/strategies/{strategy_id}    - 刪除策略

策略控制:
- POST   /api/strategies/{strategy_id}/start  - 啟動策略
- POST   /api/strategies/{strategy_id}/stop   - 停止策略
- POST   /api/strategies/start-all            - 啟動所有策略
- POST   /api/strategies/stop-all             - 停止所有策略
- GET    /api/strategies/summary              - 取得彙總狀態
"""

import logging
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.config.account_config import (
    AccountPoolManager,
    AccountConfig,
    StrategyConfig,
    ProxyConfig,
    TradingConfig,
)

logger = logging.getLogger(__name__)

# 建立兩個獨立的 router
accounts_router = APIRouter(prefix="/api/accounts", tags=["accounts"])
strategies_router = APIRouter(prefix="/api/strategies", tags=["strategies"])


# ==================== Pydantic 模型 ====================

# ----- 共用模型 -----

class ProxyConfigModel(BaseModel):
    url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


class TradingConfigModel(BaseModel):
    symbol: str = "BTC-USD"
    order_size_btc: str = "0.01"
    max_position_btc: str = "0.05"
    order_distance_bps: int = 8
    hard_stop_position_btc: Optional[str] = None


# ----- 帳號 API 模型 -----

class CreateAccountRequest(BaseModel):
    """新增帳號請求"""
    id: str = Field(..., description="帳號 ID（唯一標識）")
    name: str = Field(..., description="帳號名稱")
    exchange: str = Field(default="standx", description="交易所類型")
    api_token: str = Field(..., description="API Token")
    ed25519_private_key: str = Field(..., description="Ed25519 私鑰")
    proxy: Optional[ProxyConfigModel] = None


class UpdateAccountRequest(BaseModel):
    """更新帳號請求"""
    name: Optional[str] = None
    exchange: Optional[str] = None
    api_token: Optional[str] = None
    ed25519_private_key: Optional[str] = None
    proxy: Optional[ProxyConfigModel] = None


class AccountResponse(BaseModel):
    """帳號響應"""
    id: str
    name: str
    exchange: str
    has_credentials: bool
    has_proxy: bool
    used_by_strategies: List[str] = []  # 使用此帳號的策略 ID 列表


class AccountListResponse(BaseModel):
    """帳號列表響應"""
    accounts: List[AccountResponse]
    total: int


# ----- 策略 API 模型 -----

class CreateStrategyRequest(BaseModel):
    """新增策略請求"""
    id: str = Field(..., description="策略 ID（唯一標識）")
    name: str = Field(..., description="策略名稱")
    enabled: bool = True
    main_account_id: str = Field(..., description="主帳號 ID（從帳號池選擇）")
    hedge_account_id: str = Field(..., description="對沖帳號 ID（從帳號池選擇）")
    trading: TradingConfigModel


class UpdateStrategyRequest(BaseModel):
    """更新策略請求"""
    name: Optional[str] = None
    enabled: Optional[bool] = None
    main_account_id: Optional[str] = None
    hedge_account_id: Optional[str] = None
    trading: Optional[TradingConfigModel] = None


class StrategyResponse(BaseModel):
    """策略響應"""
    id: str
    name: str
    enabled: bool
    main_account_id: str
    main_account_name: str
    hedge_account_id: str
    hedge_account_name: str
    trading: TradingConfigModel
    status: Optional[Dict] = None  # 運行時狀態


class StrategyListResponse(BaseModel):
    """策略列表響應"""
    strategies: List[StrategyResponse]
    total: int


# ==================== 路由註冊 ====================

def register_accounts_routes(app, dependencies):
    """
    註冊帳號池 + 策略相關路由

    Args:
        app: FastAPI 應用實例
        dependencies: 依賴項字典
    """
    system_manager_getter = dependencies.get('system_manager_getter')

    def get_account_pool() -> AccountPoolManager:
        """取得帳號池管理器"""
        project_root = Path(__file__).parent.parent.parent.parent
        config_path = project_root / "config" / "accounts.yaml"
        return AccountPoolManager(config_path)

    # ==================== 帳號池 API ====================

    @accounts_router.get("")
    async def list_accounts():
        """
        列出所有帳號

        返回帳號池中的所有帳號，以及各帳號被哪些策略使用。
        """
        try:
            pool = get_account_pool()
            accounts, strategies = pool.load()

            # 建立帳號到策略的映射
            account_usage: Dict[str, List[str]] = {}
            for strategy in strategies:
                for acc_id in [strategy.main_account_id, strategy.hedge_account_id]:
                    if acc_id not in account_usage:
                        account_usage[acc_id] = []
                    if strategy.id not in account_usage[acc_id]:
                        account_usage[acc_id].append(strategy.id)

            response_accounts = []
            for acc in accounts:
                response_accounts.append(AccountResponse(
                    id=acc.id,
                    name=acc.name,
                    exchange=acc.exchange,
                    has_credentials=bool(acc.api_token and acc.ed25519_private_key),
                    has_proxy=acc.proxy is not None and bool(acc.proxy.url),
                    used_by_strategies=account_usage.get(acc.id, []),
                ))

            return JSONResponse({
                'accounts': [a.model_dump() for a in response_accounts],
                'total': len(response_accounts),
            })

        except Exception as e:
            logger.error(f"列出帳號失敗: {e}")
            return JSONResponse({'error': str(e)}, status_code=500)

    @accounts_router.post("")
    async def create_account(req: CreateAccountRequest):
        """
        新增帳號到帳號池

        新增一個獨立的帳號配置。之後可以在策略中選擇此帳號作為主帳號或對沖帳號。
        """
        try:
            pool = get_account_pool()

            # 檢查 ID 是否已存在
            existing = pool.get_account(req.id)
            if existing:
                return JSONResponse(
                    {'success': False, 'error': f'帳號 ID "{req.id}" 已存在'},
                    status_code=400
                )

            # 建立帳號配置
            proxy = None
            if req.proxy and req.proxy.url:
                proxy = ProxyConfig(
                    url=req.proxy.url,
                    username=req.proxy.username,
                    password=req.proxy.password,
                )

            account = AccountConfig(
                id=req.id,
                name=req.name,
                exchange=req.exchange,
                api_token=req.api_token,
                ed25519_private_key=req.ed25519_private_key,
                proxy=proxy,
            )

            # 驗證
            if not account.is_valid():
                return JSONResponse(
                    {'success': False, 'error': '帳號配置無效，請檢查 API Token 和 Ed25519 Key'},
                    status_code=400
                )

            # 保存
            success = pool.add_account(account)

            if success:
                logger.info(f"新增帳號: {req.name} (ID: {req.id})")
                return JSONResponse({
                    'success': True,
                    'message': '帳號已新增到帳號池。',
                    'account_id': req.id,
                })
            else:
                return JSONResponse(
                    {'success': False, 'error': '保存失敗'},
                    status_code=500
                )

        except Exception as e:
            logger.error(f"新增帳號失敗: {e}")
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    @accounts_router.get("/{account_id}")
    async def get_account(account_id: str):
        """
        取得特定帳號

        返回指定帳號的配置資訊（不包含敏感的憑證）。
        """
        try:
            pool = get_account_pool()
            account = pool.get_account(account_id)

            if not account:
                return JSONResponse(
                    {'error': f'帳號 "{account_id}" 不存在'},
                    status_code=404
                )

            # 取得使用此帳號的策略
            _, strategies = pool.load()
            used_by = []
            for strategy in strategies:
                if account_id in [strategy.main_account_id, strategy.hedge_account_id]:
                    used_by.append(strategy.id)

            response = AccountResponse(
                id=account.id,
                name=account.name,
                exchange=account.exchange,
                has_credentials=bool(account.api_token and account.ed25519_private_key),
                has_proxy=account.proxy is not None and bool(account.proxy.url),
                used_by_strategies=used_by,
            )

            return JSONResponse(response.model_dump())

        except Exception as e:
            logger.error(f"取得帳號失敗: {e}")
            return JSONResponse({'error': str(e)}, status_code=500)

    @accounts_router.put("/{account_id}")
    async def update_account(account_id: str, req: UpdateAccountRequest):
        """
        更新帳號

        更新指定帳號的配置。如果帳號正被策略使用，可能需要重啟策略才會生效。
        """
        try:
            pool = get_account_pool()
            existing = pool.get_account(account_id)

            if not existing:
                return JSONResponse(
                    {'error': f'帳號 "{account_id}" 不存在'},
                    status_code=404
                )

            # 更新欄位
            if req.name is not None:
                existing.name = req.name
            if req.exchange is not None:
                existing.exchange = req.exchange
            if req.api_token is not None:
                existing.api_token = req.api_token
            if req.ed25519_private_key is not None:
                existing.ed25519_private_key = req.ed25519_private_key
            if req.proxy is not None:
                if req.proxy.url:
                    existing.proxy = ProxyConfig(
                        url=req.proxy.url,
                        username=req.proxy.username,
                        password=req.proxy.password,
                    )
                else:
                    existing.proxy = None

            # 保存
            success = pool.update_account(existing)

            if success:
                logger.info(f"更新帳號: {account_id}")
                return JSONResponse({
                    'success': True,
                    'message': '帳號已更新。如果帳號正被使用，請重啟相關策略以套用新配置。',
                })
            else:
                return JSONResponse(
                    {'success': False, 'error': '更新失敗'},
                    status_code=500
                )

        except Exception as e:
            logger.error(f"更新帳號失敗: {e}")
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    @accounts_router.delete("/{account_id}")
    async def delete_account(account_id: str):
        """
        刪除帳號

        刪除指定帳號。如果帳號正被策略使用，將無法刪除。
        """
        try:
            pool = get_account_pool()

            success, message = pool.delete_account(account_id)

            if success:
                logger.info(f"刪除帳號: {account_id}")
                return JSONResponse({
                    'success': True,
                    'message': '帳號已刪除。',
                })
            else:
                status_code = 404 if "不存在" in message else 400
                return JSONResponse(
                    {'success': False, 'error': message},
                    status_code=status_code
                )

        except Exception as e:
            logger.error(f"刪除帳號失敗: {e}")
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    # ==================== 策略 API ====================

    @strategies_router.get("")
    async def list_strategies():
        """
        列出所有策略

        返回所有已配置的策略及其運行狀態。
        """
        try:
            pool = get_account_pool()
            accounts, strategies = pool.load()

            # 建立帳號 ID 到名稱的映射
            account_names = {acc.id: acc.name for acc in accounts}

            # 取得運行時狀態
            system_manager = system_manager_getter() if system_manager_getter else None

            response_strategies = []
            for strategy in strategies:
                # 取得運行時狀態
                status = None
                if system_manager and strategy.id in system_manager.running_strategies:
                    runtime_strategy = system_manager.running_strategies[strategy.id]
                    status = runtime_strategy.get('status', {})

                response_strategies.append(StrategyResponse(
                    id=strategy.id,
                    name=strategy.name,
                    enabled=strategy.enabled,
                    main_account_id=strategy.main_account_id,
                    main_account_name=account_names.get(strategy.main_account_id, "未知帳號"),
                    hedge_account_id=strategy.hedge_account_id,
                    hedge_account_name=account_names.get(strategy.hedge_account_id, "未知帳號"),
                    trading=TradingConfigModel(
                        symbol=strategy.trading.symbol,
                        order_size_btc=str(strategy.trading.order_size_btc),
                        max_position_btc=str(strategy.trading.max_position_btc),
                        order_distance_bps=strategy.trading.order_distance_bps,
                        hard_stop_position_btc=str(strategy.trading.hard_stop_position_btc)
                        if strategy.trading.hard_stop_position_btc else None,
                    ),
                    status=status,
                ))

            return JSONResponse({
                'strategies': [s.model_dump() for s in response_strategies],
                'total': len(response_strategies),
            })

        except Exception as e:
            logger.error(f"列出策略失敗: {e}")
            return JSONResponse({'error': str(e)}, status_code=500)

    @strategies_router.post("")
    async def create_strategy(req: CreateStrategyRequest):
        """
        新增策略

        從帳號池選擇主帳號和對沖帳號來建立新策略。
        """
        try:
            pool = get_account_pool()

            # 檢查 ID 是否已存在
            existing = pool.get_strategy(req.id)
            if existing:
                return JSONResponse(
                    {'success': False, 'error': f'策略 ID "{req.id}" 已存在'},
                    status_code=400
                )

            # 驗證帳號是否存在
            main_account = pool.get_account(req.main_account_id)
            if not main_account:
                return JSONResponse(
                    {'success': False, 'error': f'主帳號 "{req.main_account_id}" 不存在'},
                    status_code=400
                )

            hedge_account = pool.get_account(req.hedge_account_id)
            if not hedge_account:
                return JSONResponse(
                    {'success': False, 'error': f'對沖帳號 "{req.hedge_account_id}" 不存在'},
                    status_code=400
                )

            # 建立策略配置
            trading = TradingConfig(
                symbol=req.trading.symbol,
                order_size_btc=Decimal(req.trading.order_size_btc),
                max_position_btc=Decimal(req.trading.max_position_btc),
                order_distance_bps=req.trading.order_distance_bps,
                hard_stop_position_btc=Decimal(req.trading.hard_stop_position_btc)
                if req.trading.hard_stop_position_btc else None,
            )

            strategy = StrategyConfig(
                id=req.id,
                name=req.name,
                enabled=req.enabled,
                main_account_id=req.main_account_id,
                hedge_account_id=req.hedge_account_id,
                trading=trading,
            )

            # 保存
            success, message = pool.add_strategy(strategy)

            if success:
                logger.info(f"新增策略: {req.name} (ID: {req.id})")
                return JSONResponse({
                    'success': True,
                    'message': '策略已新增。',
                    'strategy_id': req.id,
                })
            else:
                return JSONResponse(
                    {'success': False, 'error': message},
                    status_code=400
                )

        except Exception as e:
            logger.error(f"新增策略失敗: {e}")
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    @strategies_router.get("/{strategy_id}")
    async def get_strategy(strategy_id: str):
        """
        取得特定策略

        返回指定策略的配置和運行狀態。
        """
        try:
            pool = get_account_pool()
            strategy = pool.get_strategy(strategy_id)

            if not strategy:
                return JSONResponse(
                    {'error': f'策略 "{strategy_id}" 不存在'},
                    status_code=404
                )

            # 取得帳號名稱
            accounts, _ = pool.load()
            account_names = {acc.id: acc.name for acc in accounts}

            # 取得運行時狀態
            status = None
            system_manager = system_manager_getter() if system_manager_getter else None
            if system_manager and strategy_id in system_manager.running_strategies:
                runtime_strategy = system_manager.running_strategies[strategy_id]
                status = runtime_strategy.get('status', {})

            response = StrategyResponse(
                id=strategy.id,
                name=strategy.name,
                enabled=strategy.enabled,
                main_account_id=strategy.main_account_id,
                main_account_name=account_names.get(strategy.main_account_id, "未知帳號"),
                hedge_account_id=strategy.hedge_account_id,
                hedge_account_name=account_names.get(strategy.hedge_account_id, "未知帳號"),
                trading=TradingConfigModel(
                    symbol=strategy.trading.symbol,
                    order_size_btc=str(strategy.trading.order_size_btc),
                    max_position_btc=str(strategy.trading.max_position_btc),
                    order_distance_bps=strategy.trading.order_distance_bps,
                    hard_stop_position_btc=str(strategy.trading.hard_stop_position_btc)
                    if strategy.trading.hard_stop_position_btc else None,
                ),
                status=status,
            )

            return JSONResponse(response.model_dump())

        except Exception as e:
            logger.error(f"取得策略失敗: {e}")
            return JSONResponse({'error': str(e)}, status_code=500)

    @strategies_router.put("/{strategy_id}")
    async def update_strategy(strategy_id: str, req: UpdateStrategyRequest):
        """
        更新策略

        更新指定策略的配置。如果策略正在運行，可能需要重啟才會生效。
        """
        try:
            pool = get_account_pool()
            existing = pool.get_strategy(strategy_id)

            if not existing:
                return JSONResponse(
                    {'error': f'策略 "{strategy_id}" 不存在'},
                    status_code=404
                )

            # 更新欄位
            if req.name is not None:
                existing.name = req.name
            if req.enabled is not None:
                existing.enabled = req.enabled

            if req.main_account_id is not None:
                # 驗證帳號是否存在
                main_account = pool.get_account(req.main_account_id)
                if not main_account:
                    return JSONResponse(
                        {'success': False, 'error': f'主帳號 "{req.main_account_id}" 不存在'},
                        status_code=400
                    )
                existing.main_account_id = req.main_account_id

            if req.hedge_account_id is not None:
                # 驗證帳號是否存在
                hedge_account = pool.get_account(req.hedge_account_id)
                if not hedge_account:
                    return JSONResponse(
                        {'success': False, 'error': f'對沖帳號 "{req.hedge_account_id}" 不存在'},
                        status_code=400
                    )
                existing.hedge_account_id = req.hedge_account_id

            if req.trading is not None:
                existing.trading.symbol = req.trading.symbol
                existing.trading.order_size_btc = Decimal(req.trading.order_size_btc)
                existing.trading.max_position_btc = Decimal(req.trading.max_position_btc)
                existing.trading.order_distance_bps = req.trading.order_distance_bps
                if req.trading.hard_stop_position_btc:
                    existing.trading.hard_stop_position_btc = Decimal(req.trading.hard_stop_position_btc)
                else:
                    existing.trading.hard_stop_position_btc = None

            # 保存
            success = pool.update_strategy(existing)

            if success:
                logger.info(f"更新策略: {strategy_id}")
                return JSONResponse({
                    'success': True,
                    'message': '策略已更新。如果策略正在運行，請重啟以套用新配置。',
                })
            else:
                return JSONResponse(
                    {'success': False, 'error': '更新失敗'},
                    status_code=500
                )

        except Exception as e:
            logger.error(f"更新策略失敗: {e}")
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    @strategies_router.delete("/{strategy_id}")
    async def delete_strategy(strategy_id: str):
        """
        刪除策略

        刪除指定策略。如果策略正在運行，需要先停止。
        """
        try:
            # 檢查是否正在運行
            system_manager = system_manager_getter() if system_manager_getter else None
            if system_manager and strategy_id in system_manager.running_strategies:
                runtime_strategy = system_manager.running_strategies[strategy_id]
                if runtime_strategy.get('status', {}).get('running'):
                    return JSONResponse(
                        {'success': False, 'error': '策略正在運行中，請先停止'},
                        status_code=400
                    )

            pool = get_account_pool()
            success = pool.delete_strategy(strategy_id)

            if success:
                logger.info(f"刪除策略: {strategy_id}")
                return JSONResponse({
                    'success': True,
                    'message': '策略已刪除。',
                })
            else:
                return JSONResponse(
                    {'success': False, 'error': f'策略 "{strategy_id}" 不存在'},
                    status_code=404
                )

        except Exception as e:
            logger.error(f"刪除策略失敗: {e}")
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    # ==================== 策略控制 API ====================

    @strategies_router.post("/{strategy_id}/start")
    async def start_strategy(strategy_id: str):
        """
        啟動策略

        啟動指定策略的做市功能。
        """
        try:
            system_manager = system_manager_getter() if system_manager_getter else None
            if not system_manager:
                return JSONResponse(
                    {'success': False, 'error': '系統管理器不可用'},
                    status_code=500
                )

            # 檢查策略是否存在於配置中
            pool = get_account_pool()
            strategy = pool.get_strategy(strategy_id)
            if not strategy:
                return JSONResponse(
                    {'success': False, 'error': f'策略 "{strategy_id}" 不存在'},
                    status_code=404
                )

            if not strategy.enabled:
                return JSONResponse(
                    {'success': False, 'error': f'策略 "{strategy_id}" 已停用，請先啟用'},
                    status_code=400
                )

            success = await system_manager.start_strategy(strategy_id)

            if success:
                return JSONResponse({
                    'success': True,
                    'message': f'策略 {strategy_id} 已啟動',
                })
            else:
                return JSONResponse(
                    {'success': False, 'error': '啟動失敗'},
                    status_code=500
                )

        except Exception as e:
            logger.error(f"啟動策略失敗: {e}")
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    @strategies_router.post("/{strategy_id}/stop")
    async def stop_strategy(strategy_id: str):
        """
        停止策略

        停止指定策略的做市功能。
        """
        try:
            system_manager = system_manager_getter() if system_manager_getter else None
            if not system_manager:
                return JSONResponse(
                    {'success': False, 'error': '系統管理器不可用'},
                    status_code=500
                )

            if strategy_id not in system_manager.running_strategies:
                return JSONResponse(
                    {'success': False, 'error': f'策略 "{strategy_id}" 未在運行'},
                    status_code=404
                )

            success = await system_manager.stop_strategy(strategy_id)

            if success:
                return JSONResponse({
                    'success': True,
                    'message': f'策略 {strategy_id} 已停止',
                })
            else:
                return JSONResponse(
                    {'success': False, 'error': '停止失敗'},
                    status_code=500
                )

        except Exception as e:
            logger.error(f"停止策略失敗: {e}")
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    @strategies_router.post("/start-all")
    async def start_all_strategies():
        """
        啟動所有策略

        啟動所有已啟用的策略。
        """
        try:
            system_manager = system_manager_getter() if system_manager_getter else None
            if not system_manager:
                return JSONResponse(
                    {'success': False, 'error': '系統管理器不可用'},
                    status_code=500
                )

            results = await system_manager.start_all_strategies()

            success_count = sum(1 for v in results.values() if v)
            total_count = len(results)

            return JSONResponse({
                'success': success_count == total_count,
                'message': f'已啟動 {success_count}/{total_count} 個策略',
                'results': results,
            })

        except Exception as e:
            logger.error(f"啟動所有策略失敗: {e}")
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    @strategies_router.post("/stop-all")
    async def stop_all_strategies():
        """
        停止所有策略

        停止所有正在運行的策略。
        """
        try:
            system_manager = system_manager_getter() if system_manager_getter else None
            if not system_manager:
                return JSONResponse(
                    {'success': False, 'error': '系統管理器不可用'},
                    status_code=500
                )

            results = await system_manager.stop_all_strategies()

            success_count = sum(1 for v in results.values() if v)
            total_count = len(results)

            return JSONResponse({
                'success': success_count == total_count,
                'message': f'已停止 {success_count}/{total_count} 個策略',
                'results': results,
            })

        except Exception as e:
            logger.error(f"停止所有策略失敗: {e}")
            return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

    @strategies_router.get("/summary")
    async def get_strategies_summary():
        """
        取得彙總狀態

        返回所有策略的彙總狀態，包括總 PnL、總倉位等。
        """
        try:
            system_manager = system_manager_getter() if system_manager_getter else None
            if not system_manager:
                return JSONResponse(
                    {'error': '系統管理器不可用'},
                    status_code=500
                )

            summary = system_manager.get_strategies_summary()
            return JSONResponse(summary)

        except Exception as e:
            logger.error(f"取得彙總狀態失敗: {e}")
            return JSONResponse({'error': str(e)}, status_code=500)

    @strategies_router.get("/{strategy_id}/status")
    async def get_strategy_status(strategy_id: str):
        """
        取得策略狀態

        返回指定策略的運行狀態、倉位、PnL 等資訊。
        """
        try:
            system_manager = system_manager_getter() if system_manager_getter else None
            if not system_manager:
                return JSONResponse(
                    {'error': '系統管理器不可用'},
                    status_code=500
                )

            if strategy_id not in system_manager.running_strategies:
                # 策略不在運行中，返回配置資訊
                pool = get_account_pool()
                strategy = pool.get_strategy(strategy_id)
                if not strategy:
                    return JSONResponse(
                        {'error': f'策略 "{strategy_id}" 不存在'},
                        status_code=404
                    )

                return JSONResponse({
                    'id': strategy.id,
                    'name': strategy.name,
                    'status': {'running': False},
                })

            runtime_strategy = system_manager.running_strategies[strategy_id]

            # 組裝狀態資訊
            result = {
                'id': strategy_id,
                'name': runtime_strategy.get('name', ''),
                'status': runtime_strategy.get('status', {}),
            }

            # 如果有 state，加入倉位和 PnL
            state = runtime_strategy.get('state')
            if state:
                result['positions'] = {
                    'main_btc': float(state.get_main_position()),
                    'hedge_btc': float(state.get_hedge_position()),
                    'net_btc': float(state.get_net_position()),
                }
                result['pnl_usd'] = float(state.get_pnl_usd())

            return JSONResponse(result)

        except Exception as e:
            logger.error(f"取得策略狀態失敗: {e}")
            return JSONResponse({'error': str(e)}, status_code=500)

    # 註冊路由
    app.include_router(accounts_router)
    app.include_router(strategies_router)
