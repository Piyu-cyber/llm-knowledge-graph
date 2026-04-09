import { useMemo, useState, useRef, useEffect } from "react";
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
  const [apiBase, setApiBase] = useState(localStorage.getItem("omniprof_api_base") || "http://127.0.0.1:8000");
  const [token, setToken] = useState(localStorage.getItem("omniprof_token") || "");
  const [active, setActive] = useState("student");
  const [activity, setActivity] = useState([]);
  const [busy, setBusy] = useState(false);

  // Chat State
  const [chatMessage, setChatMessage] = useState("");
  const [chatSession, setChatSession] = useState("sess_app_1"); // Hidden by default
  const [chatCourse, setChatCourse] = useState("cs101"); // Hidden by default
  const [chatHistory, setChatHistory] = useState([
    { role: "assistant", content: "Hi! I'm your OmniProf TA. How can I help you with your coursework today?" }
  ]);

  // Student State
  const [studentProgress, setStudentProgress] = useState(null);
  const [studentAchievements, setStudentAchievements] = useState([]);
  const [submissionFile, setSubmissionFile] = useState(null);
  const [submissionStatus, setSubmissionStatus] = useState(null);

  // Professor State
  const [profCourse, setProfCourse] = useState("cs101");
  const [cohortOverview, setCohortOverview] = useState(null);
  const [hitlQueue, setHitlQueue] = useState([]);

  const tokenPayload = useMemo(() => (token ? parseJwt(token) : null), [token]);
  const role = roleFromJwt(tokenPayload);
  const chatEndRef = useRef(null);

  useEffect(() => {
    if (chatEndRef.current) {
      chatEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [chatHistory]);

  const saveBase = (val) => { setApiBase(val); localStorage.setItem("omniprof_api_base", val); };
  const saveToken = (val) => { setToken(val); localStorage.setItem("omniprof_token", val); };

  const pushActivity = (entry) => {
    setActivity(prev => [{ ts: new Date().toISOString(), ...entry }, ...prev].slice(0, 50));
  };

  const quickLogin = async (username, password) => {
    setBusy(true);
    try {
      const res = await AuthApi.login(apiBase, username, password);
      if (res.data?.access_token) saveToken(res.data.access_token);
      pushActivity({ endpoint: "/auth/login", status: res.status, ok: res.ok, method: "POST" });
    } catch {
      pushActivity({ endpoint: "/auth/login", status: 0, ok: false, method: "POST" });
    } finally {
      setBusy(false);
    }
  };

  const runStudentChat = async () => {
    if (!chatMessage.trim()) return;
    const msgToSend = chatMessage;
    setChatMessage("");
    setChatHistory(prev => [...prev, { role: "student", content: msgToSend }]);
    setBusy(true);
    try {
      const data = await StudentApi.chat(apiBase, token, {
        message: msgToSend,
        session_id: chatSession,
        course_id: chatCourse,
      });
      setChatHistory(prev => [...prev, { role: "assistant", content: data.data?.response || "Error getting response." }]);
      pushActivity({ endpoint: "/chat", status: data.status, ok: data.ok, method: "POST" });
      // auto-refresh progress
      loadStudentData();
    } finally {
      setBusy(false);
    }
  };

  const loadStudentData = async () => {
    if (!token) return;
    try {
      const [progressRes, achievementsRes] = await Promise.all([
        StudentApi.progress(apiBase, token, chatCourse),
        StudentApi.achievements(apiBase, token),
      ]);
      if (progressRes.ok) setStudentProgress(progressRes.data);
      if (achievementsRes.ok) setStudentAchievements(achievementsRes.data?.achievements || []);
    } catch {
      // silent fail for standard users
    }
  };

  const submitAssignment = async () => {
    if (!submissionFile) return;
    setBusy(true);
    try {
      const res = await StudentApi.submitAssignment(apiBase, token, submissionFile, chatCourse);
      if (res.ok) {
        setSubmissionStatus({ status: "Submitted successfully!", id: res.data?.submission_id });
        setSubmissionFile(null);
      } else {
        setSubmissionStatus({ status: "Failed to submit." });
      }
      pushActivity({ endpoint: "/student/submit-assignment", status: res.status, ok: res.ok, method: "POST" });
    } finally {
      setBusy(false);
    }
  };

  const loadProfessorData = async () => {
    setBusy(true);
    try {
      const [overviewRes, queueRes] = await Promise.all([
        ProfessorApi.cohortOverview(apiBase, token, profCourse, 7),
        ProfessorApi.hitlQueue(apiBase, token),
      ]);
      if(overviewRes.ok) setCohortOverview(overviewRes.data);
      if(queueRes.ok) setHitlQueue(queueRes.data?.items || []);
    } finally {
      setBusy(false);
    }
  };

  // --- DERIVED DATA ---
  const mastery = studentProgress?.mastery || [];
  const low = mastery.filter(m => m.confidence_band === "low").length;
  const medium = mastery.filter(m => m.confidence_band === "medium").length;
  const high = mastery.filter(m => m.confidence_band === "high").length;
  const totalConcepts = Math.max(1, mastery.length) || 1;

  return (
    <div className="app-container">
      {/* SIDEBAR */}
      <aside className="sidebar">
        <div className="brand">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 10v6M2 10l10-5 10 5-10 5z"/><path d="M6 12v5c3 3 9 3 12 0v-5"/></svg>
          OmniProf
        </div>

        <nav className="nav-menu">
          {(role === "student" || role === "Guest" || role === "admin") && (
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
          {!token ? (
            <>
              <button className="auth-button primary" onClick={() => quickLogin("student_demo", "Student@123")} disabled={busy}>Sign in to Student</button>
              <button className="auth-button" onClick={() => quickLogin("professor_demo", "Professor@123")} disabled={busy}>Sign in to Professor</button>
            </>
          ) : (
            <button className="auth-button" onClick={() => saveToken("")}>Sign Out</button>
          )}

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

        {/* STUDENT DASHBOARD */}
        {active === "student" && role !== "professor" && (
          <StudentDashboard 
            apiBase={apiBase} 
            token={token} 
            chatCourse={chatCourse} 
            chatSession={chatSession} 
            devMode={devMode} 
            pushActivity={pushActivity} 
          />
        )}

        {/* PROFESSOR DASHBOARD */}
        {active === "professor" && (
          <ProfessorDashboard 
            apiBase={apiBase} 
            token={token} 
            profCourse={profCourse} 
            devMode={devMode} 
            pushActivity={pushActivity} 
          />
        )}
      </main>
    </div>
  );
}
