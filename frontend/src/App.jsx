import { useMemo, useState } from "react";
import { ENDPOINTS, SECTIONS } from "./endpoints";

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

function toWsUrl(apiBase) {
  if (apiBase.startsWith("https://")) return apiBase.replace("https://", "wss://");
  if (apiBase.startsWith("http://")) return apiBase.replace("http://", "ws://");
  return apiBase;
}

function buildUrl(apiBase, path, pathParams, queryParams) {
  let resolvedPath = path;
  pathParams.forEach((p) => {
    resolvedPath = resolvedPath.replace(`{${p.key}}`, encodeURIComponent(p.value || ""));
  });

  const url = new URL(`${apiBase}${resolvedPath}`);
  queryParams.forEach((q) => {
    if (q.key && q.value !== "") {
      url.searchParams.set(q.key, q.value);
    }
  });

  return url.toString();
}

function EndpointCard({ endpoint, apiBase, token, onTokenUpdate, pushLog }) {
  const [pathParams, setPathParams] = useState(endpoint.pathParams || []);
  const [queryParams, setQueryParams] = useState(endpoint.queryParams || []);
  const [bodyText, setBodyText] = useState(
    endpoint.bodyTemplate ? JSON.stringify(endpoint.bodyTemplate, null, 2) : ""
  );
  const [selectedFile, setSelectedFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [response, setResponse] = useState(null);

  const sampleCurl = useMemo(() => {
    const url = buildUrl(apiBase, endpoint.path, pathParams, queryParams);
    return `${endpoint.method} ${url}`;
  }, [apiBase, endpoint, pathParams, queryParams]);

  const updateParam = (setter, list, idx, field, value) => {
    const next = [...list];
    next[idx] = { ...next[idx], [field]: value };
    setter(next);
  };

  const execute = async () => {
    setLoading(true);
    setResponse(null);

    try {
      const url = buildUrl(apiBase, endpoint.path, pathParams, queryParams);
      const headers = {};
      if (endpoint.auth && token) {
        headers.Authorization = `Bearer ${token}`;
      }

      const options = { method: endpoint.method, headers };

      if (endpoint.isFormData) {
        const formData = new FormData();
        if (selectedFile && endpoint.fileField) {
          formData.append(endpoint.fileField, selectedFile);
        }
        options.body = formData;
      } else if (!["GET", "DELETE"].includes(endpoint.method)) {
        headers["Content-Type"] = "application/json";
        options.body = bodyText.trim() ? bodyText : "{}";
        JSON.parse(options.body);
      }

      const started = performance.now();
      const res = await fetch(url, options);
      const elapsedMs = Math.round(performance.now() - started);

      const rawText = await res.text();
      let parsed = rawText;
      try {
        parsed = JSON.parse(rawText);
      } catch {
        // Keep raw text when response is not JSON.
      }

      const payload = {
        ok: res.ok,
        status: res.status,
        elapsedMs,
        data: parsed
      };

      setResponse(payload);
      pushLog({
        ts: new Date().toISOString(),
        endpoint: endpoint.path,
        method: endpoint.method,
        status: res.status,
        ok: res.ok
      });

      if (
        (endpoint.id === "auth_login" || endpoint.id === "auth_register") &&
        parsed &&
        typeof parsed === "object" &&
        parsed.access_token
      ) {
        onTokenUpdate(parsed.access_token);
      }
    } catch (err) {
      setResponse({ ok: false, status: 0, elapsedMs: 0, data: String(err) });
    } finally {
      setLoading(false);
    }
  };

  return (
    <article className="card endpoint-card">
      <header className="endpoint-head">
        <div>
          <p className="muted micro">{endpoint.section.toUpperCase()}</p>
          <h3>{endpoint.title}</h3>
        </div>
        <span className={`method method-${endpoint.method.toLowerCase()}`}>{endpoint.method}</span>
      </header>

      <p className="muted">{endpoint.description}</p>
      <p className="mono tiny">{sampleCurl}</p>

      {endpoint.roleHint && <p className="tiny tag">Role: {endpoint.roleHint}</p>}
      {endpoint.auth && !token && <p className="warn">This endpoint requires Bearer token.</p>}

      {pathParams.length > 0 && (
        <div className="field-grid">
          {pathParams.map((p, idx) => (
            <label key={`${endpoint.id}-path-${p.key}`}>
              <span>Path: {p.key}</span>
              <input
                value={p.value}
                onChange={(e) => updateParam(setPathParams, pathParams, idx, "value", e.target.value)}
              />
            </label>
          ))}
        </div>
      )}

      {queryParams.length > 0 && (
        <div className="field-grid">
          {queryParams.map((q, idx) => (
            <label key={`${endpoint.id}-query-${q.key}`}>
              <span>Query: {q.key}</span>
              <input
                value={q.value}
                onChange={(e) => updateParam(setQueryParams, queryParams, idx, "value", e.target.value)}
              />
            </label>
          ))}
        </div>
      )}

      {endpoint.isFormData ? (
        <label>
          <span>{endpoint.fileField || "file"}</span>
          <input type="file" onChange={(e) => setSelectedFile(e.target.files?.[0] || null)} />
        </label>
      ) : (
        !["GET", "DELETE"].includes(endpoint.method) && (
          <label>
            <span>JSON body</span>
            <textarea
              rows={7}
              value={bodyText}
              onChange={(e) => setBodyText(e.target.value)}
              className="mono"
            />
          </label>
        )
      )}

      <button className="btn-primary" onClick={execute} disabled={loading}>
        {loading ? "Running..." : "Run Endpoint"}
      </button>

      {response && (
        <section className="response-box">
          <p className={`status ${response.ok ? "ok" : "bad"}`}>
            HTTP {response.status} in {response.elapsedMs} ms
          </p>
          <pre>{JSON.stringify(response.data, null, 2)}</pre>
        </section>
      )}
    </article>
  );
}

function WsStreamLab({ apiBase, token }) {
  const [sessionId, setSessionId] = useState("sess_ws_1");
  const [courseId, setCourseId] = useState("cs101");
  const [message, setMessage] = useState("Explain backtracking using a maze problem");
  const [streamed, setStreamed] = useState("");
  const [events, setEvents] = useState([]);

  const connectAndSend = () => {
    if (!token) {
      setEvents((prev) => ["Missing token", ...prev]);
      return;
    }

    const base = toWsUrl(apiBase);
    const wsUrl = `${base}/ws/chat?token=${encodeURIComponent(token)}&session_id=${encodeURIComponent(
      sessionId
    )}&course_id=${encodeURIComponent(courseId)}`;

    const socket = new WebSocket(wsUrl);
    setStreamed("");

    socket.onopen = () => {
      setEvents((prev) => [`OPEN ${new Date().toLocaleTimeString()}`, ...prev]);
      socket.send(JSON.stringify({ message }));
    };

    socket.onmessage = (evt) => {
      const payload = JSON.parse(evt.data);
      if (payload.event === "token") {
        setStreamed((prev) => prev + payload.token);
      }
      if (payload.event === "complete" || payload.event === "error") {
        socket.close();
      }
      setEvents((prev) => [JSON.stringify(payload), ...prev].slice(0, 20));
    };

    socket.onerror = () => {
      setEvents((prev) => ["WebSocket error", ...prev]);
    };
  };

  return (
    <section className="card">
      <h3>WebSocket Streaming Chat</h3>
      <p className="muted">
        Tests token streaming from <span className="mono">/ws/chat</span> using the same JWT from Auth tab.
      </p>
      <div className="field-grid">
        <label>
          <span>Session ID</span>
          <input value={sessionId} onChange={(e) => setSessionId(e.target.value)} />
        </label>
        <label>
          <span>Course ID</span>
          <input value={courseId} onChange={(e) => setCourseId(e.target.value)} />
        </label>
      </div>
      <label>
        <span>Message</span>
        <textarea rows={4} value={message} onChange={(e) => setMessage(e.target.value)} />
      </label>
      <button className="btn-primary" onClick={connectAndSend}>Start Stream</button>

      <div className="split">
        <article>
          <h4>Streamed Output</h4>
          <pre>{streamed || "(waiting for response...)"}</pre>
        </article>
        <article>
          <h4>Recent Events</h4>
          <pre>{events.join("\n\n") || "(no events yet)"}</pre>
        </article>
      </div>
    </section>
  );
}

export default function App() {
  const [apiBase, setApiBase] = useState(localStorage.getItem("omniprof_api_base") || "http://127.0.0.1:8000");
  const [token, setToken] = useState(localStorage.getItem("omniprof_token") || "");
  const [active, setActive] = useState("student_app");
  const [activity, setActivity] = useState([]);
  const [chatMessage, setChatMessage] = useState("Explain recursion with a simple real-world example");
  const [chatSession, setChatSession] = useState("sess_app_1");
  const [chatCourse, setChatCourse] = useState("cs101");
  const [chatHistory, setChatHistory] = useState([]);
  const [studentProgress, setStudentProgress] = useState(null);
  const [studentAchievements, setStudentAchievements] = useState([]);
  const [cohortOverview, setCohortOverview] = useState(null);
  const [hitlQueue, setHitlQueue] = useState([]);
  const [profCourse, setProfCourse] = useState("cs101");
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

  const quickLogin = async (username, password) => {
    try {
      const res = await fetch(`${apiBase}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password })
      });
      const data = await res.json();
      if (data.access_token) {
        saveToken(data.access_token);
      }
      setActivity((prev) => [{ ts: new Date().toISOString(), endpoint: "/auth/login", status: res.status, ok: res.ok, method: "POST" }, ...prev].slice(0, 25));
    } catch {
      // Ignore quick-login network errors in UI state.
    }
  };

  const sectionEndpoints = ENDPOINTS.filter((e) => e.section === active);

  const authHeaders = () => ({
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    "Content-Type": "application/json"
  });

  const runStudentChat = async () => {
    setBusy(true);
    try {
      const res = await fetch(`${apiBase}/chat`, {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({
          message: chatMessage,
          session_id: chatSession,
          course_id: chatCourse
        })
      });
      const data = await res.json();
      setChatHistory((prev) => [
        ...prev,
        { role: "student", content: chatMessage },
        { role: "assistant", content: data.response || JSON.stringify(data) }
      ]);
      setActivity((prev) => [{ ts: new Date().toISOString(), endpoint: "/chat", status: res.status, ok: res.ok, method: "POST" }, ...prev].slice(0, 25));
    } finally {
      setBusy(false);
    }
  };

  const loadStudentData = async () => {
    setBusy(true);
    try {
      const [progressRes, achievementsRes] = await Promise.all([
        fetch(`${apiBase}/student/progress?course_id=${encodeURIComponent(chatCourse)}`, { headers: authHeaders() }),
        fetch(`${apiBase}/student/achievements`, { headers: authHeaders() })
      ]);
      const progressData = await progressRes.json();
      const achievementsData = await achievementsRes.json();
      setStudentProgress(progressData);
      setStudentAchievements(achievementsData.achievements || []);
      setActivity((prev) => [
        { ts: new Date().toISOString(), endpoint: "/student/progress", status: progressRes.status, ok: progressRes.ok, method: "GET" },
        { ts: new Date().toISOString(), endpoint: "/student/achievements", status: achievementsRes.status, ok: achievementsRes.ok, method: "GET" },
        ...prev
      ].slice(0, 25));
    } finally {
      setBusy(false);
    }
  };

  const loadProfessorData = async () => {
    setBusy(true);
    try {
      const [overviewRes, queueRes] = await Promise.all([
        fetch(`${apiBase}/professor/cohort-overview?course_id=${encodeURIComponent(profCourse)}&inactivity_days=7`, { headers: authHeaders() }),
        fetch(`${apiBase}/professor/hitl-queue`, { headers: authHeaders() })
      ]);
      setCohortOverview(await overviewRes.json());
      const queueData = await queueRes.json();
      setHitlQueue(queueData.items || []);
      setActivity((prev) => [
        { ts: new Date().toISOString(), endpoint: "/professor/cohort-overview", status: overviewRes.status, ok: overviewRes.ok, method: "GET" },
        { ts: new Date().toISOString(), endpoint: "/professor/hitl-queue", status: queueRes.status, ok: queueRes.ok, method: "GET" },
        ...prev
      ].slice(0, 25));
    } finally {
      setBusy(false);
    }
  };

  const doHitlAction = async (queueId, action) => {
    setBusy(true);
    try {
      const res = await fetch(`${apiBase}/professor/hitl-queue/${encodeURIComponent(queueId)}/action`, {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({ action, review_note: `Action from dashboard: ${action}` })
      });
      setActivity((prev) => [{ ts: new Date().toISOString(), endpoint: "/professor/hitl-queue/{queue_id}/action", status: res.status, ok: res.ok, method: "POST" }, ...prev].slice(0, 25));
      await loadProfessorData();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="app-shell">
      <aside className="left-rail">
        <h1>OmniProf Control Room</h1>
        <p className="muted">React + Vite full-stack frontend for testing all major features.</p>

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
          <button className={active === "student_app" ? "nav-btn active" : "nav-btn"} onClick={() => setActive("student_app")}>Student App</button>
          <button className={active === "professor_app" ? "nav-btn active" : "nav-btn"} onClick={() => setActive("professor_app")}>Professor App</button>
          <button className={active === "api_lab" ? "nav-btn active" : "nav-btn"} onClick={() => setActive("api_lab")}>API Lab</button>
          <button className={active === "stream" ? "nav-btn active" : "nav-btn"} onClick={() => setActive("stream")}>Streaming</button>
        </nav>
      </aside>

      <main className="main-panel">
        <header className="hero card">
          <p className="eyebrow">OmniProf Frontend</p>
          <h2>Application Pages + Engineering Lab</h2>
          <p>
            Use Student App and Professor App for product workflows. API Lab remains available for diagnostics and deeper endpoint checks.
          </p>
        </header>

        {active === "student_app" && (
          <section className="card app-grid">
            <article className="app-pane">
              <h3>Student Chat</h3>
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
              <h3>Progress Snapshot</h3>
              <pre>{studentProgress ? JSON.stringify(studentProgress, null, 2) : "Load progress to view data."}</pre>
              <h3>Achievements</h3>
              <pre>{JSON.stringify(studentAchievements, null, 2)}</pre>
            </article>
          </section>
        )}

        {active === "professor_app" && (
          <section className="card app-grid">
            <article className="app-pane">
              <h3>Professor Overview</h3>
              <label><span>Course ID</span><input value={profCourse} onChange={(e) => setProfCourse(e.target.value)} /></label>
              <div className="button-row">
                <button className="btn-primary" onClick={loadProfessorData} disabled={busy}>Refresh Professor Data</button>
              </div>
              <pre>{cohortOverview ? JSON.stringify(cohortOverview, null, 2) : "No cohort data loaded yet."}</pre>
            </article>
            <article className="app-pane">
              <h3>HITL Queue</h3>
              {hitlQueue.length === 0 && <p className="muted">No queue items.</p>}
              {hitlQueue.map((item) => (
                <div key={item.queue_id || Math.random()} className="queue-card">
                  <p><strong>Queue ID:</strong> {item.queue_id}</p>
                  <p><strong>Student:</strong> {item.student_id}</p>
                  <p><strong>AI Grade:</strong> {item.ai_recommended_grade}</p>
                  <div className="button-row">
                    <button onClick={() => doHitlAction(item.queue_id, "approve")} disabled={busy}>Approve</button>
                    <button onClick={() => doHitlAction(item.queue_id, "reject_second_defence")} disabled={busy}>Reject</button>
                  </div>
                </div>
              ))}
            </article>
          </section>
        )}

        {active === "stream" ? (
          <WsStreamLab apiBase={apiBase} token={token} />
        ) : active === "api_lab" ? (
          <section className="card">
            <h3>API Lab Sections</h3>
            <div className="button-row wrap-row">
              {SECTIONS.filter((s) => s.key !== "stream").map((section) => (
                <button key={section.key} onClick={() => setActive(section.key)}>{section.label}</button>
              ))}
            </div>
            <p className="muted">Choose a section above to run endpoint cards.</p>
          </section>
        ) : (
          <section className="endpoint-grid">
            {sectionEndpoints.map((endpoint) => (
              <EndpointCard
                key={endpoint.id}
                endpoint={endpoint}
                apiBase={apiBase}
                token={token}
                onTokenUpdate={saveToken}
                pushLog={(entry) => setActivity((prev) => [entry, ...prev].slice(0, 25))}
              />
            ))}
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
