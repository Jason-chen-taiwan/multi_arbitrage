"""
配置管理器

處理交易所 API 配置的讀取、保存和刪除
"""

import os
from pathlib import Path
from typing import Dict
from dotenv import load_dotenv, set_key, unset_key


class ConfigManager:
    """配置管理器"""

    def __init__(self, env_file: Path):
        self.env_file = env_file
        if not env_file.exists():
            env_file.touch()
        load_dotenv(env_file)

    def get_all_configs(self) -> Dict:
        """獲取所有配置"""
        load_dotenv(self.env_file, override=True)

        configs = {'dex': {}, 'cex': {}}

        # DEX 配置
        # StandX: 支援 Token 模式 (推薦) 和 錢包簽名模式
        standx_api_token = os.getenv('STANDX_API_TOKEN')
        standx_ed25519_key = os.getenv('STANDX_ED25519_PRIVATE_KEY')
        wallet_private_key = os.getenv('WALLET_PRIVATE_KEY')

        if standx_api_token and standx_ed25519_key:
            # Token 模式 (推薦)
            configs['dex']['standx'] = {
                'name': 'StandX',
                'configured': True,
                'auth_mode': 'token',
                'api_token_masked': self._mask_key(standx_api_token),
                'ed25519_key_masked': self._mask_key(standx_ed25519_key),
                'testnet': os.getenv('STANDX_TESTNET', 'false').lower() == 'true'
            }
        elif wallet_private_key:
            # 錢包簽名模式 (舊方式)
            configs['dex']['standx'] = {
                'name': 'StandX',
                'configured': True,
                'auth_mode': 'wallet',
                'private_key_masked': self._mask_key(wallet_private_key),
                'address': os.getenv('WALLET_ADDRESS', ''),
                'testnet': os.getenv('STANDX_TESTNET', 'false').lower() == 'true'
            }

        if os.getenv('GRVT_API_KEY'):
            configs['dex']['grvt'] = {
                'name': 'GRVT',
                'configured': True,
                'api_key_masked': self._mask_key(os.getenv('GRVT_API_KEY', '')),
                'trading_account_id': os.getenv('GRVT_TRADING_ACCOUNT_ID', ''),
                'testnet': os.getenv('GRVT_TESTNET', 'false').lower() == 'true'
            }

        # CEX 配置
        for exchange in ['binance', 'okx', 'bitget', 'bybit']:
            api_key = os.getenv(f'{exchange.upper()}_API_KEY')
            if api_key:
                config = {
                    'name': exchange.title(),
                    'configured': True,
                    'api_key_masked': self._mask_key(api_key),
                    'testnet': os.getenv(f'{exchange.upper()}_TESTNET', 'false').lower() == 'true'
                }
                if exchange in ['okx', 'bitget']:
                    passphrase = os.getenv(f'{exchange.upper()}_PASSPHRASE')
                    if passphrase:
                        config['passphrase_masked'] = self._mask_key(passphrase)
                configs['cex'][exchange] = config

        return configs

    def save_config(self, exchange_name: str, exchange_type: str, config: dict, testnet: bool = False):
        """保存配置並立即啟動監控"""
        # 使用 quote_mode='never' 避免添加引號
        if exchange_type == 'dex':
            if exchange_name == 'standx':
                # 支援兩種認證模式
                auth_mode = config.get('auth_mode', 'token')
                if auth_mode == 'token':
                    # Token 模式
                    set_key(self.env_file, 'STANDX_API_TOKEN', config.get('api_token', ''), quote_mode='never')
                    set_key(self.env_file, 'STANDX_ED25519_PRIVATE_KEY', config.get('ed25519_private_key', ''), quote_mode='never')
                    # 清除舊的錢包模式配置
                    unset_key(self.env_file, 'WALLET_PRIVATE_KEY')
                    unset_key(self.env_file, 'WALLET_ADDRESS')
                else:
                    # 錢包簽名模式
                    set_key(self.env_file, 'WALLET_PRIVATE_KEY', config.get('private_key', ''), quote_mode='never')
                    set_key(self.env_file, 'WALLET_ADDRESS', config.get('address', ''), quote_mode='never')
                    # 清除 Token 模式配置
                    unset_key(self.env_file, 'STANDX_API_TOKEN')
                    unset_key(self.env_file, 'STANDX_ED25519_PRIVATE_KEY')
                set_key(self.env_file, 'STANDX_TESTNET', str(testnet).lower(), quote_mode='never')
            elif exchange_name == 'grvt':
                set_key(self.env_file, 'GRVT_API_KEY', config.get('api_key', ''), quote_mode='never')
                set_key(self.env_file, 'GRVT_API_SECRET', config.get('api_secret', ''), quote_mode='never')
                set_key(self.env_file, 'GRVT_TRADING_ACCOUNT_ID', config.get('trading_account_id', ''), quote_mode='never')
                set_key(self.env_file, 'GRVT_TESTNET', str(testnet).lower(), quote_mode='never')
        else:
            prefix = exchange_name.upper()
            set_key(self.env_file, f'{prefix}_API_KEY', config.get('api_key', ''), quote_mode='never')
            set_key(self.env_file, f'{prefix}_API_SECRET', config.get('api_secret', ''), quote_mode='never')
            set_key(self.env_file, f'{prefix}_TESTNET', str(testnet).lower(), quote_mode='never')

            if exchange_name in ['okx', 'bitget']:
                passphrase = config.get('passphrase', '')
                if passphrase:
                    set_key(self.env_file, f'{prefix}_PASSPHRASE', passphrase, quote_mode='never')

        load_dotenv(self.env_file, override=True)

    def delete_config(self, exchange_name: str, exchange_type: str):
        """刪除配置"""
        if exchange_type == 'dex':
            if exchange_name == 'standx':
                # 刪除兩種模式的所有配置
                keys = [
                    'STANDX_API_TOKEN', 'STANDX_ED25519_PRIVATE_KEY',  # Token 模式
                    'WALLET_PRIVATE_KEY', 'WALLET_ADDRESS',  # 錢包模式
                    'STANDX_TESTNET'
                ]
            else:  # grvt
                keys = ['GRVT_API_KEY', 'GRVT_API_SECRET', 'GRVT_TRADING_ACCOUNT_ID', 'GRVT_TESTNET']
        else:
            prefix = exchange_name.upper()
            keys = [f'{prefix}_API_KEY', f'{prefix}_API_SECRET', f'{prefix}_TESTNET']
            if exchange_name in ['okx', 'bitget']:
                keys.append(f'{prefix}_PASSPHRASE')

        for key in keys:
            unset_key(self.env_file, key)
            # 同時從環境變量中刪除
            if key in os.environ:
                del os.environ[key]

        load_dotenv(self.env_file, override=True)

    @staticmethod
    def _mask_key(key: str) -> str:
        """遮罩敏感信息"""
        if len(key) <= 8:
            return '*' * len(key)
        return key[:4] + '*' * (len(key) - 8) + key[-4:]
