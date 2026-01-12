#!/bin/bash

# StandX Market Maker - 虛擬環境設置腳本
# 此腳本會創建隔離的 Python 虛擬環境並安裝所有依賴

set -e  # 遇到錯誤立即退出

echo "=================================="
echo "StandX Market Maker 環境設置"
echo "=================================="

# 檢查 Python 版本
PYTHON_CMD=""
if command -v python3.11 &> /dev/null; then
    PYTHON_CMD="python3.11"
elif command -v python3.10 &> /dev/null; then
    PYTHON_CMD="python3.10"
elif command -v python3.9 &> /dev/null; then
    PYTHON_CMD="python3.9"
elif command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
else
    echo "❌ 錯誤: 找不到 Python 3.9+ 版本"
    echo "請安裝 Python 3.9 或更高版本"
    exit 1
fi

echo "✅ 找到 Python: $($PYTHON_CMD --version)"

# 創建虛擬環境
VENV_DIR="venv"

if [ -d "$VENV_DIR" ]; then
    echo "⚠️  虛擬環境已存在: $VENV_DIR"
    read -p "是否要刪除並重新創建? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "🗑️  刪除舊的虛擬環境..."
        rm -rf "$VENV_DIR"
    else
        echo "📦 使用現有虛擬環境"
    fi
fi

if [ ! -d "$VENV_DIR" ]; then
    echo "📦 創建虛擬環境..."
    $PYTHON_CMD -m venv "$VENV_DIR"
    echo "✅ 虛擬環境創建完成"
fi

# 激活虛擬環境
echo "🔄 激活虛擬環境..."
source "$VENV_DIR/bin/activate"

# 升級 pip
echo "⬆️  升級 pip..."
pip install --upgrade pip setuptools wheel

# 安裝依賴
echo "📥 安裝依賴套件..."
pip install -r requirements.txt

echo ""
echo "=================================="
echo "✅ 環境設置完成！"
echo "=================================="
echo ""
echo "📝 下一步："
echo "   1. 配置環境變數: cp .env.example .env"
echo "   2. 編輯 .env 填入您的私鑰"
echo "   3. 運行測試: ./run.sh test"
echo "   4. 啟動做市商: ./run.sh start"
echo ""
echo "💡 提示："
echo "   - 啟動虛擬環境: source venv/bin/activate"
echo "   - 退出虛擬環境: deactivate"
echo "   - 使用 run.sh 腳本會自動激活虛擬環境"
echo ""
