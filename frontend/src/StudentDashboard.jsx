import { useEffect, useMemo, useState } from "react";
import { StudentApi } from "./endpoints";
import TutorChat from "./components/TutorChat";
import StudyPlan from "./components/StudyPlan";
import MasteryPanel from "./components/MasteryPanel";

const TABS = ["Learn", "Stream", "Classwork", "People"];

export default function StudentDashboard({ apiBase, token, chatCourse, chatSession }) {
  const [activeTab, setActiveTab] = useState("Learn");
  const [progress, setProgress] = useState(null);
  const [feed, setFeed] = useState(null);

  useEffect(() => {
    if (!token) return;
    Promise.all([
      StudentApi.progress(apiBase, token, chatCourse, { forceRefresh: true }),
      StudentApi.classroomFeed(apiBase, token, chatCourse, { forceRefresh: true }),
    ]).then(([progressRes, feedRes]) => {
      if (progressRes.ok) setProgress(progressRes.data);
      if (feedRes.ok) setFeed(feedRes.data);
    });
  }, [apiBase, token, chatCourse]);

  const lowMasteryCount = useMemo(
    () => (progress?.mastery || []).filter((item) => (item.mastery_probability || 0) < 0.5).length,
    [progress],
  );
  const nearestDue = useMemo(() => (feed?.coursework || []).slice().sort((a, b) => String(a.due_date || "").localeCompare(String(b.due_date || "")))[0], [feed]);

  return (
    <div className="phase7-shell">
      <aside className="phase7-sidebar">
        <div className="phase7-brand">OmniProf</div>
        <nav className="phase7-nav">
          {TABS.map((tab) => (
            <button key={tab} className={activeTab === tab ? "active" : ""} onClick={() => setActiveTab(tab)}>{tab}</button>
          ))}
        </nav>
        <div className="phase7-sidebar-section">
          <div className="phase7-section-label">My courses</div>
          <div>{(chatCourse || "course").toUpperCase()}</div>
        </div>
        <div className="phase7-user-footer">
          <div className="avatar-pill">S</div>
          <div>
            <div>Student</div>
            <div className="phase7-muted">student</div>
          </div>
        </div>
      </aside>

      <section className="phase7-content">
        <header className="phase7-topbar">
          <div>
            <h2>{(chatCourse || "course").toUpperCase()}</h2>
            <div className="phase7-muted">Current topic: adaptive learning</div>
          </div>
          <div className="phase7-badges">
            <span className="phase7-badge">Due: {nearestDue?.due_date || "n/a"}</span>
            <span className="phase7-badge">{lowMasteryCount} concepts below 50%</span>
          </div>
        </header>

        {activeTab === "Learn" && (
          <div className="learn-grid">
            <div className="learn-main">
              <TutorChat apiBase={apiBase} token={token} courseId={chatCourse} sessionId={chatSession} />
            </div>
            <div className="learn-side">
              <StudyPlan apiBase={apiBase} token={token} courseId={chatCourse} />
              <MasteryPanel apiBase={apiBase} token={token} courseId={chatCourse} />
              <div className="phase7-panel">
                <h3>Next Up</h3>
                {(feed?.coursework || []).slice(0, 3).map((item) => (
                  <div key={item.id} className="next-up-card">
                    <strong>{item.title}</strong>
                    <div className="phase7-muted">{item.due_date || "No due date"}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {activeTab === "Stream" && (
          <div className="phase7-panel">
            <h3>Stream</h3>
            {(feed?.announcements || []).map((item, index) => <div key={index} className="feed-row">{item.title || item.body || "Announcement"}</div>)}
            {!(feed?.announcements || []).length && <p className="phase7-muted">No stream items available.</p>}
          </div>
        )}

        {activeTab === "Classwork" && (
          <div className="phase7-panel">
            <h3>Classwork</h3>
            {(feed?.coursework || []).map((item) => (
              <div key={item.id} className="feed-row">
                <strong>{item.title}</strong>
                <div className="phase7-muted">{item.student_status || "open"} | {item.due_date || "n/a"}</div>
              </div>
            ))}
            {!(feed?.coursework || []).length && <p className="phase7-muted">No classwork posted yet.</p>}
          </div>
        )}

        {activeTab === "People" && (
          <div className="phase7-panel">
            <h3>People</h3>
            <div className="feed-row">
              <strong>Professor</strong>
              <div className="phase7-muted">Demo Professor</div>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
