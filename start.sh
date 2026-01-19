#!/bin/bash
# StandX Market Maker 一鍵啟動腳本
# 用法: ./start.sh [--dev]
#   --dev: 開發模式（前後端分開運行，支援熱重載）
#   無參數: 生產模式（構建前端後由 FastAPI 服務）

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

cd "$SCRIPT_DIR"

# 顏色輸出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 檢查 Python 環境
check_python() {
    if ! command -v python &> /dev/null && ! command -v python3 &> /dev/null; then
        log_error "Python not found. Please install Python 3.8+"
        exit 1
    fi
    # 優先使用 python3
    if command -v python3 &> /dev/null; then
        PYTHON_CMD="python3"
    else
        PYTHON_CMD="python"
    fi
}

# 檢查 Node.js 環境
check_node() {
    if ! command -v npm &> /dev/null; then
        log_error "npm not found. Please install Node.js 18+"
        exit 1
    fi
}

# 設置 Python 虛擬環境
setup_venv() {
    if [ ! -d "venv" ]; then
        log_info "Creating Python virtual environment..."
        $PYTHON_CMD -m venv venv
        log_success "Virtual environment created"
    fi

    # 激活虛擬環境
    source venv/bin/activate

    # 檢查依賴
    if ! python -c "import fastapi" 2>/dev/null; then
        log_info "Installing Python dependencies..."
        pip install -r requirements.txt -q
        log_success "Dependencies installed"
    fi
}

# 檢查 .env 文件
check_env() {
    if [ ! -f ".env" ]; then
        if [ -f ".env.example" ]; then
            log_info "Creating .env from .env.example..."
            cp .env.example .env
            log_success ".env file created"
        fi
    fi
}

# 安裝前端依賴
install_frontend_deps() {
    if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
        log_info "Installing frontend dependencies..."
        cd "$FRONTEND_DIR"
        npm install
        cd "$SCRIPT_DIR"
    fi
}

# 構建前端
build_frontend() {
    log_info "Building frontend..."
    cd "$FRONTEND_DIR"
    npm run build
    cd "$SCRIPT_DIR"
    log_success "Frontend built to src/web/frontend_dist/"
}

# 開發模式
start_dev() {
    log_info "Starting in DEVELOPMENT mode..."
    check_python
    check_node
    setup_venv
    check_env
    install_frontend_deps

    log_info "Starting backend on http://localhost:9999"
    log_info "Starting frontend on http://localhost:3000"
    echo ""
    log_warning "Press Ctrl+C to stop both servers"
    echo ""

    # 使用 trap 來捕獲 Ctrl+C 並清理子進程
    trap 'kill $(jobs -p) 2>/dev/null; exit' INT TERM

    # 啟動後端
    python -m src.web.auto_dashboard &
    BACKEND_PID=$!

    # 等待後端啟動
    sleep 2

    # 啟動前端開發伺服器
    cd "$FRONTEND_DIR"
    npm run dev &
    FRONTEND_PID=$!
    cd "$SCRIPT_DIR"

    log_success "Development servers started!"
    echo ""
    echo "  Backend API:  http://localhost:9999"
    echo "  Frontend:     http://localhost:3000"
    echo "  API Docs:     http://localhost:9999/docs"
    echo ""

    # 等待任一進程退出
    wait
}

# 生產模式
start_prod() {
    log_info "Starting in PRODUCTION mode..."
    check_python
    check_node
    setup_venv
    check_env
    install_frontend_deps

    # 檢查是否需要構建前端
    if [ ! -f "$SCRIPT_DIR/src/web/frontend_dist/index.html" ]; then
        build_frontend
    else
        log_info "Frontend already built. Use --rebuild to force rebuild."
    fi

    log_info "Starting server on http://localhost:9999"
    echo ""

    # 啟動後端（會同時服務前端）
    python -m src.web.auto_dashboard
}

# 主函數
main() {
    echo ""
    echo "========================================="
    echo "  StandX Market Maker Dashboard"
    echo "========================================="
    echo ""

    case "${1:-}" in
        --dev)
            start_dev
            ;;
        --rebuild)
            check_python
            check_node
            setup_venv
            check_env
            install_frontend_deps
            build_frontend
            start_prod
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --dev       Development mode (hot reload enabled)"
            echo "  --rebuild   Force rebuild frontend before starting"
            echo "  --help      Show this help message"
            echo ""
            echo "Without options: Production mode (build frontend once, serve via FastAPI)"
            ;;
        *)
            start_prod
            ;;
    esac
}

main "$@"
