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

    # 定義必要 vs 可選的適配器
    # 做市商需要 STANDX，對沖可選 GRVT 或 STANDX_HEDGE
    REQUIRED_ADAPTERS = {"STANDX"}     # 做市必需
    OPTIONAL_ADAPTERS = {"GRVT", "STANDX_HEDGE"}  # 對沖可選

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
            'started_at': None,
            # 新增健康狀態
            'ready_for_trading': False,
            'hedging_available': False,
            'health_error': None
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

        # 加載對沖帳戶（StandX Hedge）
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
                        # 代理配置（用於女巫防護，讓對沖帳戶走不同 IP）
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
                            logger.info(f"  ✅ STANDX_HEDGE - 已連接（對沖帳戶）{proxy_info}")
                        else:
                            logger.warning("  ⚠️  STANDX_HEDGE - 連接失敗")
                except Exception as e:
                    logger.warning(f"  ⚠️  STANDX_HEDGE - 跳過: {str(e)[:50]}")
            else:
                logger.info("  ℹ️  STANDX_HEDGE - 未配置 (HEDGE_TARGET=standx_hedge 但缺少憑證)")

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

        # === 健康檢查 ===
        await self._perform_health_checks()

        # 創建監控器（排除對沖帳戶，避免女巫偵測）
        # STANDX_HEDGE 只用於對沖執行，不需要 orderbook 監控
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
        """
        執行健康檢查（含 required/optional 策略）

        - required adapters 不健康 → ready_for_trading = False
        - optional adapters 不健康 → hedging_available = False，但可以繼續運行
        """
        logger.info("🔍 正在執行健康檢查...")

        unhealthy_required = []
        unhealthy_optional = []

        for name, adapter in list(self.adapters.items()):
            try:
                # 檢查 adapter 是否有 health_check 方法
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

        # 更新系統狀態
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

            # 移除不健康的可選 adapter（避免後續錯誤）
            for name in unhealthy_optional:
                if name in self.adapters:
                    del self.adapters[name]
                    logger.info(f"移除不健康的可選 adapter: {name}")
        else:
            # 檢查是否有對沖用的 adapter
            has_hedge_adapter = any(
                name in self.OPTIONAL_ADAPTERS for name in self.adapters
            )
            self.system_status['hedging_available'] = has_hedge_adapter

            if has_hedge_adapter:
                logger.info("✅ 對沖功能就緒")
            else:
                logger.info("ℹ️  未配置對沖交易所")

    async def check_all_health(self) -> dict:
        """
        檢查所有交易所健康狀態

        Returns:
            {
                "all_healthy": bool,
                "ready_for_trading": bool,
                "hedging_available": bool,
                "exchanges": {
                    "STANDX": {...},
                    "GRVT": {...}
                }
            }
        """
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
        self.system_status['ready_for_trading'] = False
        self.system_status['hedging_available'] = False
        logger.info("系統已關閉")

    async def reconnect_all(self) -> dict:
        """
        重新連接所有已配置的交易所

        策略：先創建新的 adapters，確認成功後再斷開舊的
        這樣可以避免 aiohttp session 資源清理不完整的問題

        Returns:
            {
                "success": bool,
                "results": {
                    "STANDX": {"success": bool, "error": str or null},
                    "GRVT": {"success": bool, "error": str or null}
                }
            }
        """
        logger.info("🔄 正在重新連接所有交易所...")
        results = {}

        # 保存舊的 adapters 引用
        old_adapters = dict(self.adapters)

        # 創建新的 adapters dict
        new_adapters = {}

        # 重新加載配置
        configs = self.config_manager.get_all_configs()

        # === 第一步：創建新的 adapters（不斷開舊的）===
        logger.info("  📦 創建新的連接...")

        # 重新連接 DEX
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

        # 重新連接對沖帳戶（StandX Hedge）
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
                        # 代理配置（用於女巫防護，讓對沖帳戶走不同 IP）
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

        # 重新連接 CEX
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

        # === 第二步：先替換 adapters（讓其他程式碼立即使用新的）===
        logger.info("  🔄 切換到新連接...")
        self.adapters = new_adapters

        # 更新 monitor 的 adapters（排除對沖帳戶，避免女巫偵測）
        if self.monitor:
            monitor_adapters = {
                name: adapter
                for name, adapter in self.adapters.items()
                if name != 'STANDX_HEDGE'
            }
            self.monitor.adapters = monitor_adapters

        # === 第三步：斷開舊的連接（已不再被引用）===
        logger.info("  🔌 斷開舊連接...")
        for name, adapter in old_adapters.items():
            try:
                if hasattr(adapter, 'disconnect'):
                    await adapter.disconnect()
                    logger.info(f"  ✅ {name} 舊連接已斷開")
            except Exception as e:
                logger.warning(f"  ⚠️ 斷開 {name} 舊連接時出錯: {e}")

        # 執行健康檢查
        await self._perform_health_checks()

        success = all(r.get("success", False) for r in results.values())
        logger.info(f"🔄 重新連接完成: {'全部成功' if success else '部分失敗'}")

        return {
            "success": success,
            "results": results,
            "ready_for_trading": self.system_status.get('ready_for_trading', False),
            "hedging_available": self.system_status.get('hedging_available', False)
        }
