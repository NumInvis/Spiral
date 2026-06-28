@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ==========================================
echo   Spiral 高考志愿 Agent 一键启动
echo ==========================================
echo.

if exist .env (
    for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
        if "%%a"=="WINCODE_API_KEY" set "WINCODE_API_KEY=%%b"
    )
)

if not defined WINCODE_API_KEY (
    echo [提示] 未检测到 WINCODE_API_KEY 环境变量。
    set /p KEY="请输入 WinCode API Key（直接回车则跳过 LLM 增强）: "
    if not "!KEY!"=="" (
        set "WINCODE_API_KEY=!KEY!"
        echo WINCODE_API_KEY=!KEY!>> .env
        echo [OK] API Key 已保存到 .env，下次启动自动加载。
    ) else (
        echo [OK] 跳过 LLM 增强，使用规则解析。
    )
    echo.
)

python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.13+ 并添加到 PATH。
    pause
    exit /b 1
)

node --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Node.js，请先安装 Node.js 20+ 并添加到 PATH。
    pause
    exit /b 1
)

cd backend

if not exist venv (
    echo [1/5] 创建 Python 虚拟环境...
    python -m venv venv
    if errorlevel 1 (
        echo [错误] 虚拟环境创建失败。
        pause
        exit /b 1
    )
)

echo [2/5] 激活虚拟环境并安装依赖...
call venv\Scripts\activate.bat
python -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo [错误] Python 依赖安装失败。
    pause
    exit /b 1
)

if not exist gaokao.db (
    echo [3/5] 初始化 SQLite 数据库（首次运行较慢）...
    set SPIRAL_SKIP_RAG_SEED=1
    python seed_data.py
    if errorlevel 1 (
        echo [错误] 数据库初始化失败。
        pause
        exit /b 1
    )
) else (
    echo [3/5] 数据库已存在，跳过初始化。
)

echo [4/5] 启动后端服务...
start "Spiral Backend" cmd /k "call venv\Scripts\activate.bat && python main.py"

cd ..\frontend

if not exist node_modules (
    echo [5/5] 安装前端依赖（首次运行较慢）...
    call npm install
    if errorlevel 1 (
        echo [错误] 前端依赖安装失败。
        pause
        exit /b 1
    )
) else (
    echo [5/5] 前端依赖已安装，跳过。
)

echo 启动前端开发服务器...
start "Spiral Frontend" cmd /k "npm run dev"

echo.
echo ==========================================
echo  后端地址: http://localhost:11678/docs
echo  前端地址: http://localhost:1678
echo ==========================================
echo.

if "%~1"=="--no-pause" (
    ping -n 4 127.0.0.1 >nul
) else (
    echo 按任意键关闭本窗口（后端和前端服务仍会继续运行）...
    pause >nul
)
