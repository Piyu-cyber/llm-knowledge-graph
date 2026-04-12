import { useEffect, useState } from "react";
import { StudentApi } from "../endpoints";

export default function StudyPlan({ apiBase, token, courseId }) {
  const [state, setState] = useState({ loading: true, data: null, error: "" });

  useEffect(() => {
    let active = true;
    setState({ loading: true, data: null, error: "" });
    StudentApi.studyPlan(apiBase, token, courseId, { forceRefresh: true }).then((res) => {
      if (!active) return;
      setState({ loading: false, data: res.data, error: res.ok ? "" : res.data?.detail || "Failed to load study plan." });
    }).catch(() => {
      if (active) setState({ loading: false, data: null, error: "Failed to load study plan." });
    });
    return () => {
      active = false;
    };
  }, [apiBase, token, courseId]);

  if (state.loading) {
    return <div className="phase7-panel"><div className="phase7-skeleton" /><div className="phase7-skeleton" /><div className="phase7-skeleton" /></div>;
  }

  if (state.error) {
    return <div className="phase7-panel"><p className="phase7-muted">{state.error}</p></div>;
  }

  if (state.data?.error === "reduced_mode") {
    return <div className="phase7-panel"><p className="phase7-muted">Study plan unavailable — AI is in reduced mode.</p></div>;
  }

  return (
    <div className="phase7-panel">
      <h3>Study Plan</h3>
      {(state.data?.blocks || []).map((block, index) => (
        <div key={`${block.title}_${index}`} className="study-plan-row">
          <span className={`study-priority ${block.priority || "medium"}`} />
          <div>
            <div className="study-plan-title">{block.title}</div>
            <div className="phase7-muted">{block.duration_minutes} min</div>
          </div>
        </div>
      ))}
      {!(state.data?.blocks || []).length && <p className="phase7-muted">No study blocks available today.</p>}
      <div className="phase7-footnote">AI-generated from your mastery gaps + deadline</div>
    </div>
  );
}
