#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python_exe="$project_root/.venv/Scripts/python.exe"

if [[ ! -f "$python_exe" ]]; then
  echo "Project Python not found at $python_exe" >&2
  exit 1
fi

# Free port 8000 if a stale Python listener exists.
if command -v lsof >/dev/null 2>&1; then
  while IFS= read -r pid; do
    [[ -n "$pid" ]] || continue
    taskkill //PID "$pid" //F >/dev/null 2>&1 || true
  done < <(lsof -ti tcp:8000 || true)
else
  if command -v netstat >/dev/null 2>&1; then
    while IFS= read -r pid; do
      [[ -n "$pid" ]] || continue
      taskkill //PID "$pid" //F >/dev/null 2>&1 || true
    done < <(netstat -ano 2>/dev/null | awk '/:8000[[:space:]]/ && /LISTENING/ {print $NF}' | sort -u)
  fi
fi

app_dir="$project_root"
if command -v cygpath >/dev/null 2>&1; then
  app_dir="$(cygpath -w "$project_root")"
fi

"$python_exe" -m uvicorn backend.app:app --app-dir "$app_dir" --host 127.0.0.1 --port 8000 --reload
