"""
系統管理器

處理系統初始化、交易所連接管理
"""

import os
import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, Optional, Callable, Any

from src.adapters.factory import create_adapter
from src.adapters.base_adapter import BasePerpAdapter
from src.monitor.multi_exchange_monitor import MultiExchangeMonitor
from src.strategy.arbitrage_executor import ArbitrageExecutor

logger = logging.getLogger(__name__)


class SystemManager:
    """系統管理器 - 管理交易所連接和監控"""

    def __init__(self, config_manager):
        """
        初始化系統管理器

        Args:
            config_manager: ConfigManager 實例
        """
        self.config_manager = config_manager
        self.monitor: Optional[MultiExchangeMonitor] = None
        self.executor: Optional[ArbitrageExecutor] = None
        self.adapters: Dict[str, BasePerpAdapter] = {}
        self.system_status = {
            'running': False,
            'auto_execute': False,
            'dry_run': True,
            'started_at': None
        }

    async def init_system(self):
        """初始化系統 - 自動加載所有已配置的交易所"""
        logger.info("🚀 正在初始化系統...")

        # 加載配置
        configs = self.config_manager.get_all_configs()

        # 統一符號格式
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
                    # 優先使用 Token 模式
                    api_token = os.getenv('STANDX_API_TOKEN')
                    ed25519_key = os.getenv('STANDX_ED25519_PRIVATE_KEY')
                    if api_token and ed25519_key:
                        adapter_config['api_token'] = api_token
                        adapter_config['ed25519_private_key'] = ed25519_key
                    else:
                        # 回退到錢包簽名模式
                        private_key = os.getenv('WALLET_PRIVATE_KEY')
                        address = os.getenv('WALLET_ADDRESS')
                        if private_key:
                            adapter_config['private_key'] = private_key
                        if address:
                            adapter_config['wallet_address'] = address
                elif exchange_name == 'grvt':
                    api_key = os.getenv('GRVT_API_KEY')
                    api_secret = os.getenv('GRVT_API_SECRET')
                    if api_key:
                        adapter_config['api_key'] = api_key
                    if api_secret:
                        adapter_config['api_secret'] = api_secret

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

        # 創建監控器
        self.monitor = MultiExchangeMonitor(
            adapters=self.adapters,
            symbols=unified_symbols,
            update_interval=2.0,
            min_profit_pct=0.1
        )

        # 創建執行器
        self.executor = ArbitrageExecutor(
            monitor=self.monitor,
            adapters=self.adapters,
            max_position_size=Decimal("0.1"),
            min_profit_usd=Decimal("5.0"),
            enable_auto_execute=False,
            dry_run=True
        )

        # 啟動監控
        await self.monitor.start()
        await self.executor.start()

        self.system_status['running'] = True
        self.system_status['started_at'] = datetime.now().isoformat()

        logger.info(f"✅ 系統已啟動 - 監控 {len(self.adapters)} 個交易所")

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
                    # 優先使用 Token 模式
                    api_token = os.getenv('STANDX_API_TOKEN')
                    ed25519_key = os.getenv('STANDX_ED25519_PRIVATE_KEY')
                    if api_token and ed25519_key:
                        adapter_config['api_token'] = api_token
                        adapter_config['ed25519_private_key'] = ed25519_key
                    else:
                        # 回退到錢包簽名模式
                        private_key = os.getenv('WALLET_PRIVATE_KEY')
                        address = os.getenv('WALLET_ADDRESS')
                        if private_key:
                            adapter_config['private_key'] = private_key
                        if address:
                            adapter_config['wallet_address'] = address
                elif exchange_name == 'grvt':
                    api_key = os.getenv('GRVT_API_KEY')
                    api_secret = os.getenv('GRVT_API_SECRET')
                    if api_key:
                        adapter_config['api_key'] = api_key
                    if api_secret:
                        adapter_config['api_secret'] = api_secret
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

    async def shutdown(self):
        """關閉系統"""
        if self.monitor:
            await self.monitor.stop()
        if self.executor:
            await self.executor.stop()

        # 斷開所有連接
        for name, adapter in list(self.adapters.items()):
            if hasattr(adapter, 'disconnect'):
                try:
                    await adapter.disconnect()
                except:
                    pass

        self.system_status['running'] = False
        logger.info("系統已關閉")
