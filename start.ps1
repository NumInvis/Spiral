# 高考志愿 Agent 一键启动脚本
# 前端端口 1678，后端端口 11678

$ErrorActionPreference = "Stop"

$backend = Start-Process -FilePath "python" -ArgumentList "main.py" -WorkingDirectory "$PSScriptRoot\backend" -PassThru -NoNewWindow

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
