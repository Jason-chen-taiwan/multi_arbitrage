@echo off
chcp 65001 >nul
title StandX Market Maker

echo.
echo =========================================
echo   StandX Market Maker Dashboard
echo =========================================
echo.

:: 獲取腳本所在目錄
cd /d "%~dp0"

:: 檢查參數
if "%1"=="--dev" goto :dev_mode
if "%1"=="--rebuild" goto :rebuild_mode
if "%1"=="--help" goto :show_help
if "%1"=="-h" goto :show_help
goto :prod_mode

:show_help
echo Usage: start.bat [OPTIONS]
echo.
echo Options:
echo   --dev       Development mode (hot reload enabled)
echo   --rebuild   Force rebuild frontend before starting
echo   --help      Show this help message
echo.
echo Without options: Production mode (build frontend once, serve via FastAPI)
goto :end

:check_python
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.8+
    pause
    exit /b 1
)
goto :eof

:check_node
where npm >nul 2>nul
if errorlevel 1 (
    echo [ERROR] npm not found. Please install Node.js 18+
    pause
    exit /b 1
)
goto :eof

:setup_venv
if not exist "venv" (
    echo [INFO] Creating Python virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment
        pause
        exit /b 1
    )
    echo [SUCCESS] Virtual environment created
)

:: 激活虛擬環境
call venv\Scripts\activate.bat

:: 檢查依賴
python -c "import fastapi" 2>nul
if errorlevel 1 (
    echo [INFO] Installing Python dependencies...
    pip install -r requirements.txt -q
    echo [SUCCESS] Dependencies installed
)
goto :eof

:check_env
if not exist ".env" (
    if exist ".env.example" (
        echo [INFO] Creating .env from .env.example...
        copy .env.example .env >nul
        echo [SUCCESS] .env file created
    )
)
goto :eof

:install_frontend_deps
if not exist "frontend\node_modules" (
    echo [INFO] Installing frontend dependencies...
    cd frontend
    call npm install
    cd ..
)
goto :eof

:build_frontend
echo [INFO] Building frontend...
cd frontend
call npm run build
cd ..
echo [SUCCESS] Frontend built to src\web\frontend_dist\
goto :eof

:dev_mode
echo [INFO] Starting in DEVELOPMENT mode...
call :check_python
call :check_node
call :setup_venv
call :check_env
call :install_frontend_deps

echo.
echo [INFO] Starting backend on http://localhost:9999
echo [INFO] Starting frontend on http://localhost:3000
echo.
echo [WARNING] Press Ctrl+C to stop servers
echo.

:: 啟動後端（背景）
start "Backend" cmd /c "venv\Scripts\activate.bat && python -m src.web.auto_dashboard"

:: 等待後端啟動
timeout /t 2 /nobreak >nul

:: 啟動前端開發伺服器
cd frontend
call npm run dev
cd ..
goto :end

:rebuild_mode
echo [INFO] Rebuilding frontend...
call :check_python
call :check_node
call :setup_venv
call :check_env
call :install_frontend_deps
call :build_frontend
goto :start_server

:prod_mode
echo [INFO] Starting in PRODUCTION mode...
call :check_python
call :check_node
call :setup_venv
call :check_env
call :install_frontend_deps

:: 檢查是否需要構建前端
if not exist "src\web\frontend_dist\index.html" (
    call :build_frontend
) else (
    echo [INFO] Frontend already built. Use --rebuild to force rebuild.
)

:start_server
echo.
echo [INFO] Starting server on http://localhost:9999
echo.

python -m src.web.auto_dashboard

:end
pause
