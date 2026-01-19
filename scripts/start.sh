#!/bin/bash
# 一鍵啟動前後端
# 用法: ./scripts/start.sh [--dev]
#   --dev: 開發模式（前後端分開運行，支援熱重載）
#   無參數: 生產模式（構建前端後由 FastAPI 服務）

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

cd "$PROJECT_ROOT"

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
    if ! command -v python &> /dev/null; then
        log_error "Python not found. Please install Python 3.8+"
        exit 1
    fi
}

# 檢查 Node.js 環境
check_node() {
    if ! command -v npm &> /dev/null; then
        log_error "npm not found. Please install Node.js 18+"
        exit 1
    fi
}

# 安裝前端依賴
install_frontend_deps() {
    if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
        log_info "Installing frontend dependencies..."
        cd "$FRONTEND_DIR"
        npm install
        cd "$PROJECT_ROOT"
    fi
}

# 構建前端
build_frontend() {
    log_info "Building frontend..."
    cd "$FRONTEND_DIR"
    npm run build
    cd "$PROJECT_ROOT"
    log_success "Frontend built to src/web/frontend_dist/"
}

# 開發模式
start_dev() {
    log_info "Starting in DEVELOPMENT mode..."
    check_python
    check_node
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
    cd "$PROJECT_ROOT"

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
    install_frontend_deps

    # 檢查是否需要構建前端
    if [ ! -f "$PROJECT_ROOT/src/web/frontend_dist/index.html" ]; then
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
            check_node
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
