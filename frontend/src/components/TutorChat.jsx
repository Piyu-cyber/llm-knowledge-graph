import { useEffect, useMemo, useRef, useState } from "react";
import { StudentApi } from "../endpoints";

function Bubble({ message, onHint, hintState, canHint }) {
  return (
    <div className={`tutor-bubble-row ${message.role}`}>
      <div className="tutor-bubble">
        <div>{message.content}</div>
        {message.role === "assistant" && canHint && (
          <div className="hint-actions">
            <button onClick={() => onHint("think")}>Hint: think about concept</button>
            <button onClick={() => onHint("related")}>Show a related concept</button>
          </div>
        )}
        {hintState && <div className="inline-hint">{hintState}</div>}
      </div>
    </div>
  );
}

export default function TutorChat({ apiBase, token, courseId, sessionId }) {
  const [messages, setMessages] = useState([{ role: "assistant", content: "How can I help you with this course today?" }]);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [hintState, setHintState] = useState("");
  const [recentNotes, setRecentNotes] = useState([]);
  const [activeQuestion, setActiveQuestion] = useState("");
  const socketRef = useRef(null);
  const lastStudentMessage = useMemo(() => [...messages].reverse().find((item) => item.role === "student")?.content || "", [messages]);

  useEffect(() => {
    return () => {
      if (socketRef.current) socketRef.current.close();
    };
  }, []);

  const loadNotes = () => {
    StudentApi.notes(apiBase, token, courseId, 1, { forceRefresh: true }).then((res) => {
      if (res.ok) setRecentNotes(Array.isArray(res.data) ? res.data : []);
    });
  };

  const send = () => {
    const text = draft.trim();
    if (!text || pending) return;
    setPending(true);
    setDraft("");
    setHintState("");
    setMessages((prev) => [...prev, { role: "student", content: text }]);
    setActiveQuestion(text);
    const ws = new WebSocket(`${apiBase.replace("http", "ws")}/ws/chat?token=${encodeURIComponent(token)}&session_id=${encodeURIComponent(sessionId)}&course_id=${encodeURIComponent(courseId)}`);
    socketRef.current = ws;
    let assistantText = "";
    ws.onopen = () => ws.send(JSON.stringify({ message: text }));
    ws.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      if (payload.event === "token") {
        assistantText += payload.token || "";
      }
      if (payload.event === "complete") {
        setMessages((prev) => [...prev, { role: "assistant", content: payload.response || assistantText || "" }]);
        setPending(false);
        ws.close();
        loadNotes();
      }
      if (payload.event === "error") {
        const errorText = String(payload.message || "Chat failed.");
        const lowerError = errorText.toLowerCase();
        if (lowerError.includes("invalid token") || lowerError.includes("signature verification failed") || lowerError.includes("expired")) {
          window.dispatchEvent(
            new CustomEvent("omniprof-auth-invalid", {
              detail: { reason: errorText },
            }),
          );
        }
        setMessages((prev) => [...prev, { role: "assistant", content: payload.message || "Chat failed." }]);
        setPending(false);
      }
    };
    ws.onerror = () => {
      setMessages((prev) => [...prev, { role: "assistant", content: "Unable to connect to tutor chat." }]);
      setPending(false);
    };
  };

  const requestHint = async () => {
    setHintState("Requesting hint...");
    const response = await StudentApi.hint(apiBase, token, {
      question_text: activeQuestion || "Current coursework question",
      draft_answer: lastStudentMessage,
      concept_ids: [],
      course_id: courseId,
    });
    setHintState(response.ok ? response.data?.hint || "No hint available." : response.data?.detail || "Hint request failed.");
  };

  return (
    <div className="phase7-panel tutor-chat-panel">
      <h3>AI Tutor</h3>
      <div className="tutor-thread">
        {messages.map((message, index) => (
          <Bubble key={`${message.role}_${index}`} message={message} onHint={requestHint} hintState={index === messages.length - 1 ? hintState : ""} canHint={message.role === "assistant" && Boolean(activeQuestion)} />
        ))}
      </div>
      <div className="phase7-muted">{draft.length} characters</div>
      <div className="tutor-input-row">
        <textarea value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Ask the tutor something..." />
        <button onClick={send} disabled={pending}>{pending ? "Sending..." : "Send"}</button>
      </div>
      {recentNotes[0] && (
        <details className="notes-panel">
          <summary>Session notes</summary>
          <div className="phase7-muted">Concepts: {(recentNotes[0].concepts_covered || []).join(", ") || "None"}</div>
          <div className="phase7-muted">Connections: {(recentNotes[0].connections || []).join(" | ") || "None"}</div>
        </details>
      )}
    </div>
  );
}
