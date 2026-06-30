# 高考志愿 Agent 一键启动脚本
# 前端端口 1678，后端端口 11678

$ErrorActionPreference = "Stop"

$BackendDir = Join-Path $PSScriptRoot "backend"
$Python = Join-Path $BackendDir "venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Host "[ERROR] backend venv not found: $Python" -ForegroundColor Red
    Write-Host "        Run: cd backend; python -m venv venv; .\venv\Scripts\python.exe -m pip install -r requirements.txt" -ForegroundColor Yellow
    exit 1
}

$backend = Start-Process -FilePath $Python -ArgumentList "main.py" -WorkingDirectory $BackendDir -PassThru -NoNewWindow

# npm 是 cmd 脚本，需要用 cmd /c 启动
$frontend = Start-Process -FilePath "cmd.exe" -ArgumentList "/c npm run dev" -WorkingDirectory "$PSScriptRoot\frontend" -PassThru -NoNewWindow

Write-Host "Backend started on http://localhost:11678 (PID $($backend.Id))"
Write-Host "Frontend started on http://localhost:1678 (PID $($frontend.Id))"
Write-Host "Press Ctrl+C to stop both..."

try {
    $backend | Wait-Process
} finally {
    if ($frontend -and $frontend.Id) {
        Stop-Process -Id $frontend.Id -Force -ErrorAction SilentlyContinue
    }
    if ($backend -and $backend.Id) {
        Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
    }
    Write-Host "Stopped."
}
