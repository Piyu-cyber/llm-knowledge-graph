import { useEffect, useMemo, useState } from "react";
import { ProfessorApi } from "./endpoints";
import ClassIntelligenceFeed from "./components/ClassIntelligenceFeed";
import AITeachingCard from "./components/AITeachingCard";
import HITLQueue from "./components/HITLQueue";
import CourseHealthPanel from "./components/CourseHealthPanel";

const TABS = ["Dashboard", "Stream", "Classwork", "People", "Learn / Graph"];

export default function ProfessorDashboard({ apiBase, token, profCourse }) {
  const [activeTab, setActiveTab] = useState("Dashboard");
  const [announcements, setAnnouncements] = useState([]);
  const [coursework, setCoursework] = useState([]);
  const [students, setStudents] = useState([]);
  const [uploadId, setUploadId] = useState("");
  const [queue, setQueue] = useState([]);

  useEffect(() => {
    if (!token) return;
    Promise.all([
      ProfessorApi.announcements(apiBase, token, profCourse, { forceRefresh: true }),
      ProfessorApi.coursework(apiBase, token, profCourse, { forceRefresh: true }),
      ProfessorApi.students(apiBase, token, { forceRefresh: true }),
      ProfessorApi.hitlQueue(apiBase, token, { forceRefresh: true }),
    ]).then(([annRes, courseRes, studentsRes, queueRes]) => {
      if (annRes.ok) setAnnouncements(annRes.data?.items || []);
      if (courseRes.ok) setCoursework(courseRes.data?.items || []);
      if (studentsRes.ok) setStudents(studentsRes.data?.students || []);
      if (queueRes.ok) setQueue(queueRes.data?.items || []);
    });
  }, [apiBase, token, profCourse]);

  const integrityFlags = useMemo(() => queue.filter((item) => Number(item.style_deviation_index ?? item.sdi ?? 0) > 0.85).length, [queue]);

  const uploadLecture = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const res = await ProfessorApi.ingest(apiBase, token, file, profCourse);
    if (res.ok) setUploadId(res.data?.upload_id || "");
  };

  return (
    <div className="phase7-shell">
      <aside className="phase7-sidebar">
        <div className="phase7-brand">OmniProf</div>
        <nav className="phase7-nav">
          {TABS.map((tab) => (
            <button key={tab} className={activeTab === tab ? "active" : ""} onClick={() => setActiveTab(tab)}>{tab}</button>
          ))}
        </nav>
        <div className="phase7-user-footer">
          <div className="avatar-pill">P</div>
          <div>
            <div>Professor</div>
            <div className="phase7-muted">professor</div>
          </div>
        </div>
      </aside>

      <section className="phase7-content">
        <header className="phase7-topbar">
          <div>
            <h2>{(profCourse || "course").toUpperCase()}</h2>
            <div className="phase7-muted">{students.length} enrolled</div>
          </div>
          <div className="phase7-badges">
            <span className="phase7-badge">Integrity flags: {integrityFlags}</span>
            <span className="phase7-badge">Pending grades: {queue.length}</span>
            <span className="phase7-badge">AI insights: active</span>
          </div>
        </header>

        {activeTab === "Dashboard" && (
          <div className="prof-grid">
            <div className="prof-main">
              <ClassIntelligenceFeed apiBase={apiBase} token={token} courseId={profCourse} />
              <AITeachingCard apiBase={apiBase} token={token} uploadId={uploadId} />
              <HITLQueue apiBase={apiBase} token={token} />
            </div>
            <div className="prof-side">
              <CourseHealthPanel apiBase={apiBase} token={token} courseId={profCourse} />
              <div className="phase7-panel">
                <h3>Quick Actions</h3>
                <label className="quick-upload">
                  <input type="file" onChange={uploadLecture} />
                  <span>Upload new lecture material</span>
                </label>
              </div>
            </div>
          </div>
        )}

        {activeTab === "Stream" && (
          <div className="phase7-panel">
            <h3>Stream</h3>
            {announcements.map((item, index) => <div key={index} className="feed-row">{item.title || item.body || "Announcement"}</div>)}
            {!announcements.length && <p className="phase7-muted">No announcements posted.</p>}
          </div>
        )}

        {activeTab === "Classwork" && (
          <div className="phase7-panel">
            <h3>Classwork</h3>
            {coursework.map((item) => (
              <div key={item.id} className="feed-row">
                <strong>{item.title}</strong>
                <div className="phase7-muted">{item.due_date || "n/a"}</div>
              </div>
            ))}
            {!coursework.length && <p className="phase7-muted">No assignments created.</p>}
          </div>
        )}

        {activeTab === "People" && (
          <div className="phase7-panel">
            <h3>People</h3>
            {students.map((student, index) => (
              <div key={student.user_id || index} className="feed-row">{student.full_name || student.username || student.user_id}</div>
            ))}
            {!students.length && <p className="phase7-muted">No students found.</p>}
          </div>
        )}

        {activeTab === "Learn / Graph" && (
          <div className="phase7-panel">
            <h3>Learn / Graph</h3>
            <p className="phase7-muted">Use the existing professor graph tools from the backend while the new dashboard surfaces class intelligence and teaching support.</p>
          </div>
        )}
      </section>
    </div>
  );
}
