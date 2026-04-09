# OmniProf Frontend (Role-First UX)

This frontend is now product-oriented with role-first navigation:

- **Student Dashboard**
  - Chat journey
  - Progress visualization with low/medium/high mastery bands
  - Assignment submissions and defence status tracking
  - Achievements feed
- **Professor Dashboard**
  - HITL queue review workflow (approve / modify+approve / reject)
  - Cohort analytics and student drill-down
  - Graph editor controls for concept metadata updates
  - Learning path manager (ordered concepts + partial order edges)

JWT quick-login controls are still included to speed local testing.

## Run

From `frontend`:

```powershell
npm install
npm run dev
```

Open:

- http://127.0.0.1:5173

Backend should be running at:

- http://127.0.0.1:8000

If needed, change API base URL in the left sidebar.
