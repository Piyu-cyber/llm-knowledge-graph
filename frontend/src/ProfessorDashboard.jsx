import { useState, useEffect } from "react";
import { ProfessorApi } from "./endpoints";

export default function ProfessorDashboard({ apiBase, token, profCourse, devMode, pushActivity }) {
  const [busy, setBusy] = useState(false);
  const [cohortOverview, setCohortOverview] = useState(null);
  const [hitlQueue, setHitlQueue] = useState([]);
  const [graphData, setGraphData] = useState(null);
  const [studentList, setStudentList] = useState([]);
  const [selectedStudent, setSelectedStudent] = useState(null);
  
  // Dashboard Sub-navigation
  const [activeTab, setActiveTab] = useState("overview"); // overview, hitl, graph, students, learning_path

  const loadProfessorData = async () => {
    setBusy(true);
    try {
      const [overviewRes, queueRes] = await Promise.all([
        ProfessorApi.cohortOverview(apiBase, token, profCourse, 7),
        ProfessorApi.hitlQueue(apiBase, token),
      ]);
      if(overviewRes.ok) setCohortOverview(overviewRes.data);
      if(queueRes.ok) setHitlQueue(queueRes.data?.items || []);
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
        const res = await ProfessorApi.hitlAction(apiBase, token, queueId, { action });
        pushActivity({ endpoint: `/professor/hitl-queue/${queueId}/action`, status: res.status, ok: res.ok, method: "POST" });
        if(res.ok) {
            loadProfessorData();
        }
    } finally {
        setBusy(false);
    }
  };

  return (
    <div className="dashboard-grid">
      <div className="widgets-column" style={{gridColumn: '1 / -1'}}>
        <div className="widget" style={{padding: '0', border: 'none', background: 'transparent'}}>
            <nav style={{display: 'flex', gap: '1rem', borderBottom: '1px solid var(--border-light)', paddingBottom: '0.5rem', marginBottom: '1rem'}}>
                <button onClick={() => setActiveTab('overview')} style={{background: 'none', border: 'none', cursor: 'pointer', fontWeight: activeTab === 'overview' ? 600 : 400, color: activeTab === 'overview' ? 'var(--text-primary)' : 'var(--text-secondary)'}}>Overview</button>
                <button onClick={() => setActiveTab('hitl')} style={{background: 'none', border: 'none', cursor: 'pointer', fontWeight: activeTab === 'hitl' ? 600 : 400, color: activeTab === 'hitl' ? 'var(--text-primary)' : 'var(--text-secondary)'}}>HITL Queue {hitlQueue.length > 0 && `(${hitlQueue.length})`}</button>
                <button onClick={() => setActiveTab('graph')} style={{background: 'none', border: 'none', cursor: 'pointer', fontWeight: activeTab === 'graph' ? 600 : 400, color: activeTab === 'graph' ? 'var(--text-primary)' : 'var(--text-secondary)'}}>Graph Editor</button>
                <button onClick={() => setActiveTab('students')} style={{background: 'none', border: 'none', cursor: 'pointer', fontWeight: activeTab === 'students' ? 600 : 400, color: activeTab === 'students' ? 'var(--text-primary)' : 'var(--text-secondary)'}}>Students</button>
                <button onClick={() => setActiveTab('learning_path')} style={{background: 'none', border: 'none', cursor: 'pointer', fontWeight: activeTab === 'learning_path' ? 600 : 400, color: activeTab === 'learning_path' ? 'var(--text-primary)' : 'var(--text-secondary)'}}>Learning Path</button>
            </nav>
        </div>

        {activeTab === 'overview' && (
            <>
              <div className="widget" style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
                <div>
                  <h3 style={{marginBottom: '0.2rem'}}>Cohort Overview</h3>
                  <p style={{color: 'var(--text-secondary)', fontSize: '0.85rem', margin: 0}}>Viewing data for course <strong>{profCourse}</strong></p>
                </div>
                <button className="btn-solid" style={{width: 'auto'}} onClick={loadProfessorData} disabled={busy || !token}>Refresh Analytics</button>
              </div>

              {cohortOverview ? (
                <>
                <div className="widget">
                  <h3>Metrics Summary</h3>
                  <div style={{display:'flex', gap:'2rem', flexWrap: 'wrap'}}>
                    <div>
                      <div style={{fontSize:'2rem', fontWeight:600}}>{cohortOverview.total_students || 0}</div>
                      <div style={{fontSize:'0.85rem', color:'var(--text-secondary)'}}>Students Enrolled</div>
                    </div>
                    <div>
                      <div style={{fontSize:'2rem', fontWeight:600}}>{cohortOverview.struggling_students || 0}</div>
                      <div style={{fontSize:'0.85rem', color:'var(--text-secondary)'}}>Struggling</div>
                    </div>
                    <div>
                      <div style={{fontSize:'2rem', fontWeight:600}}>{cohortOverview.average_mastery ? cohortOverview.average_mastery.toFixed(1) : "0.0"}%</div>
                      <div style={{fontSize:'0.85rem', color:'var(--text-secondary)'}}>Avg Mastery</div>
                    </div>
                  </div>
                </div>

                <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem'}}>
                    <div className="widget">
                        <h3>Concepts with High Struggle Rates</h3>
                        {cohortOverview.struggling_concepts && cohortOverview.struggling_concepts.length > 0 ? (
                            <ul style={{paddingLeft: '1.2rem', margin: 0, fontSize: '0.9rem'}}>
                                {cohortOverview.struggling_concepts.map((c, i) => (
                                    <li key={i} style={{marginBottom: '0.3rem'}}>{c.name} <span style={{color: 'var(--text-tertiary)'}}>(Slip: {c.slip})</span></li>
                                ))}
                            </ul>
                        ) : <p className="feed-empty">No struggling concepts detected.</p>}
                    </div>

                    <div className="widget">
                        <h3>Inactive Students (&gt;7 days)</h3>
                        {cohortOverview.inactive_students && cohortOverview.inactive_students.length > 0 ? (
                            <ul style={{paddingLeft: '1.2rem', margin: 0, fontSize: '0.9rem'}}>
                                {cohortOverview.inactive_students.map((s, i) => (
                                    <li key={i} style={{marginBottom: '0.3rem'}}>{s}</li>
                                ))}
                            </ul>
                        ) : <p className="feed-empty">All students are currently active.</p>}
                    </div>
                </div>
                </>
              ) : (
                  <div className="widget"><p className="feed-empty">Loading cohort data...</p></div>
              )}
            </>
        )}

        {activeTab === 'hitl' && (
            <div className="widget">
                <h3>Human In The Loop (HITL) Action Queue</h3>
                {hitlQueue.length > 0 ? (
                hitlQueue.map((item, idx) => {
                    const sdiWarning = item.integrity?.sdi > 85;
                    return (
                    <div key={idx} style={{border: '1px solid var(--border-light)', padding: '1rem', borderRadius: '8px', marginBottom: '1rem', background: 'var(--surface-primary)'}}>
                      <div style={{display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-light)', paddingBottom: '0.5rem', marginBottom: '0.5rem'}}>
                          <strong>Submission: {item.submission_id}</strong>
                          <span style={{fontSize: '0.85rem', color: 'var(--text-secondary)'}}>Student: {item.student_id}</span>
                      </div>
                      
                      {item.integrity && item.integrity.sdi !== null && (
                         <div style={{padding: '0.5rem', borderRadius: '4px', background: sdiWarning ? '#ffcccc' : '#e6ffe6', color: sdiWarning ? '#cc0000' : '#006600', marginBottom: '0.5rem', fontSize: '0.85rem', display: 'inline-block'}}>
                             <strong>Integrity Score (SDI):</strong> {item.integrity.sdi}% 
                             {sdiWarning && " ⚠️ Flagged for anomalous writing style"}
                         </div>
                      )}

                      <div style={{marginBottom: '1rem', maxHeight: '150px', overflowY: 'auto', padding: '0.5rem', background: 'var(--surface-sunken)', borderRadius: '4px', fontSize: '0.85rem', border: '1px solid var(--border-light)'}}>
                          <div style={{fontWeight: 600, marginBottom: '0.3rem'}}>Defence Transcript:</div>
                          {item.transcript && item.transcript.map((t, i) => (
                              <div key={i} style={{marginBottom: '0.4rem'}}>
                                  <strong style={{color: t.role === 'assistant' ? 'var(--accent)' : 'inherit'}}>{t.role === 'assistant' ? 'AI' : 'Student'}:</strong> {t.content}
                              </div>
                          ))}
                          {(!item.transcript || item.transcript.length === 0) && "No transcript available."}
                      </div>

                      <div style={{marginBottom: '1rem'}}>
                          <p style={{margin: '0 0 0.2rem', fontSize: '0.9rem'}}>AI Suggested Grade: <strong>{item.ai_recommended_grade}</strong></p>
                          <p style={{margin: '0', fontSize: '0.85rem', color: 'var(--text-secondary)'}}>{item.ai_feedback}</p>
                      </div>

                      <div style={{display: 'flex', gap: '0.5rem'}}>
                        <button onClick={() => handleHitlAction(item.queue_id, 'approve')} disabled={busy} style={{padding: '0.5rem 1rem', background: 'var(--accent)', color: 'white', borderRadius: '4px', border: 'none', cursor: 'pointer'}}>Approve</button>
                        <button onClick={() => handleHitlAction(item.queue_id, 'reject_second_defence')} disabled={busy} style={{padding: '0.5rem 1rem', background: 'white', border: '1px solid var(--border-light)', borderRadius: '4px', cursor: 'pointer'}}>Reject & Request Re-defence</button>
                      </div>
                    </div>
                )})
                ) : (
                <p className="feed-empty">No pending actions required.</p>
                )}
            </div>
        )}

        {activeTab === 'graph' && (
             <div className="widget">
                <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem'}}>
                    <h3>Knowledge Graph Editor (MVP)</h3>
                    <button className="btn-solid" style={{width: 'auto', padding: '0.4rem 1rem'}} onClick={async () => {
                        setBusy(true);
                        try {
                            const res = await ProfessorApi.graphVisualization(apiBase, token, profCourse);
                            if(res.ok) setGraphData(res.data);
                        } finally { setBusy(false); }
                    }} disabled={busy || !token}>Load Graph</button>
                </div>
                
                {graphData ? (
                    <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))', gap: '1rem'}}>
                        {graphData.nodes?.map((node, i) => (
                            <div key={i} style={{padding: '1rem', background: 'var(--surface-sunken)', borderRadius: '8px', borderLeft: `4px solid ${node.level === 'CONCEPT' ? 'var(--accent)' : 'var(--border-light)'}`}}>
                                <div style={{fontWeight: 600, fontSize: '1rem', marginBottom: '0.3rem'}}>{node.label || node.id}</div>
                                <div style={{fontSize: '0.8rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px'}}>{node.level || 'Node'}</div>
                                {graphData.edges?.filter(e => e.source === node.id).length > 0 && (
                                    <div style={{marginTop: '0.5rem', fontSize: '0.85rem'}}>
                                        <div style={{fontWeight: 500, color: 'var(--text-tertiary)', marginBottom: '0.2rem'}}>Connects to:</div>
                                        {graphData.edges.filter(e => e.source === node.id).map((e, idx) => (
                                            <div key={idx} style={{background: 'var(--surface-primary)', padding: '0.2rem 0.5rem', borderRadius: '4px', display: 'inline-block', marginRight: '0.5rem', marginBottom: '0.5rem', border: '1px solid var(--border-light)'}}>{e.target} <span style={{color: 'var(--text-tertiary)', fontSize: '0.75rem'}}>({e.label})</span></div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                ) : (
                    <p className="feed-empty" style={{textAlign: 'left'}}>Click 'Load Graph' to fetch structural data for {profCourse}.</p>
                )}
             </div>
        )}

        {activeTab === 'students' && (
             <div className="widget">
                <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem'}}>
                    <h3>Student Drill-Down</h3>
                    <button className="btn-solid" style={{width: 'auto', padding: '0.4rem 1rem'}} onClick={async () => {
                        setBusy(true);
                        try {
                            const res = await ProfessorApi.students(apiBase, token);
                            if(res.ok) setStudentList(res.data?.students || []);
                        } finally { setBusy(false); }
                    }} disabled={busy || !token}>Load Enrolled Students</button>
                </div>
                
                {studentList.length > 0 ? (
                    <div style={{display: 'flex', gap: '2rem'}}>
                        <div style={{flex: '1', minWidth: '200px', borderRight: '1px solid var(--border-light)', paddingRight: '1rem'}}>
                            {studentList.map((s, i) => (
                                <button key={i} onClick={() => setSelectedStudent(s)} style={{width: '100%', textAlign: 'left', padding: '0.75rem 1rem', background: selectedStudent?.id === s.id ? 'var(--surface-sunken)' : 'transparent', border: 'none', borderLeft: selectedStudent?.id === s.id ? '3px solid var(--accent)' : '3px solid transparent', cursor: 'pointer', borderRadius: '0 4px 4px 0', marginBottom: '0.2rem', fontWeight: selectedStudent?.id === s.id ? 600 : 400}}>
                                    {s.name || s.id}
                                </button>
                            ))}
                        </div>
                        <div style={{flex: '3'}}>
                            {selectedStudent ? (
                                <div>
                                    <h4 style={{marginTop: 0, fontSize: '1.2rem'}}>{selectedStudent.name || selectedStudent.id} Profile</h4>
                                    <p style={{color: 'var(--text-secondary)'}}>Email: {selectedStudent.email || 'N/A'}</p>
                                    
                                    <div style={{marginTop: '1.5rem', padding: '1rem', background: 'var(--surface-sunken)', borderRadius: '8px'}}>
                                        <h5 style={{margin: '0 0 0.5rem', fontSize: '0.9rem', color: 'var(--text-tertiary)', textTransform: 'uppercase'}}>Private Professor Notes</h5>
                                        <textarea placeholder="Add private observation notes here..." style={{width: '100%', minHeight: '80px', padding: '0.5rem', border: '1px solid var(--border-light)', borderRadius: '4px', background: 'var(--surface-primary)', resize: 'vertical'}}></textarea>
                                    </div>
                                </div>
                            ) : (
                                <div style={{display: 'flex', height: '100%', alignItems: 'center', justifyContent: 'center', color: 'var(--text-tertiary)'}}>
                                    Select a student from the list to view their graph overlay and details.
                                </div>
                            )}
                        </div>
                    </div>
                ) : (
                    <p className="feed-empty" style={{textAlign: 'left'}}>Click 'Load Enrolled Students' to view roster.</p>
                )}
             </div>
        )}

        {activeTab === 'learning_path' && (
             <div className="widget">
                <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem'}}>
                    <h3>Learning Path Configuration</h3>
                    <div style={{display: 'flex', gap: '0.5rem'}}>
                        <button className="btn-solid" style={{background: 'var(--surface-sunken)', color: 'var(--text-primary)', border: '1px solid var(--border-light)', width: 'auto', padding: '0.4rem 1rem'}} onClick={async () => {
                            setBusy(true);
                            // Assume loadLearningPath exists
                            try {
                                const res = await ProfessorApi.loadLearningPath(apiBase, token, profCourse);
                                if(res.ok) alert("Loaded path of length: " + (res.data?.path?.length || 0));
                            } finally { setBusy(false); }
                        }} disabled={busy || !token}>Load Active Path</button>
                        
                        <button className="btn-solid" style={{width: 'auto', padding: '0.4rem 1rem'}} onClick={async () => {
                            setBusy(true);
                            try {
                                const res = await ProfessorApi.saveLearningPath(apiBase, token, { course_id: profCourse, path: [] });
                                if(res.ok) alert("Path saved successfully.");
                            } finally { setBusy(false); }
                        }} disabled={busy || !token}>Publish Path</button>
                    </div>
                </div>
                
                <p className="feed-empty" style={{textAlign: 'left'}}>
                    (MVP) In a full implementation, you would drag and drop nodes from the Knowledge Graph here to define an ordered sequence.
                </p>
                <div style={{padding: '2rem', border: '2px dashed var(--border-light)', borderRadius: '8px', textAlign: 'center', color: 'var(--text-tertiary)'}}>
                    Drag topics here to sequence
                </div>
             </div>
        )}
      </div>
    </div>
  );
}
