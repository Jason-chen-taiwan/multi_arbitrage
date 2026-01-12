#!/usr/bin/env python3
"""
配置管理面板啟動腳本
Configuration Dashboard Startup Script

啟動 Web 配置管理面板，用於可視化管理交易所 API 配置
"""
import sys
import os
from pathlib import Path

# 添加項目根目錄到 Python 路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 導入配置面板模組
from src.web.config_dashboard import app, config_manager
import uvicorn


def main():
    """主函數"""
    print("\n" + "=" * 80)
    print("🔧 EXCHANGE CONFIGURATION DASHBOARD")
    print("=" * 80)
    print("\n📝 功能特色：")
    print("  ✅ 視覺化配置所有交易所")
    print("  ✅ 自動驗證配置正確性")
    print("  ✅ 安全的憑證遮罩顯示")
    print("  ✅ 支援 DEX（StandX, GRVT）和 CEX（Binance, OKX, Bitget, Bybit）")
    print("  ✅ 一鍵保存/刪除配置")
    print("  ✅ Testnet 模式切換")

    # 檢查 .env 文件是否存在
    env_file = project_root / ".env"
    if not env_file.exists():
        print("\n⚠️  警告：.env 文件不存在")
        print("   將自動創建 .env 文件")
        env_file.touch()
        print("   ✅ .env 文件已創建")

    # 顯示當前已配置的交易所
    configs = config_manager.get_all_configs()
    dex_count = len(configs['dex'])
    cex_count = len(configs['cex'])

    print(f"\n📊 當前配置狀態：")
    print(f"  DEX 交易所: {dex_count} 個已配置")
    print(f"  CEX 交易所: {cex_count} 個已配置")

    if dex_count + cex_count == 0:
        print("\n💡 提示：尚未配置任何交易所")
        print("   請在 Web 面板中添加您的交易所配置")

    print("\n" + "=" * 80)
    print("🚀 啟動配置面板...")
    print("=" * 80)
    print("\n📍 訪問地址：http://localhost:8001")
    print("\n⚠️  按 Ctrl+C 停止服務\n")

    # 啟動服務
    try:
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=8001,
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n\n👋 配置面板已停止")
    except Exception as e:
        print(f"\n\n❌ 啟動失敗：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
