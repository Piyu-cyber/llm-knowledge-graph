import { useEffect, useState } from "react";
import { ProfessorApi } from "../endpoints";

export default function AITeachingCard({ apiBase, token, uploadId }) {
  const [plan, setPlan] = useState(null);

  useEffect(() => {
    if (!uploadId) return;
    let active = true;
    const load = () => {
      ProfessorApi.lessonPlan(apiBase, token, uploadId, { forceRefresh: true }).then((res) => {
        if (active && res.ok) setPlan(res.data);
      });
    };
    load();
    const id = setInterval(load, 5000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [apiBase, token, uploadId]);

  return (
    <div className="phase7-panel">
      <h3>AI Teaching Assistant</h3>
      {!uploadId && <p className="phase7-muted">Upload lecture material to generate a lesson plan.</p>}
      {plan && (
        <>
          <div className="phase7-muted">Segments: {(plan.lesson_plan || []).length}</div>
          <div className="phase7-muted">Quiz suggestions: {(plan.quiz_suggestions || []).length}</div>
          <div className="phase7-muted">Conflicts: {(plan.conflicts || []).length}</div>
        </>
      )}
      <div className="placeholder-card">Assignment N — suggested rubric ready</div>
    </div>
  );
}
