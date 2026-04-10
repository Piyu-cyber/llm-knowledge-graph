# Frontend-Backend Feature Audit

Date: 2026-04-10
Scope: React frontend in frontend/src audited against FastAPI backend routes in backend/app.py

## Executive Status

- Core Student and Professor workflows are implemented and integrated end-to-end.
- Remaining work is no longer only polish: there are still backend capabilities not surfaced in frontend flows.
- Learning-path sequencing plus dependency edge authoring are now implemented.

## Done (Verified End-to-End)

### Authentication and session handling

- Login flow is implemented and token is persisted for API calls.
- Role-based workspace routing (student/professor) is implemented.
- Auth-expiry handling (401) is implemented in student and professor dashboards and returns users to sign-in.
- Verified routes used: /auth/login, /auth/me (token-driven flows), protected route calls across student/professor APIs.

### Student experience

- Live tutor chat is implemented with multimodal payload support (image attach in chat).
- Classroom Hub sync is implemented (announcements, modules, coursework, discussion feed).
- Progress visualization and trajectory display are implemented.
- Assignment submission and defence status retrieval are implemented.
- Achievement feed and AI insights panel are implemented.
- Learning tools (quiz, notes, flashcards, weak-concept drills) are implemented through chat orchestration.
- Verified routes used: /chat, /student/progress, /student/achievements, /student/classroom-feed, /student/submit-assignment, /student/submissions/{submission_id}.

### Professor experience

- Command Center is implemented (create announcements, create coursework, review submissions list).
- HITL queue is implemented (fetch + approve/reject with editable grade/feedback).
- Cohort overview and student drill-down are implemented using cohort and student data joins.
- Graph screen is implemented for visualization refresh, ingest trigger, and concept metadata editing.
- Learning path editor is implemented (load, add/remove, drag reorder, publish).
- Student note save/load workflow is implemented.
- Verified routes used: /professor/hitl-queue, /professor/hitl-queue/{queue_id}/action, /professor/cohort-overview, /professor/cohort, /professor/students, /professor/classroom-announcements (GET/POST), /professor/coursework (GET/POST), /professor/submissions, /professor/graph-visualization, /professor/learning-path (GET/POST), /professor/annotate (GET/POST), /concept/{concept_id} (PATCH), /ingest.

## Remaining (Not Yet Fully Delivered)

### Functional gaps in frontend coverage

- Graph authoring coverage is now substantially expanded in UI.
  - Module, topic, concept, fact, explicit edge create/delete, and a relationship canvas are implemented.
  - Advanced authoring depth has been partially delivered:
    - Multi-select + bulk edge create/delete are now implemented.
    - Persistent drag layout for relationship canvas is now implemented (local storage per course).
    - Undo/redo stack for edge mutations is now implemented.
  - Remaining gap is full studio interaction depth (for example lasso selection and grouped transform actions).

### Product-depth gaps

- Professor note management now includes history/version browsing and version load into draft.
- Graph UX is operational with visual relationship canvas support, drag persistence, multi-select batch operations, and edge undo/redo.
  - Missing capabilities include lasso/group actions and graph-specific revision timeline.

## Backend Available But Not Wired To Frontend Screens

- These routes are now wired through the frontend developer workbench under dev mode in App shell:
  - /auth/register
  - /enrol
  - /interaction
  - /query
  - /graph and /graph-view
  - Phase 6 operational routes (integrity/background-jobs/compliance/observability/llm-router/diagnostics)

These capabilities are now represented in explicit frontend flows for validation and operations via developer mode; production-grade role-tailored UX can be iterated on top of this wiring.

## Next High-Value Steps

1. Add backend tests for grade identifier normalization and graph-edge authorization.
2. Add frontend regression coverage for graph authoring, learning-path publish, and submission history.
3. Add lasso/group selection ergonomics and grouped transform interactions in graph canvas.
4. Add graph editor revision timeline/history (beyond edge undo/redo stack).

## Implementation Plan (Current)

### Completed

- Phase 1: Learning path dependency edge editor
- Phase 2: Student submission history view
- Phase 3: Professor manual grade workflow
- Phase 4: Graph authoring MVP (module/topic/concept/fact + edge CRUD)

### In Progress

- Phase 5: Hardening and QA

Testing focus
- Backend tests for grading identifier normalization and graph-edge authorization.
- Frontend regression checks for auth expiry, command center refresh, and learning-path publish.
- UI state checks for empty/error/loading flows in graph authoring and note history features.

## Implementation Progress Update (2026-04-10)

Completed in code
- Phase 1 implemented: learning path prerequisite dependency editor added in professor UI; publish now sends partial_order_edges and blocks cyclic dependencies client-side.
- Phase 2 implemented: student submission history tab added using /student/submissions with detail drill-in to existing status panel.
- Phase 3 implemented (Option B): professor manual grading UI added using /professor/grade from Command Center.
- Phase 4 implemented: graph authoring now includes module/topic/concept/fact creation plus explicit edge create/delete.
- Governance split implemented: CURRICULUM_PATH management separated from conceptual relationship management in UI.
- Professor note history/version browser implemented with load-into-draft behavior.
- Relationship canvas implemented for conceptual edge visualization and assisted selection.

Remaining
- Hardening and QA automation still in progress (backend and frontend regression test coverage).

Current optional follow-ups
- Add backend tests specifically for grade identifier normalization and graph edge mutation authorization paths.
- Add studio-grade graph editing ergonomics (persistent layout, multi-select bulk edits, undo/redo).
