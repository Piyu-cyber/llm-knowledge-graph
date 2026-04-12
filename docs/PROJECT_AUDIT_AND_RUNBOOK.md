# OmniProf Project Audit and Runbook (April 2026)

This document is the operational source of truth for:

- Current implementation status and remaining work
- Local and Docker startup
- Full test command matrix
- Commands to verify every API in backend/app.py

## 1. Project Audit Summary

### 1.1 What is implemented

- Phase 0-6 test matrix is green in current repository state.
- Backend uses FastAPI with RustWorkX local graph persistence.
- Multi-agent orchestration is present via LangGraph.
- Phase 5 student and professor dashboard MVP routes and frontend pages are present.
- Phase 6 additions are present:
  - LLMRouter service with cascade and backoff
  - Background job queue with dead-letter queue
  - Compliance service and audit-log support

### 1.2 What remains (important)

- Production hardening still needed beyond acceptance tests:
  - True 24h soak run for background stability in a long-running environment
  - Real 30-concurrent load run with external load tool and persisted metrics artifact
  - Speculative decoding remains a research spike; should be explicitly toggled and benchmarked against TTFT target
  - Formal FERPA/GDPR legal review evidence collection is still an operational process item (not only code checks)
- Startup ergonomics:
  - Most prior launch failures were due to running from parent directory or wrong venv path.
  - Always run from project root and use repo-local venv command examples below.

## 2. Repository Layout (Operational)

- backend/app.py: FastAPI entrypoint and route definitions
- backend/services/: core services (LLM, router, queue, compliance, graph, ingestion)
- backend/db/: RustWorkX graph manager and schemas
- backend/agents/: orchestration agents and shared state
- frontend/student_dashboard.html: student UI
- frontend/professor_dashboard.html: professor UI
- tests/phases/: phase-gated pytest suites
- start-dev.ps1: Windows startup helper
- docker/docker-compose.yml: container startup

## 3. Prerequisites

- Python 3.10+ recommended
- PowerShell (Windows)
- Optional Docker Desktop
- Optional Groq API key for full cloud LLM path

## 4. Environment Setup

Run from project root:

```powershell
Set-Location C:\Users\mitta\OneDrive\Desktop\LLM\llm-knowledge-graph
```

Create and activate venv (if needed):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install -r .\backend\requirements.txt
```

Create backend env file if missing:

```powershell
if (-not (Test-Path .\backend\.env) -and (Test-Path .\backend\.env.example)) {
  Copy-Item .\backend\.env.example .\backend\.env
}
```

Set important env vars in backend/.env:

```env
GROQ_API_KEY=your_key_here
CEREBRAS_API_KEY=optional_second_provider_key
JWT_SECRET_KEY=replace_with_strong_secret
DATA_ENCRYPTION_AT_REST=true
TLS_ENFORCED=true
LLMROUTER_BACKOFF_SECONDS=20
LLMROUTER_MAX_BACKOFF_SECONDS=180
LLMROUTER_SPECULATIVE_ENABLED=true
LLMROUTER_SPECULATIVE_MIN_PROMPT_CHARS=120
```

## 5. How to Run the Project

### 5.1 Recommended Windows startup

```powershell
Set-Location C:\Users\mitta\OneDrive\Desktop\LLM\llm-knowledge-graph
.\start-dev.ps1
```

### 5.2 Direct uvicorn startup

```powershell
Set-Location C:\Users\mitta\OneDrive\Desktop\LLM\llm-knowledge-graph
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload
```

### 5.3 Frontend pages

```powershell
Set-Location C:\Users\mitta\OneDrive\Desktop\LLM\llm-knowledge-graph
python -m http.server 5500
```

Open:

- http://127.0.0.1:5500/frontend/student_dashboard.html
- http://127.0.0.1:5500/frontend/professor_dashboard.html

### 5.4 Docker

```powershell
Set-Location C:\Users\mitta\OneDrive\Desktop\LLM\llm-knowledge-graph\docker
docker compose up --build
```

## 6. Testing Commands

### 6.1 Full phase matrix

```powershell
Set-Location C:\Users\mitta\OneDrive\Desktop\LLM\llm-knowledge-graph
.\.venv\Scripts\python.exe -m pytest -q tests\phases -m "phase0 or phase1 or phase1_acceptance or phase2 or phase2_acceptance or phase3 or phase3_acceptance or phase4 or phase4_acceptance or phase5 or phase5_acceptance or phase6 or phase6_acceptance"
```

### 6.2 Per-phase shortcuts

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\phases -m "phase1 or phase1_acceptance"
.\.venv\Scripts\python.exe -m pytest -q tests\phases -m "phase2 or phase2_acceptance"
.\.venv\Scripts\python.exe -m pytest -q tests\phases -m "phase3 or phase3_acceptance"
.\.venv\Scripts\python.exe -m pytest -q tests\phases -m "phase4 or phase4_acceptance"
.\.venv\Scripts\python.exe -m pytest -q tests\phases -m "phase5 or phase5_acceptance"
.\.venv\Scripts\python.exe -m pytest -q tests\phases -m "phase6 or phase6_acceptance"
```

## 7. API Verification Commands (Every Endpoint)

Base setup in PowerShell:

```powershell
$BASE = "http://127.0.0.1:8000"
```

### 7.1 Public health

```powershell
Invoke-RestMethod -Method Get -Uri "$BASE/"
```

### 7.2 Authentication

Register student:

```powershell
$reg = Invoke-RestMethod -Method Post -Uri "$BASE/auth/register" -ContentType "application/json" -Body (@{
  username = "student_demo"
  email = "student_demo@example.com"
  password = "StrongPass123"
  full_name = "Student Demo"
  role = "student"
} | ConvertTo-Json)
$reg
```

Login student:

```powershell
$login = Invoke-RestMethod -Method Post -Uri "$BASE/auth/login" -ContentType "application/json" -Body (@{
  username = "student_demo"
  password = "StrongPass123"
} | ConvertTo-Json)
$TOKEN = $login.access_token
$AUTH = @{ Authorization = "Bearer $TOKEN" }
$login
```

Current user:

```powershell
Invoke-RestMethod -Method Get -Uri "$BASE/auth/me" -Headers $AUTH
```

### 7.3 Core learning APIs

Add concept:

```powershell
Invoke-RestMethod -Method Post -Uri "$BASE/concept" -Headers $AUTH -ContentType "application/json" -Body (@{
  name = "Gradient Descent"
  description = "Optimization concept"
  category = "ML"
  course_id = "cs101"
} | ConvertTo-Json)
```

Enroll:

```powershell
Invoke-RestMethod -Method Post -Uri "$BASE/enrol" -Headers $AUTH -ContentType "application/json" -Body (@{
  course_id = "cs101"
} | ConvertTo-Json)
```

Record interaction:

```powershell
Invoke-RestMethod -Method Post -Uri "$BASE/interaction" -Headers $AUTH -ContentType "application/json" -Body (@{
  concept_id = "concept_1"
  answered_correctly = $true
  difficulty = 0.2
} | ConvertTo-Json)
```

Get graph stats:

```powershell
Invoke-RestMethod -Method Get -Uri "$BASE/graph" -Headers $AUTH
```

Graph view:

```powershell
Invoke-RestMethod -Method Get -Uri "$BASE/graph-view?query=gradient" -Headers $AUTH
```

Ingest file (PDF/DOCX/PPTX/TXT):

```powershell
$form = @{ file = Get-Item ".\sample.pdf" }
Invoke-RestMethod -Method Post -Uri "$BASE/ingest" -Headers $AUTH -Form $form
```

Query:

```powershell
Invoke-RestMethod -Method Post -Uri "$BASE/query" -Headers $AUTH -ContentType "application/json" -Body (@{
  query = "Explain gradient descent"
  course_id = "cs101"
  use_graph = $true
  use_vector = $true
  confidence_threshold = 0.5
} | ConvertTo-Json)
```

Chat:

```powershell
Invoke-RestMethod -Method Post -Uri "$BASE/chat" -Headers $AUTH -ContentType "application/json" -Body (@{
  message = "Teach me optimization basics"
  session_id = "sess_demo_1"
  course_id = "cs101"
} | ConvertTo-Json)
```

### 7.4 Student dashboard APIs

Student progress:

```powershell
Invoke-RestMethod -Method Get -Uri "$BASE/student/progress?course_id=cs101" -Headers $AUTH
```

Submit assignment:

```powershell
$form = @{ file = Get-Item ".\sample.pdf" }
Invoke-RestMethod -Method Post -Uri "$BASE/student/submit-assignment?course_id=cs101" -Headers $AUTH -Form $form
```

Submission status:

```powershell
$submissionId = "sub_replace_me"
Invoke-RestMethod -Method Get -Uri "$BASE/student/submissions/$submissionId" -Headers $AUTH
```

WebSocket chat check (Python one-liner):

```powershell
.\.venv\Scripts\python.exe -c "import asyncio, json, websockets; token='$TOKEN'; async def main():
    uri=f'ws://127.0.0.1:8000/ws/chat?token={token}&session_id=sess_ws_1&course_id=cs101'
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({'message':'Explain gradient descent'}))
        for _ in range(6):
            msg=await ws.recv(); print(msg)
asyncio.run(main())"
```

### 7.5 Professor APIs

Register/login professor if needed:

```powershell
$regp = Invoke-RestMethod -Method Post -Uri "$BASE/auth/register" -ContentType "application/json" -Body (@{
  username = "prof_demo"
  email = "prof_demo@example.com"
  password = "StrongPass123"
  full_name = "Professor Demo"
  role = "professor"
} | ConvertTo-Json)
$loginp = Invoke-RestMethod -Method Post -Uri "$BASE/auth/login" -ContentType "application/json" -Body (@{
  username = "prof_demo"
  password = "StrongPass123"
} | ConvertTo-Json)
$PTOKEN = $loginp.access_token
$PAUTH = @{ Authorization = "Bearer $PTOKEN" }
```

HITL queue:

```powershell
Invoke-RestMethod -Method Get -Uri "$BASE/professor/hitl-queue" -Headers $PAUTH
```

HITL action:

```powershell
$queueId = "queue_replace_me"
Invoke-RestMethod -Method Post -Uri "$BASE/professor/hitl-queue/$queueId/action" -Headers $PAUTH -ContentType "application/json" -Body (@{
  action = "approve"
} | ConvertTo-Json)
```

Cohort overview:

```powershell
Invoke-RestMethod -Method Get -Uri "$BASE/professor/cohort-overview?course_id=cs101&inactivity_days=7" -Headers $PAUTH
```

Graph visualization (read-only):

```powershell
Invoke-RestMethod -Method Get -Uri "$BASE/professor/graph-visualization?course_id=cs101" -Headers $PAUTH
```

Save learning path:

```powershell
Invoke-RestMethod -Method Post -Uri "$BASE/professor/learning-path" -Headers $PAUTH -ContentType "application/json" -Body (@{
  course_id = "cs101"
  ordered_concept_ids = @("concept_a", "concept_b")
  partial_order_edges = @(@{ source_id = "concept_a"; target_id = "concept_c"; weight = 0.7 })
} | ConvertTo-Json -Depth 5)
```

Get learning path:

```powershell
Invoke-RestMethod -Method Get -Uri "$BASE/professor/learning-path?course_id=cs101" -Headers $PAUTH
```

### 7.6 Phase 6 operational APIs

LLM Router health:

```powershell
Invoke-RestMethod -Method Get -Uri "$BASE/llm-router/health" -Headers $PAUTH
```

LLM route probe:

```powershell
Invoke-RestMethod -Method Post -Uri "$BASE/llm-router/route" -Headers $PAUTH -ContentType "application/json" -Body (@{
  task = "ta_tutoring"
  prompt = "Explain backtracking"
} | ConvertTo-Json)
```

Register/login admin for admin-only APIs:

```powershell
$rega = Invoke-RestMethod -Method Post -Uri "$BASE/auth/register" -ContentType "application/json" -Body (@{
  username = "admin_demo"
  email = "admin_demo@example.com"
  password = "StrongPass123"
  full_name = "Admin Demo"
  role = "admin"
} | ConvertTo-Json)
$logina = Invoke-RestMethod -Method Post -Uri "$BASE/auth/login" -ContentType "application/json" -Body (@{
  username = "admin_demo"
  password = "StrongPass123"
} | ConvertTo-Json)
$ATOKEN = $logina.access_token
$AAUTH = @{ Authorization = "Bearer $ATOKEN" }
```

Background jobs stats:

```powershell
Invoke-RestMethod -Method Get -Uri "$BASE/background-jobs/stats" -Headers $AAUTH
```

Background jobs drain:

```powershell
Invoke-RestMethod -Method Post -Uri "$BASE/background-jobs/drain" -Headers $AAUTH
```

Compliance status:

```powershell
Invoke-RestMethod -Method Get -Uri "$BASE/compliance/status" -Headers $AAUTH
```

## 8. Common Failure Modes and Fixes

- Uvicorn fails to import app:
  - Ensure command is run from project root.
  - Use repo-local interpreter path shown in this file.
- File upload endpoint returns form parsing error:
  - Ensure python-multipart is installed from backend/requirements.txt.
- Protected endpoints return 401:
  - Re-login and refresh Bearer token.
- Professor/admin endpoints return 403:
  - Ensure token role matches endpoint guard.

## 9. Recommended Next Operational Tasks

- Add CI pipeline job for full phase matrix.
- Add nightly long-run soak script for 24h queue stability and memory growth.
- Export operational metrics (TTFT, queue depth, graph latency) to durable dashboard.
- Add per-environment secrets handling and key rotation process.
