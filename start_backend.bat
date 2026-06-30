@echo off
chcp 437 >nul
setlocal

set "PYTHON=D:\Spiral\backend\venv\Scripts\python.exe"
set "BACKEND_DIR=D:\Spiral\backend"
set "BACKEND_PORT=11678"
set "SPIRAL_SKIP_RAG_SEED=1"
set "LOG_DIR=D:\Spiral\logs"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo =========================================
echo   Spiral Backend Startup
echo =========================================
echo.

for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%BACKEND_PORT% ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 2 /nobreak >nul

for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%BACKEND_PORT% ^| findstr LISTENING') do (
    echo [ERROR] Port %BACKEND_PORT% still occupied by PID %%a
    pause
    exit /b 1
)

set "SPIRAL_SKIP_RAG_SEED=%SPIRAL_SKIP_RAG_SEED%"

cd /d "%BACKEND_DIR%"

echo [INFO] Starting backend on port %BACKEND_PORT%...
start "Spiral Backend" /MIN "%PYTHON%" -m uvicorn main:app --host 0.0.0.0 --port %BACKEND_PORT% --log-level info ^
    > "%LOG_DIR%\backend.log" 2> "%LOG_DIR%\backend.err"

set /a attempts=0
:wait_loop
set /a attempts+=1
timeout /t 1 /nobreak >nul
powershell -Command "try { $r = Invoke-RestMethod -Uri 'http://127.0.0.1:%BACKEND_PORT%/api/health' -TimeoutSec 2; exit 0 } catch { exit 1 }"
if %errorlevel%==0 goto backend_ready
if %attempts% geq 15 goto backend_timeout
goto wait_loop

:backend_timeout
echo [ERROR] Backend failed to start within 15 seconds.
echo [ERROR] Check logs: %LOG_DIR%\backend.err
pause
exit /b 1

:backend_ready
echo [OK] Backend is running on http://127.0.0.1:%BACKEND_PORT%
echo [OK] API docs: http://127.0.0.1:%BACKEND_PORT%/docs
echo.
echo Press any key to stop backend...
pause >nul

for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%BACKEND_PORT% ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1
)
echo [OK] Backend stopped.
