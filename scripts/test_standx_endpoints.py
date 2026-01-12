"""
測試 StandX API 端點

直接調用 API 確認端點是否正確
"""
import requests
import os
from dotenv import load_dotenv
from eth_account import Account
from eth_account.messages import encode_defunct

load_dotenv()

def main():
    print("=" * 60)
    print("測試 StandX API 端點")
    print("=" * 60)
    
    # 準備認證
    private_key = os.getenv("WALLET_PRIVATE_KEY")
    account = Account.from_key(private_key)
    wallet_address = account.address
    
    print(f"\n錢包地址: {wallet_address}")
    
    # 測試端點
    base_url = "https://perps.standx.com"
    
    print("\n1. 測試訂單簿端點...")
    try:
        response = requests.get(f"{base_url}/api/query_depth_book", params={"symbol": "BTC-USD"})
        print(f"   狀態碼: {response.status_code}")
        if response.ok:
            data = response.json()
            print(f"   ✅ 成功 - Bids: {len(data.get('bids', []))}, Asks: {len(data.get('asks', []))}")
        else:
            print(f"   ❌ 失敗: {response.text}")
    except Exception as e:
        print(f"   ❌ 錯誤: {e}")
    
    print("\n2. 測試餘額端點（需要認證）...")
    print("   跳過 - 需要完整的認證流程")
    
    print("\n3. 測試價格查詢端點...")
    try:
        response = requests.get(f"{base_url}/api/query_symbol_price", params={"symbol": "BTC-USD"})
        print(f"   狀態碼: {response.status_code}")
        if response.ok:
            data = response.json()
            print(f"   ✅ 成功")
            print(f"   Mark Price: ${data.get('mark_price')}")
            print(f"   Index Price: ${data.get('index_price')}")
            print(f"   Last Price: ${data.get('last_price')}")
        else:
            print(f"   ❌ 失敗: {response.text}")
    except Exception as e:
        print(f"   ❌ 錯誤: {e}")
    
    print("\n4. 列出所有可用端點...")
    endpoints = [
        "/api/health",
        "/api/query_depth_book",
        "/api/query_symbol_price",
        "/api/query_balance",  # 需要認證
        "/api/query_positions",  # 需要認證
        "/api/query_open_orders",  # 需要認證
    ]
    
    for endpoint in endpoints:
        if "query_balance" in endpoint or "query_positions" in endpoint or "query_open" in endpoint:
            print(f"   {endpoint} - [需要認證]")
        else:
            try:
                response = requests.get(f"{base_url}{endpoint}")
                if response.ok:
                    print(f"   ✅ {endpoint} - HTTP {response.status_code}")
                else:
                    print(f"   ⚠️  {endpoint} - HTTP {response.status_code}")
            except Exception as e:
                print(f"   ❌ {endpoint} - 錯誤: {e}")

if __name__ == "__main__":
    main()
