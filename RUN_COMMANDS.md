# Run Commands (No start-dev script)

## Backend (PowerShell)

Run these from the repository root (`llm-knowledge-graph`):

```powershell
# 1) Go to project root
Set-Location C:\Users\mitta\OneDrive\Desktop\LLM\llm-knowledge-graph

# 2) Activate virtual environment
.\.venv\Scripts\Activate.ps1

# 3) Install/refresh dependencies (only when needed)
python -m pip install -r .\backend\requirements.txt

# 4) Run FastAPI backend
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload
```

Backend URL:
- http://127.0.0.1:8000

API docs:
- http://127.0.0.1:8000/docs

## Default Test Accounts

These are auto-seeded on backend startup when missing:

- Student
	- Username: `student_demo`
	- Password: `Student@123`
- Professor
	- Username: `professor_demo`
	- Password: `Professor@123`

Local testing only. Rotate/remove before using shared or production deployments.

## Frontend

This project uses dashboard pages under the `frontend/` folder.

Quick open:
- `frontend/student_dashboard.html`
- `frontend/professor_dashboard.html`

Option 2 (recommended, local HTTP server):

```powershell
# In a new terminal, from repo root
Set-Location C:\Users\mitta\OneDrive\Desktop\LLM\llm-knowledge-graph
python -m http.server 5500
```

Then open:
- http://127.0.0.1:5500/frontend/student_dashboard.html
- http://127.0.0.1:5500/frontend/professor_dashboard.html

## Stop Services

Use `Ctrl + C` in the backend/frontend terminals to stop local servers.

## Phase Testing (Pytest)

```powershell
# From repo root
Set-Location C:\Users\mitta\OneDrive\Desktop\LLM\llm-knowledge-graph

# Install test tooling (one-time)
.\.venv\Scripts\python.exe -m pip install pytest pytest-cov

# Run migrated baseline suites
.\.venv\Scripts\python.exe -m pytest -q tests\legacy\test_ingestion.py tests\legacy\test_phase2.py tests\legacy\test_phase3.py

# Run all roadmap phase suites (phase0 -> phase6)
.\.venv\Scripts\python.exe -m pytest -q tests\phases -m "phase0 or phase1 or phase2 or phase3 or phase4 or phase5 or phase6"

# Run a single phase suite (example: phase4)
.\.venv\Scripts\python.exe -m pytest -q tests\phases -m phase4
```
