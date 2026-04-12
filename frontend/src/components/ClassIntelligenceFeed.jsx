import { useEffect, useState } from "react";
import { ProfessorApi } from "../endpoints";

export default function ClassIntelligenceFeed({ apiBase, token, courseId }) {
  const [alerts, setAlerts] = useState([]);
  const [quizPreview, setQuizPreview] = useState([]);

  useEffect(() => {
    let active = true;
    const load = () => {
      ProfessorApi.cohortAlerts(apiBase, token, courseId, { forceRefresh: true }).then((res) => {
        if (active && res.ok) setAlerts(Array.isArray(res.data) ? res.data : []);
      });
    };
    load();
    const id = setInterval(load, 300000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [apiBase, token, courseId]);

  const generateQuiz = async (conceptId) => {
    const res = await ProfessorApi.generateQuiz(apiBase, token, {
      concept_ids: [conceptId],
      difficulty: "easy",
      count: 5,
      course_id: courseId,
    });
    if (res.ok) setQuizPreview(Array.isArray(res.data) ? res.data : []);
  };

  return (
    <div className="phase7-panel">
      <h3>Class Intelligence</h3>
      {alerts.map((alert) => (
        <div key={alert.concept_id} className="alert-card">
          <div>
            <strong>{alert.concept_name}</strong>
            <div className="phase7-muted">{Math.round((alert.struggling_pct || 0) * 100)}% of class struggling</div>
          </div>
          {alert.urgent && <span className="alert-badge">Urgent</span>}
          <div className="alert-actions">
            <button onClick={() => generateQuiz(alert.concept_id)}>Generate re-teach plan</button>
          </div>
        </div>
      ))}
      {!alerts.length && <p className="phase7-muted">No cohort alerts right now.</p>}
      {!!quizPreview.length && <div className="phase7-footnote">Latest quiz preview: {quizPreview[0]?.question}</div>}
    </div>
  );
}
