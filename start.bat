@echo off
chcp 65001 >nul
title StandX Market Maker

echo.
echo ========================================
echo   StandX Market Maker 啟動腳本
echo ========================================
echo.

:: 獲取腳本所在目錄
cd /d "%~dp0"

:: 檢查虛擬環境
if not exist "venv" (
    echo [!] 虛擬環境不存在，正在創建...
    python -m venv venv
    if errorlevel 1 (
        echo [X] 創建虛擬環境失敗，請確認已安裝 Python
        pause
        exit /b 1
    )
    echo [OK] 虛擬環境已創建
)

:: 激活虛擬環境
echo [*] 激活虛擬環境...
call venv\Scripts\activate.bat

:: 檢查依賴
python -c "import fastapi" 2>nul
if errorlevel 1 (
    echo [!] 檢測到缺失依賴，正在安裝...
    pip install -r requirements.txt -q
    echo [OK] 依賴安裝完成
)

:: 檢查 .env 文件
if not exist ".env" (
    if exist ".env.example" (
        echo [*] 從 .env.example 創建 .env...
        copy .env.example .env >nul
        echo [OK] .env 文件已創建
    )
)

:: 啟動 Web Dashboard
echo.
echo ========================================
echo   啟動 Web Dashboard
echo   訪問: http://127.0.0.1:8888
echo ========================================
echo.

python -m uvicorn src.web.auto_dashboard:app --host 127.0.0.1 --port 8888

pause
