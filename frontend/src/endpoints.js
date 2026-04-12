function qs(params = {}) {
  const q = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  });
  const text = q.toString();
  return text ? `?${text}` : "";
}

const getCache = new Map();

function extractErrorDetail(data) {
  if (!data) return "";
  if (typeof data === "string") return data;
  if (typeof data.detail === "string") return data.detail;
  return "";
}

function notifyAuthInvalid(reason) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent("omniprof-auth-invalid", {
      detail: {
        reason: reason || "Session expired. Please sign in again.",
      },
    }),
  );
}

function cacheKey(apiBase, path, token) {
  return `${apiBase}|${path}|${token || ""}`;
}

export async function apiRequest(
  apiBase,
  path,
  {
    method = "GET",
    token = "",
    body,
    formData,
    cacheTtlMs = 0,
    forceRefresh = false,
  } = {},
) {
  const isGet = method === "GET";
  const key = isGet ? cacheKey(apiBase, path, token) : "";
  if (isGet && cacheTtlMs > 0 && !forceRefresh) {
    const existing = getCache.get(key);
    if (existing && existing.expiresAt > Date.now()) {
      return existing.payload;
    }
  }

  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (!formData) headers["Content-Type"] = "application/json";

  const started = performance.now();
  const res = await fetch(`${apiBase}${path}`, {
    method,
    headers,
    body: formData || (body ? JSON.stringify(body) : undefined),
  });
  const elapsedMs = Math.round(performance.now() - started);
  const text = await res.text();
  let data = text;
  try {
    data = JSON.parse(text);
  } catch {
    // Keep plain text payloads
  }
  const payload = { ok: res.ok, status: res.status, elapsedMs, data };
  if (res.status === 401 && token) {
    const detail = extractErrorDetail(data);
    const lowerDetail = String(detail || "").toLowerCase();
    if (lowerDetail.includes("invalid token") || lowerDetail.includes("signature verification failed") || lowerDetail.includes("expired")) {
      notifyAuthInvalid(detail);
    }
  }
  if (isGet && cacheTtlMs > 0 && res.ok) {
    getCache.set(key, { expiresAt: Date.now() + cacheTtlMs, payload });
  }
  return payload;
}

export const AuthApi = {
  register: (apiBase, payload) =>
    apiRequest(apiBase, "/auth/register", {
      method: "POST",
      body: payload,
    }),
  login: (apiBase, username, password) =>
    apiRequest(apiBase, "/auth/login", {
      method: "POST",
      body: { username, password },
    }),
  me: (apiBase, token) => apiRequest(apiBase, "/auth/me", { token }),
};

export const StudentApi = {
  chat: (apiBase, token, payload) =>
    apiRequest(apiBase, "/chat", { method: "POST", token, body: payload }),
  progress: (apiBase, token, courseId, { forceRefresh = false } = {}) =>
    apiRequest(apiBase, `/student/progress${qs({ course_id: courseId })}`, {
      token,
      cacheTtlMs: 12000,
      forceRefresh,
    }),
  classroomFeed: (apiBase, token, courseId, { forceRefresh = false } = {}) =>
    apiRequest(
      apiBase,
      `/student/classroom-feed${qs({ course_id: courseId })}`,
      { token, cacheTtlMs: 12000, forceRefresh },
    ),
  achievements: (apiBase, token, { forceRefresh = false } = {}) =>
    apiRequest(apiBase, "/student/achievements", {
      token,
      cacheTtlMs: 12000,
      forceRefresh,
    }),
  studyPlan: (apiBase, token, courseId, { forceRefresh = false } = {}) =>
    apiRequest(apiBase, `/student/study-plan${qs({ course_id: courseId })}`, {
      token,
      cacheTtlMs: 12000,
      forceRefresh,
    }),
  notes: (apiBase, token, courseId, limit = 20, { forceRefresh = false } = {}) =>
    apiRequest(apiBase, `/student/notes${qs({ course_id: courseId, limit })}`, {
      token,
      cacheTtlMs: 8000,
      forceRefresh,
    }),
  hint: (apiBase, token, payload) =>
    apiRequest(apiBase, "/hints", {
      method: "POST",
      token,
      body: payload,
    }),
  submissions: (apiBase, token, courseId, { forceRefresh = false } = {}) =>
    apiRequest(apiBase, `/student/submissions${qs({ course_id: courseId })}`, {
      token,
      cacheTtlMs: 12000,
      forceRefresh,
    }),
  submitAssignment: (apiBase, token, file, courseId, assignmentId = "") => {
    const fd = new FormData();
    fd.append("file", file);
    return apiRequest(
      apiBase,
      `/student/submit-assignment${qs({ course_id: courseId, assignment_id: assignmentId })}`,
      {
        method: "POST",
        token,
        formData: fd,
      },
    );
  },
  submissionStatus: (apiBase, token, submissionId) =>
    apiRequest(
      apiBase,
      `/student/submissions/${encodeURIComponent(submissionId)}`,
      { token },
    ),
  enrol: (apiBase, token, courseId) =>
    apiRequest(apiBase, "/enrol", {
      method: "POST",
      token,
      body: { course_id: courseId },
    }),
  recordInteraction: (apiBase, token, payload) =>
    apiRequest(apiBase, "/interaction", {
      method: "POST",
      token,
      body: payload,
    }),
  query: (apiBase, token, payload) =>
    apiRequest(apiBase, "/query", {
      method: "POST",
      token,
      body: payload,
    }),
  graphView: (apiBase, token, query, { forceRefresh = false } = {}) =>
    apiRequest(apiBase, `/graph-view${qs({ query })}`, {
      token,
      cacheTtlMs: 5000,
      forceRefresh,
    }),
  graph: (apiBase, token, { forceRefresh = false } = {}) =>
    apiRequest(apiBase, "/graph", {
      token,
      cacheTtlMs: 8000,
      forceRefresh,
    }),
};

export const ProfessorApi = {
  hitlQueue: (apiBase, token, { forceRefresh = false } = {}) =>
    apiRequest(apiBase, "/professor/hitl-queue", {
      token,
      cacheTtlMs: 10000,
      forceRefresh,
    }),
  hitlAction: (apiBase, token, queueId, payload) =>
    apiRequest(
      apiBase,
      `/professor/hitl-queue/${encodeURIComponent(queueId)}/action`,
      {
        method: "POST",
        token,
        body: payload,
      },
    ),
  cohortOverview: (
    apiBase,
    token,
    courseId,
    inactivityDays = 7,
    { forceRefresh = false } = {},
  ) =>
    apiRequest(
      apiBase,
      `/professor/cohort-overview${qs({ course_id: courseId, inactivity_days: inactivityDays })}`,
      { token, cacheTtlMs: 10000, forceRefresh },
    ),
  cohortAlerts: (apiBase, token, courseId, { forceRefresh = false } = {}) =>
    apiRequest(apiBase, `/professor/cohort-alerts${qs({ course_id: courseId })}`, {
      token,
      cacheTtlMs: 10000,
      forceRefresh,
    }),
  cohort: (apiBase, token, courseId, { forceRefresh = false } = {}) =>
    apiRequest(apiBase, `/professor/cohort${qs({ course_id: courseId })}`, {
      token,
      cacheTtlMs: 10000,
      forceRefresh,
    }),
  students: (apiBase, token, { forceRefresh = false } = {}) =>
    apiRequest(apiBase, "/professor/students", {
      token,
      cacheTtlMs: 10000,
      forceRefresh,
    }),
  announcements: (apiBase, token, courseId, { forceRefresh = false } = {}) =>
    apiRequest(
      apiBase,
      `/professor/classroom-announcements${qs({ course_id: courseId })}`,
      { token, cacheTtlMs: 8000, forceRefresh },
    ),
  createAnnouncement: (apiBase, token, payload) =>
    apiRequest(apiBase, "/professor/classroom-announcements", {
      method: "POST",
      token,
      body: payload,
    }),
  coursework: (apiBase, token, courseId, { forceRefresh = false } = {}) =>
    apiRequest(apiBase, `/professor/coursework${qs({ course_id: courseId })}`, {
      token,
      cacheTtlMs: 8000,
      forceRefresh,
    }),
  createCoursework: (apiBase, token, payload) =>
    apiRequest(apiBase, "/professor/coursework", {
      method: "POST",
      token,
      body: payload,
    }),
  gradeSubmission: (apiBase, token, payload) =>
    apiRequest(apiBase, "/professor/grade", {
      method: "POST",
      token,
      body: payload,
    }),
  submissions: (apiBase, token, courseId, { forceRefresh = false } = {}) =>
    apiRequest(
      apiBase,
      `/professor/submissions${qs({ course_id: courseId })}`,
      { token, cacheTtlMs: 8000, forceRefresh },
    ),
  graphVisualization: (apiBase, token, courseId, { forceRefresh = false } = {}) =>
    apiRequest(
      apiBase,
      `/professor/graph-visualization${qs({ course_id: courseId })}`,
      { token, cacheTtlMs: 10000, forceRefresh },
    ),
  updateConcept: (apiBase, token, conceptId, payload) =>
    apiRequest(apiBase, `/concept/${encodeURIComponent(conceptId)}`, {
      method: "PATCH",
      token,
      body: payload,
    }),
  annotateStudent: (apiBase, token, payload) =>
    apiRequest(apiBase, "/professor/annotate", {
      method: "POST",
      token,
      body: payload,
    }),
  getStudentAnnotation: (
    apiBase,
    token,
    studentId,
    { forceRefresh = false } = {},
  ) =>
    apiRequest(
      apiBase,
      `/professor/annotate${qs({ student_id: studentId })}`,
      { token, cacheTtlMs: 5000, forceRefresh },
    ),
  loadLearningPath: (apiBase, token, courseId, { forceRefresh = false } = {}) =>
    apiRequest(
      apiBase,
      `/professor/learning-path${qs({ course_id: courseId })}`,
      { token, cacheTtlMs: 10000, forceRefresh },
    ),
  saveLearningPath: (apiBase, token, payload) =>
    apiRequest(apiBase, "/professor/learning-path", {
      method: "POST",
      token,
      body: payload,
    }),
  createConcept: (apiBase, token, payload) =>
    apiRequest(apiBase, "/concept", {
      method: "POST",
      token,
      body: payload,
    }),
  createModule: (apiBase, token, payload) =>
    apiRequest(apiBase, "/professor/module", {
      method: "POST",
      token,
      body: payload,
    }),
  createTopic: (apiBase, token, payload) =>
    apiRequest(apiBase, "/professor/topic", {
      method: "POST",
      token,
      body: payload,
    }),
  createFact: (apiBase, token, payload) =>
    apiRequest(apiBase, "/professor/fact", {
      method: "POST",
      token,
      body: payload,
    }),
  createGraphEdge: (apiBase, token, payload) =>
    apiRequest(apiBase, "/professor/graph-edge", {
      method: "POST",
      token,
      body: payload,
    }),
  deleteGraphEdge: (apiBase, token, payload) =>
    apiRequest(apiBase, "/professor/graph-edge/delete", {
      method: "POST",
      token,
      body: payload,
    }),
  ingest: (apiBase, token, file, courseId) => {
    const fd = new FormData();
    fd.append("file", file);
    return apiRequest(apiBase, `/ingest${qs({ course_id: courseId })}`, {
      method: "POST",
      token,
      formData: fd,
    });
  },
  lessonPlan: (apiBase, token, uploadId, { forceRefresh = false } = {}) =>
    apiRequest(apiBase, `/professor/lesson-plan/${encodeURIComponent(uploadId)}`, {
      token,
      cacheTtlMs: 6000,
      forceRefresh,
    }),
  generateQuiz: (apiBase, token, payload) =>
    apiRequest(apiBase, "/professor/generate-quiz", {
      method: "POST",
      token,
      body: payload,
    }),
  phase6Health: (apiBase, token, { forceRefresh = false } = {}) =>
    apiRequest(apiBase, "/llm-router/health", {
      token,
      cacheTtlMs: 5000,
      forceRefresh,
    }),
  phase6ComplianceStatus: (apiBase, token, { forceRefresh = false } = {}) =>
    apiRequest(apiBase, "/compliance/status", {
      token,
      cacheTtlMs: 5000,
      forceRefresh,
    }),
  phase6JobStats: (apiBase, token, { forceRefresh = false } = {}) =>
    apiRequest(apiBase, "/background-jobs/stats", {
      token,
      cacheTtlMs: 5000,
      forceRefresh,
    }),
  phase6ObservabilityMetrics: (apiBase, token, { forceRefresh = false } = {}) =>
    apiRequest(apiBase, "/observability/metrics", {
      token,
      cacheTtlMs: 5000,
      forceRefresh,
    }),
  phase6ObservabilityTraces: (apiBase, token, limit = 20) =>
    apiRequest(apiBase, `/observability/traces${qs({ limit })}`, {
      token,
    }),
  phase6ErrorBudget: (apiBase, token, { forceRefresh = false } = {}) =>
    apiRequest(apiBase, "/observability/error-budget", {
      token,
      cacheTtlMs: 5000,
      forceRefresh,
    }),
  phase6Providers: (apiBase, token, { forceRefresh = false } = {}) =>
    apiRequest(apiBase, "/observability/providers", {
      token,
      cacheTtlMs: 5000,
      forceRefresh,
    }),
  phase6Policy: (apiBase, token, { forceRefresh = false } = {}) =>
    apiRequest(apiBase, "/integrity/policy", {
      token,
      cacheTtlMs: 5000,
      forceRefresh,
    }),
  phase6UpdatePolicy: (apiBase, token, payload) =>
    apiRequest(apiBase, "/integrity/policy", {
      method: "PATCH",
      token,
      body: payload,
    }),
  phase6DrainJobs: (apiBase, token, maxJobs = 50) =>
    apiRequest(apiBase, "/background-jobs/drain", {
      method: "POST",
      token,
      body: { max_jobs: maxJobs },
    }),
  phase6ReplayDeadLetter: (apiBase, token, maxJobs = 50) =>
    apiRequest(apiBase, "/background-jobs/replay-dead-letter", {
      method: "POST",
      token,
      body: { max_jobs: maxJobs },
    }),
  phase6History: (apiBase, token, limit = 50) =>
    apiRequest(apiBase, `/background-jobs/history${qs({ limit })}`, {
      token,
    }),
  phase6DiagnosticsRun: (apiBase, token, payload) =>
    apiRequest(apiBase, "/diagnostics/nondeterminism/run", {
      method: "POST",
      token,
      body: payload,
    }),
  phase6RouteProbe: (apiBase, token, payload) =>
    apiRequest(apiBase, "/llm-router/route", {
      method: "POST",
      token,
      body: payload,
    }),
};
