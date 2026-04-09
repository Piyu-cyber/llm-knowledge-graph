# Frontend-Backend Feature Audit

Date: 2026-04-10
Scope: React frontend in frontend/src against FastAPI backend in backend/app.py

## Summary

- Workspace diagnostics: no compile/lint errors currently reported.
- Core student and professor journeys are now wired end-to-end.
- Remaining gaps are now mostly UX depth items, not missing backend integration.

## Classification Matrix

### Fully Working End-to-End

- Authentication login + token-based API calls
  - Frontend: frontend/src/App.jsx
  - Backend: backend/app.py (/auth/login, /auth/me)
- Student tutoring chat flow
  - Frontend: frontend/src/StudentDashboard.jsx
  - Backend: backend/app.py (/chat)
- Student progress, achievements, classroom feed
  - Frontend: frontend/src/StudentDashboard.jsx
  - Backend: backend/app.py (/student/progress, /student/achievements, /student/classroom-feed)
- Student assignment submission and status
  - Frontend: frontend/src/StudentDashboard.jsx
  - Backend: backend/app.py (/student/submit-assignment, /student/submissions/{submission_id})
- Professor command center (announcements/coursework/submissions)
  - Frontend: frontend/src/ProfessorDashboard.jsx
  - Backend: backend/app.py (/professor/classroom-announcements, /professor/coursework, /professor/submissions)
- HITL queue review actions
  - Frontend: frontend/src/ProfessorDashboard.jsx
  - Backend: backend/app.py (/professor/hitl-queue, /professor/hitl-queue/{queue_id}/action)
- Cohort overview and student drill-down payload consumption
  - Frontend: frontend/src/ProfessorDashboard.jsx
  - Backend: backend/app.py (/professor/cohort-overview, /professor/cohort, /professor/students)
- Learning path fetch + publish
  - Frontend: frontend/src/ProfessorDashboard.jsx
  - Backend: backend/app.py (/professor/learning-path GET/POST)
- Professor private notes save + load
  - Frontend: frontend/src/ProfessorDashboard.jsx
  - Backend: backend/app.py (/professor/annotate POST/GET)
- Graph concept metadata updates (priority/visibility/name/description)
  - Frontend: frontend/src/ProfessorDashboard.jsx
  - Backend: backend/app.py (/concept/{concept_id} PATCH, /professor/graph-visualization)

### Backend Ready, Operationally Conditional

- Jina API embeddings path
  - Works when API key/model entitlement is valid.
  - If 401/403 occurs, service auto-disables API and falls back to local embeddings for process lifetime.
  - File: backend/services/jina_multimodal_service.py

### Partially Implemented (UX depth still possible)

- Learning path editor now supports add/remove/reorder with drag + publish.
- Still no full prerequisite edge editor in UI (partial_order_edges currently sent empty).

### Not Yet Implemented as Product Features

- Full graph authoring UI for creating modules/topics/concepts/facts and manual edge creation from frontend.
  - Backend primitives exist through services/graph layer, but dedicated professor UI workflows are not complete.
- Rich professor note history management UI (list/history/versioning).
  - Save/load latest note is implemented; advanced note management is not.

## Implemented in this audit pass

1. Professor auth-expiry handling wired
   - Frontend now triggers re-login flow on professor-side 401 responses.

2. Professor notes retrieval implemented
   - Added backend GET /professor/annotate and frontend note prefill behavior.

3. Learning path drag/drop implemented
   - Added concept pool, add/remove, drag reorder, and publish persistence flow.

4. Graph metadata edit actions expanded
   - Concept name and description edits now saved through PATCH /concept/{concept_id}.

## Recommendation

- Next high-value increment: add explicit prerequisite edge editor in professor graph UI and persist partial_order_edges in learning-path publish.
