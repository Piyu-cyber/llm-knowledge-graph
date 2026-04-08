import { useMemo, useState } from "react";
import { AuthApi, ProfessorApi, StudentApi } from "./endpoints";

function parseJwt(token) {
  try {
    const payload = token.split(".")[1];
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
    const decoded = JSON.parse(atob(normalized));
    return decoded;
  } catch {
    return null;
  }
}

function roleFromJwt(payload) {
  if (!payload) return "unknown";
  return payload.role || payload.user_role || "unknown";
}

export default function App() {
  const [apiBase, setApiBase] = useState(localStorage.getItem("omniprof_api_base") || "http://127.0.0.1:8000");
  const [token, setToken] = useState(localStorage.getItem("omniprof_token") || "");
  const [active, setActive] = useState("student");
  const [activity, setActivity] = useState([]);
  const [chatMessage, setChatMessage] = useState("Explain recursion with a simple real-world example");
  const [chatSession, setChatSession] = useState("sess_app_1");
  const [chatCourse, setChatCourse] = useState("cs101");
  const [chatHistory, setChatHistory] = useState([]);
  const [studentProgress, setStudentProgress] = useState(null);
  const [studentAchievements, setStudentAchievements] = useState([]);
  const [submissionFile, setSubmissionFile] = useState(null);
  const [submissionIds, setSubmissionIds] = useState([]);
  const [submissionLookupId, setSubmissionLookupId] = useState("");
  const [submissionStatus, setSubmissionStatus] = useState(null);
  const [cohortOverview, setCohortOverview] = useState(null);
  const [cohortStudents, setCohortStudents] = useState([]);
  const [studentsList, setStudentsList] = useState([]);
  const [selectedStudent, setSelectedStudent] = useState("");
  const [hitlQueue, setHitlQueue] = useState([]);
  const [profCourse, setProfCourse] = useState("cs101");
  const [graphData, setGraphData] = useState(null);
  const [conceptId, setConceptId] = useState("");
  const [conceptName, setConceptName] = useState("");
  const [conceptDescription, setConceptDescription] = useState("");
  const [conceptVisibility, setConceptVisibility] = useState("global");
  const [conceptPriority, setConceptPriority] = useState(1);
  const [learningPath, setLearningPath] = useState({ ordered_concept_ids: [], partial_order_edges: [] });
  const [orderedIdsText, setOrderedIdsText] = useState("");
  const [edgesText, setEdgesText] = useState("[]");
  const [actionNote, setActionNote] = useState("Reviewed in dashboard");
  const [busy, setBusy] = useState(false);

  const tokenPayload = useMemo(() => (token ? parseJwt(token) : null), [token]);

  const saveBase = (value) => {
    setApiBase(value);
    localStorage.setItem("omniprof_api_base", value);
  };

  const saveToken = (value) => {
    setToken(value);
    localStorage.setItem("omniprof_token", value);
  };

  const pushActivity = (entry) => {
    setActivity((prev) => [{ ts: new Date().toISOString(), ...entry }, ...prev].slice(0, 30));
  };

  const quickLogin = async (username, password) => {
    try {
      const res = await AuthApi.login(apiBase, username, password);
      if (res.data?.access_token) {
        saveToken(res.data.access_token);
      }
      pushActivity({ endpoint: "/auth/login", status: res.status, ok: res.ok, method: "POST" });
    } catch {
      pushActivity({ endpoint: "/auth/login", status: 0, ok: false, method: "POST" });
    }
  };

  const runStudentChat = async () => {
    setBusy(true);
    try {
      const data = await StudentApi.chat(apiBase, token, {
        message: chatMessage,
        session_id: chatSession,
        course_id: chatCourse,
      });
      setChatHistory((prev) => [
        ...prev,
        { role: "student", content: chatMessage },
        { role: "assistant", content: data.data?.response || JSON.stringify(data.data) },
      ]);
      pushActivity({ endpoint: "/chat", status: data.status, ok: data.ok, method: "POST" });
    } finally {
      setBusy(false);
    }
  };

  const loadStudentData = async () => {
    setBusy(true);
    try {
      const [progressRes, achievementsRes] = await Promise.all([
        StudentApi.progress(apiBase, token, chatCourse),
        StudentApi.achievements(apiBase, token),
      ]);
      setStudentProgress(progressRes.data);
      setStudentAchievements(progressRes.ok ? achievementsRes.data?.achievements || [] : []);
      pushActivity({ endpoint: "/student/progress", status: progressRes.status, ok: progressRes.ok, method: "GET" });
      pushActivity({ endpoint: "/student/achievements", status: achievementsRes.status, ok: achievementsRes.ok, method: "GET" });
    } finally {
      setBusy(false);
    }
  };

  const submitAssignment = async () => {
    if (!submissionFile) return;
    setBusy(true);
    try {
      const res = await StudentApi.submitAssignment(apiBase, token, submissionFile, chatCourse);
      const id = res.data?.submission_id;
      if (id) {
        setSubmissionIds((prev) => [id, ...prev].slice(0, 20));
        setSubmissionLookupId(id);
      }
      pushActivity({ endpoint: "/student/submit-assignment", status: res.status, ok: res.ok, method: "POST" });
    } finally {
      setBusy(false);
    }
  };

  const loadSubmissionStatus = async () => {
    if (!submissionLookupId) return;
    setBusy(true);
    try {
      const res = await StudentApi.submissionStatus(apiBase, token, submissionLookupId);
      setSubmissionStatus(res.data);
      pushActivity({ endpoint: "/student/submissions/{id}", status: res.status, ok: res.ok, method: "GET" });
    } finally {
      setBusy(false);
    }
  };

  const loadProfessorData = async () => {
    setBusy(true);
    try {
      const [overviewRes, queueRes, cohortRes, studentsRes] = await Promise.all([
        ProfessorApi.cohortOverview(apiBase, token, profCourse, 7),
        ProfessorApi.hitlQueue(apiBase, token),
        ProfessorApi.cohort(apiBase, token, profCourse),
        ProfessorApi.students(apiBase, token),
      ]);
      setCohortOverview(overviewRes.data);
      setHitlQueue(queueRes.data?.items || []);
      setCohortStudents(cohortRes.data?.students || []);
      setStudentsList(studentsRes.data?.students || []);
      pushActivity({ endpoint: "/professor/cohort-overview", status: overviewRes.status, ok: overviewRes.ok, method: "GET" });
      pushActivity({ endpoint: "/professor/hitl-queue", status: queueRes.status, ok: queueRes.ok, method: "GET" });
    } finally {
      setBusy(false);
    }
  };

  const doHitlAction = async (queueId, action) => {
    setBusy(true);
    try {
      const payload = { action, review_note: actionNote };
      const res = await ProfessorApi.hitlAction(apiBase, token, queueId, payload);
      pushActivity({ endpoint: "/professor/hitl-queue/{queue_id}/action", status: res.status, ok: res.ok, method: "POST" });
      await loadProfessorData();
    } finally {
      setBusy(false);
    }
  };

  const loadGraphEditorData = async () => {
    setBusy(true);
    try {
      const [graphRes, pathRes] = await Promise.all([
        ProfessorApi.graphVisualization(apiBase, token, profCourse),
        ProfessorApi.loadLearningPath(apiBase, token, profCourse),
      ]);
      setGraphData(graphRes.data);
      const lp = pathRes.data || {};
      setLearningPath(lp);
      setOrderedIdsText((lp.ordered_concept_ids || []).join("\n"));
      setEdgesText(JSON.stringify(lp.partial_order_edges || [], null, 2));
      pushActivity({ endpoint: "/professor/graph-visualization", status: graphRes.status, ok: graphRes.ok, method: "GET" });
      pushActivity({ endpoint: "/professor/learning-path", status: pathRes.status, ok: pathRes.ok, method: "GET" });
    } finally {
      setBusy(false);
    }
  };

  const saveConcept = async () => {
    if (!conceptId) return;
    setBusy(true);
    try {
      const res = await ProfessorApi.updateConcept(apiBase, token, conceptId, {
        name: conceptName || undefined,
        description: conceptDescription || undefined,
        visibility: conceptVisibility,
        priority: Number(conceptPriority),
      });
      pushActivity({ endpoint: "/concept/{concept_id}", status: res.status, ok: res.ok, method: "PATCH" });
      await loadGraphEditorData();
    } finally {
      setBusy(false);
    }
  };

  const saveLearningPath = async () => {
    setBusy(true);
    try {
      let parsedEdges = [];
      try {
        parsedEdges = JSON.parse(edgesText || "[]");
      } catch {
        parsedEdges = [];
      }
      const payload = {
        course_id: profCourse,
        ordered_concept_ids: orderedIdsText.split("\n").map((x) => x.trim()).filter(Boolean),
        partial_order_edges: Array.isArray(parsedEdges) ? parsedEdges : [],
      };
      const res = await ProfessorApi.saveLearningPath(apiBase, token, payload);
      pushActivity({ endpoint: "/professor/learning-path", status: res.status, ok: res.ok, method: "POST" });
      await loadGraphEditorData();
    } finally {
      setBusy(false);
    }
  };

  const role = roleFromJwt(tokenPayload);
  const selectedStudentRow = cohortStudents.find((s) => s.student_id === selectedStudent);
  const mastery = studentProgress?.mastery || [];
  const low = mastery.filter((m) => m.confidence_band === "low").length;
  const medium = mastery.filter((m) => m.confidence_band === "medium").length;
  const high = mastery.filter((m) => m.confidence_band === "high").length;
  const total = Math.max(1, mastery.length);

  return (
    <div className="app-shell">
      <aside className="left-rail">
        <h1>OmniProf Portal</h1>
        <p className="muted">Role-first learning and teaching experience.</p>

        <label>
          <span>API Base URL</span>
          <input value={apiBase} onChange={(e) => saveBase(e.target.value)} className="mono" />
        </label>

        <label>
          <span>Bearer Token</span>
          <textarea rows={5} value={token} onChange={(e) => saveToken(e.target.value)} className="mono" />
        </label>

        <div className="quick-login">
          <button onClick={() => quickLogin("student_demo", "Student@123")}>Quick Login: Student</button>
          <button onClick={() => quickLogin("professor_demo", "Professor@123")}>Quick Login: Professor</button>
          <button onClick={() => saveToken("")}>Clear Token</button>
        </div>

        <div className="token-meta">
          <p className="tiny">Decoded JWT</p>
          <pre>{JSON.stringify(tokenPayload, null, 2) || "No token"}</pre>
        </div>

        <nav>
          <button className={active === "student" ? "nav-btn active" : "nav-btn"} onClick={() => setActive("student")}>Student Dashboard</button>
          <button className={active === "professor" ? "nav-btn active" : "nav-btn"} onClick={() => setActive("professor")}>Professor Dashboard</button>
        </nav>
        <p className="tiny tag">JWT Role: {role}</p>
      </aside>

      <main className="main-panel">
        <header className="hero card">
          <p className="eyebrow">OmniProf Frontend</p>
          <h2>{active === "student" ? "Student Learning Dashboard" : "Professor Teaching Dashboard"}</h2>
          <p>
            {active === "student"
              ? "Chat with your TA agent, track mastery bands, monitor submissions, and celebrate achievements."
              : "Review HITL queues, understand cohort health, drill into student progress, and manage graph/learning path controls."}
          </p>
        </header>

        {active === "student" && (
          <section className="card app-grid">
            <article className="app-pane">
              <h3>Chat Journey</h3>
              <div className="field-grid">
                <label><span>Session</span><input value={chatSession} onChange={(e) => setChatSession(e.target.value)} /></label>
                <label><span>Course</span><input value={chatCourse} onChange={(e) => setChatCourse(e.target.value)} /></label>
              </div>
              <label>
                <span>Message</span>
                <textarea rows={4} value={chatMessage} onChange={(e) => setChatMessage(e.target.value)} />
              </label>
              <div className="button-row">
                <button className="btn-primary" onClick={runStudentChat} disabled={busy}>Send</button>
                <button onClick={loadStudentData} disabled={busy}>Refresh Progress + Achievements</button>
              </div>
              <div className="chat-window">
                {chatHistory.map((m, i) => (
                  <p key={`${m.role}-${i}`} className={m.role === "assistant" ? "assistant-line" : "student-line"}>
                    <strong>{m.role}:</strong> {m.content}
                  </p>
                ))}
                {chatHistory.length === 0 && <p className="muted">No messages yet.</p>}
              </div>
            </article>
            <article className="app-pane">
              <h3>Progress Bands</h3>
              <div className="progress-bars">
                <div><span>Low</span><progress max={total} value={low} /><strong>{low}</strong></div>
                <div><span>Medium</span><progress max={total} value={medium} /><strong>{medium}</strong></div>
                <div><span>High</span><progress max={total} value={high} /><strong>{high}</strong></div>
              </div>
              <pre>{studentProgress ? JSON.stringify(studentProgress, null, 2) : "Load progress to view data."}</pre>

              <h3>Submissions & Defence</h3>
              <label><span>Upload Assignment</span><input type="file" onChange={(e) => setSubmissionFile(e.target.files?.[0] || null)} /></label>
              <div className="button-row">
                <button onClick={submitAssignment} disabled={busy || !submissionFile}>Submit</button>
              </div>
              <label><span>Check Submission ID</span><input value={submissionLookupId} onChange={(e) => setSubmissionLookupId(e.target.value)} /></label>
              <div className="button-row">
                <button onClick={loadSubmissionStatus} disabled={busy || !submissionLookupId}>Refresh Status</button>
              </div>
              {submissionIds.length > 0 && <p className="tiny">Recent IDs: {submissionIds.join(", ")}</p>}
              <pre>{submissionStatus ? JSON.stringify(submissionStatus, null, 2) : "No submission status loaded."}</pre>

              <h3>Achievements Feed</h3>
              <pre>{JSON.stringify(studentAchievements, null, 2)}</pre>
            </article>
          </section>
        )}

        {active === "professor" && (
          <section className="card app-grid">
            <article className="app-pane">
              <h3>Cohort Analytics + Drill-down</h3>
              <label><span>Course ID</span><input value={profCourse} onChange={(e) => setProfCourse(e.target.value)} /></label>
              <div className="button-row">
                <button className="btn-primary" onClick={loadProfessorData} disabled={busy}>Refresh Professor Data</button>
                <button onClick={loadGraphEditorData} disabled={busy}>Load Graph + Learning Path</button>
              </div>
              <pre>{cohortOverview ? JSON.stringify(cohortOverview, null, 2) : "No cohort data loaded yet."}</pre>
              <label>
                <span>Student Drill-down</span>
                <select value={selectedStudent} onChange={(e) => setSelectedStudent(e.target.value)}>
                  <option value="">Select student</option>
                  {cohortStudents.map((s) => <option key={s.student_id} value={s.student_id}>{s.student_id}</option>)}
                </select>
              </label>
              <pre>{selectedStudentRow ? JSON.stringify(selectedStudentRow, null, 2) : "Select a student to inspect concept mastery and struggles."}</pre>
              <p className="tiny">Student roster: {studentsList.join(", ") || "None loaded"}</p>
            </article>
            <article className="app-pane">
              <h3>HITL Queue Workflow</h3>
              <label><span>Review Note</span><input value={actionNote} onChange={(e) => setActionNote(e.target.value)} /></label>
              {hitlQueue.length === 0 && <p className="muted">No queue items.</p>}
              {hitlQueue.map((item) => (
                <div key={item.queue_id || Math.random()} className="queue-card">
                  <p><strong>Queue ID:</strong> {item.queue_id}</p>
                  <p><strong>Student:</strong> {item.student_id}</p>
                  <p><strong>AI Grade:</strong> {item.ai_recommended_grade}</p>
                  <div className="button-row">
                    <button onClick={() => doHitlAction(item.queue_id, "approve")} disabled={busy}>Approve</button>
                    <button onClick={() => doHitlAction(item.queue_id, "modify_approve")} disabled={busy}>Modify + Approve</button>
                    <button onClick={() => doHitlAction(item.queue_id, "reject_second_defence")} disabled={busy}>Reject</button>
                  </div>
                </div>
              ))}

              <h3>Graph Editor UX</h3>
              <label><span>Concept ID</span><input value={conceptId} onChange={(e) => setConceptId(e.target.value)} /></label>
              <label><span>Name</span><input value={conceptName} onChange={(e) => setConceptName(e.target.value)} /></label>
              <label><span>Description</span><textarea rows={3} value={conceptDescription} onChange={(e) => setConceptDescription(e.target.value)} /></label>
              <div className="field-grid">
                <label>
                  <span>Visibility</span>
                  <select value={conceptVisibility} onChange={(e) => setConceptVisibility(e.target.value)}>
                    <option value="global">global</option>
                    <option value="enrolled-only">enrolled-only</option>
                    <option value="professor-only">professor-only</option>
                  </select>
                </label>
                <label><span>Priority</span><input type="number" value={conceptPriority} onChange={(e) => setConceptPriority(e.target.value)} /></label>
              </div>
              <button onClick={saveConcept} disabled={busy || !conceptId}>Save Concept Changes</button>
              <pre>{graphData ? JSON.stringify(graphData, null, 2) : "Load graph data to visualize editable concept targets."}</pre>

              <h3>Learning Path Manager</h3>
              <label><span>Ordered Concept IDs (newline separated)</span><textarea rows={4} value={orderedIdsText} onChange={(e) => setOrderedIdsText(e.target.value)} /></label>
              <label><span>Partial Order Edges (JSON)</span><textarea rows={5} value={edgesText} onChange={(e) => setEdgesText(e.target.value)} className="mono" /></label>
              <button onClick={saveLearningPath} disabled={busy}>Save Learning Path</button>
              <pre>{JSON.stringify(learningPath, null, 2)}</pre>
            </article>
          </section>
        )}

        <section className="card activity-log">
          <h3>Recent Calls</h3>
          <div className="activity-list">
            {activity.length === 0 && <p className="muted">No calls yet.</p>}
            {activity.map((item, idx) => (
              <p key={`${item.ts}-${idx}`} className={item.ok ? "ok" : "bad"}>
                {item.method} {item.endpoint} to {item.status} ({new Date(item.ts).toLocaleTimeString()})
              </p>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}
