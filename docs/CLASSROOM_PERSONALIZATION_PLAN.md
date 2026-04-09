# OmniProf Classroom Personalization Plan

## 1) Objective

Use existing OmniProf capabilities to support classroom learning with:

- Course-aware AI tutoring for students
- Professor-led oversight and intervention
- Personalized pathways using graph + mastery overlays
- Repeatable testing and rollout workflow

## 2) Current Feature Matrix

### Student-facing

- Auth and role-scoped access (`/auth/login`, `/auth/me`)
- Tutoring orchestration (`/chat`, `/ws/chat`)
- Retrieval and query diagnostics (`/query`)
- Course enrollment (`/enrol`)
- Interaction logging and mastery updates (`/interaction`)
- Progress dashboard API (`/student/progress`)
- Achievement feed (`/student/achievements`)
- Assignment + defence workflow (`/student/submit-assignment`, `/student/submissions/{id}`)

### Professor-facing

- HITL grading queue (`/professor/hitl-queue`)
- HITL review actions (`/professor/hitl-queue/{queue_id}/action`)
- Cohort analytics (`/professor/cohort-overview`, `/professor/cohort`, `/professor/students`)
- Knowledge graph visibility (`/professor/graph-visualization`)
- Learning path controls (`/professor/learning-path`)
- Professor grading + annotations (`/professor/grade`, `/professor/annotate`)

### Ops / hardening

- LLM routing health + probes
- Background queue stats / drain / replay / history
- Compliance status and observability metrics/traces
- Embeddings health endpoint

## 3) Data Bootstrap Plan

1. Ingest two PDFs (syllabus + combined PPT) into graph/RAG.
2. Create 3 baseline student personas for differentiated support.
3. Enroll persona students in target course (`cs101`) to initialize overlays.
4. Validate key flows with each persona:
   - tutoring
   - progress retrieval
   - assignment + submission status

## 4) Personalization Testing Plan

- Foundation learner: expects simpler explanations + scaffolded flow.
- Balanced learner: expects moderate depth + revision prompts.
- Advanced learner: expects deeper links and challenge prompts.

Success signals:

- Distinct response style by persona over repeated chats.
- Progress and mastery records created for each student.
- Professor dashboard sees persona students and queue activity.

## 5) Immediate Implementation Steps

1. Fix runtime error in memory context assembly.
2. Run bootstrap script to ingest course docs and create personas.
3. Smoke test auth/chat/progress for each persona.
4. Validate professor cohort + HITL APIs with seeded data.

## 6) Next Enhancements (optional)

- Add explicit persona-aware prompt conditioning in TA flow.
- Add persona management UI for professors.
- Add automated scenario test suite per persona archetype.
