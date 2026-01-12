#!/bin/bash
# 統一啟動腳本 - 自動激活虛擬環境並運行系統

# 顏色定義
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 獲取腳本所在目錄
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 檢查虛擬環境
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}⚠️  虛擬環境不存在，正在創建...${NC}"
    python3 -m venv venv
    echo -e "${GREEN}✅ 虛擬環境已創建${NC}"
fi

# 激活虛擬環境
echo -e "${BLUE}🔄 激活虛擬環境...${NC}"
source venv/bin/activate

# 檢查依賴
if ! python -c "import aiohttp" 2>/dev/null; then
    echo -e "${YELLOW}⚠️  檢測到缺失依賴，正在安裝...${NC}"
    pip install -r requirements.txt -q
    echo -e "${GREEN}✅ 依賴安裝完成${NC}"
fi

# 檢查 .env 文件
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}⚠️  .env 文件不存在${NC}"
    if [ -f ".env.example" ]; then
        echo -e "${BLUE}   正在從 .env.example 創建 .env...${NC}"
        cp .env.example .env
        echo -e "${GREEN}✅ .env 文件已創建${NC}"
        echo -e "${YELLOW}💡 提示：請運行 'python arbitrage.py config' 配置交易所${NC}"
    fi
fi

# 運行主程序
echo ""
python arbitrage.py "$@"

# 保持在虛擬環境中（如果是互動模式）
if [ $# -eq 0 ]; then
    exec bash
fi
