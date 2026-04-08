# OmniProf Frontend (React + Vite)

This frontend is a unified API workbench for validating OmniProf end-to-end flows.

## Features

- JWT auth session controls and quick login buttons
- Student feature testing: chat, query, enroll, interaction, progress, achievements, submissions
- Content/graph testing: ingest, graph snapshots, graph view, concept create/update
- Professor feature testing: HITL queue, cohort, learning path, annotations, grading
- Phase 6 ops testing: LLM router health/route, background jobs, compliance
- WebSocket streaming test lab for `/ws/chat`

## Run

From repository root:

```powershell
Set-Location C:\Users\mitta\OneDrive\Desktop\LLM\llm-knowledge-graph\frontend
npm install
npm run dev
```

Open:

- http://127.0.0.1:5173

Backend should be running at:

- http://127.0.0.1:8000

If needed, change API base URL in the left sidebar of the app.
