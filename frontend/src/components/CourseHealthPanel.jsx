import { useEffect, useMemo, useState } from "react";
import { ProfessorApi } from "../endpoints";

export default function CourseHealthPanel({ apiBase, token, courseId }) {
  const [students, setStudents] = useState([]);
  const [overview, setOverview] = useState(null);
  const [queue, setQueue] = useState([]);
  const [alerts, setAlerts] = useState([]);

  useEffect(() => {
    Promise.all([
      ProfessorApi.students(apiBase, token, { forceRefresh: true }),
      ProfessorApi.cohortOverview(apiBase, token, courseId, 7, { forceRefresh: true }),
      ProfessorApi.hitlQueue(apiBase, token, { forceRefresh: true }),
      ProfessorApi.cohortAlerts(apiBase, token, courseId, { forceRefresh: true }),
    ]).then(([studentsRes, overviewRes, queueRes, alertsRes]) => {
      if (studentsRes.ok) setStudents(studentsRes.data?.students || []);
      if (overviewRes.ok) setOverview(overviewRes.data);
      if (queueRes.ok) setQueue(queueRes.data?.items || []);
      if (alertsRes.ok) setAlerts(Array.isArray(alertsRes.data) ? alertsRes.data : []);
    });
  }, [apiBase, token, courseId]);

  const integrityFlags = useMemo(() => queue.filter((item) => Number(item.style_deviation_index ?? item.sdi ?? 0) > 0.85).length, [queue]);

  return (
    <div className="phase7-panel">
      <h3>Course Health</h3>
      <div className="metrics-grid">
        <div className="metric-card"><strong>{students.length}</strong><span>Enrolled students</span></div>
        <div className="metric-card"><strong>{Math.round((overview?.avg_mastery || 0) * 100)}%</strong><span>Average mastery</span></div>
        <div className="metric-card"><strong>{queue.length}</strong><span>Pending grades</span></div>
        <div className={`metric-card ${integrityFlags ? "metric-danger" : ""}`}><strong>{integrityFlags}</strong><span>Integrity flags</span></div>
      </div>
      <div className="phase7-footnote">Weak concepts: {(alerts || []).slice(0, 3).map((row) => row.concept_name).join(", ") || "None"}</div>
    </div>
  );
}
