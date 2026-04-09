import { useMemo, useState } from "react";
import { AuthApi } from "./endpoints";
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
