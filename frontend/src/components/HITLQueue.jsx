import { useEffect, useState } from "react";
import { ProfessorApi } from "../endpoints";

export default function HITLQueue({ apiBase, token, onAction }) {
  const [items, setItems] = useState([]);

  const load = () => {
    ProfessorApi.hitlQueue(apiBase, token, { forceRefresh: true }).then((res) => {
      if (res.ok) setItems(res.data?.items || []);
    });
  };

  useEffect(() => {
    load();
  }, [apiBase, token]);

  const act = async (queueId, action) => {
    await ProfessorApi.hitlAction(apiBase, token, queueId, { action });
    load();
    if (onAction) onAction();
  };

  return (
    <div className="phase7-panel">
      <h3>HITL Queue</h3>
      {items.map((item) => {
        const integrity = Number(item.style_deviation_index ?? item.sdi ?? 0);
        const confidence = Number(item.evaluator_confidence ?? 0);
        return (
          <div key={item.queue_id} className="queue-card">
            <div className="queue-title">{item.student_id || "Student"} • {item.submission_id || item.defence_record_id}</div>
            <div className="phase7-muted">Evaluator confidence: {Math.round(confidence * 100)}%</div>
            <div className="mastery-bar-shell"><div className={`mastery-bar ${integrity > 0.85 ? "red" : integrity >= 0.4 ? "amber" : "green"}`} style={{ width: `${Math.min(100, integrity <= 1 ? integrity * 100 : integrity)}%` }} /></div>
            {integrity > 0.85 && <div className="flag-text">flagged</div>}
            <div className="alert-actions">
              <button onClick={() => act(item.queue_id, integrity > 0.85 ? "approve" : "approve")}>{integrity > 0.85 ? "Investigate" : "Approve"}</button>
              <button onClick={() => act(item.queue_id, "request_redefence")}>Request re-defence</button>
            </div>
          </div>
        );
      })}
      {!items.length && <p className="phase7-muted">No queue items pending.</p>}
    </div>
  );
}
