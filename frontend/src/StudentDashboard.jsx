import { memo, useMemo, useState, useRef, useEffect } from "react";
import { StudentApi } from "./endpoints";

const CHAT_HISTORY_CAP = 120;

const ChatMessage = memo(function ChatMessage({ message }) {
  return (
    <div className={`message-row ${message.role}`}>
      <div className={`message-bubble ${message.isNew ? "message-enter" : ""}`}>
        {message.content}
        {message.role === "assistant" && message.contextRef && (
          <div className="context-chip">
            <svg
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              style={{ marginRight: "0.2rem", verticalAlign: "text-top" }}
            >
              <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path>
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path>
            </svg>
            Topic Context: {message.contextRef}
          </div>
        )}
      </div>
    </div>
  );
});

export default function StudentDashboard({
  apiBase,
  token,
  chatCourse,
  chatSession,
  lowPowerMode,
  devMode,
  pushActivity,
  onAuthExpired,
}) {
  const [chatMessage, setChatMessage] = useState("");
  const [chatHistory, setChatHistory] = useState([
    {
      role: "assistant",
      content:
        "Hi! I'm your OmniProf TA. How can I help you with your coursework today?",
      isNew: false,
    },
  ]);
  const [studentProgress, setStudentProgress] = useState(null);
  const [studentAchievements, setStudentAchievements] = useState([]);
  const [submissionFile, setSubmissionFile] = useState(null);
  const [dragActive, setDragActive] = useState(false);
  const [submissionStatus, setSubmissionStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [imagePayload, setImagePayload] = useState(null);
  const [studentExperienceMode, setStudentExperienceMode] =
    useState("classroom");
  const [studentTab, setStudentTab] = useState("progress");
  const [lastChatMeta, setLastChatMeta] = useState(null);
  const [chatAchievements, setChatAchievements] = useState([]);
  const [toolOutput, setToolOutput] = useState("");
  const [classAnnouncements, setClassAnnouncements] = useState([]);
  const [courseModules, setCourseModules] = useState([]);
  const [upcomingCoursework, setUpcomingCoursework] = useState([]);
  const [discussionPosts, setDiscussionPosts] = useState([]);
  const [selectedAssignmentId, setSelectedAssignmentId] = useState("");

  const chatEndRef = useRef(null);

  useEffect(() => {
    if (chatEndRef.current) {
      chatEndRef.current.scrollIntoView({
        behavior: lowPowerMode ? "auto" : "smooth",
      });
    }
  }, [chatHistory, lowPowerMode]);

  const appendMessage = (message) => {
    setChatHistory((prev) => {
      const next = prev
        .map((m) => (m.isNew ? { ...m, isNew: false } : m))
        .concat(message);
      return next.length > CHAT_HISTORY_CAP
        ? next.slice(next.length - CHAT_HISTORY_CAP)
        : next;
    });
  };

  const runStudentChat = async () => {
    if (!chatMessage.trim() && !imagePayload) return;
    const msgToSend = chatMessage;
    setChatMessage("");

    let contentToDisplay = msgToSend;
    if (imagePayload) contentToDisplay += " [Image Attached]";

    appendMessage({ role: "student", content: contentToDisplay, isNew: false });

    setBusy(true);
    try {
      const data = await StudentApi.chat(apiBase, token, {
        message: msgToSend,
        session_id: chatSession,
        course_id: chatCourse,
        image_base64: imagePayload,
      });

      if (!data.ok) {
        const detail =
          data.data?.detail || data.data?.message || "Request failed";
        const isUnauthorized = data.status === 401;
        appendMessage({
          role: "assistant",
          content: isUnauthorized
            ? "Session expired or unauthorized. Please sign in again."
            : `Request failed (${data.status}): ${detail}`,
          contextRef: "System",
          isNew: !lowPowerMode,
        });
        if (isUnauthorized && onAuthExpired) onAuthExpired();
        pushActivity({
          endpoint: "/chat",
          status: data.status,
          ok: data.ok,
          method: "POST",
        });
        return;
      }

      const meta = data.data?.metadata || {};
      const contextRef =
        data.data?.active_agent || meta.intent || "TA_Knowledge";
      setLastChatMeta({
        activeAgent: data.data?.active_agent || "unknown",
        intent: meta.intent || "unknown",
        llmProvider: meta.llm_provider || "unknown",
        cragScore: meta.crag_score,
        reducedMode: Boolean(meta.reduced_mode),
        newAchievements: meta.new_achievements_count || 0,
        cognitionUpdates: meta.cognition_updates || [],
      });
      if (Array.isArray(meta.achievements) && meta.achievements.length > 0) {
        setChatAchievements((prev) => {
          const merged = [...meta.achievements, ...prev];
          return merged.slice(0, 12);
        });
      }
      appendMessage({
        role: "assistant",
        content: data.data?.response || "Error getting response.",
        contextRef,
        isNew: !lowPowerMode,
      });
      pushActivity({
        endpoint: "/chat",
        status: data.status,
        ok: data.ok,
        method: "POST",
      });
      setImagePayload(null);
      loadStudentData();
    } catch {
      appendMessage({
        role: "assistant",
        content: "Network or server error while sending your message.",
        contextRef: "System",
        isNew: !lowPowerMode,
      });
    } finally {
      setBusy(false);
    }
  };

  const runLearningTool = async (promptText, label) => {
    if (!token || busy) return;
    appendMessage({ role: "student", content: label, isNew: false });
    setBusy(true);
    try {
      const data = await StudentApi.chat(apiBase, token, {
        message: promptText,
        session_id: chatSession,
        course_id: chatCourse,
      });
      if (!data.ok) {
        const detail =
          data.data?.detail || data.data?.message || "Request failed";
        setToolOutput(`Tool request failed (${data.status}): ${detail}`);
        appendMessage({
          role: "assistant",
          content: `Tool request failed (${data.status}): ${detail}`,
          contextRef: "System",
          isNew: !lowPowerMode,
        });
        if (data.status === 401 && onAuthExpired) onAuthExpired();
        return;
      }

      const responseText = data.data?.response || "No output generated.";
      const meta = data.data?.metadata || {};
      setToolOutput(responseText);
      setLastChatMeta({
        activeAgent: data.data?.active_agent || "unknown",
        intent: meta.intent || "unknown",
        llmProvider: meta.llm_provider || "unknown",
        cragScore: meta.crag_score,
        reducedMode: Boolean(meta.reduced_mode),
        newAchievements: meta.new_achievements_count || 0,
        cognitionUpdates: meta.cognition_updates || [],
      });
      appendMessage({
        role: "assistant",
        content: responseText,
        contextRef: data.data?.active_agent || meta.intent || "LearningTool",
        isNew: !lowPowerMode,
      });
    } finally {
      setBusy(false);
    }
  };

  const loadStudentData = async () => {
    if (!token) return;
    try {
      const [progressRes, achievementsRes, classroomRes] = await Promise.all([
        StudentApi.progress(apiBase, token, chatCourse),
        StudentApi.achievements(apiBase, token),
        StudentApi.classroomFeed(apiBase, token, chatCourse),
      ]);
      if (progressRes.ok) setStudentProgress(progressRes.data);
      if (achievementsRes.ok)
        setStudentAchievements(achievementsRes.data?.achievements || []);
      if (classroomRes.ok) {
        setClassAnnouncements(classroomRes.data?.announcements || []);
        setCourseModules(
          (classroomRes.data?.modules || []).map((m, idx) => ({
            id: m.module_name || `module_${idx}`,
            name: m.module_name || `Module ${idx + 1}`,
            done: Boolean(m.completed),
            conceptCount: m.concept_count || 0,
            visitedCount: m.visited_count || 0,
          })),
        );
        setUpcomingCoursework(
          (classroomRes.data?.coursework || []).map((c) => ({
            id: c.id,
            title: c.title,
            due: c.due_date || "n/a",
            status: c.student_status || "open",
            submissionId: c.student_submission_id || null,
          })),
        );
        setDiscussionPosts(classroomRes.data?.discussions || []);
      }
    } catch {
      // silent fail
    }
  };

  const submitAssignment = async () => {
    if (!submissionFile) return;
    setBusy(true);
    try {
      const res = await StudentApi.submitAssignment(
        apiBase,
        token,
        submissionFile,
        chatCourse,
        selectedAssignmentId,
      );
      if (res.ok) {
        setSubmissionStatus({
          status: "Submitted successfully!",
          id: res.data?.submission_id,
          state: "pending",
        });
        setSubmissionFile(null);
        setSelectedAssignmentId("");
      } else {
        setSubmissionStatus({ status: "Failed to submit." });
      }
      pushActivity({
        endpoint: "/student/submit-assignment",
        status: res.status,
        ok: res.ok,
        method: "POST",
      });
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (token) {
      loadStudentData();
    }
  }, [token, chatCourse]);

  const applySubmissionFile = (file) => {
    if (!file) return;
    setSubmissionFile(file);
  };

  const onDragEnter = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(true);
  };

  const onDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(true);
  };

  const onDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
  };

  const onDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    applySubmissionFile(e.dataTransfer?.files?.[0] || null);
  };

  const loadSubmissionDetails = async (id) => {
    if (!id) return;
    setBusy(true);
    try {
      const res = await StudentApi.submissionStatus(apiBase, token, id);
      if (res.ok) {
        setSubmissionStatus({
          status: "Status Pulled",
          id: res.data.submission_id,
          workflow: res.data.workflow_status,
          pending_approval: res.data.pending_professor_approval,
          grade: res.data.final_grade,
          transcript: res.data.transcript || [],
        });
      }
    } finally {
      setBusy(false);
    }
  };

  // SD-2: Progress Mastery as Confidence Bands
  const mastery = studentProgress?.mastery || [];
  const { low, medium, high, totalConcepts } = useMemo(() => {
    const lowCount = mastery.filter((m) => m.confidence_band === "low").length;
    const mediumCount = mastery.filter(
      (m) => m.confidence_band === "medium",
    ).length;
    const highCount = mastery.filter(
      (m) => m.confidence_band === "high",
    ).length;
    return {
      low: lowCount,
      medium: mediumCount,
      high: highCount,
      totalConcepts: Math.max(1, mastery.length),
    };
  }, [mastery]);
  const trajectory = studentProgress?.recommended_trajectory || [];
  const weakConceptNames = useMemo(() => {
    const rows = mastery.filter((m) => m.confidence_band === "low");
    return rows
      .map((m) => m.concept_name || m.concept || m.name)
      .filter(Boolean)
      .slice(0, 5);
  }, [mastery]);

  const completedModules = useMemo(
    () => courseModules.filter((m) => m.done).length,
    [courseModules],
  );

  const openCourseworkSubmission = (workId) => {
    setSelectedAssignmentId(workId || "");
    setStudentTab("defence");
  };

  return (
    <div className="student-platform-shell">
      <div className="student-experience-switch">
        <button
          className={`experience-btn ${studentExperienceMode === "classroom" ? "active" : ""}`}
          onClick={() => setStudentExperienceMode("classroom")}
        >
          Classroom Hub
        </button>
        <button
          className={`experience-btn ${studentExperienceMode === "tutor" ? "active" : ""}`}
          onClick={() => setStudentExperienceMode("tutor")}
        >
          Live Tutor
        </button>
      </div>

      <div className="dashboard-grid">
        {/* Left: Classroom Hub / Chat */}
        <div className="chat-section">
          {studentExperienceMode === "classroom" ? (
            <div className="classroom-hub">
              <div className="classroom-hero">
                <h3>{chatCourse.toUpperCase()} Classroom</h3>
                <p>
                  Course progress {completedModules}/{courseModules.length}{" "}
                  modules completed. Use hub cards to manage learning,
                  assignments, and collaboration.
                </p>
                <div className="classroom-hero-actions">
                  <button
                    className="btn-solid"
                    onClick={() => setStudentTab("defence")}
                  >
                    Open Coursework
                  </button>
                  <button
                    className="btn-solid"
                    style={{
                      background: "var(--bg-secondary)",
                      color: "var(--text-primary)",
                      border: "1px solid var(--border-light)",
                    }}
                    onClick={() => setStudentExperienceMode("tutor")}
                  >
                    Ask Live Tutor
                  </button>
                </div>
              </div>

              <div className="classroom-hub-grid">
                <div className="classroom-card">
                  <h4>Class Stream</h4>
                  {classAnnouncements.length > 0 ? (
                    classAnnouncements.map((a) => (
                      <div key={a.id} className="classroom-list-item">
                        <div className="classroom-item-top">
                          <strong>{a.title}</strong>
                          <span>
                            {a.created_at
                              ? new Date(a.created_at).toLocaleDateString()
                              : ""}
                          </span>
                        </div>
                        <p>{a.body || ""}</p>
                        <span className="classroom-tag">
                          {a.audience || "all"}
                        </span>
                      </div>
                    ))
                  ) : (
                    <p
                      className="feed-empty"
                      style={{ textAlign: "left", padding: 0 }}
                    >
                      No announcements yet.
                    </p>
                  )}
                </div>

                <div className="classroom-card">
                  <h4>Upcoming Coursework</h4>
                  {upcomingCoursework.length > 0 ? (
                    upcomingCoursework.map((work) => (
                      <div
                        key={work.id}
                        className="classroom-list-item compact"
                      >
                        <div className="classroom-item-top">
                          <strong>{work.title}</strong>
                          <span>{work.due}</span>
                        </div>
                        <div className="classroom-row-actions">
                          <span
                            className={`classroom-tag ${work.status === "submitted" || work.status === "approved" ? "ok" : "warn"}`}
                          >
                            {String(work.status || "open").replace("_", " ")}
                          </span>
                          {work.status !== "approved" &&
                            work.status !== "submitted" && (
                              <button
                                className="link-action"
                                onClick={() =>
                                  openCourseworkSubmission(work.id)
                                }
                              >
                                Open submission
                              </button>
                            )}
                        </div>
                      </div>
                    ))
                  ) : (
                    <p
                      className="feed-empty"
                      style={{ textAlign: "left", padding: 0 }}
                    >
                      No coursework published for this course.
                    </p>
                  )}
                </div>

                <div className="classroom-card">
                  <h4>Module Tracker</h4>
                  {courseModules.length > 0 ? (
                    courseModules.map((m) => (
                      <label key={m.id} className="classroom-check-item">
                        <input type="checkbox" checked={m.done} readOnly />
                        <span>
                          {m.name} ({m.visitedCount}/{m.conceptCount})
                        </span>
                      </label>
                    ))
                  ) : (
                    <p
                      className="feed-empty"
                      style={{ textAlign: "left", padding: 0 }}
                    >
                      Module progress will appear after overlays sync.
                    </p>
                  )}
                </div>

                <div className="classroom-card">
                  <h4>Discussion Board</h4>
                  {discussionPosts.length > 0 ? (
                    discussionPosts.map((post) => (
                      <div
                        key={post.id}
                        className="classroom-list-item compact"
                      >
                        <div className="classroom-item-top">
                          <strong>{post.topic}</strong>
                          <span>{post.replies} replies</span>
                        </div>
                        <p>Started by {post.author}</p>
                      </div>
                    ))
                  ) : (
                    <p
                      className="feed-empty"
                      style={{ textAlign: "left", padding: 0 }}
                    >
                      No discussions yet.
                    </p>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <>
              <div className="chat-history">
                {chatHistory.map((m, i) => (
                  <ChatMessage key={i} message={m} />
                ))}
                <div ref={chatEndRef} />
              </div>

              <div className="chat-input-container">
                <div className="chat-input-wrapper">
                  <textarea
                    value={chatMessage}
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
                    <div
                      style={{
                        position: "absolute",
                        bottom: "1rem",
                        left: "1rem",
                        backgroundColor: "var(--surface-sunken)",
                        padding: "0.2rem 0.5rem",
                        borderRadius: "4px",
                        fontSize: "0.75rem",
                        color: "var(--accent)",
                      }}
                    >
                      Image Selected
                      <button
                        style={{
                          background: "none",
                          border: "none",
                          color: "inherit",
                          marginLeft: "0.5rem",
                          cursor: "pointer",
                        }}
                        onClick={() => setImagePayload(null)}
                      >
                        X
                      </button>
                    </div>
                  )}
                  <div style={{ display: "flex", alignItems: "center" }}>
                    <label
                      className="image-upload-btn"
                      style={{
                        marginRight: "0.5rem",
                        cursor: "pointer",
                        color: "var(--text-secondary)",
                      }}
                    >
                      <svg
                        width="20"
                        height="20"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                      >
                        <rect
                          x="3"
                          y="3"
                          width="18"
                          height="18"
                          rx="2"
                          ry="2"
                        ></rect>
                        <circle cx="8.5" cy="8.5" r="1.5"></circle>
                        <polyline points="21 15 16 10 5 21"></polyline>
                      </svg>
                      <input
                        type="file"
                        accept="image/*"
                        style={{ display: "none" }}
                        onChange={(e) => {
                          const file = e.target.files?.[0];
                          if (file) {
                            const reader = new FileReader();
                            reader.onloadend = () =>
                              setImagePayload(reader.result);
                            reader.readAsDataURL(file);
                          }
                        }}
                        disabled={busy || !token}
                      />
                    </label>
                    <button
                      className="send-button"
                      onClick={runStudentChat}
                      disabled={
                        busy || (!chatMessage.trim() && !imagePayload) || !token
                      }
                    >
                      <svg viewBox="0 0 24 24">
                        <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
                      </svg>
                    </button>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Right: Widgets */}
        <div className="widgets-column">
          <div className="widget" style={{ paddingBottom: "0.75rem" }}>
            <div className="student-tabs">
              <button
                className={`student-tab-btn ${studentTab === "progress" ? "active" : ""}`}
                onClick={() => setStudentTab("progress")}
              >
                Progress
              </button>
              <button
                className={`student-tab-btn ${studentTab === "defence" ? "active" : ""}`}
                onClick={() => setStudentTab("defence")}
              >
                Defence
              </button>
              <button
                className={`student-tab-btn ${studentTab === "achievements" ? "active" : ""}`}
                onClick={() => setStudentTab("achievements")}
              >
                Gamification
              </button>
              <button
                className={`student-tab-btn ${studentTab === "insights" ? "active" : ""}`}
                onClick={() => setStudentTab("insights")}
              >
                AI Insights
              </button>
              <button
                className={`student-tab-btn ${studentTab === "tools" ? "active" : ""}`}
                onClick={() => setStudentTab("tools")}
              >
                Learning Tools
              </button>
            </div>
          </div>

          {/* SD-2: Mastery Concept Visualization */}
          {studentTab === "progress" && (
            <div className="widget">
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginBottom: "1.25rem",
                }}
              >
                <h3 style={{ margin: 0 }}>Knowledge Mastery</h3>
                <button
                  onClick={loadStudentData}
                  disabled={!token}
                  style={{
                    fontSize: "0.8rem",
                    color: "var(--accent)",
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                  }}
                >
                  Sync
                </button>
              </div>

              <p
                style={{
                  fontSize: "0.8rem",
                  color: "var(--text-tertiary)",
                  marginBottom: "1rem",
                }}
              >
                Independent progress tracking based on AI evaluation.
              </p>

              {token ? (
                <>
                  <div className="progress-list">
                    <div className="progress-item">
                      <span className="progress-label">High Confidence</span>
                      <div className="progress-track">
                        <div
                          className="progress-fill high"
                          style={{ width: `${(high / totalConcepts) * 100}%` }}
                        ></div>
                      </div>
                      {/* Purposely masking individual raw counting stats to keep student focused purely on bands as per SD-2 */}
                    </div>
                    <div className="progress-item">
                      <span className="progress-label">Med Confidence</span>
                      <div className="progress-track">
                        <div
                          className="progress-fill medium"
                          style={{
                            width: `${(medium / totalConcepts) * 100}%`,
                          }}
                        ></div>
                      </div>
                    </div>
                    <div className="progress-item">
                      <span className="progress-label">Low Confidence</span>
                      <div className="progress-track">
                        <div
                          className="progress-fill low"
                          style={{ width: `${(low / totalConcepts) * 100}%` }}
                        ></div>
                      </div>
                    </div>
                  </div>

                  {trajectory.length > 0 && (
                    <div style={{ marginTop: "1.5rem" }}>
                      <h4
                        style={{
                          fontSize: "0.85rem",
                          textTransform: "uppercase",
                          color: "var(--text-tertiary)",
                          marginBottom: "0.5rem",
                        }}
                      >
                        Recommended Trajectory
                      </h4>
                      {trajectory.map((t, idx) => (
                        <div
                          key={idx}
                          style={{
                            fontSize: "0.85rem",
                            padding: "0.5rem",
                            background: "var(--surface-sunken)",
                            marginBottom: "0.4rem",
                            borderRadius: "4px",
                            borderLeft: "3px solid var(--accent)",
                          }}
                        >
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
          )}

          {/* SD-4: Submission and Defence Interface */}
          {studentTab === "defence" && (
            <div className="widget submission-widget">
              <h3>Submission Defence</h3>
              <p
                style={{
                  fontSize: "0.8rem",
                  color: "var(--text-tertiary)",
                  marginBottom: "1rem",
                }}
              >
                Submit work and engage in an automated evaluation session.
              </p>
              {selectedAssignmentId && (
                <div
                  style={{
                    marginBottom: "0.7rem",
                    fontSize: "0.82rem",
                    color: "var(--text-secondary)",
                  }}
                >
                  Linked coursework: <strong>{selectedAssignmentId}</strong>
                </div>
              )}
              <label
                className={`file-upload-area ${dragActive ? "drag-active" : ""}`}
                onDragEnter={onDragEnter}
                onDragOver={onDragOver}
                onDragLeave={onDragLeave}
                onDrop={onDrop}
              >
                <span className="file-upload-lbl">
                  {submissionFile
                    ? submissionFile.name
                    : "Click here to attach file"}
                </span>
                <input
                  type="file"
                  onChange={(e) =>
                    applySubmissionFile(e.target.files?.[0] || null)
                  }
                />
              </label>
              <button
                className="btn-solid"
                onClick={submitAssignment}
                disabled={!submissionFile || busy || !token}
              >
                {busy ? "Submitting..." : "Turn in"}
              </button>

              {submissionStatus && submissionStatus.id && (
                <button
                  style={{
                    marginTop: "0.5rem",
                    width: "100%",
                    padding: "0.5rem",
                    border: "1px solid var(--border-light)",
                    borderRadius: "6px",
                    background: "transparent",
                    cursor: "pointer",
                    fontWeight: 600,
                  }}
                  onClick={() => loadSubmissionDetails(submissionStatus.id)}
                >
                  Check Defence Status
                </button>
              )}

              {submissionStatus && (
                <div
                  style={{
                    marginTop: "1rem",
                    fontSize: "0.85rem",
                    background: "var(--bg-secondary)",
                    padding: "0.75rem",
                    borderRadius: "6px",
                    border: "1px solid var(--border-light)",
                  }}
                >
                  <div
                    style={{
                      fontWeight: 600,
                      borderBottom: "1px solid var(--border-light)",
                      paddingBottom: "0.3rem",
                      marginBottom: "0.3rem",
                    }}
                  >
                    Status: {submissionStatus.status}
                  </div>

                  {submissionStatus.workflow && (
                    <div>Defence Action: {submissionStatus.workflow}</div>
                  )}

                  {/* Force grade hiding based on SD-4 specification - Do not show AI recommended grade without approval */}
                  {submissionStatus.pending_approval ? (
                    <div
                      style={{
                        color: "#d97706",
                        marginTop: "0.3rem",
                        fontWeight: 600,
                      }}
                    >
                      ⚠️ Scores & AI feedback hidden pending Professor approval.
                    </div>
                  ) : (
                    submissionStatus.grade && (
                      <div style={{ fontWeight: 600 }}>
                        Official Grade: {submissionStatus.grade}
                      </div>
                    )
                  )}

                  {/* Display Defence Transcript */}
                  {submissionStatus.transcript &&
                    submissionStatus.transcript.length > 0 && (
                      <div style={{ marginTop: "0.75rem" }}>
                        <div
                          style={{
                            fontWeight: 600,
                            color: "var(--text-secondary)",
                            marginBottom: "0.2rem",
                          }}
                        >
                          Your Defence Transcript:
                        </div>
                        <div
                          style={{
                            maxHeight: "120px",
                            overflowY: "auto",
                            padding: "0.5rem",
                            background: "var(--bg-primary)",
                            borderRadius: "4px",
                            border: "1px solid var(--border-light)",
                            fontSize: "0.8rem",
                          }}
                        >
                          {submissionStatus.transcript.map((t, idx) => (
                            <div key={idx} style={{ marginBottom: "0.4rem" }}>
                              <span
                                style={{
                                  fontWeight: 600,
                                  color:
                                    t.role === "assistant"
                                      ? "var(--accent)"
                                      : "inherit",
                                }}
                              >
                                {t.role === "assistant" ? "AI Eval" : "You"}
                                :{" "}
                              </span>
                              <span>{t.content}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                </div>
              )}
            </div>
          )}

          {/* SD-3: Private Achievement Feed */}
          {studentTab === "achievements" && (
            <div className="widget">
              <h3>Private Achievements</h3>
              <p
                style={{
                  fontSize: "0.8rem",
                  color: "var(--text-tertiary)",
                  marginBottom: "1rem",
                }}
              >
                Milestones earned are strictly private to you.
              </p>
              {chatAchievements.length > 0 && (
                <div
                  style={{
                    marginBottom: "1rem",
                    padding: "0.75rem",
                    background: "var(--bg-secondary)",
                    borderRadius: "6px",
                    border: "1px solid var(--border-light)",
                  }}
                >
                  <div
                    style={{
                      fontSize: "0.8rem",
                      color: "var(--text-secondary)",
                      marginBottom: "0.4rem",
                    }}
                  >
                    Latest rewards from chat flow
                  </div>
                  {chatAchievements.slice(0, 4).map((ach, idx) => (
                    <div
                      key={idx}
                      style={{ fontSize: "0.82rem", marginBottom: "0.3rem" }}
                    >
                      + {ach.name || "Milestone"}
                    </div>
                  ))}
                </div>
              )}
              {studentAchievements.length > 0 ? (
                studentAchievements.map((ach, idx) => (
                  <div
                    key={idx}
                    className="feed-item"
                    style={{ display: "flex", flexDirection: "column" }}
                  >
                    <span style={{ fontWeight: 600 }}>
                      🏆 {ach.name || "Award"}
                    </span>
                    <span
                      className="meta"
                      style={{ color: "var(--text-secondary)" }}
                    >
                      {ach.description || "Earned via mastery behavior"}
                    </span>
                    <span
                      style={{
                        fontSize: "0.7rem",
                        color: "var(--text-tertiary)",
                        marginTop: "0.2rem",
                        fontVariantNumeric: "tabular-nums",
                      }}
                    >
                      {ach.earned_at
                        ? new Date(ach.earned_at).toLocaleString()
                        : new Date().toLocaleString()}
                    </span>
                  </div>
                ))
              ) : (
                <p className="feed-empty">
                  Keep learning to earn achievements.
                </p>
              )}
            </div>
          )}

          {studentTab === "insights" && (
            <div className="widget">
              <h3>AI Orchestration Insights</h3>
              <p
                style={{
                  fontSize: "0.8rem",
                  color: "var(--text-tertiary)",
                  marginBottom: "1rem",
                }}
              >
                Live backend orchestration details from your latest chat turn.
              </p>
              {lastChatMeta ? (
                <div
                  style={{
                    display: "grid",
                    gap: "0.6rem",
                    fontSize: "0.88rem",
                  }}
                >
                  <div>
                    <strong>Active Agent:</strong> {lastChatMeta.activeAgent}
                  </div>
                  <div>
                    <strong>Intent:</strong> {lastChatMeta.intent}
                  </div>
                  <div>
                    <strong>LLM Provider:</strong> {lastChatMeta.llmProvider}
                  </div>
                  <div>
                    <strong>CRAG Score:</strong>{" "}
                    {lastChatMeta.cragScore ?? "n/a"}
                  </div>
                  <div>
                    <strong>Reduced Mode:</strong>{" "}
                    {lastChatMeta.reducedMode ? "yes" : "no"}
                  </div>
                  <div>
                    <strong>New Achievements:</strong>{" "}
                    {lastChatMeta.newAchievements}
                  </div>
                  <div>
                    <strong>Cognition Updates:</strong>{" "}
                    {(lastChatMeta.cognitionUpdates || []).length}
                  </div>
                </div>
              ) : (
                <p className="feed-empty">
                  Send a message to view orchestration traces.
                </p>
              )}
            </div>
          )}

          {studentTab === "tools" && (
            <>
              <div className="widget">
                <h3>Learning Tools</h3>
                <p
                  style={{
                    fontSize: "0.8rem",
                    color: "var(--text-tertiary)",
                    marginBottom: "1rem",
                  }}
                >
                  Use quick study actions powered by existing course knowledge
                  and TA orchestration.
                </p>

                <div className="tool-section">
                  <h4 className="tool-section-title">Quick Generators</h4>
                  <div className="tool-grid">
                    <button
                      className="btn-solid"
                      onClick={() =>
                        runLearningTool(
                          "Using course context, generate a 5-question MCQ quiz with answer key and one-line explanations.",
                          "Generate a 5-question quiz",
                        )
                      }
                      disabled={busy || !token}
                    >
                      Generate Quiz
                    </button>
                    <button
                      className="btn-solid"
                      onClick={() =>
                        runLearningTool(
                          "Create concise revision notes from course material in bullet points and include key definitions.",
                          "Generate concise revision notes",
                        )
                      }
                      disabled={busy || !token}
                    >
                      Generate Notes
                    </button>
                    <button
                      className="btn-solid"
                      onClick={() =>
                        runLearningTool(
                          "Generate 10 flashcards from course context with front and back format.",
                          "Generate flashcards",
                        )
                      }
                      disabled={busy || !token}
                    >
                      Generate Flashcards
                    </button>
                  </div>
                </div>

                <div className="tool-section">
                  <h4 className="tool-section-title">Weak Concept Drills</h4>
                  {weakConceptNames.length > 0 ? (
                    <div className="tool-grid">
                      {weakConceptNames.map((concept, idx) => (
                        <button
                          key={idx}
                          className="btn-solid"
                          style={{
                            background: "var(--bg-secondary)",
                            color: "var(--text-primary)",
                            border: "1px solid var(--border-light)",
                          }}
                          onClick={() =>
                            runLearningTool(
                              `Teach me ${concept} as a beginner, then give 2 quick practice checks.`,
                              `Drill concept: ${concept}`,
                            )
                          }
                          disabled={busy || !token}
                        >
                          Drill: {concept}
                        </button>
                      ))}
                    </div>
                  ) : (
                    <p
                      className="feed-empty"
                      style={{ textAlign: "left", padding: 0 }}
                    >
                      Sync progress first to populate weak concept drills.
                    </p>
                  )}
                </div>
              </div>

              <div className="widget">
                <h3>Tool Output</h3>
                <p
                  style={{
                    fontSize: "0.8rem",
                    color: "var(--text-tertiary)",
                    marginBottom: "0.9rem",
                  }}
                >
                  Separate output section for generated quiz, notes, flashcards,
                  and drills.
                </p>
                <div className="tool-output-box">
                  {toolOutput || "Run a tool action to view generated content."}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
