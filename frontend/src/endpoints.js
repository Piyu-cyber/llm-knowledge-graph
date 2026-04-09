function qs(params = {}) {
  const q = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  });
  const text = q.toString();
  return text ? `?${text}` : "";
}

export async function apiRequest(apiBase, path, { method = "GET", token = "", body, formData } = {}) {
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
  return { ok: res.ok, status: res.status, elapsedMs, data };
}

export const AuthApi = {
  login: (apiBase, username, password) =>
    apiRequest(apiBase, "/auth/login", { method: "POST", body: { username, password } }),
  me: (apiBase, token) => apiRequest(apiBase, "/auth/me", { token }),
};

export const StudentApi = {
  chat: (apiBase, token, payload) => apiRequest(apiBase, "/chat", { method: "POST", token, body: payload }),
  progress: (apiBase, token, courseId) =>
    apiRequest(apiBase, `/student/progress${qs({ course_id: courseId })}`, { token }),
  achievements: (apiBase, token) => apiRequest(apiBase, "/student/achievements", { token }),
  submitAssignment: (apiBase, token, file, courseId) => {
    const fd = new FormData();
    fd.append("file", file);
    return apiRequest(apiBase, `/student/submit-assignment${qs({ course_id: courseId })}`, {
      method: "POST",
      token,
      formData: fd,
    });
  },
  submissionStatus: (apiBase, token, submissionId) =>
    apiRequest(apiBase, `/student/submissions/${encodeURIComponent(submissionId)}`, { token }),
};

export const ProfessorApi = {
  hitlQueue: (apiBase, token) => apiRequest(apiBase, "/professor/hitl-queue", { token }),
  hitlAction: (apiBase, token, queueId, payload) =>
    apiRequest(apiBase, `/professor/hitl-queue/${encodeURIComponent(queueId)}/action`, {
      method: "POST",
      token,
      body: payload,
    }),
  cohortOverview: (apiBase, token, courseId, inactivityDays = 7) =>
    apiRequest(apiBase, `/professor/cohort-overview${qs({ course_id: courseId, inactivity_days: inactivityDays })}`, { token }),
  cohort: (apiBase, token, courseId) =>
    apiRequest(apiBase, `/professor/cohort${qs({ course_id: courseId })}`, { token }),
  students: (apiBase, token) => apiRequest(apiBase, "/professor/students", { token }),
  graphVisualization: (apiBase, token, courseId) =>
    apiRequest(apiBase, `/professor/graph-visualization${qs({ course_id: courseId })}`, { token }),
  updateConcept: (apiBase, token, conceptId, payload) =>
    apiRequest(apiBase, `/concept/${encodeURIComponent(conceptId)}`, {
      method: "PATCH",
      token,
      body: payload,
    }),
  loadLearningPath: (apiBase, token, courseId) =>
    apiRequest(apiBase, `/professor/learning-path${qs({ course_id: courseId })}`, { token }),
  saveLearningPath: (apiBase, token, payload) =>
    apiRequest(apiBase, "/professor/learning-path", { method: "POST", token, body: payload }),
  ingest: (apiBase, token, file, courseId) => {
    const fd = new FormData();
    fd.append("file", file);
    return apiRequest(apiBase, `/ingest${qs({ course_id: courseId })}`, {
      method: "POST",
      token,
      formData: fd,
    });
  },
};
