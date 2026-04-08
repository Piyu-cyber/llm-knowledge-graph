import { useState, useRef, useEffect } from "react";
import { StudentApi } from "./endpoints";

export default function StudentDashboard({ apiBase, token, chatCourse, chatSession, devMode, pushActivity }) {
  const [chatMessage, setChatMessage] = useState("");
  const [chatHistory, setChatHistory] = useState([
    { role: "assistant", content: "Hi! I'm your OmniProf TA. How can I help you with your coursework today?" }
  ]);
  const [studentProgress, setStudentProgress] = useState(null);
  const [studentAchievements, setStudentAchievements] = useState([]);
  const [submissionFile, setSubmissionFile] = useState(null);
  const [submissionStatus, setSubmissionStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [imagePayload, setImagePayload] = useState(null); // base64 payload

  const chatEndRef = useRef(null);

  useEffect(() => {
    if (chatEndRef.current) {
      chatEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [chatHistory]);

  const runStudentChat = async () => {
    if (!chatMessage.trim() && !imagePayload) return;
    const msgToSend = chatMessage;
    setChatMessage("");
    
    // Add user message to UI
    let contentToDisplay = msgToSend;
    if (imagePayload) contentToDisplay += " [Image Attached]";
    setChatHistory(prev => [...prev, { role: "student", content: contentToDisplay }]);
    
    setBusy(true);
    try {
      const data = await StudentApi.chat(apiBase, token, {
        message: msgToSend,
        session_id: chatSession,
        course_id: chatCourse,
        image_base64: imagePayload // Pass image to backend if supported
      });
      setChatHistory(prev => [...prev, { role: "assistant", content: data.data?.response || "Error getting response." }]);
      pushActivity({ endpoint: "/chat", status: data.status, ok: data.ok, method: "POST" });
      setImagePayload(null);
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
        setSubmissionStatus({ status: "Submitted successfully!", id: res.data?.submission_id, state: "pending" });
        setSubmissionFile(null);
      } else {
        setSubmissionStatus({ status: "Failed to submit." });
      }
      pushActivity({ endpoint: "/student/submit-assignment", status: res.status, ok: res.ok, method: "POST" });
    } finally {
      setBusy(false);
    }
  };

  const loadSubmissionDetails = async (id) => {
    if(!id) return;
    setBusy(true);
    try {
        const res = await StudentApi.submissionStatus(apiBase, token, id);
        if(res.ok) {
            setSubmissionStatus({
                status: "Status Pulled", id: res.data.submission_id,
                workflow: res.data.workflow_status,
                pending_approval: res.data.pending_professor_approval,
                grade: res.data.final_grade,
                transcript_count: res.data.transcript ? res.data.transcript.length : 0
            });
        }
    } finally {
        setBusy(false);
    }
  };


  const mastery = studentProgress?.mastery || [];
  const low = mastery.filter(m => m.confidence_band === "low").length;
  const medium = mastery.filter(m => m.confidence_band === "medium").length;
  const high = mastery.filter(m => m.confidence_band === "high").length;
  const totalConcepts = Math.max(1, mastery.length) || 1;
  const trajectory = studentProgress?.recommended_trajectory || [];

  return (
    <div className="dashboard-grid">
      {/* Left: Chat */}
      <div className="chat-section">
        <div className="chat-history">
          {chatHistory.map((m, i) => (
            <div key={i} className={`message-row ${m.role}`}>
              <div className="message-bubble">{m.content}</div>
            </div>
          ))}
          <div ref={chatEndRef} />
        </div>
        
        <div className="chat-input-container">
          <div className="chat-input-wrapper">
            <textarea 
              value={chatMessage} 
              onChange={(e) => setChatMessage(e.target.value)} 
              placeholder="Ask a question about your course..."
              disabled={busy || !token}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  runStudentChat();
                }
              }}
            />
            {imagePayload && (
                <div style={{position: 'absolute', bottom: '1rem', left: '1rem', backgroundColor: 'var(--surface-sunken)', padding: '0.2rem 0.5rem', borderRadius: '4px', fontSize: '0.75rem', color: 'var(--accent)'}}>
                    Image Selected
                    <button style={{background:'none', border:'none', color:'inherit', marginLeft:'0.5rem', cursor:'pointer'}} onClick={() => setImagePayload(null)}>X</button>
                </div>
            )}
            <div style={{display: 'flex', alignItems: 'center'}}>
              <label className="image-upload-btn" style={{marginRight: '0.5rem', cursor: 'pointer', color: 'var(--text-secondary)'}}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>
                <input type="file" accept="image/*" style={{display: 'none'}} onChange={(e) => {
                    const file = e.target.files?.[0];
                    if(file) {
                        const reader = new FileReader();
                        reader.onloadend = () => setImagePayload(reader.result);
                        reader.readAsDataURL(file);
                    }
                }} disabled={busy || !token}/>
              </label>
              <button className="send-button" onClick={runStudentChat} disabled={busy || (!chatMessage.trim() && !imagePayload) || !token}>
                <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
              </button>
            </div>
          </div>
          {!token && <p style={{fontSize: '0.75rem', color: '#8e8ea0', textAlign: 'center', marginTop: '0.5rem'}}>Please sign in from the sidebar to chat.</p>}
        </div>
      </div>

      {/* Right: Widgets */}
      <div className="widgets-column">
        <div className="widget">
          <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem'}}>
            <h3 style={{margin: 0}}>Progress</h3>
            <button onClick={loadStudentData} disabled={!token} style={{fontSize: '0.8rem', color: 'var(--accent)', background: 'none', border: 'none', cursor: 'pointer'}}>Sync</button>
          </div>
          
          {token ? (
            <>
              <div className="progress-list">
                <div className="progress-item">
                  <span className="progress-label">Strong</span>
                  <div className="progress-track"><div className="progress-fill high" style={{width: `${(high/totalConcepts)*100}%`}}></div></div>
                  <span className="progress-value">{high}</span>
                </div>
                <div className="progress-item">
                  <span className="progress-label">Neutral</span>
                  <div className="progress-track"><div className="progress-fill medium" style={{width: `${(medium/totalConcepts)*100}%`}}></div></div>
                  <span className="progress-value">{medium}</span>
                </div>
                <div className="progress-item">
                  <span className="progress-label">Weak</span>
                  <div className="progress-track"><div className="progress-fill low" style={{width: `${(low/totalConcepts)*100}%`}}></div></div>
                  <span className="progress-value">{low}</span>
                </div>
              </div>
              
              {trajectory.length > 0 && (
                  <div style={{marginTop: '1.5rem'}}>
                    <h4 style={{fontSize: '0.85rem', textTransform: 'uppercase', color: 'var(--text-tertiary)', marginBottom: '0.5rem'}}>Recommended Trajectory</h4>
                    {trajectory.map((t, idx) => (
                        <div key={idx} style={{fontSize: '0.85rem', padding: '0.5rem', background: 'var(--surface-sunken)', marginBottom: '0.4rem', borderRadius: '4px', borderLeft: '3px solid var(--accent)'}}>
                            {t}
                        </div>
                    ))}
                  </div>
              )}
            </>
          ) : (
            <p className="feed-empty">Sign in to view progress.</p>
          )}
          {devMode && studentProgress && (
            <pre className="code-block" style={{marginTop: '1rem'}}>{JSON.stringify(studentProgress, null, 2)}</pre>
          )}
        </div>

        <div className="widget">
          <h3>Assignments</h3>
          <label className="file-upload-area">
            <span className="file-upload-lbl">{submissionFile ? submissionFile.name : "Click here to attach file"}</span>
            <input type="file" onChange={(e) => setSubmissionFile(e.target.files?.[0] || null)} />
          </label>
          <button className="btn-solid" onClick={submitAssignment} disabled={!submissionFile || busy || !token}>
            {busy ? "Submitting..." : "Turn in"}
          </button>

          {submissionStatus && submissionStatus.id && (
             <button style={{marginTop: '0.5rem', width: '100%', padding: '0.5rem', border: '1px solid var(--border-light)', borderRadius: '6px', background: 'transparent', cursor: 'pointer'}} onClick={() => loadSubmissionDetails(submissionStatus.id)}>
                 Check Defence Status
             </button>
          )}
          
          {submissionStatus && (
            <div style={{marginTop: '1rem', fontSize: '0.85rem', textAlign: 'center', background: 'var(--surface-sunken)', padding: '0.5rem', borderRadius: '4px'}}>
              <strong>{submissionStatus.status}</strong>
              {submissionStatus.workflow && <div>State: {submissionStatus.workflow}</div>}
              {submissionStatus.pending_approval && <div style={{color: 'orange'}}>Scores hidden pending professor approval</div>}
              {submissionStatus.grade && <div>Grade: {submissionStatus.grade}</div>}
              {devMode && submissionStatus.id && <><span style={{color: 'var(--text-tertiary)', fontSize:'0.75rem'}}>ID: {submissionStatus.id}</span></>}
            </div>
          )}
        </div>

        <div className="widget">
          <h3>Achievements</h3>
          {studentAchievements.length > 0 ? (
            studentAchievements.map((ach, idx) => (
              <div key={idx} className="feed-item">
                <p><strong>🏆 {ach.name || "Award"}</strong></p>
                <p className="meta">{ach.description || "Earned via mastery"}</p>
              </div>
            ))
          ) : (
            <p className="feed-empty">Keep learning to earn achievements.</p>
          )}
        </div>
      </div>
    </div>
  );
}
