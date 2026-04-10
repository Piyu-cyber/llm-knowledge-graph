import { useMemo, useState } from "react";
import { AuthApi, ProfessorApi, StudentApi } from "./endpoints";
import StudentDashboard from "./StudentDashboard";
import ProfessorDashboard from "./ProfessorDashboard";

function parseJwt(token) {
  try {
    const payload = token.split(".")[1];
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(normalized));
  } catch {
    return null;
  }
}

function roleFromJwt(payload) {
  if (!payload) return "Guest";
  return payload.role || payload.user_role || "Guest";
}

export default function App() {
  // --- STATE ---
  const [devMode, setDevMode] = useState(false);
  const [lowPowerMode, setLowPowerMode] = useState(localStorage.getItem("omniprof_low_power") === "1");
  const [apiBase, setApiBase] = useState(localStorage.getItem("omniprof_api_base") || "http://127.0.0.1:8000");
  const [token, setToken] = useState(localStorage.getItem("omniprof_token") || "");
  const [active, setActive] = useState("student");
  const [activity, setActivity] = useState([]);
  const [busy, setBusy] = useState(false);
  const [authView, setAuthView] = useState(token ? "workspace" : "landing");
  const [loginUsername, setLoginUsername] = useState("student_demo");
  const [loginPassword, setLoginPassword] = useState("Student@123");
  const [authError, setAuthError] = useState("");

  const [chatSession, setChatSession] = useState("sess_app_1"); // Hidden by default
  const [chatCourse, setChatCourse] = useState("cs101"); // Hidden by default

  // Professor State
  const [profCourse, setProfCourse] = useState("cs101");
  const [workbenchBusy, setWorkbenchBusy] = useState(false);
  const [workbenchResult, setWorkbenchResult] = useState(null);
  const [registerDraft, setRegisterDraft] = useState({
    username: "",
    email: "",
    password: "",
    full_name: "",
    role: "student",
    switchToken: true,
  });
  const [enrolCourseDraft, setEnrolCourseDraft] = useState("cs101");
  const [interactionDraft, setInteractionDraft] = useState({
    concept_id: "",
    answered_correctly: true,
    difficulty: "0",
  });
  const [queryDraft, setQueryDraft] = useState({
    query: "",
    course_id: "cs101",
  });
  const [graphViewQuery, setGraphViewQuery] = useState("");
  const [phase6Draft, setPhase6Draft] = useState({
    maxJobs: "25",
    traceLimit: "20",
    historyLimit: "30",
    diagnosticsRuns: "3",
    diagnosticsPrompt: "Explain gradient descent simply.",
    routerPrompt: "Summarize Bayesian inference in 2 lines.",
    routerRouteHint: "auto",
  });

  const tokenPayload = useMemo(() => (token ? parseJwt(token) : null), [token]);
  const role = roleFromJwt(tokenPayload);

  const saveBase = (val) => { setApiBase(val); localStorage.setItem("omniprof_api_base", val); };
  const saveToken = (val) => { setToken(val); localStorage.setItem("omniprof_token", val); };
  const saveLowPowerMode = (enabled) => {
    setLowPowerMode(enabled);
    localStorage.setItem("omniprof_low_power", enabled ? "1" : "0");
  };

  const pushActivity = (entry) => {
    setActivity(prev => [{ ts: new Date().toISOString(), ...entry }, ...prev].slice(0, 50));
  };

  const applySuccessfulLogin = (accessToken) => {
    saveToken(accessToken);
    const payload = parseJwt(accessToken);
    const nextRole = roleFromJwt(payload);
    if (nextRole === "professor") {
      setActive("professor");
    } else {
      setActive("student");
    }
    setAuthError("");
    setAuthView("workspace");
  };

  const handleSignOut = () => {
    saveToken("");
    setAuthError("");
    setAuthView("landing");
  };

  const quickLogin = async (username, password) => {
    setBusy(true);
    setAuthError("");
    try {
      const res = await AuthApi.login(apiBase, username, password);
      if (res.ok && res.data?.access_token) {
        applySuccessfulLogin(res.data.access_token);
      } else {
        setAuthError(res.data?.detail || "Login failed. Please check credentials.");
      }
      pushActivity({ endpoint: "/auth/login", status: res.status, ok: res.ok, method: "POST" });
    } catch {
      setAuthError("Network error while signing in.");
      pushActivity({ endpoint: "/auth/login", status: 0, ok: false, method: "POST" });
    } finally {
      setBusy(false);
    }
  };

  const submitLogin = async (e) => {
    e.preventDefault();
    if (!loginUsername.trim() || !loginPassword.trim()) {
      setAuthError("Username and password are required.");
      return;
    }
    await quickLogin(loginUsername.trim(), loginPassword);
  };

  const openLoginForRole = (roleHint) => {
    if (roleHint === "professor") {
      setLoginUsername("professor_demo");
      setLoginPassword("Professor@123");
    } else {
      setLoginUsername("student_demo");
      setLoginPassword("Student@123");
    }
    setAuthError("");
    setAuthView("login");
  };

  const runWorkbenchAction = async ({ endpoint, method, call, onSuccess }) => {
    setWorkbenchBusy(true);
    setWorkbenchResult(null);
    try {
      const res = await call();
      pushActivity({ endpoint, status: res.status, ok: res.ok, method });
      setWorkbenchResult({ endpoint, method, status: res.status, ok: res.ok, data: res.data });
      if (res.ok && onSuccess) onSuccess(res);
    } catch (err) {
      setWorkbenchResult({
        endpoint,
        method,
        status: 0,
        ok: false,
        data: { detail: String(err?.message || err || "Network error") },
      });
      pushActivity({ endpoint, status: 0, ok: false, method });
    } finally {
      setWorkbenchBusy(false);
    }
  };

  const isAuthenticated = Boolean(token);

  if (!isAuthenticated && authView === "landing") {
    return (
      <div className="auth-shell">
        <section className="landing-page">
          <h1>OmniProf</h1>
          <p>Adaptive learning workspace with syllabus-guided retrieval and tutoring.</p>
          <div className="landing-actions">
            <button className="auth-button primary" onClick={() => openLoginForRole("student")}>Continue as Student</button>
            <button className="auth-button" onClick={() => openLoginForRole("professor")}>Continue as Professor</button>
          </div>
          <button className="landing-secondary" onClick={() => setAuthView("login")}>Use custom credentials</button>
        </section>
      </div>
    );
  }

  if (!isAuthenticated && authView === "login") {
    return (
      <div className="auth-shell">
        <section className="login-page">
          <h2>Sign in to OmniProf</h2>
          <form onSubmit={submitLogin} className="login-form">
            <label>
              Username
              <input value={loginUsername} onChange={(e) => setLoginUsername(e.target.value)} autoComplete="username" />
            </label>
            <label>
              Password
              <input type="password" value={loginPassword} onChange={(e) => setLoginPassword(e.target.value)} autoComplete="current-password" />
            </label>
            {authError && <div className="auth-error">{authError}</div>}
            <button type="submit" className="auth-button primary" disabled={busy}>{busy ? "Signing in..." : "Sign in"}</button>
          </form>
          <div className="login-quick">
            <button className="auth-button" onClick={() => openLoginForRole("student")} disabled={busy}>Use Student Demo</button>
            <button className="auth-button" onClick={() => openLoginForRole("professor")} disabled={busy}>Use Professor Demo</button>
          </div>
          <button className="landing-secondary" onClick={() => setAuthView("landing")}>Back to landing</button>
        </section>
      </div>
    );
  }

  return (
    <div className={`app-container paper-theme ${lowPowerMode ? "reduced-motion" : ""}`}>
      {/* SIDEBAR */}
      <aside className="sidebar">
        <div className="brand">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 10v6M2 10l10-5 10 5-10 5z"/><path d="M6 12v5c3 3 9 3 12 0v-5"/></svg>
          OmniProf
        </div>

        <nav className="nav-menu">
          {(role === "student" || role === "admin" || role === "Guest") && (
            <button className={`nav-item ${active === "student" ? "active" : ""}`} onClick={() => setActive("student")}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>
              Student Workspace
            </button>
          )}
          {(role === "professor" || role === "Guest" || role === "admin") && (
            <button className={`nav-item ${active === "professor" ? "active" : ""}`} onClick={() => setActive("professor")}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>
              Professor Tools
            </button>
          )}
        </nav>

        <div className="sidebar-footer">
          <div className="role-badge">Logged in as: {role}</div>
          <button className="auth-button" onClick={handleSignOut}>Sign Out</button>

          <label className="perf-toggle">
            <input
              type="checkbox"
              checked={lowPowerMode}
              onChange={(e) => saveLowPowerMode(e.target.checked)}
            />
            <span>Low-power mode</span>
          </label>

          <button className="dev-mode-toggle" title="Developer Settings" onClick={() => setDevMode(!devMode)}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33h.09a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9c.26.6.8.97 1.48 1h.11a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>
          </button>
        </div>
      </aside>

      {/* MAIN CONTENT */}
      <main className="main-content">
        {devMode && (
          <div className="dev-banner">
            Developer Mode Active. Internal configurations and API settings are exposed below.
          </div>
        )}

        <header className="header">
          <h1>{active === "student" ? "Welcome back." : "Professor Dashboard"}</h1>
          <p>{active === "student" ? "Your AI Teaching Assistant is ready to help." : "Manage your cohort and human-in-the-loop queue."}</p>
        </header>

        {(active === "student" || active === "professor") && devMode && (
          <div className="header" style={{paddingTop: 0, paddingBottom: 0}}>
            <div className="dev-panel">
              <h4>API Configuration</h4>
              <div className="field-group">
                <label>API Base URL</label>
                <input value={apiBase} onChange={(e) => saveBase(e.target.value)} />
              </div>
              <div className="field-group">
                <label>Active JWT Token</label>
                <textarea rows="3" value={token} onChange={(e) => saveToken(e.target.value)} placeholder="eyJh..." />
              </div>
              
              <h4>Session Overrides</h4>
              <div style={{display: 'flex', gap: '1rem', marginBottom: '1rem'}}>
                <div style={{flex: 1}}>
                  <label style={{fontSize: '0.85rem', display:'block', marginBottom:'0.5rem'}}>Course ID</label>
                  <input value={active==="student"?chatCourse:profCourse} onChange={(e) => active==="student"?setChatCourse(e.target.value):setProfCourse(e.target.value)} />
                </div>
                {active==="student" && (
                  <div style={{flex: 1}}>
                    <label style={{fontSize: '0.85rem', display:'block', marginBottom:'0.5rem'}}>Session ID</label>
                    <input value={chatSession} onChange={(e) => setChatSession(e.target.value)} />
                  </div>
                )}
              </div>

              <h4>Backend Workbench (Remaining API Flows)</h4>
              <div style={{display: "grid", gap: "0.9rem"}}>
                <div style={{padding: "0.65rem", border: "1px solid var(--border-light)", borderRadius: "8px"}}>
                  <strong style={{fontSize: "0.82rem"}}>Auth Register</strong>
                  <div style={{display: "grid", gap: "0.45rem", gridTemplateColumns: "repeat(2, minmax(120px, 1fr))", marginTop: "0.45rem"}}>
                    <input placeholder="username" value={registerDraft.username} onChange={(e) => setRegisterDraft((p) => ({ ...p, username: e.target.value }))} />
                    <input placeholder="email" value={registerDraft.email} onChange={(e) => setRegisterDraft((p) => ({ ...p, email: e.target.value }))} />
                    <input placeholder="password" type="password" value={registerDraft.password} onChange={(e) => setRegisterDraft((p) => ({ ...p, password: e.target.value }))} />
                    <input placeholder="full name" value={registerDraft.full_name} onChange={(e) => setRegisterDraft((p) => ({ ...p, full_name: e.target.value }))} />
                    <select value={registerDraft.role} onChange={(e) => setRegisterDraft((p) => ({ ...p, role: e.target.value }))}>
                      <option value="student">student</option>
                      <option value="professor">professor</option>
                      <option value="admin">admin</option>
                    </select>
                    <label style={{display: "flex", alignItems: "center", gap: "0.45rem", fontSize: "0.78rem"}}>
                      <input type="checkbox" checked={registerDraft.switchToken} onChange={(e) => setRegisterDraft((p) => ({ ...p, switchToken: e.target.checked }))} />
                      Switch to new token
                    </label>
                  </div>
                  <button
                    className="btn-solid"
                    style={{width: "auto", marginTop: "0.45rem", padding: "0.32rem 0.7rem"}}
                    disabled={workbenchBusy}
                    onClick={() => runWorkbenchAction({
                      endpoint: "/auth/register",
                      method: "POST",
                      call: () => AuthApi.register(apiBase, {
                        username: registerDraft.username.trim(),
                        email: registerDraft.email.trim(),
                        password: registerDraft.password,
                        full_name: registerDraft.full_name.trim() || undefined,
                        role: registerDraft.role,
                      }),
                      onSuccess: (res) => {
                        if (registerDraft.switchToken && res.data?.access_token) {
                          applySuccessfulLogin(res.data.access_token);
                        }
                      },
                    })}
                  >
                    Register User
                  </button>
                </div>

                <div style={{padding: "0.65rem", border: "1px solid var(--border-light)", borderRadius: "8px"}}>
                  <strong style={{fontSize: "0.82rem"}}>Enrollment / Interaction / Query</strong>
                  <div style={{display: "grid", gap: "0.45rem", gridTemplateColumns: "repeat(3, minmax(120px, 1fr))", marginTop: "0.45rem"}}>
                    <input placeholder="course_id" value={enrolCourseDraft} onChange={(e) => setEnrolCourseDraft(e.target.value)} />
                    <button className="btn-solid" style={{width: "auto", padding: "0.32rem 0.7rem"}} disabled={workbenchBusy || !token} onClick={() => runWorkbenchAction({ endpoint: "/enrol", method: "POST", call: () => StudentApi.enrol(apiBase, token, enrolCourseDraft.trim()) })}>Enrol</button>
                    <span style={{fontSize: "0.74rem", color: "var(--text-secondary)", alignSelf: "center"}}>Requires active JWT</span>
                  </div>

                  <div style={{display: "grid", gap: "0.45rem", gridTemplateColumns: "2fr 1fr 1fr auto", marginTop: "0.45rem"}}>
                    <input placeholder="concept_id" value={interactionDraft.concept_id} onChange={(e) => setInteractionDraft((p) => ({ ...p, concept_id: e.target.value }))} />
                    <select value={interactionDraft.answered_correctly ? "true" : "false"} onChange={(e) => setInteractionDraft((p) => ({ ...p, answered_correctly: e.target.value === "true" }))}>
                      <option value="true">correct</option>
                      <option value="false">incorrect</option>
                    </select>
                    <input type="number" step="0.1" min="-4" max="4" placeholder="difficulty" value={interactionDraft.difficulty} onChange={(e) => setInteractionDraft((p) => ({ ...p, difficulty: e.target.value }))} />
                    <button className="btn-solid" style={{width: "auto", padding: "0.32rem 0.7rem"}} disabled={workbenchBusy || !token} onClick={() => runWorkbenchAction({ endpoint: "/interaction", method: "POST", call: () => StudentApi.recordInteraction(apiBase, token, { concept_id: interactionDraft.concept_id.trim(), answered_correctly: interactionDraft.answered_correctly, difficulty: Number(interactionDraft.difficulty || 0) }) })}>Record Interaction</button>
                  </div>

                  <div style={{display: "grid", gap: "0.45rem", gridTemplateColumns: "3fr 1fr auto", marginTop: "0.45rem"}}>
                    <input placeholder="query" value={queryDraft.query} onChange={(e) => setQueryDraft((p) => ({ ...p, query: e.target.value }))} />
                    <input placeholder="course_id" value={queryDraft.course_id} onChange={(e) => setQueryDraft((p) => ({ ...p, course_id: e.target.value }))} />
                    <button className="btn-solid" style={{width: "auto", padding: "0.32rem 0.7rem"}} disabled={workbenchBusy || !token} onClick={() => runWorkbenchAction({ endpoint: "/query", method: "POST", call: () => StudentApi.query(apiBase, token, { query: queryDraft.query, course_id: queryDraft.course_id || undefined, use_graph: true, use_vector: true, confidence_threshold: 0.5 }) })}>Run Query</button>
                  </div>
                </div>

                <div style={{padding: "0.65rem", border: "1px solid var(--border-light)", borderRadius: "8px"}}>
                  <strong style={{fontSize: "0.82rem"}}>Graph / Graph-View</strong>
                  <div style={{display: "grid", gap: "0.45rem", gridTemplateColumns: "3fr auto auto", marginTop: "0.45rem"}}>
                    <input placeholder="graph-view query" value={graphViewQuery} onChange={(e) => setGraphViewQuery(e.target.value)} />
                    <button className="btn-solid" style={{width: "auto", padding: "0.32rem 0.7rem"}} disabled={workbenchBusy || !token} onClick={() => runWorkbenchAction({ endpoint: "/graph", method: "GET", call: () => StudentApi.graph(apiBase, token, { forceRefresh: true }) })}>Get /graph</button>
                    <button className="btn-solid" style={{width: "auto", padding: "0.32rem 0.7rem"}} disabled={workbenchBusy || !token} onClick={() => runWorkbenchAction({ endpoint: "/graph-view", method: "GET", call: () => StudentApi.graphView(apiBase, token, graphViewQuery.trim(), { forceRefresh: true }) })}>Get /graph-view</button>
                  </div>
                </div>

                <div style={{padding: "0.65rem", border: "1px solid var(--border-light)", borderRadius: "8px"}}>
                  <strong style={{fontSize: "0.82rem"}}>Phase 6 Operations</strong>
                  <div style={{display: "flex", gap: "0.45rem", flexWrap: "wrap", marginTop: "0.45rem"}}>
                    <button className="btn-solid" style={{width: "auto", padding: "0.28rem 0.62rem"}} disabled={workbenchBusy || !token} onClick={() => runWorkbenchAction({ endpoint: "/llm-router/health", method: "GET", call: () => ProfessorApi.phase6Health(apiBase, token, { forceRefresh: true }) })}>Router Health</button>
                    <button className="btn-solid" style={{width: "auto", padding: "0.28rem 0.62rem"}} disabled={workbenchBusy || !token} onClick={() => runWorkbenchAction({ endpoint: "/integrity/policy", method: "GET", call: () => ProfessorApi.phase6Policy(apiBase, token, { forceRefresh: true }) })}>Integrity Policy</button>
                    <button className="btn-solid" style={{width: "auto", padding: "0.28rem 0.62rem"}} disabled={workbenchBusy || !token} onClick={() => runWorkbenchAction({ endpoint: "/background-jobs/stats", method: "GET", call: () => ProfessorApi.phase6JobStats(apiBase, token, { forceRefresh: true }) })}>Job Stats</button>
                    <button className="btn-solid" style={{width: "auto", padding: "0.28rem 0.62rem"}} disabled={workbenchBusy || !token} onClick={() => runWorkbenchAction({ endpoint: "/compliance/status", method: "GET", call: () => ProfessorApi.phase6ComplianceStatus(apiBase, token, { forceRefresh: true }) })}>Compliance</button>
                    <button className="btn-solid" style={{width: "auto", padding: "0.28rem 0.62rem"}} disabled={workbenchBusy || !token} onClick={() => runWorkbenchAction({ endpoint: "/observability/metrics", method: "GET", call: () => ProfessorApi.phase6ObservabilityMetrics(apiBase, token, { forceRefresh: true }) })}>Metrics</button>
                    <button className="btn-solid" style={{width: "auto", padding: "0.28rem 0.62rem"}} disabled={workbenchBusy || !token} onClick={() => runWorkbenchAction({ endpoint: "/observability/error-budget", method: "GET", call: () => ProfessorApi.phase6ErrorBudget(apiBase, token, { forceRefresh: true }) })}>Error Budget</button>
                    <button className="btn-solid" style={{width: "auto", padding: "0.28rem 0.62rem"}} disabled={workbenchBusy || !token} onClick={() => runWorkbenchAction({ endpoint: "/observability/providers", method: "GET", call: () => ProfessorApi.phase6Providers(apiBase, token, { forceRefresh: true }) })}>Providers</button>
                  </div>

                  <div style={{display: "grid", gap: "0.45rem", gridTemplateColumns: "1fr auto auto", marginTop: "0.55rem"}}>
                    <input type="number" min="1" max="200" value={phase6Draft.traceLimit} onChange={(e) => setPhase6Draft((p) => ({ ...p, traceLimit: e.target.value }))} placeholder="trace limit" />
                    <button className="btn-solid" style={{width: "auto", padding: "0.28rem 0.62rem"}} disabled={workbenchBusy || !token} onClick={() => runWorkbenchAction({ endpoint: "/observability/traces", method: "GET", call: () => ProfessorApi.phase6ObservabilityTraces(apiBase, token, Number(phase6Draft.traceLimit || 20)) })}>Traces</button>
                    <button className="btn-solid" style={{width: "auto", padding: "0.28rem 0.62rem"}} disabled={workbenchBusy || !token} onClick={() => runWorkbenchAction({ endpoint: "/background-jobs/history", method: "GET", call: () => ProfessorApi.phase6History(apiBase, token, Number(phase6Draft.historyLimit || 30)) })}>Job History</button>
                  </div>

                  <div style={{display: "grid", gap: "0.45rem", gridTemplateColumns: "1fr auto auto", marginTop: "0.55rem"}}>
                    <input type="number" min="1" max="200" value={phase6Draft.maxJobs} onChange={(e) => setPhase6Draft((p) => ({ ...p, maxJobs: e.target.value }))} placeholder="max jobs" />
                    <button className="btn-solid" style={{width: "auto", padding: "0.28rem 0.62rem"}} disabled={workbenchBusy || !token} onClick={() => runWorkbenchAction({ endpoint: "/background-jobs/drain", method: "POST", call: () => ProfessorApi.phase6DrainJobs(apiBase, token, Number(phase6Draft.maxJobs || 25)) })}>Drain Jobs</button>
                    <button className="btn-solid" style={{width: "auto", padding: "0.28rem 0.62rem"}} disabled={workbenchBusy || !token} onClick={() => runWorkbenchAction({ endpoint: "/background-jobs/replay-dead-letter", method: "POST", call: () => ProfessorApi.phase6ReplayDeadLetter(apiBase, token, Number(phase6Draft.maxJobs || 25)) })}>Replay Dead Letter</button>
                  </div>

                  <div style={{display: "grid", gap: "0.45rem", gridTemplateColumns: "2fr 1fr auto", marginTop: "0.55rem"}}>
                    <input value={phase6Draft.diagnosticsPrompt} onChange={(e) => setPhase6Draft((p) => ({ ...p, diagnosticsPrompt: e.target.value }))} placeholder="diagnostics prompt" />
                    <input type="number" min="1" max="12" value={phase6Draft.diagnosticsRuns} onChange={(e) => setPhase6Draft((p) => ({ ...p, diagnosticsRuns: e.target.value }))} placeholder="runs" />
                    <button className="btn-solid" style={{width: "auto", padding: "0.28rem 0.62rem"}} disabled={workbenchBusy || !token} onClick={() => runWorkbenchAction({ endpoint: "/diagnostics/nondeterminism/run", method: "POST", call: () => ProfessorApi.phase6DiagnosticsRun(apiBase, token, { prompt: phase6Draft.diagnosticsPrompt, runs: Number(phase6Draft.diagnosticsRuns || 3) }) })}>Run Diagnostics</button>
                  </div>

                  <div style={{display: "grid", gap: "0.45rem", gridTemplateColumns: "2fr 1fr auto", marginTop: "0.55rem"}}>
                    <input value={phase6Draft.routerPrompt} onChange={(e) => setPhase6Draft((p) => ({ ...p, routerPrompt: e.target.value }))} placeholder="router prompt" />
                    <input value={phase6Draft.routerRouteHint} onChange={(e) => setPhase6Draft((p) => ({ ...p, routerRouteHint: e.target.value }))} placeholder="route hint" />
                    <button className="btn-solid" style={{width: "auto", padding: "0.28rem 0.62rem"}} disabled={workbenchBusy || !token} onClick={() => runWorkbenchAction({ endpoint: "/llm-router/route", method: "POST", call: () => ProfessorApi.phase6RouteProbe(apiBase, token, { prompt: phase6Draft.routerPrompt, route_hint: phase6Draft.routerRouteHint }) })}>Route Probe</button>
                  </div>
                </div>

                {workbenchResult && (
                  <div style={{padding: "0.65rem", border: "1px solid var(--border-light)", borderRadius: "8px", background: "var(--bg-secondary)"}}>
                    <div style={{fontSize: "0.78rem", color: "var(--text-secondary)", marginBottom: "0.35rem"}}>
                      {workbenchResult.method} {workbenchResult.endpoint} | status {workbenchResult.status} | {workbenchResult.ok ? "ok" : "error"}
                    </div>
                    <pre style={{margin: 0, fontSize: "0.72rem", maxHeight: "240px", overflow: "auto"}}>
                      {JSON.stringify(workbenchResult.data, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        <section className={`workspace-stage workspace-${active}`}>
          {/* STUDENT DASHBOARD */}
          {active === "student" && role !== "professor" && (
            <StudentDashboard 
              apiBase={apiBase} 
              token={token} 
              chatCourse={chatCourse} 
              chatSession={chatSession} 
              lowPowerMode={lowPowerMode}
              devMode={devMode} 
              pushActivity={pushActivity}
              onAuthExpired={() => {
                saveToken("");
                setAuthError("Session expired. Please sign in again.");
                setAuthView("login");
              }}
            />
          )}

          {/* PROFESSOR DASHBOARD */}
          {active === "professor" && (
            <ProfessorDashboard 
              apiBase={apiBase} 
              token={token} 
              profCourse={profCourse} 
              lowPowerMode={lowPowerMode}
              devMode={devMode} 
              pushActivity={pushActivity}
              onAuthExpired={() => {
                saveToken("");
                setAuthError("Session expired. Please sign in again.");
                setAuthView("login");
              }}
            />
          )}
        </section>
      </main>
    </div>
  );
}
