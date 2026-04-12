import { useEffect, useMemo, useState } from "react";
import { StudentApi } from "../endpoints";

export default function MasteryPanel({ apiBase, token, courseId }) {
  const [progress, setProgress] = useState(null);

  useEffect(() => {
    let active = true;
    StudentApi.progress(apiBase, token, courseId, { forceRefresh: true }).then((res) => {
      if (active && res.ok) setProgress(res.data);
    });
    return () => {
      active = false;
    };
  }, [apiBase, token, courseId]);

  const mastery = useMemo(() => {
    const rows = progress?.mastery || [];
    return [...rows].sort((a, b) => (a.mastery_probability ?? 0) - (b.mastery_probability ?? 0));
  }, [progress]);

  return (
    <div className="phase7-panel">
      <h3>Concept Mastery</h3>
      {mastery.map((item) => {
        const theta = Math.round((item.mastery_probability || 0) * 100);
        const tone = theta >= 75 ? "green" : theta >= 40 ? "amber" : "red";
        return (
          <div key={item.concept_id} className="mastery-row">
            <div className="mastery-labels">
              <span>{item.concept_name}</span>
              <span>{theta}%</span>
            </div>
            <div className="mastery-bar-shell">
              <div className={`mastery-bar ${tone}`} style={{ width: `${theta}%` }} />
            </div>
          </div>
        );
      })}
      {!mastery.length && <p className="phase7-muted">No mastery data yet.</p>}
      <div className="phase7-footnote">{progress?.notes_count ?? 0} session notes saved</div>
    </div>
  );
}
