# OmniProf v3.0

AI-driven educational platform with multi-agent orchestration, adaptive tutoring, knowledge tracing, and professor review workflows.

## Project Status (April 2026)

- Phase 0 to Phase 6 completed
- Feature-complete backend for MVP scope
- Student and professor app flows available
- 95+ automated tests across phase and legacy suites
- Phase 7 remains planned for deeper production hardening (soak/load/compliance ops)

For operational verification details, see docs/PROJECT_AUDIT_AND_RUNBOOK.md.

## Table of Contents

- Overview
- What Is Implemented
- High-Level Architecture
- Repository Structure
- Prerequisites
- Quick Start (Windows)
- Manual Start (Cross-platform)
- Frontend Development
- Configuration
- Default Demo Accounts
- API Overview
- Testing
- Observability and Hardening Endpoints
- Documentation Map
- Known Gaps and Next Steps

## Overview

OmniProf combines:

- Multi-agent orchestration for tutoring, evaluation, integrity checks, curriculum actions, and gamification
- Dual memory approach:
  - Semantic knowledge graph (RustWorkX + JSON persistence)
  - Episodic memory index (FAISS)
- Adaptive teaching behavior through routing, confidence grading, and mastery-aware response patterns
- Professor-in-the-loop queue and classroom management endpoints

Primary backend entry point: backend/app.py

## What Is Implemented

### Multi-agent layer

- TA Agent
- Evaluator Agent
- Integrity Agent
- Cognitive Engine Agent
- Curriculum Agent
- Gamification Agent
- Summarisation Agent
- Graph-based orchestrator and intent classifier

Code locations:
- backend/agents/
- backend/services/crag_service.py
- backend/services/llm_router.py

### Backend services

- Authentication and RBAC
- Graph and concept management
- Document ingestion (PDF, DOCX, PPTX, TXT)
- Query and chat APIs
- Student progress and achievement APIs
- Professor review, grading, annotation, and cohort endpoints
- Background job queue and dead-letter replay
- Compliance and observability endpoints

Code locations:
- backend/services/
- backend/db/
- backend/auth/
- backend/models/

### Frontend

- React + Vite application in frontend/src/
- Role-oriented views for student and professor journeys
- Legacy static HTML dashboards retained for reference

## High-Level Architecture

```text
Client (React + Vite / API consumers)
          |
          v
FastAPI API Layer (backend/app.py)
          |
          v
LangGraph Orchestration + Services
(TA/Evaluator/Integrity/Cognitive/Curriculum/Gamification/Summarisation)
          |
          v
Data + Memory
- RustWorkX JSON graph persistence (data/)
- FAISS index for episodic/vector retrieval
- User, audit, and review JSON stores
```

## Repository Structure

```text
llm-knowledge-graph/
  backend/
    agents/
    auth/
    db/
    models/
    services/
    app.py
    requirements.txt
  frontend/
    src/
    package.json
  data/
  docs/
  tests/
    phases/
    legacy/
  run-backend.ps1
  start-dev.ps1
  .env.example
  backend/.env.example
```

## Prerequisites

- Python 3.10+ recommended
- Node.js 18+ recommended
- npm
- Windows PowerShell (for provided scripts)

External provider keys for full LLM functionality:
- GROQ_API_KEY
- Optional fallback: CEREBRAS_API_KEY

## Quick Start (Windows)

Run from project root (llm-knowledge-graph):

```powershell
# 1) Create and activate local virtual environment (if needed)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2) Install backend dependencies
python -m pip install -r .\backend\requirements.txt

# 3) Start backend (recommended script)
.\run-backend.ps1
```

Backend URLs:
- API root: http://127.0.0.1:8000
- OpenAPI docs: http://127.0.0.1:8000/docs

Alternative startup script:

```powershell
.\start-dev.ps1
```

The start-dev.ps1 script can auto-create backend/.env from backend/.env.example if missing.

## Manual Start (Cross-platform)

If you do not use PowerShell scripts:

```bash
pip install -r backend/requirements.txt
uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload
```

## Frontend Development

In a separate terminal:

```powershell
Set-Location .\frontend
npm install
npm run dev
```

Frontend URL:
- http://127.0.0.1:5173

Default backend target is http://127.0.0.1:8000.

## Configuration

Two templates exist:

- Root template: .env.example
- Backend template used by startup script: backend/.env.example

Typical setup:

```powershell
Copy-Item .\backend\.env.example .\backend\.env
```

Key variables (current examples):

- GROQ_API_KEY
- CEREBRAS_API_KEY
- INTEGRITY_MIN_TOKENS
- LLMROUTER_BACKOFF_SECONDS
- LLMROUTER_MAX_BACKOFF_SECONDS

Additional options are listed in the root .env.example.

## Default Demo Accounts

On backend startup, demo accounts are seeded when absent:

- Student
  - Username: student_demo
  - Password: Student@123
- Professor
  - Username: professor_demo
  - Password: Professor@123

These are for local development only.

## API Overview

### Core endpoints

Authentication:
- POST /auth/register
- POST /auth/login
- GET /auth/me

Learning and interaction:
- POST /chat
- POST /query
- POST /interaction
- GET /student/progress
- GET /student/achievements
- GET /student/classroom-feed

Knowledge and ingestion:
- POST /ingest
- GET /graph
- GET /graph-view
- POST /concept

Enrollment:
- POST /enrol

Professor workflows:
- GET /professor/hitl-queue
- POST /professor/hitl-queue/{queue_id}/action
- GET /professor/cohort-overview
- GET /professor/graph-visualization
- POST /professor/learning-path
- GET /professor/learning-path
- GET /professor/students
- GET/POST /professor/classroom-announcements
- GET/POST /professor/coursework
- GET /professor/submissions
- POST /professor/grade
- POST /professor/annotate

Streaming:
- WebSocket /ws/chat

For complete schemas and request/response models, use live docs at /docs.

## Testing

From project root:

```powershell
# Legacy baseline suites
.\.venv\Scripts\python.exe -m pytest -q tests\legacy\test_ingestion.py tests\legacy\test_phase2.py tests\legacy\test_phase3.py

# Roadmap phases
.\.venv\Scripts\python.exe -m pytest -q tests\phases -m "phase0 or phase1 or phase2 or phase3 or phase4 or phase5 or phase6"

# Example single phase
.\.venv\Scripts\python.exe -m pytest -q tests\phases -m phase4
```

You can also run everything with:

```powershell
pytest -q
```

## Observability and Hardening Endpoints

Phase 6 endpoints include:

- GET /llm-router/health
- POST /llm-router/route
- POST /diagnostics/nondeterminism/run
- GET /integrity/policy
- GET /background-jobs/stats
- POST /background-jobs/drain
- POST /background-jobs/replay-dead-letter
- GET /background-jobs/history
- GET /compliance/status
- GET /observability/metrics
- GET /observability/traces
- GET /observability/error-budget
- GET /observability/providers
- GET /health/embeddings

## Documentation Map

- docs/QUICK_START.md
- docs/RUN_COMMANDS.md
- docs/COMPLETION_STATUS.md
- docs/PROJECT_AUDIT_AND_RUNBOOK.md
- docs/PHASE_WISE_TESTING_PLAN.md
- docs/INDEX.md

## Known Gaps and Next Steps

Planned Phase 7 work:

- 24-hour soak testing
- higher-concurrency load testing
- production monitoring and SRE hardening
- formal legal/compliance validation workflows

## Notes

- Data and local persistence files are under data/.
- If provider keys are missing or unavailable, some LLM-backed routes operate in reduced mode.
- This repository is optimized for local-first development and testing.
