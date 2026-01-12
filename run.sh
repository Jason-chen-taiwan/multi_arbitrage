#!/bin/bash

# StandX Market Maker - 便捷啟動腳本
# 自動激活虛擬環境並運行相應命令

set -e

VENV_DIR="venv"

# 顏色定義
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 檢查虛擬環境
check_venv() {
    if [ ! -d "$VENV_DIR" ]; then
        echo -e "${RED}❌ 虛擬環境不存在${NC}"
        echo -e "${YELLOW}請先運行: ./setup.sh${NC}"
        exit 1
    fi
}

# 激活虛擬環境
activate_venv() {
    source "$VENV_DIR/bin/activate"
}

# 顯示幫助
show_help() {
    echo "=================================="
    echo "StandX Market Maker 啟動腳本"
    echo "=================================="
    echo ""
    echo "使用方法: ./run.sh [命令] [選項]"
    echo ""
    echo "命令:"
    echo "  setup              - 設置虛擬環境（首次使用）"
    echo "  test               - 運行測試（終端 Dashboard）"
    echo "  web                - 啟動 Web Dashboard 演示"
    echo "  dashboard          - 僅啟動 Web Dashboard Server"
    echo "  start [config]     - 啟動做市商"
    echo "  start-uptime       - 啟動 Uptime Program 做市商"
    echo "  install            - 安裝/更新依賴"
    echo "  clean              - 清理虛擬環境"
    echo "  shell              - 進入虛擬環境 shell"
    echo ""
    echo "範例:"
    echo "  ./run.sh setup                    # 首次設置"
    echo "  ./run.sh test                     # 測試終端 Dashboard"
    echo "  ./run.sh web                      # 測試 Web Dashboard"
    echo "  ./run.sh start-uptime             # 啟動 Uptime 策略"
    echo "  ./run.sh start config/config.yaml # 使用自定義配置"
    echo ""
}

# 主邏輯
case "$1" in
    setup)
        echo -e "${BLUE}🚀 開始設置虛擬環境...${NC}"
        ./setup.sh
        ;;
    
    test)
        check_venv
        activate_venv
        echo -e "${BLUE}🧪 運行終端 Dashboard 測試...${NC}"
        python scripts/test_dashboard.py "${@:2}"
        ;;
    
    web)
        check_venv
        activate_venv
        echo -e "${BLUE}🌐 啟動 Web Dashboard 演示...${NC}"
        echo -e "${GREEN}訪問: http://localhost:8000${NC}"
        python scripts/demo_web_dashboard.py "${@:2}"
        ;;
    
    dashboard)
        check_venv
        activate_venv
        echo -e "${BLUE}🌐 啟動 Web Dashboard Server...${NC}"
        echo -e "${GREEN}訪問: http://localhost:8000${NC}"
        python scripts/run_dashboard.py "${@:2}"
        ;;
    
    start)
        check_venv
        activate_venv
        if [ -z "$2" ]; then
            echo -e "${BLUE}🚀 啟動做市商（默認配置）...${NC}"
            python scripts/run_mm.py
        else
            echo -e "${BLUE}🚀 啟動做市商（配置: $2）...${NC}"
            python scripts/run_mm.py "$2"
        fi
        ;;
    
    start-uptime)
        check_venv
        activate_venv
        echo -e "${BLUE}🎯 啟動 Uptime Program 做市商...${NC}"
        python scripts/run_mm.py config/uptime_config.yaml
        ;;
    
    install)
        check_venv
        activate_venv
        echo -e "${BLUE}📥 安裝/更新依賴...${NC}"
        pip install --upgrade pip
        pip install -r requirements.txt
        echo -e "${GREEN}✅ 依賴安裝完成${NC}"
        ;;
    
    clean)
        echo -e "${YELLOW}⚠️  將刪除虛擬環境: $VENV_DIR${NC}"
        read -p "確定要繼續嗎? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo -e "${BLUE}🗑️  清理虛擬環境...${NC}"
            rm -rf "$VENV_DIR"
            echo -e "${GREEN}✅ 清理完成${NC}"
            echo -e "${YELLOW}重新設置請運行: ./run.sh setup${NC}"
        fi
        ;;
    
    shell)
        check_venv
        echo -e "${BLUE}🐚 進入虛擬環境 shell...${NC}"
        echo -e "${YELLOW}提示: 輸入 'exit' 或按 Ctrl+D 退出${NC}"
        activate_venv
        exec $SHELL
        ;;
    
    help|--help|-h|"")
        show_help
        ;;
    
    *)
        echo -e "${RED}❌ 未知命令: $1${NC}"
        echo ""
        show_help
        exit 1
        ;;
esac
