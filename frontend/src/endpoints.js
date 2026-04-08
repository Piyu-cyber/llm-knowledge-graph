export const ENDPOINTS = [
  {
    id: "home",
    section: "overview",
    title: "Health",
    method: "GET",
    path: "/",
    description: "Backend health and version check.",
    auth: false
  },
  {
    id: "auth_register",
    section: "auth",
    title: "Register",
    method: "POST",
    path: "/auth/register",
    auth: false,
    description: "Create a user and return token.",
    bodyTemplate: {
      username: "new_student",
      email: "new_student@example.com",
      password: "Student@123",
      full_name: "New Student",
      role: "student"
    }
  },
  {
    id: "auth_login",
    section: "auth",
    title: "Login",
    method: "POST",
    path: "/auth/login",
    auth: false,
    description: "Get JWT token for API calls.",
    bodyTemplate: {
      username: "student_demo",
      password: "Student@123"
    }
  },
  {
    id: "auth_me",
    section: "auth",
    title: "Current User",
    method: "GET",
    path: "/auth/me",
    auth: true,
    description: "Resolve user profile from JWT."
  },
  {
    id: "chat",
    section: "student",
    title: "Multi-Agent Chat",
    method: "POST",
    path: "/chat",
    auth: true,
    description: "Main orchestration endpoint for tutoring/evaluation/progress intents.",
    bodyTemplate: {
      message: "Explain recursion with a simple example",
      session_id: "sess_ui_1",
      course_id: "cs101"
    }
  },
  {
    id: "query",
    section: "student",
    title: "CRAG Query",
    method: "POST",
    path: "/query",
    auth: true,
    description: "Single-turn CRAG query pipeline.",
    bodyTemplate: {
      query: "What is dynamic programming?",
      course_id: "cs101",
      use_graph: true,
      use_vector: true,
      confidence_threshold: 0.5
    }
  },
  {
    id: "enrol",
    section: "student",
    title: "Enroll Student",
    method: "POST",
    path: "/enrol",
    auth: true,
    description: "Initialize StudentOverlay nodes for a course.",
    bodyTemplate: {
      course_id: "cs101"
    }
  },
  {
    id: "interaction",
    section: "student",
    title: "Record Interaction",
    method: "POST",
    path: "/interaction",
    auth: true,
    description: "Update BKT theta/slip/mastery for a concept.",
    bodyTemplate: {
      concept_id: "replace_with_concept_id",
      answered_correctly: true,
      difficulty: 0.0
    }
  },
  {
    id: "student_progress",
    section: "student",
    title: "Student Progress",
    method: "GET",
    path: "/student/progress",
    auth: true,
    description: "Mastery bands and module/concept progress.",
    queryParams: [{ key: "course_id", value: "cs101" }]
  },
  {
    id: "student_achievements",
    section: "student",
    title: "Achievements",
    method: "GET",
    path: "/student/achievements",
    auth: true,
    description: "Read earned gamification badges."
  },
  {
    id: "student_submit",
    section: "student",
    title: "Submit Assignment",
    method: "POST",
    path: "/student/submit-assignment",
    auth: true,
    description: "Upload assignment and open defence workflow.",
    isFormData: true,
    fileField: "file",
    queryParams: [{ key: "course_id", value: "cs101" }]
  },
  {
    id: "student_submission_status",
    section: "student",
    title: "Submission Status",
    method: "GET",
    path: "/student/submissions/{submission_id}",
    auth: true,
    description: "Track defence approval status and final grade.",
    pathParams: [{ key: "submission_id", value: "replace_with_submission_id" }]
  },
  {
    id: "ingest",
    section: "graph",
    title: "Ingest File",
    method: "POST",
    path: "/ingest",
    auth: true,
    description: "Upload and ingest PDF/DOCX/PPTX/TXT.",
    isFormData: true,
    fileField: "file"
  },
  {
    id: "graph",
    section: "graph",
    title: "Graph Snapshot",
    method: "GET",
    path: "/graph",
    auth: true,
    description: "Read current knowledge graph payload."
  },
  {
    id: "graph_view",
    section: "graph",
    title: "Graph View by Query",
    method: "GET",
    path: "/graph-view",
    auth: true,
    description: "Get subgraph nodes and edges around a query.",
    queryParams: [{ key: "query", value: "recursion" }]
  },
  {
    id: "concept_create",
    section: "graph",
    title: "Create Concept",
    method: "POST",
    path: "/concept",
    auth: true,
    description: "Add concept via protected endpoint.",
    bodyTemplate: {
      name: "Sample Concept",
      description: "Created from UI workbench",
      category: "Algorithms",
      course_id: "cs101"
    }
  },
  {
    id: "concept_update",
    section: "graph",
    title: "Update Concept",
    method: "PATCH",
    path: "/concept/{concept_id}",
    auth: true,
    description: "Update concept metadata.",
    pathParams: [{ key: "concept_id", value: "replace_with_concept_id" }],
    bodyTemplate: {
      name: "Renamed Concept",
      description: "Updated via React workbench",
      visibility: "global",
      priority: 1
    }
  },
  {
    id: "prof_hitl_queue",
    section: "professor",
    title: "HITL Queue",
    method: "GET",
    path: "/professor/hitl-queue",
    auth: true,
    description: "Review defence records waiting for human approval."
  },
  {
    id: "prof_hitl_action",
    section: "professor",
    title: "HITL Queue Action",
    method: "POST",
    path: "/professor/hitl-queue/{queue_id}/action",
    auth: true,
    description: "Approve, modify+approve, or reject a queued entry.",
    pathParams: [{ key: "queue_id", value: "replace_with_queue_id" }],
    bodyTemplate: {
      action: "approve",
      review_note: "Looks good",
      modified_grade: 0.91,
      modified_feedback: "Strong defence"
    }
  },
  {
    id: "prof_cohort_overview",
    section: "professor",
    title: "Cohort Overview",
    method: "GET",
    path: "/professor/cohort-overview",
    auth: true,
    description: "Topic mastery distribution and inactive students.",
    queryParams: [
      { key: "course_id", value: "cs101" },
      { key: "inactivity_days", value: "7" }
    ]
  },
  {
    id: "prof_graph_visualization",
    section: "professor",
    title: "Graph Visualization",
    method: "GET",
    path: "/professor/graph-visualization",
    auth: true,
    description: "Read-only graph payload for professor UI.",
    queryParams: [{ key: "course_id", value: "cs101" }]
  },
  {
    id: "prof_learning_path_save",
    section: "professor",
    title: "Save Learning Path",
    method: "POST",
    path: "/professor/learning-path",
    auth: true,
    description: "Persist ordered/partial course path.",
    bodyTemplate: {
      course_id: "cs101",
      ordered_concept_ids: ["concept_a", "concept_b"],
      partial_order_edges: [{ source: "concept_a", target: "concept_b" }]
    }
  },
  {
    id: "prof_learning_path_get",
    section: "professor",
    title: "Get Learning Path",
    method: "GET",
    path: "/professor/learning-path",
    auth: true,
    description: "Fetch course learning path config.",
    queryParams: [{ key: "course_id", value: "cs101" }]
  },
  {
    id: "prof_cohort",
    section: "professor",
    title: "Professor Cohort",
    method: "GET",
    path: "/professor/cohort",
    auth: true,
    description: "Per-student concept mastery summary.",
    queryParams: [{ key: "course_id", value: "cs101" }]
  },
  {
    id: "prof_students",
    section: "professor",
    title: "Professor Students",
    method: "GET",
    path: "/professor/students",
    auth: true,
    description: "List enrolled students inferred from overlays."
  },
  {
    id: "prof_grade",
    section: "professor",
    title: "Grade Defence Record",
    method: "POST",
    path: "/professor/grade",
    auth: true,
    description: "Approve or reject a defence with optional override.",
    bodyTemplate: {
      record_id: "replace_with_record_id",
      action: "approve",
      modified_grade: 0.89,
      modified_feedback: "Solid work"
    }
  },
  {
    id: "prof_annotate",
    section: "professor",
    title: "Annotate Student",
    method: "POST",
    path: "/professor/annotate",
    auth: true,
    description: "Create private professor annotation for a student.",
    bodyTemplate: {
      student_id: "replace_with_student_id",
      annotation: "Needs help with recursion and DP base cases"
    }
  },
  {
    id: "router_health",
    section: "phase6",
    title: "LLM Router Health",
    method: "GET",
    path: "/llm-router/health",
    auth: true,
    description: "Provider availability and backoff visibility."
  },
  {
    id: "router_route",
    section: "phase6",
    title: "LLM Router Probe",
    method: "POST",
    path: "/llm-router/route",
    auth: true,
    description: "Probe route selection for a task/prompt pair.",
    bodyTemplate: {
      task: "intent_classification",
      prompt: "Classify this request intent"
    }
  },
  {
    id: "jobs_stats",
    section: "phase6",
    title: "Background Jobs Stats",
    method: "GET",
    path: "/background-jobs/stats",
    auth: true,
    description: "Queue and dead-letter depth.",
    roleHint: "admin"
  },
  {
    id: "jobs_drain",
    section: "phase6",
    title: "Background Jobs Drain",
    method: "POST",
    path: "/background-jobs/drain",
    auth: true,
    description: "Run due jobs and flush retries.",
    roleHint: "admin"
  },
  {
    id: "compliance_status",
    section: "phase6",
    title: "Compliance Status",
    method: "GET",
    path: "/compliance/status",
    auth: true,
    description: "FERPA/GDPR readiness checks.",
    roleHint: "admin"
  },
  {
    id: "integrity_policy_get",
    section: "phase6",
    title: "Integrity Policy",
    method: "GET",
    path: "/integrity/policy",
    auth: true,
    description: "Read runtime integrity policy values.",
    roleHint: "professor"
  },
  {
    id: "integrity_policy_patch",
    section: "phase6",
    title: "Update Integrity Policy",
    method: "PATCH",
    path: "/integrity/policy",
    auth: true,
    description: "Update minimum token threshold for SDI visibility at runtime.",
    roleHint: "professor",
    bodyTemplate: {
      min_token_threshold: 700
    }
  },
  {
    id: "nondeterminism_run",
    section: "phase6",
    title: "Run Nondeterminism Diff",
    method: "POST",
    path: "/diagnostics/nondeterminism/run",
    auth: true,
    description: "Execute repeated routed calls and persist reproducibility artifact.",
    roleHint: "admin",
    bodyTemplate: {
      task: "ta_tutoring",
      prompt: "Explain BFS",
      runs: 5
    }
  },
  {
    id: "embeddings_health",
    section: "phase6",
    title: "Embeddings Health",
    method: "GET",
    path: "/health/embeddings",
    auth: true,
    description: "Active embedding backend and probe-vector health metrics."
  }
];

export const SECTIONS = [
  { key: "overview", label: "Overview" },
  { key: "auth", label: "Auth" },
  { key: "student", label: "Student Lab" },
  { key: "graph", label: "Graph + Content" },
  { key: "professor", label: "Professor Lab" },
  { key: "phase6", label: "Ops + Hardening" },
  { key: "stream", label: "WebSocket Stream" }
];
