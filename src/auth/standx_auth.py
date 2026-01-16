"""
StandX Authentication Module

Implements authentication for StandX Perps API:

方式 1: Token 模式 (推薦)
  - 直接使用 StandX 提供的 API Token + Ed25519 Private Key
  - 無需錢包簽名

方式 2: 錢包簽名模式 (舊方式)
  1. Generate ed25519 key pair
  2. Obtain signature data
  3. Sign with wallet
  4. Get access token
  5. Sign request bodies
"""

import time
import json
import base64
import base58
from typing import Dict, Tuple, Optional, Callable, Awaitable
from uuid import uuid4
from nacl.signing import SigningKey
import requests


class StandXAuth:
    """
    StandX API Authentication Manager

    Handles JWT token generation and request signing for StandX Perps API.

    支援兩種認證方式:
    1. Token 模式: 直接使用 API Token + Ed25519 Private Key
    2. 錢包簽名模式: 使用錢包私鑰進行簽名認證
    """

    def __init__(
        self,
        base_url: str = "https://api.standx.com",
        api_token: Optional[str] = None,
        ed25519_private_key: Optional[str] = None,
    ):
        """
        Initialize the authentication manager.

        Args:
            base_url: StandX API base URL
            api_token: API Token (Token 模式)
            ed25519_private_key: Ed25519 Private Key (Token 模式)
        """
        self.base_url = base_url

        # Token storage
        self.access_token: Optional[str] = None
        self.token_expiry: Optional[int] = None

        # Token 模式: 使用提供的 API Token 和 Ed25519 Private Key
        if api_token and ed25519_private_key:
            self.access_token = api_token
            self.token_expiry = int(time.time()) + 86400 * 365  # 假設 1 年有效

            # 從提供的 private key 恢復 signing key
            self.signing_key = self._load_ed25519_key(ed25519_private_key)
            self.verify_key = self.signing_key.verify_key
            self.request_id = base58.b58encode(bytes(self.verify_key)).decode('utf-8')
            self._token_mode = True
        else:
            # 錢包簽名模式: 生成新的 ed25519 key pair
            self.signing_key = SigningKey.generate()
            self.verify_key = self.signing_key.verify_key
            self.request_id = base58.b58encode(bytes(self.verify_key)).decode('utf-8')
            self._token_mode = False

    def _load_ed25519_key(self, private_key_str: str) -> SigningKey:
        """
        從字符串加載 Ed25519 private key

        支援格式:
        - Base58 編碼 (StandX 默認)
        - Base64 編碼
        - Hex 編碼 (帶或不帶 0x 前綴)
        """
        # 移除空白
        key_str = private_key_str.strip()

        # 嘗試 Base58 解碼 (StandX 默認格式)
        try:
            key_bytes = base58.b58decode(key_str)
            if len(key_bytes) == 32:
                return SigningKey(key_bytes)
            elif len(key_bytes) == 64:
                # 有些格式包含 public key，取前 32 bytes
                return SigningKey(key_bytes[:32])
        except Exception:
            pass

        # 嘗試 Base64 解碼
        try:
            key_bytes = base64.b64decode(key_str)
            if len(key_bytes) == 32:
                return SigningKey(key_bytes)
            elif len(key_bytes) == 64:
                return SigningKey(key_bytes[:32])
        except Exception:
            pass

        # 嘗試 Hex 解碼
        try:
            if key_str.startswith('0x'):
                key_str = key_str[2:]
            key_bytes = bytes.fromhex(key_str)
            if len(key_bytes) == 32:
                return SigningKey(key_bytes)
            elif len(key_bytes) == 64:
                return SigningKey(key_bytes[:32])
        except Exception:
            pass

        raise ValueError(
            f"無法解析 Ed25519 private key，支援格式: Base58, Base64, Hex。"
            f"長度應為 32 bytes (64 hex chars)。收到: {len(key_str)} chars"
        )

    @property
    def is_token_mode(self) -> bool:
        """是否使用 Token 模式認證"""
        return self._token_mode
    
    async def authenticate(
        self,
        chain: str,
        wallet_address: str,
        sign_message_fn: Callable[[str], Awaitable[str]],
        expires_seconds: int = 604800
    ) -> Dict[str, any]:
        """
        Complete authentication flow.
        
        Args:
            chain: Blockchain network ('bsc' or 'solana')
            wallet_address: Wallet address
            sign_message_fn: Async function to sign messages with wallet
            expires_seconds: Token expiration time (default: 7 days)
            
        Returns:
            Login response containing token and user info
        """
        # Step 1: Get signature data from server
        signed_data_jwt = await self._prepare_signin(chain, wallet_address)
        
        # Step 2: Parse JWT to get message
        payload = self._parse_jwt(signed_data_jwt)
        
        # Step 3: Sign message with wallet
        signature = await sign_message_fn(payload['message'])
        
        # Step 4: Login and get access token
        login_response = await self._login(
            chain, signature, signed_data_jwt, expires_seconds
        )
        
        # Store token
        self.access_token = login_response['token']
        self.token_expiry = int(time.time()) + expires_seconds
        
        return login_response
    
    async def _prepare_signin(self, chain: str, address: str) -> str:
        """
        Step 1: Request signature data from server.
        
        Args:
            chain: Blockchain network
            address: Wallet address
            
        Returns:
            Signed data JWT string
        """
        url = f"{self.base_url}/v1/offchain/prepare-signin?chain={chain}"
        headers = {"Content-Type": "application/json"}
        data = {
            "address": address,
            "requestId": self.request_id
        }
        
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        
        result = response.json()
        if not result.get('success'):
            raise Exception("Failed to prepare sign-in")
        
        return result['signedData']
    
    async def _login(
        self,
        chain: str,
        signature: str,
        signed_data: str,
        expires_seconds: int
    ) -> Dict[str, any]:
        """
        Step 2: Login with signature to get access token.
        
        Args:
            chain: Blockchain network
            signature: Wallet signature
            signed_data: Signed data JWT from prepare_signin
            expires_seconds: Token expiration time
            
        Returns:
            Login response with token
        """
        url = f"{self.base_url}/v1/offchain/login?chain={chain}"
        headers = {"Content-Type": "application/json"}
        data = {
            "signature": signature,
            "signedData": signed_data,
            "expiresSeconds": expires_seconds
        }
        
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        
        return response.json()
    
    def sign_request(self, payload: str) -> Dict[str, str]:
        """
        Generate body signature headers for API requests.
        
        Args:
            payload: Request body as JSON string
            
        Returns:
            Dictionary of signature headers
        """
        version = "v1"
        request_id = str(uuid4())
        timestamp = int(time.time() * 1000)  # milliseconds
        
        # Build message: {version},{id},{timestamp},{payload}
        message = f"{version},{request_id},{timestamp},{payload}"
        
        # Sign with ed25519 private key
        signed = self.signing_key.sign(message.encode('utf-8'))
        
        # Base64 encode signature
        signature = base64.b64encode(signed.signature).decode('utf-8')
        
        return {
            "x-request-sign-version": version,
            "x-request-id": request_id,
            "x-request-timestamp": str(timestamp),
            "x-request-signature": signature
        }
    
    def get_auth_headers(self, payload: Optional[str] = None) -> Dict[str, str]:
        """
        Get complete authentication headers for API requests.
        
        Args:
            payload: Optional request body for signature
            
        Returns:
            Dictionary of all required headers
        """
        if not self.access_token:
            raise Exception("Not authenticated. Call authenticate() first.")
        
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        # Add body signature if payload provided
        if payload:
            signature_headers = self.sign_request(payload)
            headers.update(signature_headers)
        
        return headers
    
    def is_token_valid(self) -> bool:
        """Check if current token is still valid."""
        if not self.access_token or not self.token_expiry:
            return False
        
        # Add 5 minute buffer before expiry
        return int(time.time()) < (self.token_expiry - 300)
    
    @staticmethod
    def _parse_jwt(token: str) -> Dict[str, any]:
        """
        Parse JWT token payload.
        
        Args:
            token: JWT token string
            
        Returns:
            Decoded payload dictionary
        """
        # Split token and get payload (middle part)
        parts = token.split('.')
        if len(parts) != 3:
            raise ValueError("Invalid JWT format")
        
        payload_b64 = parts[1]
        
        # Add padding if needed
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += '=' * padding
        
        # Decode base64
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        
        return json.loads(payload_bytes.decode('utf-8'))


class AsyncStandXAuth(StandXAuth):
    """
    Async version using aiohttp for better performance.

    使用方式:

    # Token 模式 (推薦)
    auth = AsyncStandXAuth(
        api_token="eyJhbGci...",
        ed25519_private_key="3cqUwpXqkE9gA5CmSDBKCJdv8TytJERNUy9im5tASjSX"
    )
    # 無需調用 authenticate()，直接使用

    # 錢包簽名模式
    auth = AsyncStandXAuth()
    await auth.authenticate(chain="bsc", wallet_address="0x...", sign_message_fn=sign_fn)
    """

    def __init__(
        self,
        base_url: str = "https://api.standx.com",
        api_token: Optional[str] = None,
        ed25519_private_key: Optional[str] = None,
    ):
        super().__init__(
            base_url=base_url,
            api_token=api_token,
            ed25519_private_key=ed25519_private_key,
        )

    async def _prepare_signin(self, chain: str, address: str) -> str:
        """Async version of prepare_signin."""
        import aiohttp

        url = f"{self.base_url}/v1/offchain/prepare-signin?chain={chain}"
        headers = {
            "Content-Type": "application/json",
            "Accept-Encoding": "gzip, deflate"  # 不要 brotli
        }
        data = {
            "address": address,
            "requestId": self.request_id
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as response:
                response.raise_for_status()
                result = await response.json()
                
                if not result.get('success'):
                    raise Exception("Failed to prepare sign-in")
                
                return result['signedData']
    
    async def _login(
        self,
        chain: str,
        signature: str,
        signed_data: str,
        expires_seconds: int
    ) -> Dict[str, any]:
        """Async version of login."""
        import aiohttp

        url = f"{self.base_url}/v1/offchain/login?chain={chain}"
        headers = {
            "Content-Type": "application/json",
            "Accept-Encoding": "gzip, deflate"  # 不要 brotli
        }
        data = {
            "signature": signature,
            "signedData": signed_data,
            "expiresSeconds": expires_seconds
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Login failed ({response.status}): {error_text}")
                return await response.json()
