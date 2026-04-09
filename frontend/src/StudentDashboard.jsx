import { useState, useRef, useEffect } from "react";
import { StudentApi } from "./endpoints";

const TypewriterText = ({ text }) => {
  const [displayed, setDisplayed] = useState("");
  useEffect(() => {
    setDisplayed("");
    let index = 0;
    const interval = setInterval(() => {
      setDisplayed(text.substring(0, index));
      index += 3; // speed up typewriter slightly
      if (index > text.length) {
        setDisplayed(text);
        clearInterval(interval);
      }
    }, 10);
    return () => clearInterval(interval);
  }, [text]);
  return <span>{displayed}</span>;
};

export default function StudentDashboard({ apiBase, token, chatCourse, chatSession, devMode, pushActivity }) {
  const [chatMessage, setChatMessage] = useState("");
  const [chatHistory, setChatHistory] = useState([
    { role: "assistant", content: "Hi! I'm your OmniProf TA. How can I help you with your coursework today?", isNew: false }
  ]);
  const [studentProgress, setStudentProgress] = useState(null);
  const [studentAchievements, setStudentAchievements] = useState([]);
  const [submissionFile, setSubmissionFile] = useState(null);
  const [submissionStatus, setSubmissionStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [imagePayload, setImagePayload] = useState(null);

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
    
    let contentToDisplay = msgToSend;
    if (imagePayload) contentToDisplay += " [Image Attached]";
    
    // Mark old assistant messages as not new to stop their typewriter animation
    setChatHistory(prev => prev.map(m => ({...m, isNew: false})).concat([{ role: "student", content: contentToDisplay, isNew: false }]));
    
    setBusy(true);
    try {
      const data = await StudentApi.chat(apiBase, token, {
        message: msgToSend,
        session_id: chatSession,
        course_id: chatCourse,
        image_base64: imagePayload
      });
      // SD-1: Parse topic context references if provided in metadata
      const contextRef = data.data?.metadata?.active_agent || "TA_Knowledge";
      setChatHistory(prev => [...prev, { 
          role: "assistant", 
          content: data.data?.response || "Error getting response.",
          contextRef: contextRef,
          isNew: true 
      }]);
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
      // silent fail
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
                status: "Status Pulled", 
                id: res.data.submission_id,
                workflow: res.data.workflow_status,
                pending_approval: res.data.pending_professor_approval,
                grade: res.data.final_grade,
                transcript: res.data.transcript || []
            });
        }
    } finally {
        setBusy(false);
    }
  };

  // SD-2: Progress Mastery as Confidence Bands 
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
              <div className="message-bubble">
                  {m.role === "assistant" && m.isNew ? <TypewriterText text={m.content} /> : m.content}
                  
                  {/* SD-1: Context Referencing explicitly */}
                  {m.role === "assistant" && m.contextRef && (
                      <div style={{marginTop: '0.5rem', fontSize: '0.75rem', color: 'var(--text-tertiary)', borderTop: '1px solid var(--border-light)', paddingTop: '0.4rem'}}>
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{marginRight: '0.2rem', verticalAlign: 'text-top'}}><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path></svg>
                          Topic Context: {m.contextRef}
                      </div>
                  )}
              </div>
            </div>
          ))}
          <div ref={chatEndRef} />
        </div>
        
        <div className="chat-input-container">
          <div className="chat-input-wrapper">
            <textarea 
              value={chatMessage} 
              onChange={(e) => setChatMessage(e.target.value)} 
              placeholder="Ask a question. Your TA supports context tracing and flows intuitively..."
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
        </div>
      </div>

      {/* Right: Widgets */}
      <div className="widgets-column">
        {/* SD-2: Mastery Concept Visualization */}
        <div className="widget">
          <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem'}}>
            <h3 style={{margin: 0}}>Knowledge Mastery</h3>
            <button onClick={loadStudentData} disabled={!token} style={{fontSize: '0.8rem', color: 'var(--accent)', background: 'none', border: 'none', cursor: 'pointer'}}>Sync</button>
          </div>
          
          <p style={{fontSize: '0.8rem', color: 'var(--text-tertiary)', marginBottom: '1rem'}}>Independent progress tracking based on AI evaluation.</p>

          {token ? (
            <>
              <div className="progress-list">
                <div className="progress-item">
                  <span className="progress-label">High Confidence</span>
                  <div className="progress-track"><div className="progress-fill high" style={{width: `${(high/totalConcepts)*100}%`}}></div></div>
                  {/* Purposely masking individual raw counting stats to keep student focused purely on bands as per SD-2 */}
                </div>
                <div className="progress-item">
                  <span className="progress-label">Med Confidence</span>
                  <div className="progress-track"><div className="progress-fill medium" style={{width: `${(medium/totalConcepts)*100}%`}}></div></div>
                </div>
                <div className="progress-item">
                  <span className="progress-label">Low Confidence</span>
                  <div className="progress-track"><div className="progress-fill low" style={{width: `${(low/totalConcepts)*100}%`}}></div></div>
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
        </div>

        {/* SD-4: Submission and Defence Interface */}
        <div className="widget">
          <h3>Submission Defence</h3>
          <p style={{fontSize: '0.8rem', color: 'var(--text-tertiary)', marginBottom: '1rem'}}>Submit work and engage in an automated evaluation session.</p>
          <label className="file-upload-area">
            <span className="file-upload-lbl">{submissionFile ? submissionFile.name : "Click here to attach file"}</span>
            <input type="file" onChange={(e) => setSubmissionFile(e.target.files?.[0] || null)} />
          </label>
          <button className="btn-solid" onClick={submitAssignment} disabled={!submissionFile || busy || !token}>
            {busy ? "Submitting..." : "Turn in"}
          </button>

          {submissionStatus && submissionStatus.id && (
             <button style={{marginTop: '0.5rem', width: '100%', padding: '0.5rem', border: '1px solid var(--border-light)', borderRadius: '6px', background: 'transparent', cursor: 'pointer', fontWeight: 600}} onClick={() => loadSubmissionDetails(submissionStatus.id)}>
                 Check Defence Status
             </button>
          )}
          
          {submissionStatus && (
            <div style={{marginTop: '1rem', fontSize: '0.85rem', background: 'var(--bg-secondary)', padding: '0.75rem', borderRadius: '6px', border: '1px solid var(--border-light)'}}>
              <div style={{fontWeight: 600, borderBottom: '1px solid var(--border-light)', paddingBottom: '0.3rem', marginBottom: '0.3rem'}}>
                Status: {submissionStatus.status}
              </div>
              
              {submissionStatus.workflow && <div>Defence Action: {submissionStatus.workflow}</div>}
              
              {/* Force grade hiding based on SD-4 specification - Do not show AI recommended grade without approval */}
              {submissionStatus.pending_approval ? (
                 <div style={{color: '#d97706', marginTop: '0.3rem', fontWeight: 600}}>
                    ⚠️ Scores & AI feedback hidden pending Professor approval.
                 </div>
              ) : (
                 submissionStatus.grade && <div style={{fontWeight: 600}}>Official Grade: {submissionStatus.grade}</div>
              )}

              {/* Display Defence Transcript */}
              {submissionStatus.transcript && submissionStatus.transcript.length > 0 && (
                 <div style={{marginTop: '0.75rem'}}>
                    <div style={{fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.2rem'}}>Your Defence Transcript:</div>
                    <div style={{maxHeight: '120px', overflowY: 'auto', padding: '0.5rem', background: 'var(--bg-primary)', borderRadius: '4px', border: '1px solid var(--border-light)', fontSize: '0.8rem'}}>
                       {submissionStatus.transcript.map((t, idx) => (
                           <div key={idx} style={{marginBottom: '0.4rem'}}>
                               <span style={{fontWeight: 600, color: t.role === 'assistant' ? 'var(--accent)' : 'inherit'}}>{t.role === 'assistant' ? 'AI Eval' : 'You'}: </span>
                               <span>{t.content}</span>
                           </div>
                       ))}
                    </div>
                 </div>
              )}
            </div>
          )}
        </div>

        {/* SD-3: Private Achievement Feed */}
        <div className="widget">
           <h3>Private Achievements</h3>
           <p style={{fontSize: '0.8rem', color: 'var(--text-tertiary)', marginBottom: '1rem'}}>Milestones earned are strictly private to you.</p>
          {studentAchievements.length > 0 ? (
            studentAchievements.map((ach, idx) => (
              <div key={idx} className="feed-item" style={{display: 'flex', flexDirection: 'column'}}>
                <span style={{fontWeight: 600}}>🏆 {ach.name || "Award"}</span>
                <span className="meta" style={{color: 'var(--text-secondary)'}}>{ach.description || "Earned via mastery behavior"}</span>
                <span style={{fontSize: '0.7rem', color: 'var(--text-tertiary)', marginTop: '0.2rem', fontVariantNumeric: 'tabular-nums'}}>
                    {ach.earned_at ? new Date(ach.earned_at).toLocaleString() : new Date().toLocaleString()}
                </span>
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
