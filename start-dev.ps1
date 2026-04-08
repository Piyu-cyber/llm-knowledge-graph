$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

# Kill any previous uvicorn instances to avoid port conflicts.
$existing = Get-CimInstance Win32_Process -Filter "name = 'python.exe'" |
    Where-Object { $_.CommandLine -like '*uvicorn backend.app:app*' }

if ($existing) {
    $existing | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
}

# Also free port 8000 if another leftover python process is listening.
$portListeners = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique

if ($portListeners) {
    foreach ($procId in $portListeners) {
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($proc -and $proc.ProcessName -eq 'python') {
            Stop-Process -Id $procId -Force
        }
    }
}

# Create backend/.env from template if missing.
if (-not (Test-Path .\backend\.env) -and (Test-Path .\backend\.env.example)) {
    Copy-Item .\backend\.env.example .\backend\.env
    Write-Host "Created backend/.env from backend/.env.example. Configure GROQ_API_KEY and/or CEREBRAS_API_KEY for router providers."
}

$venvPath = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPath)) {
    throw "Python executable not found at $venvPath. Recreate the venv in project root and install requirements."
}

$venvPython = Resolve-Path $venvPath

Write-Host "Starting API at http://127.0.0.1:8000"
& $venvPython -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload
