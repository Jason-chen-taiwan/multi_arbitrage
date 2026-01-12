"""
Test StandX Connection
Quick script to verify StandX adapter authentication
"""
import asyncio
import os
from dotenv import load_dotenv
from src.adapters.factory import create_adapter

async def test_connection():
    """Test connection to StandX"""

    # Load environment variables
    load_dotenv()

    # Get credentials
    private_key = os.getenv("WALLET_PRIVATE_KEY")
    if not private_key:
        print("❌ WALLET_PRIVATE_KEY not found in .env")
        return False

    print("=" * 60)
    print("🧪 Testing StandX Connection")
    print("=" * 60)

    try:
        # Create adapter
        config = {
            "exchange_name": "standx",
            "private_key": private_key,
            "chain": os.getenv("CHAIN", "bsc"),
            "base_url": os.getenv("STANDX_BASE_URL", "https://api.standx.com"),
            "perps_url": os.getenv("STANDX_PERPS_URL", "https://perps.standx.com")
        }

        print(f"📝 Config:")
        print(f"  - Chain: {config['chain']}")
        print(f"  - Base URL: {config['base_url']}")
        print(f"  - Perps URL: {config['perps_url']}")
        print()

        adapter = create_adapter(config)
        print(f"✅ Adapter created: {adapter.__class__.__name__}")
        print(f"📍 Wallet Address: {adapter.wallet_address}")
        print()

        # Test connection
        print("🔌 Attempting to connect...")
        success = await adapter.connect()

        if success:
            print("=" * 60)
            print("✅ CONNECTION SUCCESSFUL!")
            print("=" * 60)
            print()

            # Test balance fetch
            try:
                print("💰 Fetching balance...")
                balance = await adapter.get_balance()
                print(f"  Total Balance: ${balance.total_balance}")
                print(f"  Available: ${balance.available_balance}")
                print(f"  Used Margin: ${balance.used_margin}")
                print()
            except Exception as e:
                print(f"⚠️  Balance fetch failed: {e}")
                print()

            # Test positions fetch
            try:
                print("📊 Fetching positions...")
                positions = await adapter.get_positions()
                print(f"  Open Positions: {len(positions)}")
                for pos in positions:
                    print(f"    - {pos.symbol}: {pos.side} {pos.size} @ ${pos.entry_price}")
                print()
            except Exception as e:
                print(f"⚠️  Positions fetch failed: {e}")
                print()

            # Disconnect
            await adapter.disconnect()
            print("👋 Disconnected successfully")
            return True
        else:
            print("=" * 60)
            print("❌ CONNECTION FAILED")
            print("=" * 60)
            return False

    except Exception as e:
        print("=" * 60)
        print(f"❌ ERROR: {e}")
        print("=" * 60)
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    result = asyncio.run(test_connection())
    exit(0 if result else 1)
