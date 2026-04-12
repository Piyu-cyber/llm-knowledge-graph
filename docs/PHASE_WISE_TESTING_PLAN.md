# OmniProf Phase-Wise Testing Plan

This plan aligns with:

- `OmniProf_Assessment_Roadmap.pdf` (phase-gated delivery)
- Current repository state after latest pull
- Current architecture uses `rustworkx` graph ops

## Current Baseline (Observed)

- Legacy suite compatibility has been restored (constructor/signature mismatches fixed).
- `pytest`, `pytest-cov`, and `python-multipart` are installed in the active venv.
- Full suite status (Apr 7, 2026): `95 passed`.
- Frontend and backend remain aligned with phase 0-6 deliverables.

## Testing Principles

- Keep **phase gates** strict: do not move to next phase until gate passes.
- Prefer **small deterministic tests** for service logic.
- Add **integration tests** for API contract and critical end-to-end flows.
- Keep a **single source of truth** for test commands in this file.

---

## Phase 0: Test Harness Stabilization (Do this first)

### Objective

Make tests runnable and deterministic before phase-level validation.

### Scope

- Install and standardize test runner and tools.
- Migrate outdated scripts to current service signatures.
- Create shared fixtures for app client, auth, temp files.

### Tasks

1. Install test dependencies in project venv:
   - `pytest`
   - `pytest-cov`
   - `httpx` (if not already available)
2. Create structure:
   - `tests/unit/`
   - `tests/integration/`
   - `tests/e2e/`
   - `tests/conftest.py`
3. Replace old ad-hoc scripts (`tests/legacy/test_ingestion.py`, `tests/legacy/test_phase2.py`) with pytest tests.
4. Add a smoke test for app startup and `/docs` availability.

### Gate

- `pytest -q` runs successfully.
- No import/signature errors.

---

## Phase 1: Auth + RBAC Foundation Testing

### Objective

Validate authentication and role enforcement end-to-end.

### What to test

- `/auth/register`, `/auth/login`, `/auth/me`
- Token failure paths:
  - expired token
  - malformed token
  - missing token
- Role gates:
  - student blocked from professor/admin operations
  - professor allowed where expected
  - admin full access

### Test types

- Unit:
  - JWT create/verify, password hashing and verification
  - RBAC filter builders (`backend/auth/rbac.py`)
- Integration:
  - Protected endpoint behavior with valid/invalid tokens
  - course-level visibility behavior

### Gate

- 100% pass on auth + RBAC integration suite.
- Zero unauthorized data leak in role tests.

---

## Phase 2: Ingestion + Graph Build Testing (Now rustworkx-backed)

### Objective

Validate ingestion pipeline and graph construction correctness.

### What to test

- Multi-format extraction paths:
  - PDF, DOCX, PPTX, TXT (at least one fixture each)
- LLM extraction robustness:
  - valid JSON response
  - malformed/truncated response handling
  - empty extraction returns explicit error status
- Graph operations via `GraphService`:
  - `create_concept`, `create_relationship`
  - `get_graph`, `search_concepts`, `get_related_concepts`, `expand_graph`
- API contracts:
  - `/ingest`
  - `/graph`
  - `/graph-view`
  - `/ingest-debug`

### Test types

- Unit:
  - `IngestionService` stage transitions and `get_last_status()`
  - graph persistence load/save (`graph_store.pkl`) behavior
- Integration:
  - ingest sample file -> graph has >0 nodes and expected relations

### Gate

- Ingest returns non-zero concept/relationship counts for known sample docs.
- `/graph-view` returns `nodes` and `edges` schema compatible with frontend.

---

## Phase 3: Personalization / Overlay / Query-Time Access Testing

### Objective

Verify query-time filtering and personalization logic correctness.

### What to test

- Query path (`/query`) for:
  - normal query
  - ambiguous query branch
  - summary query branch
  - BAD relevance fallback path
- Role-aware result filtering:
  - student should not receive restricted concepts
- Confidence behavior:
  - confidence bounds and expected adjustments

### Test types

- Unit:
  - CRAG decision and fallback branches (`CRAGService`)
- Integration:
  - role-based querying with seeded graph + rag content

### Gate

- No restricted graph content in student query responses.
- All CRAG branches tested and passing.

---

## Phase 4: Memory + Agent Orchestration Testing

### Objective

Validate reliability and safety of multi-agent flows.

### What to test

- Agent graph orchestration transitions (`backend/agents/`)
- Cognitive engine behavior and fallbacks
- Background tasks:
  - summarisation agent jobs
  - curriculum agent jobs
- Failure containment:
  - one agent failure should not crash full request path

### Test types

- Unit:
  - state transition tests for orchestration graph
- Integration:
  - chat/query endpoint with agent-driven branches

### Gate

- End-to-end agent path completes under normal and degraded conditions.
- No uncaught exceptions in orchestration loop tests.

---

## Phase 5: Dashboard + Frontend E2E Testing

### Objective

Ensure user workflows are functional in UI.

### What to test

- Upload -> ingest -> diagnostics panel updates
- Query -> answer -> graph visualization render
- Knowledge Graph Browser:
  - network graph rendering
  - node click -> query behavior
- API base fallback logic for local ports (`8000`, `8010`)

### Test types

- Manual scripted checks (minimum)
- Optional Playwright/Cypress e2e automation

### Gate

- All critical user flows pass without manual workaround.
- Graph renders as node-edge network, not only cards.

---

## Phase 6: Performance / Reliability / Hardening

### Objective

Prove system reliability under realistic load and failure.

### What to test

- Throughput and latency:
  - concurrent `/query`
  - concurrent `/ingest` (bounded)
- Memory growth over repeated ingestion/query cycles
- Recovery:
  - corrupted graph store file handling
  - missing embedding/index files
- Security regression checks:
  - auth bypass attempts
  - malformed payloads

### Tooling suggestions

- `locust` or `k6` for load
- pytest markers:
  - `@pytest.mark.slow`
  - `@pytest.mark.load`

### Gate

- SLA targets defined and met.
- No critical crash or data corruption under stress tests.

---

## Suggested Execution Order (Practical)

1. Phase 0 harness stabilization
2. Phase 2 ingestion + graph tests (highest current risk)
3. Phase 1 auth/RBAC regression
4. Phase 3 query-time access tests
5. Phase 5 frontend e2e checks
6. Phase 4 agent reliability tests
7. Phase 6 load/hardening

Reason: current repo pain points are ingestion/graph behavior and test drift after refactors.

---

## Immediate Command Set

Run from project root (`llm-knowledge-graph`):

```powershell
# Install test runner
.\.venv\Scripts\python.exe -m pip install pytest pytest-cov

# Run all tests once migrated to pytest
.\.venv\Scripts\python.exe -m pytest -q

# Run only ingestion/graph tests
.\.venv\Scripts\python.exe -m pytest -q tests/integration -k "ingest or graph"

# Run auth/rbac tests
.\.venv\Scripts\python.exe -m pytest -q tests/unit -k "auth or rbac"
```

---

## Definition of Done (Project-Level)

- All phase gates pass.
- CI-ready pytest suite exists (not ad-hoc scripts).
- Critical workflows have both API and UI coverage.
- Regression pack runs on every pull.
