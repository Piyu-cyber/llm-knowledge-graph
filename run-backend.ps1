$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $pythonExe)) {
    throw "Project Python not found at $pythonExe"
}

# Free port 8000 if stale python listener exists.
$listeners = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($listeners) {
    $listeners | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {
        $p = Get-Process -Id $_ -ErrorAction SilentlyContinue
        if ($p -and $p.ProcessName -eq "python") {
            Stop-Process -Id $_ -Force
        }
    }
}

& $pythonExe -m uvicorn backend.app:app --app-dir $projectRoot --host 127.0.0.1 --port 8000 --reload
