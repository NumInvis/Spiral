@echo off
chcp 437 >nul
setlocal

set "FRONTEND_DIR=D:\Spiral\frontend"
set "FRONTEND_PORT=1678"
set "LOG_DIR=D:\Spiral\logs"

REM 优先使用系统 PATH 中的 node/npm，去掉对 kimi-desktop 运行时的隐式依赖
where npm >nul 2>&1
if %errorlevel%==0 (
    set "NPM=npm.cmd"
) else (
    set "NPM=C:\Users\ThinkBook\AppData\Local\Programs\kimi-desktop\resources\resources\runtime\npm.cmd"
)

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo =========================================
echo   Spiral Frontend Startup
echo =========================================
echo.

if not exist "%FRONTEND_DIR%\node_modules" (
    echo [WARN] node_modules not found. Running npm install...
    cd /d "%FRONTEND_DIR%"
    "%NPM%" install
    if %errorlevel% neq 0 (
        echo [ERROR] npm install failed.
        pause
        exit /b 1
    )
)

for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%FRONTEND_PORT% ^| findstr LISTENING') do (
    echo [WARN] Port %FRONTEND_PORT% occupied by PID %%a. Killing...
    taskkill /F /PID %%a >nul 2>&1
    timeout /t 2 /nobreak >nul
)

cd /d "%FRONTEND_DIR%"

echo [INFO] Starting frontend dev server on port %FRONTEND_PORT%...
start "Spiral Frontend" /MIN cmd /c ""%NPM%" run dev ^> ^"%LOG_DIR%\frontend.log^" 2^> ^"%LOG_DIR%\frontend.err^""

set /a attempts=0
:wait_loop
set /a attempts+=1
timeout /t 1 /nobreak >nul
powershell -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:%FRONTEND_PORT%/' -TimeoutSec 2; exit 0 } catch { exit 1 }"
if %errorlevel%==0 goto frontend_ready
if %attempts% geq 20 goto frontend_timeout
goto wait_loop

:frontend_timeout
echo [ERROR] Frontend failed to start within 20 seconds.
echo [ERROR] Check logs: %LOG_DIR%\frontend.err
pause
exit /b 1

:frontend_ready
echo [OK] Frontend is running on http://127.0.0.1:%FRONTEND_PORT%
echo.
echo Press any key to stop frontend...
pause >nul

taskkill /F /IM node.exe >nul 2>&1
echo [OK] Frontend stopped.
