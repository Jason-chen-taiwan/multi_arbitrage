"""
系統管理器 (v2)

處理系統初始化、交易所連接管理
支援帳號池 + 策略架構

架構:
- 帳號池: 獨立管理多個交易所帳號
- 策略: 從帳號池選擇主帳號和對沖帳號
- Adapter 快取: 避免同一帳號建立多個連接
"""

import os
import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, Optional, Callable, Any, List

from dotenv import load_dotenv

from src.adapters.factory import create_adapter
from src.adapters.base_adapter import BasePerpAdapter
from src.monitor.multi_exchange_monitor import MultiExchangeMonitor
from src.strategy.arbitrage_executor import ArbitrageExecutor
from src.config.account_config import (
    AccountPoolManager,
    AccountConfig,
    StrategyConfig,
    TradingConfig,
)

logger = logging.getLogger(__name__)


@dataclass
class RunningStrategy:
    """
    運行中的策略資料結構

    封裝一個策略實例及其相關資源
    """
    id: str
    name: str
    config: StrategyConfig
    main_account: AccountConfig
    hedge_account: AccountConfig
    main_adapter: Optional[BasePerpAdapter] = None
    hedge_adapter: Optional[BasePerpAdapter] = None
    executor: Optional[Any] = None  # MarketMakerExecutor
    state: Optional[Any] = None     # MMState
    hedge_engine: Optional[Any] = None  # HedgeEngine
    status: Dict = field(default_factory=lambda: {
        'connected': False,
        'main_healthy': False,
        'hedge_healthy': False,
        'running': False,
        'error': None,
    })


# 向後兼容別名
AccountPair = RunningStrategy


class SystemManager:
    """系統管理器 - 管理帳號池和策略"""

    # 定義必要 vs 可選的適配器
    REQUIRED_ADAPTERS = {"STANDX"}     # 做市必需
    OPTIONAL_ADAPTERS = {"GRVT", "STANDX_HEDGE"}  # 對沖可選

    def __init__(self, config_manager, account_pool: Optional[AccountPoolManager] = None):
        """
        初始化系統管理器

        Args:
            config_manager: ConfigManager 實例（向後兼容）
            account_pool: AccountPoolManager 實例
        """
        self.config_manager = config_manager
        self.account_pool = account_pool
        self.monitor: Optional[MultiExchangeMonitor] = None
        self.executor: Optional[ArbitrageExecutor] = None

        # 策略管理
        self.running_strategies: Dict[str, RunningStrategy] = {}

        # Adapter 快取（帳號 ID -> Adapter）
        # 避免同一帳號在多個策略中重複建立連接
        self._adapter_cache: Dict[str, BasePerpAdapter] = {}

        # 向後兼容：account_pairs 別名
        self.account_pairs = self.running_strategies

        # 舊版單帳號兼容
        self.adapters: Dict[str, BasePerpAdapter] = {}

        self.system_status = {
            'running': False,
            'auto_execute': False,
            'dry_run': True,
            'started_at': None,
            'ready_for_trading': False,
            'hedging_available': False,
            'health_error': None,
            # 多帳號狀態
            'multi_account_mode': False,
            'active_strategies': 0,
            'total_strategies': 0,
            # 向後兼容
            'active_pairs': 0,
            'total_pairs': 0,
        }

        # 向後兼容別名
        self.multi_account_config = self.account_pool

    def _init_account_pool(self):
        """初始化帳號池管理器"""
        if self.account_pool is None:
            project_root = Path(__file__).parent.parent.parent
            config_path = project_root / "config" / "accounts.yaml"
            self.account_pool = AccountPoolManager(config_path)
            self.multi_account_config = self.account_pool

    async def init_system(self):
        """初始化系統 - 自動加載所有已配置的策略"""
        logger.info("🚀 正在初始化系統...")

        # 重新載入 .env
        load_dotenv(override=True)

        # 初始化帳號池
        self._init_account_pool()

        # 載入帳號和策略
        accounts, strategies = self.account_pool.load()
        enabled_strategies = [s for s in strategies if s.enabled]

        if enabled_strategies:
            # 多帳號模式
            logger.info(f"📦 發現 {len(enabled_strategies)} 個啟用的策略，啟用多帳號模式")
            self.system_status['multi_account_mode'] = True
            self.system_status['total_strategies'] = len(enabled_strategies)
            self.system_status['total_pairs'] = len(enabled_strategies)  # 向後兼容
            await self._init_strategies(enabled_strategies)
        else:
            # 單帳號模式（向後兼容）
            logger.info("📦 未發現啟用的策略，使用單帳號模式")
            self.system_status['multi_account_mode'] = False
            await self._init_single_account_mode()

    async def _init_strategies(self, strategies: List[StrategyConfig]):
        """
        初始化多策略模式

        為每個策略建立獨立的 executor，共用 adapter
        """
        unified_symbols = ['BTC-USD', 'ETH-USD']
        successful_count = 0

        for strategy_config in strategies:
            try:
                running_strategy = await self._init_strategy(strategy_config)
                if running_strategy:
                    self.running_strategies[strategy_config.id] = running_strategy
                    successful_count += 1
                    logger.info(f"  ✅ 策略 {strategy_config.name} (ID: {strategy_config.id}) 已初始化")
            except Exception as e:
                logger.error(f"  ❌ 策略 {strategy_config.name} 初始化失敗: {e}")

        self.system_status['active_strategies'] = successful_count
        self.system_status['active_pairs'] = successful_count  # 向後兼容

        # 設置第一個策略的 adapter 為兼容模式
        if self.running_strategies:
            first_strategy = list(self.running_strategies.values())[0]
            if first_strategy.main_adapter:
                self.adapters['STANDX'] = first_strategy.main_adapter
            if first_strategy.hedge_adapter:
                self.adapters['STANDX_HEDGE'] = first_strategy.hedge_adapter

        # 創建監控器
        if self.adapters:
            self.monitor = MultiExchangeMonitor(
                adapters={k: v for k, v in self.adapters.items() if k != 'STANDX_HEDGE'},
                symbols=unified_symbols,
                update_interval=2.0,
                min_profit_pct=0.1
            )

            self.executor = ArbitrageExecutor(
                monitor=self.monitor,
                adapters=self.adapters,
                max_position_size=Decimal("0.1"),
                min_profit_usd=Decimal("5.0"),
                enable_auto_execute=False,
                dry_run=True
            )

            await self.monitor.start()
            await self.executor.start()

        self.system_status['running'] = True
        self.system_status['started_at'] = datetime.now().isoformat()
        self.system_status['ready_for_trading'] = successful_count > 0

        logger.info(f"✅ 系統已啟動 - {successful_count}/{len(strategies)} 個策略成功初始化")

    async def _init_strategy(self, config: StrategyConfig) -> Optional[RunningStrategy]:
        """
        初始化單個策略

        Args:
            config: 策略配置

        Returns:
            初始化完成的 RunningStrategy，失敗時返回 None
        """
        # 從帳號池取得帳號
        main_account = self.account_pool.get_account(config.main_account_id)
        hedge_account = self.account_pool.get_account(config.hedge_account_id)

        if not main_account:
            logger.error(f"策略 {config.name}: 主帳號 {config.main_account_id} 不存在")
            return None

        if not hedge_account:
            logger.error(f"策略 {config.name}: 對沖帳號 {config.hedge_account_id} 不存在")
            return None

        strategy = RunningStrategy(
            id=config.id,
            name=config.name,
            config=config,
            main_account=main_account,
            hedge_account=hedge_account,
        )

        # 取得或建立主帳號 adapter
        try:
            strategy.main_adapter = await self._get_or_create_adapter(main_account)
            if strategy.main_adapter:
                strategy.status['main_healthy'] = True
                logger.info(f"    ✅ 主帳號 {main_account.name} 已連接")
            else:
                logger.error(f"    ❌ 主帳號 {main_account.name} 連接失敗")
                return None
        except Exception as e:
            logger.error(f"    ❌ 主帳號 {main_account.name} 初始化失敗: {e}")
            return None

        # 取得或建立對沖帳號 adapter
        try:
            strategy.hedge_adapter = await self._get_or_create_adapter(hedge_account)
            if strategy.hedge_adapter:
                strategy.status['hedge_healthy'] = True
                logger.info(f"    ✅ 對沖帳號 {hedge_account.name} 已連接")
            else:
                logger.warning(f"    ⚠️  對沖帳號 {hedge_account.name} 連接失敗")
        except Exception as e:
            logger.warning(f"    ⚠️  對沖帳號 {hedge_account.name} 初始化失敗: {e}")

        strategy.status['connected'] = True
        return strategy

    async def _get_or_create_adapter(self, account: AccountConfig) -> Optional[BasePerpAdapter]:
        """
        取得或建立帳號的 adapter

        使用快取避免重複建立連接

        Args:
            account: 帳號配置

        Returns:
            Adapter 實例
        """
        # 檢查快取
        if account.id in self._adapter_cache:
            return self._adapter_cache[account.id]

        # 建立新的 adapter
        adapter_config = {
            'exchange_name': account.exchange,
            'api_token': account.api_token,
            'ed25519_private_key': account.ed25519_private_key,
            'testnet': os.getenv('STANDX_TESTNET', 'false').lower() == 'true',
        }

        # 代理配置
        if account.proxy and account.proxy.is_configured():
            adapter_config['proxy_url'] = account.proxy.url
            adapter_config['proxy_username'] = account.proxy.username
            adapter_config['proxy_password'] = account.proxy.password
            logger.info(f"    ℹ️  帳號 {account.name} 使用代理: {account.proxy.url[:30]}...")

        adapter = create_adapter(adapter_config)

        if hasattr(adapter, 'connect'):
            connected = await adapter.connect()
            if not connected:
                return None

        # 加入快取
        self._adapter_cache[account.id] = adapter
        return adapter

    # ==================== 策略管理方法 ====================

    def get_strategy(self, strategy_id: str) -> Optional[RunningStrategy]:
        """取得指定策略"""
        return self.running_strategies.get(strategy_id)

    def get_all_strategies(self) -> List[RunningStrategy]:
        """取得所有策略"""
        return list(self.running_strategies.values())

    def get_active_strategies(self) -> List[RunningStrategy]:
        """取得所有運行中的策略"""
        return [s for s in self.running_strategies.values() if s.status.get('running')]

    async def start_strategy(self, strategy_id: str) -> bool:
        """
        啟動指定策略

        Args:
            strategy_id: 策略 ID

        Returns:
            是否啟動成功
        """
        # 檢查是否已在運行
        if strategy_id in self.running_strategies:
            strategy = self.running_strategies[strategy_id]
            if strategy.status.get('running'):
                logger.warning(f"策略 {strategy_id} 已在運行中")
                return True
            # 已載入但未運行，標記為運行
            strategy.status['running'] = True
            logger.info(f"策略 {strategy_id} 已啟動")
            return True

        # 需要新載入策略
        strategy_config = self.account_pool.get_strategy(strategy_id)
        if not strategy_config:
            logger.error(f"策略 {strategy_id} 不存在")
            return False

        if not strategy_config.enabled:
            logger.error(f"策略 {strategy_id} 已停用")
            return False

        try:
            running_strategy = await self._init_strategy(strategy_config)
            if running_strategy:
                running_strategy.status['running'] = True
                self.running_strategies[strategy_id] = running_strategy
                self.system_status['active_strategies'] = len(self.get_active_strategies())
                self.system_status['active_pairs'] = self.system_status['active_strategies']
                logger.info(f"策略 {strategy_id} 已啟動")
                return True
            return False
        except Exception as e:
            logger.error(f"啟動策略 {strategy_id} 失敗: {e}")
            return False

    async def stop_strategy(self, strategy_id: str) -> bool:
        """
        停止指定策略

        Args:
            strategy_id: 策略 ID

        Returns:
            是否停止成功
        """
        strategy = self.running_strategies.get(strategy_id)
        if not strategy:
            logger.error(f"策略 {strategy_id} 未在運行")
            return False

        if strategy.executor and hasattr(strategy.executor, 'stop'):
            await strategy.executor.stop()

        strategy.status['running'] = False
        self.system_status['active_strategies'] = len(self.get_active_strategies())
        self.system_status['active_pairs'] = self.system_status['active_strategies']
        logger.info(f"策略 {strategy_id} 已停止")
        return True

    async def start_all_strategies(self) -> Dict[str, bool]:
        """啟動所有已啟用的策略"""
        results = {}
        _, strategies = self.account_pool.load()
        for strategy in strategies:
            if strategy.enabled:
                results[strategy.id] = await self.start_strategy(strategy.id)
        return results

    async def stop_all_strategies(self) -> Dict[str, bool]:
        """停止所有運行中的策略"""
        results = {}
        for strategy_id in list(self.running_strategies.keys()):
            results[strategy_id] = await self.stop_strategy(strategy_id)
        return results

    def get_strategies_summary(self) -> Dict:
        """
        取得策略彙總狀態

        Returns:
            所有策略的彙總狀態
        """
        total_pnl = Decimal("0")
        total_net_btc = Decimal("0")
        total_main_btc = Decimal("0")
        total_hedge_btc = Decimal("0")
        active_count = 0

        for strategy in self.running_strategies.values():
            if strategy.state:
                total_pnl += strategy.state.get_pnl_usd()
                total_net_btc += strategy.state.get_net_position()
                if hasattr(strategy.state, 'get_main_position'):
                    total_main_btc += strategy.state.get_main_position()
                if hasattr(strategy.state, 'get_hedge_position'):
                    total_hedge_btc += strategy.state.get_hedge_position()
            if strategy.status.get('running'):
                active_count += 1

        return {
            'total_pnl': float(total_pnl),
            'total_net_btc': float(total_net_btc),
            'total_main_btc': float(total_main_btc),
            'total_hedge_btc': float(total_hedge_btc),
            'active_strategies': active_count,
            'total_strategies': len(self.running_strategies),
            'multi_account_mode': self.system_status.get('multi_account_mode', False),
            # 向後兼容
            'active_pairs': active_count,
            'total_pairs': len(self.running_strategies),
        }

    # ==================== 向後兼容方法 ====================

    # 將 account_pairs 相關方法映射到 running_strategies
    def get_account_pair(self, pair_id: str) -> Optional[RunningStrategy]:
        """向後兼容：取得指定帳號組"""
        return self.get_strategy(pair_id)

    def get_all_account_pairs(self) -> List[RunningStrategy]:
        """向後兼容：取得所有帳號組"""
        return self.get_all_strategies()

    def get_active_pairs(self) -> List[RunningStrategy]:
        """向後兼容：取得所有運行中的帳號組"""
        return self.get_active_strategies()

    async def start_pair(self, pair_id: str) -> bool:
        """向後兼容：啟動帳號組"""
        return await self.start_strategy(pair_id)

    async def stop_pair(self, pair_id: str) -> bool:
        """向後兼容：停止帳號組"""
        return await self.stop_strategy(pair_id)

    async def start_all_pairs(self) -> Dict[str, bool]:
        """向後兼容：啟動所有帳號組"""
        return await self.start_all_strategies()

    async def stop_all_pairs(self) -> Dict[str, bool]:
        """向後兼容：停止所有帳號組"""
        return await self.stop_all_strategies()

    def get_aggregated_status(self) -> Dict:
        """向後兼容：取得彙總狀態"""
        return self.get_strategies_summary()

    # ==================== 單帳號模式（向後兼容）====================

    async def _init_single_account_mode(self):
        """初始化單帳號模式（向後兼容）"""
        configs = self.config_manager.get_all_configs()
        unified_symbols = ['BTC-USD', 'ETH-USD']

        self.adapters = {}

        # 加載 DEX
        for exchange_name, config in configs['dex'].items():
            try:
                adapter_config = {
                    'exchange_name': exchange_name,
                    'testnet': config.get('testnet', False)
                }

                if exchange_name == 'standx':
                    api_token = os.getenv('STANDX_API_TOKEN')
                    ed25519_key = os.getenv('STANDX_ED25519_PRIVATE_KEY')
                    if api_token and ed25519_key:
                        adapter_config['api_token'] = api_token
                        adapter_config['ed25519_private_key'] = ed25519_key
                    else:
                        private_key = os.getenv('WALLET_PRIVATE_KEY')
                        address = os.getenv('WALLET_ADDRESS')
                        if private_key:
                            adapter_config['private_key'] = private_key
                        if address:
                            adapter_config['wallet_address'] = address
                elif exchange_name == 'grvt':
                    api_key = os.getenv('GRVT_API_KEY')
                    api_secret = os.getenv('GRVT_API_SECRET')
                    trading_account_id = os.getenv('GRVT_TRADING_ACCOUNT_ID')
                    if api_key:
                        adapter_config['api_key'] = api_key
                    if api_secret:
                        adapter_config['api_secret'] = api_secret
                    if trading_account_id:
                        adapter_config['trading_account_id'] = trading_account_id

                adapter = create_adapter(adapter_config)

                if hasattr(adapter, 'connect'):
                    connected = await adapter.connect()
                    if not connected:
                        logger.warning(f"  ⚠️  {exchange_name.upper()} - 連接失敗")
                        continue

                self.adapters[exchange_name.upper()] = adapter
                logger.info(f"  ✅ {exchange_name.upper()} - 已連接")
            except Exception as e:
                logger.warning(f"  ⚠️  {exchange_name.upper()} - 跳過: {str(e)[:50]}")

        # 加載對沖帳戶
        hedge_target = os.getenv('HEDGE_TARGET', 'grvt')
        if hedge_target == 'standx_hedge':
            hedge_token = os.getenv('STANDX_HEDGE_API_TOKEN')
            hedge_key = os.getenv('STANDX_HEDGE_ED25519_PRIVATE_KEY')
            if hedge_token and hedge_key:
                try:
                    hedge_config = {
                        'exchange_name': 'standx',
                        'api_token': hedge_token,
                        'ed25519_private_key': hedge_key,
                        'testnet': os.getenv('STANDX_TESTNET', 'false').lower() == 'true',
                        'proxy_url': os.getenv('STANDX_HEDGE_PROXY_URL'),
                        'proxy_username': os.getenv('STANDX_HEDGE_PROXY_USERNAME'),
                        'proxy_password': os.getenv('STANDX_HEDGE_PROXY_PASSWORD'),
                    }
                    hedge_adapter = create_adapter(hedge_config)
                    if hasattr(hedge_adapter, 'connect'):
                        connected = await hedge_adapter.connect()
                        if connected:
                            self.adapters['STANDX_HEDGE'] = hedge_adapter
                            proxy_info = " (via proxy)" if hedge_config.get('proxy_url') else ""
                            logger.info(f"  ✅ STANDX_HEDGE - 已連接{proxy_info}")
                        else:
                            logger.warning("  ⚠️  STANDX_HEDGE - 連接失敗")
                except Exception as e:
                    logger.warning(f"  ⚠️  STANDX_HEDGE - 跳過: {str(e)[:50]}")

        # 加載 CEX
        for exchange_name, config in configs['cex'].items():
            try:
                adapter_config = {
                    'exchange_name': exchange_name,
                    'api_key': os.getenv(f'{exchange_name.upper()}_API_KEY'),
                    'api_secret': os.getenv(f'{exchange_name.upper()}_API_SECRET'),
                    'testnet': config.get('testnet', False)
                }

                if exchange_name in ['okx', 'bitget']:
                    passphrase = os.getenv(f'{exchange_name.upper()}_PASSPHRASE')
                    if passphrase:
                        adapter_config['passphrase'] = passphrase

                adapter = create_adapter(adapter_config)

                if hasattr(adapter, 'connect'):
                    connected = await adapter.connect()
                    if not connected:
                        logger.warning(f"  ⚠️  {exchange_name.upper()} - 連接失敗")
                        continue

                self.adapters[exchange_name.upper()] = adapter
                logger.info(f"  ✅ {exchange_name.upper()} - 已連接")
            except Exception as e:
                logger.warning(f"  ⚠️  {exchange_name.upper()} - 跳過: {str(e)[:50]}")

        if len(self.adapters) == 0:
            logger.warning("⚠️  沒有已配置的交易所")
            return

        await self._perform_health_checks()

        monitor_adapters = {
            name: adapter
            for name, adapter in self.adapters.items()
            if name != 'STANDX_HEDGE'
        }
        self.monitor = MultiExchangeMonitor(
            adapters=monitor_adapters,
            symbols=unified_symbols,
            update_interval=2.0,
            min_profit_pct=0.1
        )

        self.executor = ArbitrageExecutor(
            monitor=self.monitor,
            adapters=self.adapters,
            max_position_size=Decimal("0.1"),
            min_profit_usd=Decimal("5.0"),
            enable_auto_execute=False,
            dry_run=True
        )

        await self.monitor.start()
        await self.executor.start()

        self.system_status['running'] = True
        self.system_status['started_at'] = datetime.now().isoformat()

        logger.info(f"✅ 系統已啟動 - 監控 {len(self.adapters)} 個交易所")

    # ==================== 其他方法 ====================

    async def add_exchange(self, exchange_name: str, exchange_type: str) -> bool:
        """動態添加交易所到監控系統"""
        if not self.monitor:
            return False

        try:
            if exchange_type == 'dex':
                adapter_config = {
                    'exchange_name': exchange_name,
                    'testnet': os.getenv(f'{exchange_name.upper()}_TESTNET', 'false').lower() == 'true'
                }

                if exchange_name == 'standx':
                    api_token = os.getenv('STANDX_API_TOKEN')
                    ed25519_key = os.getenv('STANDX_ED25519_PRIVATE_KEY')
                    if api_token and ed25519_key:
                        adapter_config['api_token'] = api_token
                        adapter_config['ed25519_private_key'] = ed25519_key
                    else:
                        private_key = os.getenv('WALLET_PRIVATE_KEY')
                        address = os.getenv('WALLET_ADDRESS')
                        if private_key:
                            adapter_config['private_key'] = private_key
                        if address:
                            adapter_config['wallet_address'] = address
                elif exchange_name == 'grvt':
                    api_key = os.getenv('GRVT_API_KEY')
                    api_secret = os.getenv('GRVT_API_SECRET')
                    trading_account_id = os.getenv('GRVT_TRADING_ACCOUNT_ID')
                    if api_key:
                        adapter_config['api_key'] = api_key
                    if api_secret:
                        adapter_config['api_secret'] = api_secret
                    if trading_account_id:
                        adapter_config['trading_account_id'] = trading_account_id
            else:
                adapter_config = {
                    'exchange_name': exchange_name,
                    'api_key': os.getenv(f'{exchange_name.upper()}_API_KEY'),
                    'api_secret': os.getenv(f'{exchange_name.upper()}_API_SECRET'),
                    'testnet': os.getenv(f'{exchange_name.upper()}_TESTNET', 'false').lower() == 'true'
                }

                if exchange_name in ['okx', 'bitget']:
                    passphrase = os.getenv(f'{exchange_name.upper()}_PASSPHRASE')
                    if passphrase:
                        adapter_config['passphrase'] = passphrase

            adapter = create_adapter(adapter_config)

            if hasattr(adapter, 'connect'):
                connected = await adapter.connect()
                if not connected:
                    logger.error(f"❌ {exchange_name.upper()} 連接失敗")
                    return False

            self.adapters[exchange_name.upper()] = adapter
            self.monitor.adapters[exchange_name.upper()] = adapter

            logger.info(f"✅ {exchange_name.upper()} 已添加到監控系統")
            return True

        except Exception as e:
            logger.error(f"❌ 添加 {exchange_name.upper()} 失敗: {e}")
            return False

    async def remove_exchange(self, exchange_name: str):
        """從監控系統移除交易所"""
        if not self.monitor:
            return

        exchange_key = exchange_name.upper()

        if exchange_key in self.adapters:
            adapter = self.adapters[exchange_key]
            if hasattr(adapter, 'disconnect'):
                try:
                    await adapter.disconnect()
                except Exception as e:
                    logger.warning(f"⚠️  斷開 {exchange_key} 連接時出錯: {e}")
            del self.adapters[exchange_key]

        if exchange_key in self.monitor.adapters:
            del self.monitor.adapters[exchange_key]

        logger.info(f"✅ {exchange_key} 已從監控系統移除")

    async def _perform_health_checks(self):
        """執行健康檢查"""
        logger.info("🔍 正在執行健康檢查...")

        unhealthy_required = []
        unhealthy_optional = []

        for name, adapter in list(self.adapters.items()):
            try:
                if not hasattr(adapter, 'health_check'):
                    logger.warning(f"  ⚠️  {name} - 無健康檢查方法")
                    continue

                health = await adapter.health_check()

                if not health.get("healthy", False):
                    if name in self.REQUIRED_ADAPTERS:
                        unhealthy_required.append(name)
                        logger.error(
                            f"  ❌ {name} (必要) 健康檢查失敗: {health.get('error', 'Unknown')}"
                        )
                    else:
                        unhealthy_optional.append(name)
                        logger.warning(
                            f"  ⚠️  {name} (可選) 健康檢查失敗: {health.get('error', 'Unknown')}"
                        )
                else:
                    latency = health.get("latency_ms", 0)
                    logger.info(f"  ✅ {name} 健康檢查通過 ({latency:.0f}ms)")

            except Exception as e:
                if name in self.REQUIRED_ADAPTERS:
                    unhealthy_required.append(name)
                    logger.error(f"  ❌ {name} (必要) 健康檢查異常: {e}")
                else:
                    unhealthy_optional.append(name)
                    logger.warning(f"  ⚠️  {name} (可選) 健康檢查異常: {e}")

        if unhealthy_required:
            self.system_status['ready_for_trading'] = False
            self.system_status['health_error'] = f"必要交易所不可用: {unhealthy_required}"
            logger.error(f"🚫 系統無法交易: {unhealthy_required} 不健康")
        else:
            self.system_status['ready_for_trading'] = True
            self.system_status['health_error'] = None
            logger.info("✅ 做市功能就緒")

        if unhealthy_optional:
            self.system_status['hedging_available'] = False
            logger.warning(f"⚠️  對沖功能不可用: {unhealthy_optional}")

            for name in unhealthy_optional:
                if name in self.adapters:
                    del self.adapters[name]
                    logger.info(f"移除不健康的可選 adapter: {name}")
        else:
            has_hedge_adapter = any(
                name in self.OPTIONAL_ADAPTERS for name in self.adapters
            )
            self.system_status['hedging_available'] = has_hedge_adapter

            if has_hedge_adapter:
                logger.info("✅ 對沖功能就緒")
            else:
                logger.info("ℹ️  未配置對沖交易所")

    async def check_all_health(self) -> dict:
        """檢查所有交易所健康狀態"""
        results = {}

        for name, adapter in self.adapters.items():
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

        return {
            "all_healthy": all_healthy,
            "ready_for_trading": self.system_status.get('ready_for_trading', False),
            "hedging_available": self.system_status.get('hedging_available', False),
            "exchanges": results
        }

    async def shutdown(self):
        """關閉系統"""
        # 停止所有策略
        for strategy in self.running_strategies.values():
            if strategy.executor and hasattr(strategy.executor, 'stop'):
                try:
                    await strategy.executor.stop()
                except:
                    pass

        # 斷開快取中的所有 adapter
        for account_id, adapter in self._adapter_cache.items():
            if hasattr(adapter, 'disconnect'):
                try:
                    await adapter.disconnect()
                except:
                    pass

        self._adapter_cache.clear()
        self.running_strategies.clear()

        if self.monitor:
            await self.monitor.stop()
        if self.executor:
            await self.executor.stop()

        for name, adapter in list(self.adapters.items()):
            if hasattr(adapter, 'disconnect'):
                try:
                    await adapter.disconnect()
                except:
                    pass

        self.system_status['running'] = False
        self.system_status['ready_for_trading'] = False
        self.system_status['hedging_available'] = False
        logger.info("系統已關閉")

    async def reconnect_all(self) -> dict:
        """重新連接所有已配置的交易所"""
        logger.info("🔄 正在重新連接所有交易所...")
        results = {}

        load_dotenv(override=True)

        old_adapters = dict(self.adapters)
        new_adapters = {}

        configs = self.config_manager.get_all_configs()

        logger.info("  📦 創建新的連接...")

        for exchange_name, config in configs['dex'].items():
            name_upper = exchange_name.upper()
            try:
                adapter_config = {
                    'exchange_name': exchange_name,
                    'testnet': config.get('testnet', False)
                }

                if exchange_name == 'standx':
                    api_token = os.getenv('STANDX_API_TOKEN')
                    ed25519_key = os.getenv('STANDX_ED25519_PRIVATE_KEY')
                    if api_token and ed25519_key:
                        adapter_config['api_token'] = api_token
                        adapter_config['ed25519_private_key'] = ed25519_key
                    else:
                        private_key = os.getenv('WALLET_PRIVATE_KEY')
                        address = os.getenv('WALLET_ADDRESS')
                        if private_key:
                            adapter_config['private_key'] = private_key
                        if address:
                            adapter_config['wallet_address'] = address

                elif exchange_name == 'grvt':
                    api_key = os.getenv('GRVT_API_KEY')
                    api_secret = os.getenv('GRVT_API_SECRET')
                    trading_account_id = os.getenv('GRVT_TRADING_ACCOUNT_ID')
                    if api_key:
                        adapter_config['api_key'] = api_key
                    if api_secret:
                        adapter_config['api_secret'] = api_secret
                    if trading_account_id:
                        adapter_config['trading_account_id'] = trading_account_id

                adapter = create_adapter(adapter_config)

                if hasattr(adapter, 'connect'):
                    connected = await adapter.connect()
                    if not connected:
                        results[name_upper] = {"success": False, "error": "連接失敗"}
                        logger.error(f"  ❌ {name_upper} 重新連接失敗")
                        continue

                new_adapters[name_upper] = adapter
                results[name_upper] = {"success": True, "error": None}
                logger.info(f"  ✅ {name_upper} 新連接已建立")

            except Exception as e:
                results[name_upper] = {"success": False, "error": str(e)}
                logger.error(f"  ❌ {name_upper} 重新連接異常: {e}")

        hedge_target = os.getenv('HEDGE_TARGET', 'grvt')
        if hedge_target == 'standx_hedge':
            hedge_token = os.getenv('STANDX_HEDGE_API_TOKEN')
            hedge_key = os.getenv('STANDX_HEDGE_ED25519_PRIVATE_KEY')
            if hedge_token and hedge_key:
                try:
                    hedge_config = {
                        'exchange_name': 'standx',
                        'api_token': hedge_token,
                        'ed25519_private_key': hedge_key,
                        'testnet': os.getenv('STANDX_TESTNET', 'false').lower() == 'true',
                        'proxy_url': os.getenv('STANDX_HEDGE_PROXY_URL'),
                        'proxy_username': os.getenv('STANDX_HEDGE_PROXY_USERNAME'),
                        'proxy_password': os.getenv('STANDX_HEDGE_PROXY_PASSWORD'),
                    }
                    hedge_adapter = create_adapter(hedge_config)
                    if hasattr(hedge_adapter, 'connect'):
                        connected = await hedge_adapter.connect()
                        if connected:
                            new_adapters['STANDX_HEDGE'] = hedge_adapter
                            results['STANDX_HEDGE'] = {"success": True, "error": None}
                            proxy_info = " (via proxy)" if hedge_config.get('proxy_url') else ""
                            logger.info(f"  ✅ STANDX_HEDGE 新連接已建立{proxy_info}")
                        else:
                            results['STANDX_HEDGE'] = {"success": False, "error": "連接失敗"}
                            logger.error("  ❌ STANDX_HEDGE 重新連接失敗")
                except Exception as e:
                    results['STANDX_HEDGE'] = {"success": False, "error": str(e)}
                    logger.error(f"  ❌ STANDX_HEDGE 重新連接異常: {e}")

        for exchange_name, config in configs['cex'].items():
            name_upper = exchange_name.upper()
            try:
                adapter_config = {
                    'exchange_name': exchange_name,
                    'api_key': os.getenv(f'{exchange_name.upper()}_API_KEY'),
                    'api_secret': os.getenv(f'{exchange_name.upper()}_API_SECRET'),
                    'testnet': config.get('testnet', False)
                }

                if exchange_name in ['okx', 'bitget']:
                    passphrase = os.getenv(f'{exchange_name.upper()}_PASSPHRASE')
                    if passphrase:
                        adapter_config['passphrase'] = passphrase

                adapter = create_adapter(adapter_config)

                if hasattr(adapter, 'connect'):
                    connected = await adapter.connect()
                    if not connected:
                        results[name_upper] = {"success": False, "error": "連接失敗"}
                        logger.error(f"  ❌ {name_upper} 重新連接失敗")
                        continue

                new_adapters[name_upper] = adapter
                results[name_upper] = {"success": True, "error": None}
                logger.info(f"  ✅ {name_upper} 新連接已建立")

            except Exception as e:
                results[name_upper] = {"success": False, "error": str(e)}
                logger.error(f"  ❌ {name_upper} 重新連接異常: {e}")

        logger.info("  🔄 切換到新連接...")
        self.adapters = new_adapters

        if self.monitor:
            monitor_adapters = {
                name: adapter
                for name, adapter in self.adapters.items()
                if name != 'STANDX_HEDGE'
            }
            self.monitor.adapters = monitor_adapters

        logger.info("  🔌 斷開舊連接...")
        for name, adapter in old_adapters.items():
            try:
                if hasattr(adapter, 'disconnect'):
                    await adapter.disconnect()
                    logger.info(f"  ✅ {name} 舊連接已斷開")
            except Exception as e:
                logger.warning(f"  ⚠️ 斷開 {name} 舊連接時出錯: {e}")

        await self._perform_health_checks()

        success = all(r.get("success", False) for r in results.values())
        logger.info(f"🔄 重新連接完成: {'全部成功' if success else '部分失敗'}")

        return {
            "success": success,
            "results": results,
            "ready_for_trading": self.system_status.get('ready_for_trading', False),
            "hedging_available": self.system_status.get('hedging_available', False)
        }
