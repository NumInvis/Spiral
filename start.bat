@echo off
chcp 65001 >nul 2>&1
setlocal

set "ROOT=%~dp0"
set "PYTHON=%ROOT%backend\venv\Scripts\python.exe"
set "BACKEND_DIR=%ROOT%backend"
set "FRONTEND_DIR=%ROOT%frontend"
set "BACKEND_PORT=11678"
set "FRONTEND_PORT=1678"
set "LOG_DIR=%ROOT%logs"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

cd /d "%ROOT%"

cls
echo ==========================================
echo   Spiral Gaokao Agent - One-click Start
echo ==========================================
echo.

if not exist "%PYTHON%" (
    echo [ERROR] Backend venv not found: %PYTHON%
    echo         Run: cd backend ^&^& python -m venv venv ^&^& .\venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
    echo [ERROR] npm not found. Please install Node.js 20+ and ensure npm is in PATH.
    pause
    exit /b 1
)

echo [OK] Python: %PYTHON%
echo [OK] npm:   %CD%\frontend
echo.

set "SPIRAL_SKIP_RAG_SEED=1"

echo [INFO] Cleaning up existing processes on ports %BACKEND_PORT% and %FRONTEND_PORT%...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%BACKEND_PORT% ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%FRONTEND_PORT% ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1
timeout /t 2 /nobreak >nul
echo [OK] Cleanup done.
echo.

echo [1/2] Starting backend...
cd /d "%BACKEND_DIR%"
start "Spiral Backend" /MIN "%PYTHON%" -m uvicorn main:app --host 127.0.0.1 --port %BACKEND_PORT% --log-level info > "%LOG_DIR%\backend.log" 2> "%LOG_DIR%\backend.err"

set /a attempts=0
:loop_backend
set /a attempts+=1
timeout /t 1 /nobreak >nul
powershell -Command "try { $r = Invoke-RestMethod -Uri 'http://127.0.0.1:%BACKEND_PORT%/api/health' -TimeoutSec 2; exit 0 } catch { exit 1 }"
if %errorlevel%==0 goto backend_ok
if %attempts% geq 15 goto backend_fail
goto loop_backend

:backend_fail
echo [ERROR] Backend failed to start within 15s. Check: %LOG_DIR%\backend.err
pause
exit /b 1

:backend_ok
echo [OK] Backend running at http://127.0.0.1:%BACKEND_PORT%

echo [2/2] Starting frontend...
cd /d "%FRONTEND_DIR%"

if not exist "node_modules" (
    echo [INFO] Installing frontend dependencies...
    call npm install
    if errorlevel 1 (
        echo [ERROR] Frontend dependency installation failed.
        pause
        exit /b 1
    )
)

start "Spiral Frontend" /MIN cmd /c "npm run dev ^> ^"%LOG_DIR%\frontend.log^" 2^> ^"%LOG_DIR%\frontend.err^""

set /a attempts=0
:loop_frontend
set /a attempts+=1
timeout /t 1 /nobreak >nul
powershell -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:%FRONTEND_PORT%/' -TimeoutSec 2; exit 0 } catch { exit 1 }"
if %errorlevel%==0 goto frontend_ok
if %attempts% geq 20 goto frontend_fail
goto loop_frontend

:frontend_fail
echo [ERROR] Frontend failed to start within 20s. Check: %LOG_DIR%\frontend.err
pause
exit /b 1

:frontend_ok
echo [OK] Frontend running at http://127.0.0.1:%FRONTEND_PORT%

echo.
echo ==========================================
echo   All services started successfully!
echo ==========================================
echo.
echo   Backend API:  http://127.0.0.1:%BACKEND_PORT%
echo   API Docs:     http://127.0.0.1:%BACKEND_PORT%/docs
echo   Frontend:     http://127.0.0.1:%FRONTEND_PORT%
echo.
echo   Logs: %LOG_DIR%
echo.
echo   Press any key to stop all services...
echo ==========================================
pause >nul

echo [INFO] Shutting down...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%BACKEND_PORT% ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1
taskkill /F /IM node.exe >nul 2>&1
echo [OK] All services stopped.
