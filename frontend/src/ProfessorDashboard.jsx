import { useState, useEffect, useRef } from "react";
import { ProfessorApi } from "./endpoints";

export default function ProfessorDashboard({ apiBase, token, profCourse, devMode, pushActivity }) {
  const [busy, setBusy] = useState(false);
  const [cohortOverview, setCohortOverview] = useState(null);
  const [hitlQueue, setHitlQueue] = useState([]);
  const [graphData, setGraphData] = useState(null);
  const [studentList, setStudentList] = useState([]);
  const [selectedStudent, setSelectedStudent] = useState(null);
  
  // Dashboard Sub-navigation
  const [activeTab, setActiveTab] = useState("overview"); 
  const fileInputRef = useRef(null);

  // Store editable states for HITL items
  const [hitlEditState, setHitlEditState] = useState({});

  const loadProfessorData = async () => {
    setBusy(true);
    try {
      const [overviewRes, queueRes] = await Promise.all([
        ProfessorApi.cohortOverview(apiBase, token, profCourse, 7),
        ProfessorApi.hitlQueue(apiBase, token),
      ]);
      if(overviewRes.ok) setCohortOverview(overviewRes.data);
      if(queueRes.ok) {
        // PD-6: Sort queue to float Anomalous Input (SDI > 85%) to the very top.
        const items = queueRes.data?.items || [];
        items.sort((a, b) => {
            const aSdi = a.integrity?.sdi || 0;
            const bSdi = b.integrity?.sdi || 0;
            if (aSdi > 85 && bSdi <= 85) return -1;
            if (bSdi > 85 && aSdi <= 85) return 1;
            return 0; // maintain default order beyond flag
        });
        setHitlQueue(items);

        // Prepopulate edit states for inputs
        const initialEdit = {};
        for (const item of items) {
           initialEdit[item.queue_id] = {
               ai_recommended_grade: item.ai_recommended_grade,
               ai_feedback: item.ai_feedback
           };
        }
        setHitlEditState(initialEdit);
      }
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
     if(token) {
        loadProfessorData();
     }
  }, [token, profCourse]);

  const handleHitlAction = async (queueId, action) => {
    setBusy(true);
    try {
        const payload = { action, ...hitlEditState[queueId] }; 
        const res = await ProfessorApi.hitlAction(apiBase, token, queueId, payload);
        pushActivity({ endpoint: `/professor/hitl-queue/${queueId}/action`, status: res.status, ok: res.ok, method: "POST" });
        if(res.ok) {
            loadProfessorData();
        }
    } finally {
        setBusy(false);
    }
  };

  const handleEditChange = (queueId, field, value) => {
      setHitlEditState(prev => ({
          ...prev,
          [queueId]: {
              ...prev[queueId],
              [field]: value
          }
      }));
  };

  // Mock sequences for Learning Path
  const learningSequence = ["Introduction to Architecture", "Centralized Systems", "Decentralized Nodes", "Consensus Algorithms"];

  const handleFileUpload = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    
    setBusy(true);
    try {
        const res = await ProfessorApi.ingest(apiBase, token, file, profCourse);
        pushActivity({ endpoint: `/ingest?course_id=${profCourse}`, status: res.status, ok: res.ok, method: "POST" });
        if(res.ok) {
            alert(`Successfully ingested! Added ${res.data?.concepts_added || 0} concepts and ${res.data?.relationships_added || 0} relationships from ${file.name}.`);
            // Refresh graph visualization
            const graphRes = await ProfessorApi.graphVisualization(apiBase, token, profCourse);
            if(graphRes.ok) setGraphData(graphRes.data);
        } else {
            alert(`Failed to ingest document: ${res.data?.detail || res.data?.message || 'Unknown error'}`);
        }
    } finally {
        setBusy(false);
        if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  return (
    <div className="dashboard-grid">
      <div className="widgets-column" style={{gridColumn: '1 / -1'}}>
        <div className="widget" style={{padding: '0', border: 'none', background: 'transparent'}}>
            <nav style={{display: 'flex', gap: '1rem', borderBottom: '1px solid var(--border-light)', paddingBottom: '0.5rem', marginBottom: '1rem', overflowX: 'auto'}}>
                <button onClick={() => setActiveTab('overview')} style={{background: 'none', border: 'none', cursor: 'pointer', fontWeight: activeTab === 'overview' ? 600 : 400, color: activeTab === 'overview' ? 'var(--text-primary)' : 'var(--text-secondary)'}}>Overview</button>
                <button onClick={() => setActiveTab('hitl')} style={{background: 'none', border: 'none', cursor: 'pointer', fontWeight: activeTab === 'hitl' ? 600 : 400, color: activeTab === 'hitl' ? 'var(--text-primary)' : 'var(--text-secondary)'}}>
                  HITL Review Queue {hitlQueue.length > 0 && <span style={{backgroundColor: 'var(--accent)', color: 'white', padding: '0.1rem 0.4rem', borderRadius: '12px', fontSize: '0.75rem', marginLeft: '0.3rem'}}>{hitlQueue.length}</span>}
                </button>
                <button onClick={() => setActiveTab('graph')} style={{background: 'none', border: 'none', cursor: 'pointer', fontWeight: activeTab === 'graph' ? 600 : 400, color: activeTab === 'graph' ? 'var(--text-primary)' : 'var(--text-secondary)'}}>Knowledge Graph</button>
                <button onClick={() => setActiveTab('students')} style={{background: 'none', border: 'none', cursor: 'pointer', fontWeight: activeTab === 'students' ? 600 : 400, color: activeTab === 'students' ? 'var(--text-primary)' : 'var(--text-secondary)'}}>Student Drill-Down</button>
                <button onClick={() => setActiveTab('learning_path')} style={{background: 'none', border: 'none', cursor: 'pointer', fontWeight: activeTab === 'learning_path' ? 600 : 400, color: activeTab === 'learning_path' ? 'var(--text-primary)' : 'var(--text-secondary)'}}>Learning Paths</button>
            </nav>
        </div>

        {/* PD-1: Cohort Progress Overview */}
        {activeTab === 'overview' && (
            <>
              <div className="widget" style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
                <div>
                  <h3 style={{marginBottom: '0.2rem'}}>Cohort Progress Overview</h3>
                  <p style={{color: 'var(--text-secondary)', fontSize: '0.85rem', margin: 0}}>Macro-level insight over course <strong>{profCourse}</strong></p>
                </div>
                <button className="btn-solid" style={{width: 'auto'}} onClick={loadProfessorData} disabled={busy || !token}>Refresh Analytics</button>
              </div>

              {cohortOverview ? (
                <>
                <div className="widget">
                  <h3>Metrics Summary</h3>
                  <div style={{display:'flex', gap:'3rem', flexWrap: 'wrap'}}>
                    <div>
                      <div style={{fontSize:'2.5rem', fontWeight:600}}>{cohortOverview.total_students || 0}</div>
                      <div style={{fontSize:'0.85rem', color:'var(--text-secondary)'}}>Students Enrolled</div>
                    </div>
                    <div>
                      <div style={{fontSize:'2.5rem', fontWeight:600}}>{cohortOverview.struggling_students || 0}</div>
                      <div style={{fontSize:'0.85rem', color:'var(--text-secondary)'}}>Struggling</div>
                    </div>
                    <div>
                      <div style={{fontSize:'2.5rem', fontWeight:600}}>{cohortOverview.average_mastery ? cohortOverview.average_mastery.toFixed(1) : "0.0"}%</div>
                      <div style={{fontSize:'0.85rem', color:'var(--text-secondary)'}}>Average Mastery</div>
                    </div>
                  </div>
                </div>

                <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem'}}>
                    <div className="widget">
                        <h3>Concepts with High Struggle Rates</h3>
                        <p style={{fontSize: '0.8rem', color: 'var(--text-tertiary)', marginBottom: '1rem'}}>Based on IRT Slip parameter modelling across the cohort.</p>
                        {cohortOverview.struggling_concepts && cohortOverview.struggling_concepts.length > 0 ? (
                            <ul style={{paddingLeft: '1.2rem', margin: 0, fontSize: '0.9rem'}}>
                                {cohortOverview.struggling_concepts.map((c, i) => (
                                    <li key={i} style={{marginBottom: '0.4rem'}}>
                                        <strong>{c.name}</strong> 
                                        <div style={{color: '#d97706', fontSize: '0.8rem'}}>Slip Ratio: {c.slip}</div>
                                    </li>
                                ))}
                            </ul>
                        ) : <p className="feed-empty">No universally struggling concepts detected.</p>}
                    </div>

                    <div className="widget">
                        <h3>Unengaged Students (&gt;7 days)</h3>
                        <p style={{fontSize: '0.8rem', color: 'var(--text-tertiary)', marginBottom: '1rem'}}>Students requiring intervention prompts.</p>
                        {cohortOverview.inactive_students && cohortOverview.inactive_students.length > 0 ? (
                            <ul style={{paddingLeft: '1.2rem', margin: 0, fontSize: '0.9rem'}}>
                                {cohortOverview.inactive_students.map((s, i) => (
                                    <li key={i} style={{marginBottom: '0.3rem'}}>{s}</li>
                                ))}
                            </ul>
                        ) : <p className="feed-empty">All students actively participating.</p>}
                    </div>
                </div>
                </>
              ) : (
                  <div className="widget"><p className="feed-empty">Loading cohort parameters...</p></div>
              )}
            </>
        )}

        {/* PD-4 & PD-6: HITL Queue & Integrity */}
        {activeTab === 'hitl' && (
            <div className="widget">
                <h3 style={{marginBottom: '0.2rem'}}>Human In The Loop (HITL) Queue</h3>
                <p style={{fontSize: '0.8rem', color: 'var(--text-tertiary)', marginBottom: '1.5rem'}}>Evaluate, modify, and officially credential AI-audited submissions. Anomalous inputs rise to the top.</p>
                {hitlQueue.length > 0 ? (
                hitlQueue.map((item, idx) => {
                    const sdiWarning = item.integrity?.sdi > 85;
                    const editObj = hitlEditState[item.queue_id] || {};

                    return (
                    <div key={idx} style={{border: '1px solid var(--border-light)', padding: '1.5rem', borderRadius: '8px', marginBottom: '1.5rem', background: 'var(--surface-primary)', boxShadow: sdiWarning ? '0 0 0 2px #ef4444' : 'none'}}>
                      <div style={{display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-light)', paddingBottom: '0.5rem', marginBottom: '1rem'}}>
                          <div>
                             <strong style={{fontSize: '1.1rem'}}>Submission Evaluator: {item.submission_id}</strong>
                             <div style={{fontSize: '0.85rem', color: 'var(--accent)'}}>Student: {item.student_id}</div>
                          </div>
                          
                          {/* PD-6: Flagging */}
                          {item.integrity && item.integrity.sdi !== null && (
                             <div style={{padding: '0.5rem 1rem', borderRadius: '4px', background: sdiWarning ? '#fee2e2' : '#f0fdf4', color: sdiWarning ? '#b91c1c' : '#15803d', display: 'flex', alignItems: 'center', fontWeight: 600}}>
                                 {sdiWarning ? "⚠️ Anomalous Input (SDI > 85%)" : "Integrity Cleared"} 
                                 <span style={{marginLeft: '0.5rem', fontWeight: 400}}> | SDI: {item.integrity.sdi}%</span>
                             </div>
                          )}
                      </div>

                      <div style={{marginBottom: '1.5rem'}}>
                          <div style={{fontWeight: 600, marginBottom: '0.5rem', color: 'var(--text-secondary)'}}>Multi-turn Defence Transcript</div>
                          <div style={{maxHeight: '200px', overflowY: 'auto', padding: '1rem', background: 'var(--bg-secondary)', borderRadius: '6px', fontSize: '0.9rem', border: '1px solid var(--border-light)'}}>
                              {item.transcript && item.transcript.map((t, i) => (
                                  <div key={i} style={{marginBottom: '0.6rem'}}>
                                      <strong style={{color: t.role === 'assistant' ? 'var(--accent)' : 'var(--text-primary)'}}>{t.role === 'assistant' ? 'Evaluator' : 'Student'}:</strong> {t.content}
                                  </div>
                              ))}
                              {(!item.transcript || item.transcript.length === 0) && "No transcript available."}
                          </div>
                      </div>

                      {/* PD-4: Editable Overrides */}
                      <div style={{display: 'grid', gridTemplateColumns: '1fr 3fr', gap: '1rem', marginBottom: '1.5rem', background: 'var(--bg-secondary)', padding: '1rem', borderRadius: '6px'}}>
                          <div>
                              <label style={{display: 'block', fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.3rem', color: 'var(--text-secondary)'}}>Final Grade (AI Rec: {item.ai_recommended_grade})</label>
                              <input 
                                  type="text" 
                                  value={editObj.ai_recommended_grade || ""} 
                                  onChange={(e) => handleEditChange(item.queue_id, "ai_recommended_grade", e.target.value)}
                                  style={{fontWeight: 600, fontSize: '1.1rem'}}
                              />
                          </div>
                          <div>
                              <label style={{display: 'block', fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.3rem', color: 'var(--text-secondary)'}}>Feedback / Professor Notes</label>
                              <textarea 
                                  value={editObj.ai_feedback || ""}
                                  onChange={(e) => handleEditChange(item.queue_id, "ai_feedback", e.target.value)}
                                  style={{resize: 'vertical', minHeight: '80px', fontSize: '0.9rem'}}
                              />
                          </div>
                      </div>

                      <div style={{display: 'flex', gap: '1rem'}}>
                        <button onClick={() => handleHitlAction(item.queue_id, 'approve')} disabled={busy} className="btn-solid" style={{background: 'var(--accent)', flex: 1}}>Confirm & Credential Grade</button>
                        <button onClick={() => handleHitlAction(item.queue_id, 'reject_second_defence')} disabled={busy} className="btn-solid" style={{background: 'white', color: 'var(--brand)', border: '1px solid var(--brand)', flex: 1}}>Reject & Mandate Re-defence</button>
                      </div>
                    </div>
                )})
                ) : (
                <div style={{padding: '3rem', textAlign: 'center', border: '2px dashed var(--border-light)', borderRadius: '8px'}}>
                    <h4 style={{color: 'var(--text-tertiary)', fontWeight: 400}}>The queue is completely clear.</h4>
                </div>
                )}
            </div>
        )}

        {/* PD-3: Knowledge Graph Editor */}
        {activeTab === 'graph' && (
             <div className="widget">
                <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem'}}>
                    <div>
                        <h3 style={{marginBottom: '0'}}>Knowledge Graph Editor</h3>
                        <p style={{fontSize: '0.8rem', color: 'var(--text-tertiary)', margin: '0.2rem 0 0'}}>Direct manipulation of course graph nodes and boundaries.</p>
                    </div>
                    <div style={{display: 'flex', gap: '1rem'}}>
                        <input type="file" ref={fileInputRef} style={{ display: 'none' }} accept=".pdf,.doc,.docx,.ppt,.pptx,.txt" onChange={handleFileUpload} />
                        <button className="btn-solid" style={{width: 'auto', padding: '0.4rem 1rem', background: 'var(--bg-secondary)', color: 'var(--brand)', border: '1px solid var(--border-light)'}} onClick={() => fileInputRef.current?.click()} disabled={busy || !token}>Upload Material (Re-ingest)</button>
                        <button className="btn-solid" style={{width: 'auto', padding: '0.4rem 1rem'}} onClick={async () => {
                            setBusy(true);
                            try {
                                const res = await ProfessorApi.graphVisualization(apiBase, token, profCourse);
                                if(res.ok) setGraphData(res.data);
                            } finally { setBusy(false); }
                        }} disabled={busy || !token}>Fetch Graph Map</button>
                    </div>
                </div>
                
                {graphData ? (
                    <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: '1.5rem', marginTop: '1.5rem'}}>
                        {graphData.nodes?.map((node, i) => (
                            <div key={i} style={{padding: '1rem', background: 'var(--surface-primary)', borderRadius: '8px', border: '1px solid var(--border-light)', borderLeft: `6px solid ${node.level === 'CONCEPT' ? 'var(--accent)' : 'var(--border-light)'}`, position: 'relative'}}>
                                <div style={{fontWeight: 600, fontSize: '1.1rem', marginBottom: '0.3rem'}}>{node.label || node.id}</div>
                                <div style={{fontSize: '0.75rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '0.5rem'}}>{node.level || 'Node Entity'}</div>
                                
                                {/* Placeholder Editor Tags */}
                                <div style={{display: 'flex', gap: '0.5rem', marginTop: '1rem', borderTop: '1px solid var(--border-light)', paddingTop: '0.5rem'}}>
                                    <label style={{fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.3rem'}}>
                                        <input type="checkbox" /> High Priority
                                    </label>
                                    <label style={{fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.3rem', color: 'var(--text-tertiary)'}}>
                                        <input type="checkbox" /> Out of Scope
                                    </label>
                                </div>
                            </div>
                        ))}
                    </div>
                ) : (
                    <div style={{padding: '3rem', textAlign: 'center', border: '2px dashed var(--border-light)', borderRadius: '8px'}}>
                        <p style={{color: 'var(--text-tertiary)', margin: 0}}>Fetch node data to visualize graph dimensions.</p>
                    </div>
                )}
             </div>
        )}

        {/* PD-2: Individual Student Drill-Down */}
        {activeTab === 'students' && (
             <div className="widget">
                <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem'}}>
                    <div>
                        <h3 style={{marginBottom: 0}}>Student Profile Drill-Down</h3>
                        <p style={{fontSize: '0.8rem', color: 'var(--text-tertiary)', margin: '0.2rem 0 0'}}>Inspect personalized graph overlays and BKT parameters.</p>
                    </div>
                    <button className="btn-solid" style={{width: 'auto', padding: '0.4rem 1rem'}} onClick={async () => {
                        setBusy(true);
                        try {
                            const res = await ProfessorApi.students(apiBase, token);
                            if(res.ok) setStudentList(res.data?.students || []);
                        } finally { setBusy(false); }
                    }} disabled={busy || !token}>Fetch Roster</button>
                </div>
                
                {studentList.length > 0 ? (
                    <div style={{display: 'flex', gap: '2rem'}}>
                        <div style={{flex: '1', minWidth: '220px', borderRight: '1px solid var(--border-light)', paddingRight: '1rem'}}>
                            {studentList.map((s, i) => (
                                <button key={i} onClick={() => setSelectedStudent(s)} style={{width: '100%', textAlign: 'left', padding: '0.75rem 1rem', background: selectedStudent?.id === s.id ? 'var(--bg-secondary)' : 'transparent', border: 'none', borderLeft: selectedStudent?.id === s.id ? '3px solid var(--brand)' : '3px solid transparent', cursor: 'pointer', borderRadius: '0 4px 4px 0', marginBottom: '0.5rem', fontWeight: selectedStudent?.id === s.id ? 600 : 400}}>
                                    👤 {s.name || s.id}
                                </button>
                            ))}
                        </div>
                        <div style={{flex: '3'}}>
                            {selectedStudent ? (
                                <div>
                                    <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', borderBottom: '1px solid var(--border-light)', paddingBottom: '0.5rem', marginBottom: '1rem'}}>
                                        <h4 style={{marginTop: 0, fontSize: '1.3rem'}}>{selectedStudent.name || selectedStudent.id}</h4>
                                        <span style={{color: 'var(--text-secondary)', fontSize: '0.9rem'}}>{selectedStudent.email || 'N/A'}</span>
                                    </div>
                                    
                                    {/* Mocking explicit PD-2 overlay data visually */}
                                    <h5 style={{fontSize: '0.9rem', marginBottom: '0.5rem'}}>Personalized Knowledge Overlay</h5>
                                    <div style={{overflowX: 'auto', marginBottom: '1.5rem'}}>
                                        <table style={{width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem'}}>
                                            <thead>
                                                <tr style={{background: 'var(--bg-secondary)', textAlign: 'left'}}>
                                                    <th style={{padding: '0.5rem'}}>Concept Node</th>
                                                    <th style={{padding: '0.5rem'}}>Visited</th>
                                                    <th style={{padding: '0.5rem'}}>Mastery Estimate</th>
                                                    <th style={{padding: '0.5rem'}}>Session Hist</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                <tr style={{borderBottom: '1px solid var(--border-light)'}}>
                                                    <td style={{padding: '0.5rem'}}>CS_Architecture</td>
                                                    <td style={{padding: '0.5rem'}}>Yes</td>
                                                    <td style={{padding: '0.5rem'}}>0.72 (Theta: 0.1)</td>
                                                    <td style={{padding: '0.5rem'}}><a href="#" style={{color: 'var(--accent)'}}>View Transcript</a></td>
                                                </tr>
                                                <tr style={{borderBottom: '1px solid var(--border-light)'}}>
                                                    <td style={{padding: '0.5rem'}}>Linked_Lists</td>
                                                    <td style={{padding: '0.5rem'}}>Yes</td>
                                                    <td style={{padding: '0.5rem', color: '#b91c1c'}}>0.31 (Theta: -0.4)</td>
                                                    <td style={{padding: '0.5rem'}}><a href="#" style={{color: 'var(--accent)'}}>View Transcript</a></td>
                                                </tr>
                                            </tbody>
                                        </table>
                                    </div>

                                    <div style={{padding: '1.5rem', background: 'var(--bg-secondary)', borderRadius: '8px', border: '1px solid var(--border-light)'}}>
                                        <h5 style={{margin: '0 0 0.5rem', fontSize: '0.9rem'}}>Private Professor Notes</h5>
                                        <p style={{fontSize: '0.8rem', color: 'var(--text-tertiary)', marginBottom: '0.5rem'}}>Invisible to the student. Saves as overlay attribute.</p>
                                        <textarea placeholder="Record engagement markers, struggle points, or manual appraisal..." style={{width: '100%', minHeight: '100px', padding: '0.75rem', border: '1px solid var(--border-light)', borderRadius: '4px', resize: 'vertical'}}></textarea>
                                        <div style={{textAlign: 'right', marginTop: '0.5rem'}}><button className="btn-solid" style={{width: 'auto', padding: '0.4rem 1rem'}}>Save Note</button></div>
                                    </div>
                                </div>
                            ) : (
                                <div style={{display: 'flex', height: '100%', alignItems: 'center', justifyContent: 'center', color: 'var(--text-tertiary)', background: 'var(--bg-secondary)', borderRadius: '8px', border: '2px dashed var(--border-light)'}}>
                                    Select a roster profile to inspect graph overlay parameters.
                                </div>
                            )}
                        </div>
                    </div>
                ) : (
                    <div style={{padding: '3rem', textAlign: 'center', border: '2px dashed var(--border-light)', borderRadius: '8px'}}>
                        <p className="feed-empty" style={{margin: 0}}>Roster unloaded. Fetch students above.</p>
                    </div>
                )}
             </div>
        )}

        {/* PD-5: Learning Path Configuration */}
        {activeTab === 'learning_path' && (
             <div className="widget">
                <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem'}}>
                    <div>
                        <h3 style={{marginBottom: 0}}>Recommended Traversal Path</h3>
                        <p style={{fontSize: '0.8rem', color: 'var(--text-tertiary)', margin: '0.4rem 0 0'}}>Define the core sequence weights for TA and Curriculum agents.</p>
                    </div>
                    <div style={{display: 'flex', gap: '1rem'}}>
                        <button className="btn-solid" style={{background: 'var(--bg-secondary)', color: 'var(--text-primary)', border: '1px solid var(--border-light)', width: 'auto', padding: '0.4rem 1rem'}} onClick={() => alert("Loaded path.")} disabled={busy || !token}>Fetch Active Priority</button>
                        <button className="btn-solid" style={{width: 'auto', padding: '0.4rem 1rem'}} onClick={() => alert("Published into Graph routing weights.")} disabled={busy || !token}>Publish Propagation</button>
                    </div>
                </div>
                
                <div style={{marginTop: '2rem', padding: '2rem', background: 'var(--bg-secondary)', borderRadius: '8px', border: '1px solid var(--border-light)'}}>
                    <div style={{display: 'flex', alignItems: 'center', overflowX: 'auto', paddingBottom: '1rem', gap: '0.5rem'}}>
                        {learningSequence.map((topic, index) => (
                            <div key={index} style={{display: 'flex', alignItems: 'center'}}>
                                <div style={{background: 'white', padding: '0.75rem 1.25rem', borderRadius: '4px', border: '1px solid var(--accent)', fontWeight: 500, fontSize: '0.9rem', whiteSpace: 'nowrap'}}>
                                    {topic}
                                </div>
                                {index < learningSequence.length - 1 && (
                                    <div style={{color: 'var(--accent)', fontSize: '1.5rem', fontWeight: 'bold', padding: '0 0.5rem'}}>→</div>
                                )}
                            </div>
                        ))}
                    </div>
                    <p style={{fontSize: '0.8rem', color: 'var(--text-tertiary)', textAlign: 'center', marginTop: '1rem'}}>
                        (MVP Simulator) Drag and drop topics from Graph Editor here to sequence the curriculum overlay.
                    </p>
                </div>
             </div>
        )}
      </div>
    </div>
  );
}
