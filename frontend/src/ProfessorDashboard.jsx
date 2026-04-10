import { useState, useEffect, useMemo, useRef } from "react";
import { ProfessorApi } from "./endpoints";

export default function ProfessorDashboard({
  apiBase,
  token,
  profCourse,
  devMode,
  pushActivity,
  onAuthExpired,
}) {
  const [busy, setBusy] = useState(false);
  const [cohortOverview, setCohortOverview] = useState(null);
  const [hitlQueue, setHitlQueue] = useState([]);
  const [graphData, setGraphData] = useState(null);
  const [studentList, setStudentList] = useState([]);
  const [studentSnapshots, setStudentSnapshots] = useState([]);
  const [selectedStudent, setSelectedStudent] = useState(null);

  // Dashboard Sub-navigation
  const [activeTab, setActiveTab] = useState("command_center");
  const fileInputRef = useRef(null);

  // Store editable states for HITL items
  const [hitlEditState, setHitlEditState] = useState({});
  const [announcementDraft, setAnnouncementDraft] = useState("");
  const [classAnnouncements, setClassAnnouncements] = useState([]);
  const [assignmentDraft, setAssignmentDraft] = useState({
    title: "",
    dueDate: "",
    rubric: "Conceptual Accuracy",
    points: 20,
  });
  const [publishedAssignments, setPublishedAssignments] = useState([]);
  const [courseSubmissions, setCourseSubmissions] = useState([]);
  const [learningSequence, setLearningSequence] = useState([]);
  const [learningPathEdges, setLearningPathEdges] = useState([]);
  const [edgeDraftSource, setEdgeDraftSource] = useState("");
  const [edgeDraftTarget, setEdgeDraftTarget] = useState("");
  const [edgeDraftWeight, setEdgeDraftWeight] = useState("0.7");
  const [graphNodeFlags, setGraphNodeFlags] = useState({});
  const [graphNodeDrafts, setGraphNodeDrafts] = useState({});
  const [graphStatus, setGraphStatus] = useState("");
  const [manualGradeStatus, setManualGradeStatus] = useState("");
  const [gradeDraft, setGradeDraft] = useState({
    open: false,
    recordId: "",
    action: "approve",
    modified_grade: "",
    modified_feedback: "",
  });
  const [newConceptDraft, setNewConceptDraft] = useState({
    name: "",
    description: "",
    category: "general",
  });
  const [conceptCreateStatus, setConceptCreateStatus] = useState("");
  const [newModuleDraft, setNewModuleDraft] = useState({
    name: "",
    description: "",
    visibility: "global",
  });
  const [newTopicDraft, setNewTopicDraft] = useState({
    module_id: "",
    name: "",
    description: "",
    visibility: "global",
  });
  const [newFactDraft, setNewFactDraft] = useState({
    concept_id: "",
    name: "",
    description: "",
    visibility: "global",
  });
  const [authoringStatus, setAuthoringStatus] = useState("");
  const [graphEdgeDraft, setGraphEdgeDraft] = useState({
    source_id: "",
    target_id: "",
    relation: "REQUIRES",
    weight: "1.0",
  });
  const [graphEdgeStatus, setGraphEdgeStatus] = useState("");
  const [noteDraftByStudent, setNoteDraftByStudent] = useState({});
  const [noteHistoryByStudent, setNoteHistoryByStudent] = useState({});
  const [noteStatus, setNoteStatus] = useState("");
  const [draggingSeqIndex, setDraggingSeqIndex] = useState(null);
  const [canvasNodePositions, setCanvasNodePositions] = useState({});
  const [selectedCanvasNodes, setSelectedCanvasNodes] = useState([]);
  const [canvasSelectionMode, setCanvasSelectionMode] = useState(false);
  const [edgeUndoStack, setEdgeUndoStack] = useState([]);
  const [edgeRedoStack, setEdgeRedoStack] = useState([]);
  const [draggedCanvasNodeId, setDraggedCanvasNodeId] = useState("");
  const relationshipSvgRef = useRef(null);
  const relationshipLayoutStorageKey = useMemo(
    () => `omniprof_relationship_canvas_${String(profCourse || "").trim() || "default"}`,
    [profCourse],
  );

  const handleAuthFailure = (res) => {
    if (res?.status === 401 && onAuthExpired) {
      onAuthExpired();
      return true;
    }
    return false;
  };

  const normalizeTranscript = (value) => {
    if (Array.isArray(value)) return value;
    if (typeof value === "string") {
      const trimmed = value.trim();
      if (!trimmed) return [];
      try {
        const parsed = JSON.parse(trimmed);
        if (Array.isArray(parsed)) return parsed;
      } catch {
        // keep as single-line fallback
      }
      return [{ role: "assistant", content: trimmed }];
    }
    if (value && typeof value === "object") {
      return [value];
    }
    return [];
  };

  const getHitlSdi = (item) => {
    const value = item?.integrity?.sdi ?? item?.sdi;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  };

  const loadProfessorData = async () => {
    setBusy(true);
    try {
      const [overviewRes, queueRes] = await Promise.all([
        ProfessorApi.cohortOverview(apiBase, token, profCourse, 7, {
          forceRefresh: true,
        }),
        ProfessorApi.hitlQueue(apiBase, token, { forceRefresh: true }),
      ]);
      if (handleAuthFailure(overviewRes) || handleAuthFailure(queueRes)) return;
      if (overviewRes.ok) setCohortOverview(overviewRes.data);
      if (queueRes.ok) {
        // PD-6: Sort queue to float Anomalous Input (SDI > 85%) to the very top.
        const items = (queueRes.data?.items || []).map((item) => ({
          ...item,
          transcript: normalizeTranscript(item?.transcript),
        }));
        items.sort((a, b) => {
          const aSdi = getHitlSdi(a) ?? 0;
          const bSdi = getHitlSdi(b) ?? 0;
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
            ai_feedback: item.ai_feedback,
          };
        }
        setHitlEditState(initialEdit);
      }
    } finally {
      setBusy(false);
    }
  };

  const hydrateGraphData = (payload) => {
    const data = payload || {};
    setGraphData(data);
    const nextFlags = {};
    const nextDrafts = {};
    for (const node of data.nodes || []) {
      if (node.level !== "CONCEPT") continue;
      nextFlags[node.id] = {
        highPriority: String(node.priority || "normal").toLowerCase() === "high",
        outOfScope: String(node.visibility || "global").toLowerCase() === "professor-only",
      };
      nextDrafts[node.id] = {
        name: node.label || "",
        description: node.description || "",
      };
    }
    setGraphNodeFlags(nextFlags);
    setGraphNodeDrafts(nextDrafts);
  };

  useEffect(() => {
    if (token) {
      loadProfessorData();
      loadCommandCenterData();
      loadLearningPathData();
    }
  }, [token, profCourse]);

  useEffect(() => {
    if (
      (activeTab === "students" || activeTab === "command_center") &&
      token &&
      studentList.length === 0 &&
      studentSnapshots.length === 0
    ) {
      loadStudentWiseData();
    }
  }, [activeTab, token, studentList.length, studentSnapshots.length]);

  useEffect(() => {
    if (activeTab === "command_center" && token) {
      loadCommandCenterData();
    }
  }, [activeTab, token, profCourse]);

  useEffect(() => {
    if (!token) return;
    if (activeTab !== "graph" && activeTab !== "learning_path") return;
    if (graphData) return;

    ProfessorApi.graphVisualization(apiBase, token, profCourse).then((res) => {
      if (handleAuthFailure(res)) return;
      if (res.ok) hydrateGraphData(res.data);
    });
  }, [activeTab, token, apiBase, profCourse, graphData]);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(relationshipLayoutStorageKey);
      if (!raw) {
        setCanvasNodePositions({});
        return;
      }
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object") {
        setCanvasNodePositions(parsed);
      }
    } catch {
      setCanvasNodePositions({});
    }
  }, [relationshipLayoutStorageKey]);

  useEffect(() => {
    try {
      localStorage.setItem(
        relationshipLayoutStorageKey,
        JSON.stringify(canvasNodePositions || {}),
      );
    } catch {
      // Ignore localStorage quota/serialization failures in authoring UX.
    }
  }, [canvasNodePositions, relationshipLayoutStorageKey]);

  const handleHitlAction = async (queueId, action) => {
    setBusy(true);
    try {
      const payload = { action, ...hitlEditState[queueId] };
      const res = await ProfessorApi.hitlAction(
        apiBase,
        token,
        queueId,
        payload,
      );
      if (handleAuthFailure(res)) return;
      pushActivity({
        endpoint: `/professor/hitl-queue/${queueId}/action`,
        status: res.status,
        ok: res.ok,
        method: "POST",
      });
      if (res.ok) {
        loadProfessorData();
      }
    } finally {
      setBusy(false);
    }
  };

  const handleEditChange = (queueId, field, value) => {
    setHitlEditState((prev) => ({
      ...prev,
      [queueId]: {
        ...prev[queueId],
        [field]: value,
      },
    }));
  };

  const toStudentId = (row) =>
    String(
      row?.student_id ||
        row?.user_id ||
        row?.id ||
        row?.username ||
        row?.name ||
        "",
    ).trim();

  const toNumber = (value, fallback = 0) => {
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
  };

  const loadStudentWiseData = async () => {
    setBusy(true);
    try {
      const [studentsRes, cohortRes] = await Promise.all([
        ProfessorApi.students(apiBase, token, { forceRefresh: true }),
        ProfessorApi.cohort(apiBase, token, profCourse, {
          forceRefresh: true,
        }),
      ]);
      if (handleAuthFailure(studentsRes) || handleAuthFailure(cohortRes)) return;

      if (studentsRes.ok) {
        setStudentList(studentsRes.data?.students || []);
      }

      if (cohortRes.ok) {
        const cohortStudents =
          cohortRes.data?.students ||
          cohortRes.data?.student_stats ||
          cohortRes.data?.items ||
          [];
        setStudentSnapshots(
          Array.isArray(cohortStudents) ? cohortStudents : [],
        );
      }

      pushActivity({
        endpoint: "/professor/students",
        status: studentsRes.status,
        ok: studentsRes.ok,
        method: "GET",
      });
      pushActivity({
        endpoint: `/professor/cohort?course_id=${profCourse}`,
        status: cohortRes.status,
        ok: cohortRes.ok,
        method: "GET",
      });
    } finally {
      setBusy(false);
    }
  };

  const loadCommandCenterData = async () => {
    if (!token) return;
    setBusy(true);
    try {
      const [annRes, cwRes, subRes] = await Promise.all([
        ProfessorApi.announcements(apiBase, token, profCourse, {
          forceRefresh: true,
        }),
        ProfessorApi.coursework(apiBase, token, profCourse, {
          forceRefresh: true,
        }),
        ProfessorApi.submissions(apiBase, token, profCourse, {
          forceRefresh: true,
        }),
      ]);
      if (handleAuthFailure(annRes) || handleAuthFailure(cwRes) || handleAuthFailure(subRes)) return;
      if (annRes.ok) setClassAnnouncements(annRes.data?.items || []);
      if (cwRes.ok) setPublishedAssignments(cwRes.data?.items || []);
      if (subRes.ok) setCourseSubmissions(subRes.data?.items || []);
    } finally {
      setBusy(false);
    }
  };

  const loadLearningPathData = async () => {
    if (!token) return;
    setBusy(true);
    try {
      const [res, graphRes] = await Promise.all([
        ProfessorApi.loadLearningPath(apiBase, token, profCourse, {
          forceRefresh: true,
        }),
        ProfessorApi.graphVisualization(apiBase, token, profCourse, {
          forceRefresh: true,
        }),
      ]);
      if (handleAuthFailure(res) || handleAuthFailure(graphRes)) return;

      if (!graphRes.ok) {
        setGraphStatus(`Failed to load graph (${graphRes.status}).`);
        return;
      }

      hydrateGraphData(graphRes.data);
      const conceptIds = new Set(
        (graphRes.data?.nodes || [])
          .filter((n) => n.level === "CONCEPT")
          .map((n) => n.id),
      );

      if (!res.ok) {
        setGraphStatus(`Failed to load learning path (${res.status}).`);
        return;
      }

      const orderedRaw = Array.isArray(res.data?.ordered_concept_ids)
        ? res.data.ordered_concept_ids
        : [];
      const filtered = orderedRaw.filter((id) => conceptIds.has(id));
      const partialRaw = Array.isArray(res.data?.partial_order_edges)
        ? res.data.partial_order_edges
        : [];
      const partialFiltered = partialRaw
        .map((edge) => ({
          source_id: String(edge?.source_id || "").trim(),
          target_id: String(edge?.target_id || "").trim(),
          weight: Number(edge?.weight ?? 0.7),
        }))
        .filter(
          (edge) =>
            edge.source_id &&
            edge.target_id &&
            conceptIds.has(edge.source_id) &&
            conceptIds.has(edge.target_id),
        )
        .map((edge) => ({
          ...edge,
          weight: Number.isFinite(edge.weight)
            ? Math.min(2, Math.max(0.1, edge.weight))
            : 0.7,
        }));
      const removedCount = orderedRaw.length - filtered.length;
      setLearningSequence(filtered);
      setLearningPathEdges(partialFiltered);
      setGraphStatus(
        removedCount > 0
          ? `Learning path loaded. Removed ${removedCount} stale concept id(s).`
          : `Learning path loaded (${filtered.length} concepts).`,
      );
    } finally {
      setBusy(false);
    }
  };

  const publishLearningPath = async () => {
    if (!token) return;

    const sequenceEdges = [];
    for (let i = 0; i < learningSequence.length - 1; i += 1) {
      sequenceEdges.push({
        source_id: learningSequence[i],
        target_id: learningSequence[i + 1],
      });
    }
    const combinedEdges = [
      ...sequenceEdges,
      ...learningPathEdges.map((edge) => ({
        source_id: edge.source_id,
        target_id: edge.target_id,
      })),
    ];

    const adjacency = {};
    for (const edge of combinedEdges) {
      if (!edge.source_id || !edge.target_id) continue;
      if (edge.source_id === edge.target_id) {
        setGraphStatus("Cannot publish learning path: self-referential dependency found.");
        return;
      }
      if (!adjacency[edge.source_id]) adjacency[edge.source_id] = [];
      adjacency[edge.source_id].push(edge.target_id);
    }

    const visited = new Set();
    const inStack = new Set();
    const stack = [];
    let cyclePath = null;

    const dfs = (node) => {
      visited.add(node);
      inStack.add(node);
      stack.push(node);
      for (const next of adjacency[node] || []) {
        if (cyclePath) return;
        if (!visited.has(next)) {
          dfs(next);
          continue;
        }
        if (inStack.has(next)) {
          const idx = stack.indexOf(next);
          cyclePath = [...stack.slice(idx), next];
          return;
        }
      }
      stack.pop();
      inStack.delete(node);
    };

    Object.keys(adjacency).forEach((node) => {
      if (!visited.has(node) && !cyclePath) dfs(node);
    });

    if (cyclePath) {
      const labels = cyclePath.map((id) => learningConceptLabelById[id] || id);
      setGraphStatus(`Cannot publish learning path: dependency cycle detected (${labels.join(" -> ")}).`);
      return;
    }

    setBusy(true);
    const payload = {
      course_id: profCourse,
      ordered_concept_ids: learningSequence,
      partial_order_edges: learningPathEdges,
    };
    try {
      const res = await ProfessorApi.saveLearningPath(apiBase, token, payload);
      if (handleAuthFailure(res)) return;
      if (res.ok) {
        setGraphStatus(`Learning path published (${learningSequence.length} concepts).`);
      } else {
        setGraphStatus(
          `Failed to publish learning path (${res.status}): ${res.data?.detail || res.data?.message || "Unknown error"}`,
        );
      }
    } finally {
      setBusy(false);
    }
  };

  const moveLearningNode = (fromIndex, toIndex) => {
    if (fromIndex === null || toIndex === null || fromIndex === toIndex) return;
    setLearningSequence((prev) => {
      if (
        fromIndex < 0 ||
        toIndex < 0 ||
        fromIndex >= prev.length ||
        toIndex >= prev.length
      ) {
        return prev;
      }
      const next = [...prev];
      const [dragged] = next.splice(fromIndex, 1);
      next.splice(toIndex, 0, dragged);
      return next;
    });
  };

  const addConceptToLearningPath = (conceptId) => {
    if (!conceptId) return;
    setLearningSequence((prev) => (prev.includes(conceptId) ? prev : [...prev, conceptId]));
  };

  const removeConceptFromLearningPath = (conceptId) => {
    setLearningSequence((prev) => prev.filter((id) => id !== conceptId));
    setLearningPathEdges((prev) =>
      prev.filter(
        (edge) => edge.source_id !== conceptId && edge.target_id !== conceptId,
      ),
    );
  };

  const addLearningPathEdge = () => {
    const source_id = String(edgeDraftSource || "").trim();
    const target_id = String(edgeDraftTarget || "").trim();
    const weight = Number(edgeDraftWeight || "0.7");

    if (!source_id || !target_id) {
      setGraphStatus("Select both source and target concepts before adding dependency.");
      return;
    }
    if (source_id === target_id) {
      setGraphStatus("Dependency source and target cannot be the same concept.");
      return;
    }
    if (
      learningPathEdges.some(
        (edge) => edge.source_id === source_id && edge.target_id === target_id,
      )
    ) {
      setGraphStatus("Dependency already exists in this learning path.");
      return;
    }

    setLearningPathEdges((prev) => [
      ...prev,
      {
        source_id,
        target_id,
        weight: Number.isFinite(weight) ? Math.min(2, Math.max(0.1, weight)) : 0.7,
      },
    ]);
    setGraphStatus("Dependency added. Publish to persist.");
  };

  const removeLearningPathEdge = (sourceId, targetId) => {
    setLearningPathEdges((prev) =>
      prev.filter(
        (edge) => !(edge.source_id === sourceId && edge.target_id === targetId),
      ),
    );
  };

  const openManualGrade = (submission) => {
    setManualGradeStatus("");
    setGradeDraft({
      open: true,
      recordId: String(submission?.submission_id || "").trim(),
      action: "approve",
      modified_grade:
        submission?.final_grade !== null && submission?.final_grade !== undefined
          ? String(submission.final_grade)
          : "",
      modified_feedback: "",
    });
  };

  const submitManualGrade = async () => {
    if (!gradeDraft.recordId) {
      setManualGradeStatus("Missing submission identifier.");
      return;
    }
    setBusy(true);
    setManualGradeStatus("");
    try {
      const payload = {
        record_id: gradeDraft.recordId,
        action: gradeDraft.action,
        modified_grade:
          gradeDraft.action === "approve" && gradeDraft.modified_grade !== ""
            ? Number(gradeDraft.modified_grade)
            : null,
        modified_feedback: String(gradeDraft.modified_feedback || "").trim(),
      };
      const res = await ProfessorApi.gradeSubmission(apiBase, token, payload);
      if (handleAuthFailure(res)) return;
      if (res.ok) {
        setManualGradeStatus("Manual grading action saved.");
        setGradeDraft((prev) => ({ ...prev, open: false }));
        await loadCommandCenterData();
        await loadProfessorData();
      } else {
        setManualGradeStatus(
          `Manual grading failed (${res.status}): ${res.data?.detail || res.data?.message || "Unknown error"}`,
        );
      }
    } finally {
      setBusy(false);
    }
  };

  const createGraphConcept = async () => {
    if (!token) return;
    const name = String(newConceptDraft.name || "").trim();
    if (!name) {
      setConceptCreateStatus("Concept name is required.");
      return;
    }

    setBusy(true);
    setConceptCreateStatus("");
    try {
      const res = await ProfessorApi.createConcept(apiBase, token, {
        name,
        description: String(newConceptDraft.description || "").trim(),
        category: String(newConceptDraft.category || "general").trim(),
        course_id: profCourse,
      });
      if (handleAuthFailure(res)) return;
      if (!res.ok) {
        setConceptCreateStatus(
          `Create concept failed (${res.status}): ${res.data?.detail || res.data?.message || "Unknown error"}`,
        );
        return;
      }

      setNewConceptDraft({ name: "", description: "", category: "general" });
      setConceptCreateStatus("Concept created. Refreshing graph map...");
      const graphRes = await ProfessorApi.graphVisualization(
        apiBase,
        token,
        profCourse,
        { forceRefresh: true },
      );
      if (handleAuthFailure(graphRes)) return;
      if (graphRes.ok) {
        hydrateGraphData(graphRes.data);
        setConceptCreateStatus("Concept created and graph map refreshed.");
      }
    } finally {
      setBusy(false);
    }
  };

  const refreshGraphMap = async () => {
    const graphRes = await ProfessorApi.graphVisualization(
      apiBase,
      token,
      profCourse,
      { forceRefresh: true },
    );
    if (handleAuthFailure(graphRes)) return false;
    if (graphRes.ok) {
      hydrateGraphData(graphRes.data);
      return true;
    }
    return false;
  };

  const normalizeEdgePayload = (payload) => {
    const source_id = String(payload?.source_id || "").trim();
    const target_id = String(payload?.target_id || "").trim();
    const relation = String(payload?.relation || "REQUIRES").trim().toUpperCase();
    const weightVal = Number(payload?.weight ?? 1);
    const weight = Number.isFinite(weightVal) ? Math.min(3, Math.max(0.1, weightVal)) : 1;
    return { source_id, target_id, relation, weight };
  };

  const appendEdgeHistory = (entry) => {
    if (!entry) return;
    setEdgeUndoStack((prev) => [...prev, entry].slice(-40));
    setEdgeRedoStack([]);
  };

  const createGraphEdgeInternal = async (payload, { recordHistory = true, refresh = true } = {}) => {
    const normalized = normalizeEdgePayload(payload);
    const res = await ProfessorApi.createGraphEdge(apiBase, token, normalized);
    if (handleAuthFailure(res)) return { ok: false, cancelled: true };
    if (!res.ok) {
      return {
        ok: false,
        message: `Create edge failed (${res.status}): ${res.data?.detail || res.data?.message || "Unknown error"}`,
      };
    }

    if (recordHistory) {
      appendEdgeHistory({
        undo: [
          {
            type: "delete",
            payload: {
              source_id: normalized.source_id,
              target_id: normalized.target_id,
              relation: normalized.relation,
            },
          },
        ],
        redo: [{ type: "create", payload: normalized }],
      });
    }

    if (refresh) await refreshGraphMap();
    return { ok: true };
  };

  const deleteGraphEdgeInternal = async (payload, { recordHistory = true, refresh = true } = {}) => {
    const normalized = normalizeEdgePayload(payload);
    const deletePayload = {
      source_id: normalized.source_id,
      target_id: normalized.target_id,
      relation: normalized.relation,
    };
    const res = await ProfessorApi.deleteGraphEdge(apiBase, token, deletePayload);
    if (handleAuthFailure(res)) return { ok: false, cancelled: true };
    if (!res.ok) {
      return {
        ok: false,
        message: `Delete edge failed (${res.status}): ${res.data?.detail || res.data?.message || "Unknown error"}`,
      };
    }

    if (recordHistory) {
      appendEdgeHistory({
        undo: [{ type: "create", payload: normalized }],
        redo: [{ type: "delete", payload: deletePayload }],
      });
    }

    if (refresh) await refreshGraphMap();
    return { ok: true };
  };

  const executeEdgeActions = async (actions) => {
    for (const action of actions || []) {
      if (!action?.type || !action?.payload) continue;
      if (action.type === "create") {
        const res = await ProfessorApi.createGraphEdge(apiBase, token, normalizeEdgePayload(action.payload));
        if (handleAuthFailure(res)) return false;
        if (!res.ok) return false;
      } else if (action.type === "delete") {
        const normalized = normalizeEdgePayload(action.payload);
        const res = await ProfessorApi.deleteGraphEdge(apiBase, token, {
          source_id: normalized.source_id,
          target_id: normalized.target_id,
          relation: normalized.relation,
        });
        if (handleAuthFailure(res)) return false;
        if (!res.ok) return false;
      }
    }
    return true;
  };

  const undoLastEdgeChange = async () => {
    if (!edgeUndoStack.length || !token) return;
    const entry = edgeUndoStack[edgeUndoStack.length - 1];
    setBusy(true);
    try {
      const ok = await executeEdgeActions(entry.undo);
      if (!ok) {
        setGraphEdgeStatus("Undo failed due to API error.");
        return;
      }
      setEdgeUndoStack((prev) => prev.slice(0, -1));
      setEdgeRedoStack((prev) => [...prev, entry].slice(-40));
      await refreshGraphMap();
      setGraphEdgeStatus("Undid latest edge mutation.");
    } finally {
      setBusy(false);
    }
  };

  const redoLastEdgeChange = async () => {
    if (!edgeRedoStack.length || !token) return;
    const entry = edgeRedoStack[edgeRedoStack.length - 1];
    setBusy(true);
    try {
      const ok = await executeEdgeActions(entry.redo);
      if (!ok) {
        setGraphEdgeStatus("Redo failed due to API error.");
        return;
      }
      setEdgeRedoStack((prev) => prev.slice(0, -1));
      setEdgeUndoStack((prev) => [...prev, entry].slice(-40));
      await refreshGraphMap();
      setGraphEdgeStatus("Re-applied edge mutation.");
    } finally {
      setBusy(false);
    }
  };

  const createBulkEdgesFromSelection = async () => {
    if (!token) return;
    if (selectedCanvasNodes.length < 2) {
      setGraphEdgeStatus("Select at least two nodes for bulk edge creation.");
      return;
    }

    const relation = String(graphEdgeDraft.relation || "REQUIRES").trim().toUpperCase();
    const weight = Number(graphEdgeDraft.weight || "1.0");
    const byId = {};
    relationshipCanvas.nodes.forEach((node) => {
      byId[node.id] = node;
    });
    const orderedIds = [...selectedCanvasNodes].sort((a, b) => {
      const ax = byId[a]?.x ?? 0;
      const bx = byId[b]?.x ?? 0;
      return ax - bx;
    });

    if (orderedIds.length < 2) {
      setGraphEdgeStatus("Unable to resolve selected node order for bulk create.");
      return;
    }

    setBusy(true);
    try {
      let successCount = 0;
      const undo = [];
      const redo = [];

      for (let i = 0; i < orderedIds.length - 1; i += 1) {
        const payload = normalizeEdgePayload({
          source_id: orderedIds[i],
          target_id: orderedIds[i + 1],
          relation,
          weight,
        });
        const res = await ProfessorApi.createGraphEdge(apiBase, token, payload);
        if (handleAuthFailure(res)) return;
        if (res.ok) {
          successCount += 1;
          undo.push({
            type: "delete",
            payload: {
              source_id: payload.source_id,
              target_id: payload.target_id,
              relation: payload.relation,
            },
          });
          redo.push({ type: "create", payload });
        }
      }

      if (successCount > 0) {
        appendEdgeHistory({ undo, redo });
        await refreshGraphMap();
        setGraphEdgeStatus(`Bulk create completed: ${successCount} edge(s) added.`);
      } else {
        setGraphEdgeStatus("Bulk create completed with no new edges.");
      }
    } finally {
      setBusy(false);
    }
  };

  const deleteBulkEdgesFromSelection = async () => {
    if (!token) return;
    if (selectedCanvasNodes.length < 2) {
      setGraphEdgeStatus("Select at least two nodes for bulk edge delete.");
      return;
    }

    const relation = String(graphEdgeDraft.relation || "REQUIRES").trim().toUpperCase();
    const selected = new Set(selectedCanvasNodes);
    const candidates = conceptualGraphEdges.filter(
      (edge) => edge.relation === relation && selected.has(edge.source) && selected.has(edge.target),
    );

    if (!candidates.length) {
      setGraphEdgeStatus(`No ${relation} edges found between selected nodes.`);
      return;
    }

    setBusy(true);
    try {
      let successCount = 0;
      const undo = [];
      const redo = [];
      for (const edge of candidates) {
        const deletePayload = {
          source_id: edge.source,
          target_id: edge.target,
          relation: edge.relation,
        };
        const res = await ProfessorApi.deleteGraphEdge(apiBase, token, deletePayload);
        if (handleAuthFailure(res)) return;
        if (res.ok) {
          successCount += 1;
          undo.push({
            type: "create",
            payload: normalizeEdgePayload({
              source_id: edge.source,
              target_id: edge.target,
              relation: edge.relation,
              weight: edge.weight,
            }),
          });
          redo.push({ type: "delete", payload: deletePayload });
        }
      }

      if (successCount > 0) {
        appendEdgeHistory({ undo, redo });
        await refreshGraphMap();
        setGraphEdgeStatus(`Bulk delete completed: ${successCount} edge(s) removed.`);
      } else {
        setGraphEdgeStatus("Bulk delete completed with no changes.");
      }
    } finally {
      setBusy(false);
    }
  };

  const createGraphModule = async () => {
    const name = String(newModuleDraft.name || "").trim();
    if (!name) {
      setAuthoringStatus("Module name is required.");
      return;
    }
    setBusy(true);
    setAuthoringStatus("");
    try {
      const res = await ProfessorApi.createModule(apiBase, token, {
        course_id: profCourse,
        name,
        description: String(newModuleDraft.description || "").trim(),
        visibility: newModuleDraft.visibility || "global",
      });
      if (handleAuthFailure(res)) return;
      if (!res.ok) {
        setAuthoringStatus(
          `Create module failed (${res.status}): ${res.data?.detail || res.data?.message || "Unknown error"}`,
        );
        return;
      }
      setNewModuleDraft({ name: "", description: "", visibility: "global" });
      const ok = await refreshGraphMap();
      setAuthoringStatus(ok ? "Module created." : "Module created; graph refresh failed.");
    } finally {
      setBusy(false);
    }
  };

  const createGraphTopic = async () => {
    const module_id = String(newTopicDraft.module_id || "").trim();
    const name = String(newTopicDraft.name || "").trim();
    if (!module_id || !name) {
      setAuthoringStatus("Topic requires module and name.");
      return;
    }
    setBusy(true);
    setAuthoringStatus("");
    try {
      const res = await ProfessorApi.createTopic(apiBase, token, {
        module_id,
        name,
        description: String(newTopicDraft.description || "").trim(),
        visibility: newTopicDraft.visibility || "global",
      });
      if (handleAuthFailure(res)) return;
      if (!res.ok) {
        setAuthoringStatus(
          `Create topic failed (${res.status}): ${res.data?.detail || res.data?.message || "Unknown error"}`,
        );
        return;
      }
      setNewTopicDraft({ module_id: "", name: "", description: "", visibility: "global" });
      const ok = await refreshGraphMap();
      setAuthoringStatus(ok ? "Topic created." : "Topic created; graph refresh failed.");
    } finally {
      setBusy(false);
    }
  };

  const createGraphFact = async () => {
    const concept_id = String(newFactDraft.concept_id || "").trim();
    const name = String(newFactDraft.name || "").trim();
    if (!concept_id || !name) {
      setAuthoringStatus("Fact requires concept and name.");
      return;
    }
    setBusy(true);
    setAuthoringStatus("");
    try {
      const res = await ProfessorApi.createFact(apiBase, token, {
        concept_id,
        name,
        description: String(newFactDraft.description || "").trim(),
        visibility: newFactDraft.visibility || "global",
      });
      if (handleAuthFailure(res)) return;
      if (!res.ok) {
        setAuthoringStatus(
          `Create fact failed (${res.status}): ${res.data?.detail || res.data?.message || "Unknown error"}`,
        );
        return;
      }
      setNewFactDraft({ concept_id: "", name: "", description: "", visibility: "global" });
      const ok = await refreshGraphMap();
      setAuthoringStatus(ok ? "Fact created." : "Fact created; graph refresh failed.");
    } finally {
      setBusy(false);
    }
  };

  const createGraphEdge = async () => {
    if (!token) return;
    const source_id = String(graphEdgeDraft.source_id || "").trim();
    const target_id = String(graphEdgeDraft.target_id || "").trim();

    if (!source_id || !target_id) {
      setGraphEdgeStatus("Select both source and target concepts.");
      return;
    }
    if (source_id === target_id) {
      setGraphEdgeStatus("Source and target must be different concepts.");
      return;
    }

    setBusy(true);
    setGraphEdgeStatus("");
    try {
      const result = await createGraphEdgeInternal(
        {
          source_id,
          target_id,
          relation: graphEdgeDraft.relation,
          weight: graphEdgeDraft.weight,
        },
        { recordHistory: true, refresh: true },
      );
      if (result.cancelled) return;
      if (!result.ok) {
        setGraphEdgeStatus(result.message || "Create edge failed.");
        return;
      }
      setGraphEdgeStatus("Edge saved and graph map refreshed.");
    } finally {
      setBusy(false);
    }
  };

  const deleteGraphEdge = async (edge) => {
    if (!token || !edge) return;
    setBusy(true);
    setGraphEdgeStatus("");
    try {
      const result = await deleteGraphEdgeInternal(
        {
          source_id: edge.source,
          target_id: edge.target,
          relation: edge.relation,
          weight: edge.weight,
        },
        { recordHistory: true, refresh: true },
      );
      if (result.cancelled) return;
      if (!result.ok) {
        setGraphEdgeStatus(result.message || "Delete edge failed.");
        return;
      }
      setGraphEdgeStatus("Edge deleted.");
    } finally {
      setBusy(false);
    }
  };

  const handleGraphDraftChange = (nodeId, field, value) => {
    setGraphNodeDrafts((prev) => ({
      ...prev,
      [nodeId]: {
        ...(prev[nodeId] || {}),
        [field]: value,
      },
    }));
  };

  const saveGraphConceptDraft = async (nodeId) => {
    const draft = graphNodeDrafts[nodeId] || {};
    const payload = {
      name: String(draft.name || "").trim(),
      description: String(draft.description || "").trim(),
    };
    const res = await ProfessorApi.updateConcept(apiBase, token, nodeId, payload);
    if (handleAuthFailure(res)) return;
    if (!res.ok) {
      setGraphStatus(`Failed to update concept (${res.status}).`);
      return;
    }

    setGraphStatus("Concept content updated.");
    setGraphData((prev) => {
      if (!prev?.nodes) return prev;
      return {
        ...prev,
        nodes: prev.nodes.map((n) =>
          n.id === nodeId
            ? { ...n, label: payload.name || n.label, description: payload.description }
            : n,
        ),
      };
    });
  };

  const publishAnnouncement = () => {
    const text = announcementDraft.trim();
    if (!text) return;
    setBusy(true);
    ProfessorApi.createAnnouncement(apiBase, token, {
      course_id: profCourse,
      title: text,
      body: text,
      audience: "all",
    })
      .then((res) => {
        if (handleAuthFailure(res)) return;
        if (res.ok) {
          setAnnouncementDraft("");
          loadCommandCenterData();
        }
      })
      .finally(() => setBusy(false));
  };

  const publishAssignmentDraft = () => {
    if (!assignmentDraft.title.trim() || !assignmentDraft.dueDate) return;
    setBusy(true);
    ProfessorApi.createCoursework(apiBase, token, {
      course_id: profCourse,
      title: assignmentDraft.title.trim(),
      description: `${assignmentDraft.rubric} | ${assignmentDraft.points} points`,
      due_date: assignmentDraft.dueDate,
      max_points: assignmentDraft.points,
      rubric: assignmentDraft.rubric,
    })
      .then((res) => {
        if (handleAuthFailure(res)) return;
        if (res.ok) {
          setAssignmentDraft((prev) => ({
            ...prev,
            title: "",
            dueDate: "",
            points: prev.points,
            rubric: prev.rubric,
          }));
          loadCommandCenterData();
        }
      })
      .finally(() => setBusy(false));
  };

  const studentWiseRows = useMemo(() => {
    const inactiveSet = new Set(
      (cohortOverview?.inactive_students || []).map((s) => String(s)),
    );
    const pendingByStudent = {};
    for (const q of hitlQueue) {
      const sid = toStudentId(q);
      if (!sid) continue;
      pendingByStudent[sid] = (pendingByStudent[sid] || 0) + 1;
    }

    const snapshotMap = {};
    for (const row of studentSnapshots) {
      const sid = toStudentId(row);
      if (!sid) continue;
      snapshotMap[sid] = row;
    }

    const rosterMap = {};
    for (const row of studentList) {
      const sid = toStudentId(row);
      if (!sid) continue;
      rosterMap[sid] = row;
    }

    const ids = new Set([
      ...Object.keys(snapshotMap),
      ...Object.keys(rosterMap),
      ...Object.keys(pendingByStudent),
    ]);

    const rows = [...ids].map((id) => {
      const roster = rosterMap[id] || {};
      const snapshot = snapshotMap[id] || {};
      const mastery = toNumber(
        snapshot.average_mastery ?? snapshot.mastery ?? snapshot.mastery_pct,
        null,
      );
      const lowConfidence = toNumber(
        snapshot.low_confidence_count ??
          snapshot.low_count ??
          snapshot.struggling_count,
        0,
      );
      const activityCount = toNumber(
        snapshot.interactions ?? snapshot.turns ?? snapshot.activity_count,
        0,
      );
      const riskConcepts =
        snapshot.at_risk_concepts || snapshot.struggling_concepts || [];

      return {
        id,
        name: roster.name || roster.full_name || snapshot.name || id,
        email: roster.email || snapshot.email || "N/A",
        mastery,
        lowConfidence,
        activityCount,
        pendingHitl: pendingByStudent[id] || 0,
        inactive: inactiveSet.has(id),
        lastActive: snapshot.last_active_at || snapshot.last_active || "n/a",
        riskConcepts: Array.isArray(riskConcepts) ? riskConcepts : [],
      };
    });

    rows.sort((a, b) => {
      if (b.pendingHitl !== a.pendingHitl) return b.pendingHitl - a.pendingHitl;
      if (b.lowConfidence !== a.lowConfidence)
        return b.lowConfidence - a.lowConfidence;
      return String(a.name).localeCompare(String(b.name));
    });

    return rows;
  }, [studentList, studentSnapshots, cohortOverview, hitlQueue]);

  const selectedStudentDetails = useMemo(() => {
    if (!selectedStudent) return null;
    const selectedId = toStudentId(selectedStudent);
    return studentWiseRows.find((row) => row.id === selectedId) || null;
  }, [selectedStudent, studentWiseRows]);

  const interventionCandidates = useMemo(() => {
    return studentWiseRows
      .filter(
        (row) => row.lowConfidence > 0 || row.pendingHitl > 0 || row.inactive,
      )
      .slice(0, 6);
  }, [studentWiseRows]);

  const availableLearningConcepts = useMemo(() => {
    const nodes = graphData?.nodes || [];
    const concepts = nodes.filter((n) => n.level === "CONCEPT");
    return concepts.filter((c) => !learningSequence.includes(c.id));
  }, [graphData, learningSequence]);

  const learningConceptLabelById = useMemo(() => {
    const map = {};
    for (const node of graphData?.nodes || []) {
      if (node.level !== "CONCEPT") continue;
      map[node.id] = node.label || node.name || node.id;
    }
    return map;
  }, [graphData]);

  const learningConceptOptions = useMemo(
    () =>
      (graphData?.nodes || []).filter((n) => n.level === "CONCEPT"),
    [graphData],
  );

  const moduleOptions = useMemo(
    () => (graphData?.nodes || []).filter((n) => n.level === "MODULE"),
    [graphData],
  );

  const editableGraphEdges = useMemo(() => {
    const conceptIds = new Set(learningConceptOptions.map((n) => n.id));
    const allowed = new Set(["REQUIRES", "EXTENDS", "CONTRASTS", "CURRICULUM_PATH"]);
    return (graphData?.edges || [])
      .filter((edge) => conceptIds.has(edge.source) && conceptIds.has(edge.target))
      .map((edge) => ({
        ...edge,
        relation: String(edge.relation || "").toUpperCase(),
      }))
      .filter((edge) => allowed.has(edge.relation));
  }, [graphData, learningConceptOptions]);

  const conceptualGraphEdges = useMemo(
    () =>
      editableGraphEdges.filter((edge) =>
        ["REQUIRES", "EXTENDS", "CONTRASTS"].includes(edge.relation),
      ),
    [editableGraphEdges],
  );

  const curriculumGraphEdges = useMemo(
    () => editableGraphEdges.filter((edge) => edge.relation === "CURRICULUM_PATH"),
    [editableGraphEdges],
  );

  const relationshipCanvas = useMemo(() => {
    const used = new Set();
    conceptualGraphEdges.forEach((edge) => {
      used.add(edge.source);
      used.add(edge.target);
    });
    const nodes = learningConceptOptions
      .filter((node) => used.has(node.id))
      .slice(0, 18)
      .map((node) => ({ id: node.id, label: node.label || node.id }));

    if (nodes.length === 0) {
      return { nodes: [], edges: [] };
    }

    const width = 760;
    const height = 320;
    const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
    const cx = width / 2;
    const cy = height / 2;
    const r = Math.min(width, height) * 0.38;
    const pos = {};
    nodes.forEach((node, idx) => {
      const angle = (Math.PI * 2 * idx) / nodes.length;
      const defaultPos = {
        x: cx + r * Math.cos(angle),
        y: cy + r * Math.sin(angle),
      };
      const custom = canvasNodePositions[node.id] || null;
      pos[node.id] = custom
        ? {
            x: clamp(Number(custom.x) || defaultPos.x, 24, width - 24),
            y: clamp(Number(custom.y) || defaultPos.y, 24, height - 24),
          }
        : defaultPos;
    });

    const edges = conceptualGraphEdges
      .filter((edge) => pos[edge.source] && pos[edge.target])
      .map((edge) => ({ ...edge, sourcePos: pos[edge.source], targetPos: pos[edge.target] }));

    const positionedNodes = nodes.map((node) => ({ ...node, ...pos[node.id] }));
    return { nodes: positionedNodes, edges, width, height };
  }, [conceptualGraphEdges, learningConceptOptions, canvasNodePositions]);

  const handleCanvasSelectNode = (nodeId, evt) => {
    if (canvasSelectionMode || evt?.shiftKey) {
      setSelectedCanvasNodes((prev) => {
        if (prev.includes(nodeId)) {
          return prev.filter((id) => id !== nodeId);
        }
        return [...prev, nodeId];
      });
      return;
    }

    setSelectedCanvasNodes([nodeId]);
    setGraphEdgeDraft((prev) => {
      if (!prev.source_id || (prev.source_id && prev.target_id)) {
        return { ...prev, source_id: nodeId, target_id: "" };
      }
      if (!prev.target_id) {
        return { ...prev, target_id: nodeId };
      }
      return prev;
    });
  };

  const toCanvasCoords = (evt) => {
    const svg = relationshipSvgRef.current;
    if (!svg) return null;
    const rect = svg.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const x = ((evt.clientX - rect.left) / rect.width) * relationshipCanvas.width;
    const y = ((evt.clientY - rect.top) / rect.height) * relationshipCanvas.height;
    return { x, y };
  };

  const handleCanvasNodeMouseDown = (nodeId, evt) => {
    evt.preventDefault();
    setDraggedCanvasNodeId(nodeId);
  };

  const handleCanvasMouseMove = (evt) => {
    if (!draggedCanvasNodeId) return;
    const coords = toCanvasCoords(evt);
    if (!coords) return;
    const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
    setCanvasNodePositions((prev) => ({
      ...prev,
      [draggedCanvasNodeId]: {
        x: clamp(coords.x, 24, relationshipCanvas.width - 24),
        y: clamp(coords.y, 24, relationshipCanvas.height - 24),
      },
    }));
  };

  const handleCanvasMouseUp = () => {
    if (draggedCanvasNodeId) {
      setDraggedCanvasNodeId("");
    }
  };

  useEffect(() => {
    const valid = new Set(learningConceptOptions.map((node) => node.id));
    setSelectedCanvasNodes((prev) => prev.filter((id) => valid.has(id)));
  }, [learningConceptOptions]);

  const handleFileUpload = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setBusy(true);
    try {
      const res = await ProfessorApi.ingest(apiBase, token, file, profCourse);
      if (handleAuthFailure(res)) return;
      pushActivity({
        endpoint: `/ingest?course_id=${profCourse}`,
        status: res.status,
        ok: res.ok,
        method: "POST",
      });
      if (res.ok) {
        alert(
          `Successfully ingested! Added ${res.data?.concepts_added || 0} concepts and ${res.data?.relationships_added || 0} relationships from ${file.name}.`,
        );
        // Refresh graph visualization
        const graphRes = await ProfessorApi.graphVisualization(
          apiBase,
          token,
          profCourse,
        );
        if (handleAuthFailure(graphRes)) return;
        if (graphRes.ok) hydrateGraphData(graphRes.data);
      } else {
        alert(
          `Failed to ingest document: ${res.data?.detail || res.data?.message || "Unknown error"}`,
        );
      }
    } finally {
      setBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleGraphFlagToggle = async (node, field, checked) => {
    if (!node || node.level !== "CONCEPT") return;
    const nodeId = node.id;

    setGraphNodeFlags((prev) => ({
      ...prev,
      [nodeId]: {
        ...(prev[nodeId] || {}),
        [field]: checked,
      },
    }));

    const payload =
      field === "highPriority"
        ? { priority: checked ? "high" : "normal" }
        : { visibility: checked ? "professor-only" : "global" };

    const res = await ProfessorApi.updateConcept(apiBase, token, nodeId, payload);
    if (handleAuthFailure(res)) return;
    pushActivity({
      endpoint: `/concept/${nodeId}`,
      status: res.status,
      ok: res.ok,
      method: "PATCH",
    });

    if (res.ok) {
      setGraphStatus("Concept metadata updated.");
      return;
    }

    setGraphStatus(`Failed to update concept (${res.status}).`);
    setGraphNodeFlags((prev) => ({
      ...prev,
      [nodeId]: {
        ...(prev[nodeId] || {}),
        [field]: !checked,
      },
    }));
  };

  const handleSaveProfessorNote = async () => {
    if (!selectedStudentDetails?.id || !token) return;
    const studentId = selectedStudentDetails.id;
    const annotation = (noteDraftByStudent[studentId] || "").trim();

    setBusy(true);
    try {
      const res = await ProfessorApi.annotateStudent(apiBase, token, {
        student_id: studentId,
        annotation,
      });
      if (handleAuthFailure(res)) return;
      pushActivity({
        endpoint: "/professor/annotate",
        status: res.status,
        ok: res.ok,
        method: "POST",
      });
      if (res.ok) {
        const historyRes = await ProfessorApi.getStudentAnnotation(
          apiBase,
          token,
          studentId,
          { forceRefresh: true },
        );
        if (!handleAuthFailure(historyRes) && historyRes.ok) {
          const items = Array.isArray(historyRes.data?.items)
            ? historyRes.data.items
            : [];
          setNoteHistoryByStudent((prev) => ({ ...prev, [studentId]: items }));
        }
      }
      setNoteStatus(res.ok ? "Note saved." : `Failed to save note (${res.status}).`);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    const studentId = toStudentId(selectedStudent);
    if (!studentId || !token) return;

    ProfessorApi.getStudentAnnotation(apiBase, token, studentId, {
      forceRefresh: true,
    }).then((res) => {
      if (handleAuthFailure(res) || !res.ok) return;
      const items = Array.isArray(res.data?.items) ? res.data.items : [];
      setNoteHistoryByStudent((prev) => ({ ...prev, [studentId]: items }));
      const latest = items[0] || null;
      const noteText = latest?.annotation || "";
      setNoteDraftByStudent((prev) => {
        if (typeof prev[studentId] === "string" && prev[studentId].length > 0) {
          return prev;
        }
        return { ...prev, [studentId]: noteText };
      });
    });
  }, [selectedStudent, token, apiBase]);

  return (
    <div className="dashboard-grid">
      <div className="widgets-column" style={{ gridColumn: "1 / -1" }}>
        <div
          className="widget"
          style={{ padding: "0", border: "none", background: "transparent" }}
        >
          <nav
            style={{
              display: "flex",
              gap: "1rem",
              borderBottom: "1px solid var(--border-light)",
              paddingBottom: "0.5rem",
              marginBottom: "1rem",
              overflowX: "auto",
            }}
          >
            <button
              onClick={() => setActiveTab("command_center")}
              style={{
                background: "none",
                border: "none",
                cursor: "pointer",
                fontWeight: activeTab === "command_center" ? 600 : 400,
                color:
                  activeTab === "command_center"
                    ? "var(--text-primary)"
                    : "var(--text-secondary)",
              }}
            >
              Command Center
            </button>
            <button
              onClick={() => setActiveTab("overview")}
              style={{
                background: "none",
                border: "none",
                cursor: "pointer",
                fontWeight: activeTab === "overview" ? 600 : 400,
                color:
                  activeTab === "overview"
                    ? "var(--text-primary)"
                    : "var(--text-secondary)",
              }}
            >
              Overview
            </button>
            <button
              onClick={() => setActiveTab("hitl")}
              style={{
                background: "none",
                border: "none",
                cursor: "pointer",
                fontWeight: activeTab === "hitl" ? 600 : 400,
                color:
                  activeTab === "hitl"
                    ? "var(--text-primary)"
                    : "var(--text-secondary)",
              }}
            >
              HITL Review Queue{" "}
              {hitlQueue.length > 0 && (
                <span
                  style={{
                    backgroundColor: "var(--accent)",
                    color: "white",
                    padding: "0.1rem 0.4rem",
                    borderRadius: "12px",
                    fontSize: "0.75rem",
                    marginLeft: "0.3rem",
                  }}
                >
                  {hitlQueue.length}
                </span>
              )}
            </button>
            <button
              onClick={() => setActiveTab("graph")}
              style={{
                background: "none",
                border: "none",
                cursor: "pointer",
                fontWeight: activeTab === "graph" ? 600 : 400,
                color:
                  activeTab === "graph"
                    ? "var(--text-primary)"
                    : "var(--text-secondary)",
              }}
            >
              Knowledge Graph
            </button>
            <button
              onClick={() => setActiveTab("students")}
              style={{
                background: "none",
                border: "none",
                cursor: "pointer",
                fontWeight: activeTab === "students" ? 600 : 400,
                color:
                  activeTab === "students"
                    ? "var(--text-primary)"
                    : "var(--text-secondary)",
              }}
            >
              Student Drill-Down
            </button>
            <button
              onClick={() => setActiveTab("learning_path")}
              style={{
                background: "none",
                border: "none",
                cursor: "pointer",
                fontWeight: activeTab === "learning_path" ? 600 : 400,
                color:
                  activeTab === "learning_path"
                    ? "var(--text-primary)"
                    : "var(--text-secondary)",
              }}
            >
              Learning Paths
            </button>
          </nav>
        </div>

        {activeTab === "command_center" && (
          <>
            <div className="widget">
              <div className="prof-command-grid">
                <div className="prof-studio-card">
                  <h3>Class Announcement Studio</h3>
                  <p className="prof-card-subtext">
                    Broadcast updates, office-hour notes, and exam alerts.
                  </p>
                  <textarea
                    value={announcementDraft}
                    onChange={(e) => setAnnouncementDraft(e.target.value)}
                    placeholder="Write an announcement for your classroom stream..."
                    style={{ minHeight: "100px", resize: "vertical" }}
                  />
                  <div
                    style={{
                      marginTop: "0.6rem",
                      display: "flex",
                      justifyContent: "flex-end",
                    }}
                  >
                    <button
                      className="btn-solid"
                      style={{ width: "auto", padding: "0.45rem 0.9rem" }}
                      onClick={publishAnnouncement}
                    >
                      Publish Announcement
                    </button>
                  </div>
                  <div style={{ marginTop: "0.8rem" }}>
                    {classAnnouncements.slice(0, 3).map((item) => (
                      <div key={item.id} className="prof-list-item">
                        <strong>{item.title}</strong>
                        <span>
                          {item.audience || "all"} •{" "}
                          {item.created_at
                            ? new Date(item.created_at).toLocaleDateString()
                            : "n/a"}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="prof-studio-card">
                  <h3>Assignment Builder</h3>
                  <p className="prof-card-subtext">
                    Create coursework experiences similar to classroom
                    platforms.
                  </p>
                  <div className="prof-form-grid">
                    <label>
                      Title
                      <input
                        value={assignmentDraft.title}
                        onChange={(e) =>
                          setAssignmentDraft((prev) => ({
                            ...prev,
                            title: e.target.value,
                          }))
                        }
                        placeholder="e.g. Final Project Proposal"
                      />
                    </label>
                    <label>
                      Due date
                      <input
                        type="date"
                        value={assignmentDraft.dueDate}
                        onChange={(e) =>
                          setAssignmentDraft((prev) => ({
                            ...prev,
                            dueDate: e.target.value,
                          }))
                        }
                      />
                    </label>
                    <label>
                      Rubric focus
                      <select
                        value={assignmentDraft.rubric}
                        onChange={(e) =>
                          setAssignmentDraft((prev) => ({
                            ...prev,
                            rubric: e.target.value,
                          }))
                        }
                      >
                        <option>Conceptual Accuracy</option>
                        <option>Reasoning Depth</option>
                        <option>Code Quality</option>
                        <option>Presentation Clarity</option>
                      </select>
                    </label>
                    <label>
                      Points
                      <input
                        type="number"
                        min="1"
                        max="100"
                        value={assignmentDraft.points}
                        onChange={(e) =>
                          setAssignmentDraft((prev) => ({
                            ...prev,
                            points: Number(e.target.value) || 20,
                          }))
                        }
                      />
                    </label>
                  </div>
                  <div
                    style={{
                      marginTop: "0.7rem",
                      display: "flex",
                      justifyContent: "flex-end",
                    }}
                  >
                    <button
                      className="btn-solid"
                      style={{ width: "auto", padding: "0.45rem 0.9rem" }}
                      onClick={publishAssignmentDraft}
                    >
                      Publish Assignment
                    </button>
                  </div>
                  <div style={{ marginTop: "0.8rem" }}>
                    {publishedAssignments.slice(0, 4).map((item) => (
                      <div key={item.id} className="prof-list-item">
                        <strong>{item.title}</strong>
                        <span>
                          Due {item.due_date} • {item.submission_count || 0}{" "}
                          submissions
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>

            <div className="widget">
              <h3>Intervention Planner</h3>
              <p className="prof-card-subtext">
                Students prioritized by low-confidence load, inactivity, and
                pending HITL review.
              </p>
              {interventionCandidates.length > 0 ? (
                <div className="prof-intervention-grid">
                  {interventionCandidates.map((row) => (
                    <div key={row.id} className="prof-intervention-card">
                      <div className="prof-intervention-header">
                        <strong>{row.name}</strong>
                        <span
                          className={`classroom-tag ${row.inactive ? "warn" : "ok"}`}
                        >
                          {row.inactive ? "Inactive" : "Active"}
                        </span>
                      </div>
                      <p>
                        Mastery:{" "}
                        {row.mastery === null
                          ? "n/a"
                          : `${row.mastery.toFixed(1)}%`}
                      </p>
                      <p>Low-confidence concepts: {row.lowConfidence}</p>
                      <p>Pending HITL: {row.pendingHitl}</p>
                      <button
                        className="link-action"
                        onClick={() => setActiveTab("students")}
                      >
                        Open Student Reflection
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="feed-empty">
                  Load students/cohort data to generate intervention
                  recommendations.
                </p>
              )}
            </div>

            <div className="widget">
              <h3>Operations Console</h3>
              <div className="prof-ops-grid">
                <div className="prof-ops-item">
                  <div className="prof-ops-label">Pending HITL</div>
                  <div className="prof-ops-value">{hitlQueue.length}</div>
                </div>
                <div className="prof-ops-item">
                  <div className="prof-ops-label">Total Submissions</div>
                  <div className="prof-ops-value">
                    {courseSubmissions.length}
                  </div>
                </div>
                <div className="prof-ops-item">
                  <div className="prof-ops-label">Roster Size</div>
                  <div className="prof-ops-value">
                    {studentWiseRows.length || studentList.length}
                  </div>
                </div>
                <div className="prof-ops-item">
                  <div className="prof-ops-label">Inactive Students</div>
                  <div className="prof-ops-value">
                    {cohortOverview?.inactive_students?.length || 0}
                  </div>
                </div>
                <div className="prof-ops-item">
                  <div className="prof-ops-label">Average Mastery</div>
                  <div className="prof-ops-value">
                    {cohortOverview?.average_mastery
                      ? `${cohortOverview.average_mastery.toFixed(1)}%`
                      : "n/a"}
                  </div>
                </div>
              </div>
            </div>

            <div className="widget">
              <h3>Submission Review Desk</h3>
              <p className="prof-card-subtext">
                Apply explicit professor grading actions using the manual grade route.
              </p>
              {courseSubmissions.length > 0 ? (
                <div style={{ display: "grid", gap: "0.55rem" }}>
                  {courseSubmissions.slice(0, 12).map((item) => (
                    <div
                      key={item.submission_id}
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        gap: "0.8rem",
                        padding: "0.6rem 0.75rem",
                        border: "1px solid var(--border-light)",
                        borderRadius: "6px",
                        background: "var(--surface-primary)",
                      }}
                    >
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: "0.84rem", fontWeight: 600 }}>
                          {item.assignment_id || "assignment"} - {item.submission_id}
                        </div>
                        <div style={{ fontSize: "0.77rem", color: "var(--text-secondary)" }}>
                          Student: {item.student_id || "n/a"} | Status: {item.status || "n/a"}
                        </div>
                      </div>
                      <button
                        className="btn-solid"
                        style={{ width: "auto", padding: "0.3rem 0.7rem" }}
                        onClick={() => openManualGrade(item)}
                      >
                        Grade
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="feed-empty" style={{ textAlign: "left", padding: 0 }}>
                  No submissions available for manual grading.
                </p>
              )}
              {manualGradeStatus && (
                <div
                  style={{
                    marginTop: "0.7rem",
                    fontSize: "0.8rem",
                    color: "var(--text-secondary)",
                  }}
                >
                  {manualGradeStatus}
                </div>
              )}
            </div>
          </>
        )}

        {/* PD-1: Cohort Progress Overview */}
        {activeTab === "overview" && (
          <>
            <div
              className="widget"
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <div>
                <h3 style={{ marginBottom: "0.2rem" }}>
                  Cohort Progress Overview
                </h3>
                <p
                  style={{
                    color: "var(--text-secondary)",
                    fontSize: "0.85rem",
                    margin: 0,
                  }}
                >
                  Macro-level insight over course <strong>{profCourse}</strong>
                </p>
              </div>
              <button
                className="btn-solid"
                style={{ width: "auto" }}
                onClick={loadProfessorData}
                disabled={busy || !token}
              >
                Refresh Analytics
              </button>
            </div>

            {cohortOverview ? (
              <>
                <div className="widget">
                  <h3>Metrics Summary</h3>
                  <div
                    style={{ display: "flex", gap: "3rem", flexWrap: "wrap" }}
                  >
                    <div>
                      <div style={{ fontSize: "2.5rem", fontWeight: 600 }}>
                        {cohortOverview.total_students || 0}
                      </div>
                      <div
                        style={{
                          fontSize: "0.85rem",
                          color: "var(--text-secondary)",
                        }}
                      >
                        Students Enrolled
                      </div>
                    </div>
                    <div>
                      <div style={{ fontSize: "2.5rem", fontWeight: 600 }}>
                        {cohortOverview.struggling_students || 0}
                      </div>
                      <div
                        style={{
                          fontSize: "0.85rem",
                          color: "var(--text-secondary)",
                        }}
                      >
                        Struggling
                      </div>
                    </div>
                    <div>
                      <div style={{ fontSize: "2.5rem", fontWeight: 600 }}>
                        {cohortOverview.average_mastery
                          ? cohortOverview.average_mastery.toFixed(1)
                          : "0.0"}
                        %
                      </div>
                      <div
                        style={{
                          fontSize: "0.85rem",
                          color: "var(--text-secondary)",
                        }}
                      >
                        Average Mastery
                      </div>
                    </div>
                  </div>
                </div>

                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1fr 1fr",
                    gap: "2rem",
                  }}
                >
                  <div className="widget">
                    <h3>Concepts with High Struggle Rates</h3>
                    <p
                      style={{
                        fontSize: "0.8rem",
                        color: "var(--text-tertiary)",
                        marginBottom: "1rem",
                      }}
                    >
                      Based on IRT Slip parameter modelling across the cohort.
                    </p>
                    {cohortOverview.struggling_concepts &&
                    cohortOverview.struggling_concepts.length > 0 ? (
                      <ul
                        style={{
                          paddingLeft: "1.2rem",
                          margin: 0,
                          fontSize: "0.9rem",
                        }}
                      >
                        {cohortOverview.struggling_concepts.map((c, i) => (
                          <li key={i} style={{ marginBottom: "0.4rem" }}>
                            <strong>{c.name}</strong>
                            <div
                              style={{ color: "#d97706", fontSize: "0.8rem" }}
                            >
                              Slip Ratio: {c.slip}
                            </div>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="feed-empty">
                        No universally struggling concepts detected.
                      </p>
                    )}
                  </div>

                  <div className="widget">
                    <h3>Unengaged Students (&gt;7 days)</h3>
                    <p
                      style={{
                        fontSize: "0.8rem",
                        color: "var(--text-tertiary)",
                        marginBottom: "1rem",
                      }}
                    >
                      Students requiring intervention prompts.
                    </p>
                    {cohortOverview.inactive_students &&
                    cohortOverview.inactive_students.length > 0 ? (
                      <ul
                        style={{
                          paddingLeft: "1.2rem",
                          margin: 0,
                          fontSize: "0.9rem",
                        }}
                      >
                        {cohortOverview.inactive_students.map((s, i) => (
                          <li key={i} style={{ marginBottom: "0.3rem" }}>
                            {s}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="feed-empty">
                        All students actively participating.
                      </p>
                    )}
                  </div>
                </div>
              </>
            ) : (
              <div className="widget">
                <p className="feed-empty">Loading cohort parameters...</p>
              </div>
            )}
          </>
        )}

        {/* PD-4 & PD-6: HITL Queue & Integrity */}
        {activeTab === "hitl" && (
          <div className="widget">
            <h3 style={{ marginBottom: "0.2rem" }}>
              Human In The Loop (HITL) Queue
            </h3>
            <p
              style={{
                fontSize: "0.8rem",
                color: "var(--text-tertiary)",
                marginBottom: "1.5rem",
              }}
            >
              Evaluate, modify, and officially credential AI-audited
              submissions. Anomalous inputs rise to the top.
            </p>
            {hitlQueue.length > 0 ? (
              hitlQueue.map((item, idx) => {
                const sdi = getHitlSdi(item);
                const sdiWarning = (sdi ?? -1) > 85;
                const editObj = hitlEditState[item.queue_id] || {};

                return (
                  <div
                    key={item.queue_id || item.defence_record_id || idx}
                    style={{
                      border: "1px solid var(--border-light)",
                      padding: "1.5rem",
                      borderRadius: "8px",
                      marginBottom: "1.5rem",
                      background: "var(--surface-primary)",
                      boxShadow: sdiWarning ? "0 0 0 2px #ef4444" : "none",
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        borderBottom: "1px solid var(--border-light)",
                        paddingBottom: "0.5rem",
                        marginBottom: "1rem",
                      }}
                    >
                      <div>
                        <strong style={{ fontSize: "1.1rem" }}>
                          Submission Evaluator: {item.submission_id}
                        </strong>
                        <div
                          style={{
                            fontSize: "0.85rem",
                            color: "var(--accent)",
                          }}
                        >
                          Student: {item.student_id}
                        </div>
                      </div>

                      {/* PD-6: Flagging */}
                      {sdi !== null && (
                        <div
                          style={{
                            padding: "0.5rem 1rem",
                            borderRadius: "4px",
                            background: sdiWarning ? "#fee2e2" : "#f0fdf4",
                            color: sdiWarning ? "#b91c1c" : "#15803d",
                            display: "flex",
                            alignItems: "center",
                            fontWeight: 600,
                          }}
                        >
                          {sdiWarning
                            ? "⚠️ Anomalous Input (SDI > 85%)"
                            : "Integrity Cleared"}
                          <span
                            style={{ marginLeft: "0.5rem", fontWeight: 400 }}
                          >
                            {" "}| SDI: {sdi}%
                          </span>
                        </div>
                      )}
                    </div>

                    <div style={{ marginBottom: "1.5rem" }}>
                      <div
                        style={{
                          fontWeight: 600,
                          marginBottom: "0.5rem",
                          color: "var(--text-secondary)",
                        }}
                      >
                        Multi-turn Defence Transcript
                      </div>
                      <div
                        style={{
                          maxHeight: "200px",
                          overflowY: "auto",
                          padding: "1rem",
                          background: "var(--bg-secondary)",
                          borderRadius: "6px",
                          fontSize: "0.9rem",
                          border: "1px solid var(--border-light)",
                        }}
                      >
                        {Array.isArray(item.transcript) &&
                          item.transcript.map((t, i) => (
                            <div key={i} style={{ marginBottom: "0.6rem" }}>
                              <strong
                                style={{
                                  color:
                                    t.role === "assistant"
                                      ? "var(--accent)"
                                      : "var(--text-primary)",
                                }}
                              >
                                {t.role === "assistant"
                                  ? "Evaluator"
                                  : "Student"}
                                :
                              </strong>{" "}
                              {t.content}
                            </div>
                          ))}
                        {(!Array.isArray(item.transcript) ||
                          item.transcript.length === 0) &&
                          "No transcript available."}
                      </div>
                    </div>

                    {/* PD-4: Editable Overrides */}
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "1fr 3fr",
                        gap: "1rem",
                        marginBottom: "1.5rem",
                        background: "var(--bg-secondary)",
                        padding: "1rem",
                        borderRadius: "6px",
                      }}
                    >
                      <div>
                        <label
                          style={{
                            display: "block",
                            fontSize: "0.85rem",
                            fontWeight: 600,
                            marginBottom: "0.3rem",
                            color: "var(--text-secondary)",
                          }}
                        >
                          Final Grade (AI Rec: {item.ai_recommended_grade})
                        </label>
                        <input
                          type="text"
                          value={editObj.ai_recommended_grade || ""}
                          onChange={(e) =>
                            handleEditChange(
                              item.queue_id,
                              "ai_recommended_grade",
                              e.target.value,
                            )
                          }
                          style={{ fontWeight: 600, fontSize: "1.1rem" }}
                        />
                      </div>
                      <div>
                        <label
                          style={{
                            display: "block",
                            fontSize: "0.85rem",
                            fontWeight: 600,
                            marginBottom: "0.3rem",
                            color: "var(--text-secondary)",
                          }}
                        >
                          Feedback / Professor Notes
                        </label>
                        <textarea
                          value={editObj.ai_feedback || ""}
                          onChange={(e) =>
                            handleEditChange(
                              item.queue_id,
                              "ai_feedback",
                              e.target.value,
                            )
                          }
                          style={{
                            resize: "vertical",
                            minHeight: "80px",
                            fontSize: "0.9rem",
                          }}
                        />
                      </div>
                    </div>

                    <div style={{ display: "flex", gap: "1rem" }}>
                      <button
                        onClick={() =>
                          handleHitlAction(item.queue_id, "approve")
                        }
                        disabled={busy}
                        className="btn-solid"
                        style={{ background: "var(--accent)", flex: 1 }}
                      >
                        Confirm & Credential Grade
                      </button>
                      <button
                        onClick={() =>
                          handleHitlAction(
                            item.queue_id,
                            "reject_second_defence",
                          )
                        }
                        disabled={busy}
                        className="btn-solid"
                        style={{
                          background: "white",
                          color: "var(--brand)",
                          border: "1px solid var(--brand)",
                          flex: 1,
                        }}
                      >
                        Reject & Mandate Re-defence
                      </button>
                    </div>
                  </div>
                );
              })
            ) : (
              <div
                style={{
                  padding: "3rem",
                  textAlign: "center",
                  border: "2px dashed var(--border-light)",
                  borderRadius: "8px",
                }}
              >
                <h4 style={{ color: "var(--text-tertiary)", fontWeight: 400 }}>
                  The queue is completely clear.
                </h4>
              </div>
            )}
          </div>
        )}

        {/* PD-3: Knowledge Graph Editor */}
        {activeTab === "graph" && (
          <div className="widget">
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: "1rem",
              }}
            >
              <div>
                <h3 style={{ marginBottom: "0" }}>Knowledge Graph Editor</h3>
                <p
                  style={{
                    fontSize: "0.8rem",
                    color: "var(--text-tertiary)",
                    margin: "0.2rem 0 0",
                  }}
                >
                  Direct manipulation of course graph nodes and boundaries.
                </p>
              </div>
              <div style={{ display: "flex", gap: "1rem" }}>
                <input
                  type="file"
                  ref={fileInputRef}
                  style={{ display: "none" }}
                  accept=".pdf,.doc,.docx,.ppt,.pptx,.txt"
                  onChange={handleFileUpload}
                />
                <button
                  className="btn-solid"
                  style={{
                    width: "auto",
                    padding: "0.4rem 1rem",
                    background: "var(--bg-secondary)",
                    color: "var(--brand)",
                    border: "1px solid var(--border-light)",
                  }}
                  onClick={() => fileInputRef.current?.click()}
                  disabled={busy || !token}
                >
                  Upload Material (Re-ingest)
                </button>
                <button
                  className="btn-solid"
                  style={{ width: "auto", padding: "0.4rem 1rem" }}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      const res = await ProfessorApi.graphVisualization(
                        apiBase,
                        token,
                        profCourse,
                      );
                      if (handleAuthFailure(res)) return;
                      if (res.ok) {
                        hydrateGraphData(res.data);
                        setGraphStatus("Graph map refreshed.");
                      } else {
                        setGraphStatus(`Failed to load graph (${res.status}).`);
                      }
                    } finally {
                      setBusy(false);
                    }
                  }}
                  disabled={busy || !token}
                >
                  Fetch Graph Map
                </button>
              </div>
            </div>

            <div
              style={{
                display: "grid",
                gap: "0.55rem",
                gridTemplateColumns: "2fr 3fr 1fr auto",
                alignItems: "end",
                marginBottom: "1rem",
                padding: "0.8rem",
                borderRadius: "8px",
                background: "var(--bg-secondary)",
                border: "1px solid var(--border-light)",
              }}
            >
              <label style={{ fontSize: "0.78rem" }}>
                Module Name
                <input
                  value={newModuleDraft.name}
                  onChange={(e) =>
                    setNewModuleDraft((prev) => ({ ...prev, name: e.target.value }))
                  }
                  placeholder="e.g. Probability Foundations"
                />
              </label>
              <label style={{ fontSize: "0.78rem" }}>
                Module Description
                <input
                  value={newModuleDraft.description}
                  onChange={(e) =>
                    setNewModuleDraft((prev) => ({
                      ...prev,
                      description: e.target.value,
                    }))
                  }
                  placeholder="High-level module summary"
                />
              </label>
              <label style={{ fontSize: "0.78rem" }}>
                Visibility
                <select
                  value={newModuleDraft.visibility}
                  onChange={(e) =>
                    setNewModuleDraft((prev) => ({
                      ...prev,
                      visibility: e.target.value,
                    }))
                  }
                >
                  <option value="global">global</option>
                  <option value="enrolled-only">enrolled-only</option>
                  <option value="professor-only">professor-only</option>
                </select>
              </label>
              <button
                className="btn-solid"
                style={{ width: "auto", padding: "0.45rem 0.8rem" }}
                onClick={createGraphModule}
                disabled={busy || !token}
              >
                Create Module
              </button>
            </div>

            <div
              style={{
                display: "grid",
                gap: "0.55rem",
                gridTemplateColumns: "2fr 2fr 3fr 1fr auto",
                alignItems: "end",
                marginBottom: "1rem",
                padding: "0.8rem",
                borderRadius: "8px",
                background: "var(--bg-secondary)",
                border: "1px solid var(--border-light)",
              }}
            >
              <label style={{ fontSize: "0.78rem" }}>
                Parent Module
                <select
                  value={newTopicDraft.module_id}
                  onChange={(e) =>
                    setNewTopicDraft((prev) => ({
                      ...prev,
                      module_id: e.target.value,
                    }))
                  }
                >
                  <option value="">Select module</option>
                  {moduleOptions.map((node) => (
                    <option key={`topic_module_${node.id}`} value={node.id}>
                      {node.label || node.id}
                    </option>
                  ))}
                </select>
              </label>
              <label style={{ fontSize: "0.78rem" }}>
                Topic Name
                <input
                  value={newTopicDraft.name}
                  onChange={(e) =>
                    setNewTopicDraft((prev) => ({ ...prev, name: e.target.value }))
                  }
                  placeholder="e.g. Conditional Probability"
                />
              </label>
              <label style={{ fontSize: "0.78rem" }}>
                Topic Description
                <input
                  value={newTopicDraft.description}
                  onChange={(e) =>
                    setNewTopicDraft((prev) => ({
                      ...prev,
                      description: e.target.value,
                    }))
                  }
                  placeholder="Topic-level summary"
                />
              </label>
              <label style={{ fontSize: "0.78rem" }}>
                Visibility
                <select
                  value={newTopicDraft.visibility}
                  onChange={(e) =>
                    setNewTopicDraft((prev) => ({
                      ...prev,
                      visibility: e.target.value,
                    }))
                  }
                >
                  <option value="global">global</option>
                  <option value="enrolled-only">enrolled-only</option>
                  <option value="professor-only">professor-only</option>
                </select>
              </label>
              <button
                className="btn-solid"
                style={{ width: "auto", padding: "0.45rem 0.8rem" }}
                onClick={createGraphTopic}
                disabled={busy || !token}
              >
                Create Topic
              </button>
            </div>

            <div
              style={{
                display: "grid",
                gap: "0.55rem",
                gridTemplateColumns: "2fr 2fr 3fr 1fr auto",
                alignItems: "end",
                marginBottom: "1rem",
                padding: "0.8rem",
                borderRadius: "8px",
                background: "var(--bg-secondary)",
                border: "1px solid var(--border-light)",
              }}
            >
              <label style={{ fontSize: "0.78rem" }}>
                Parent Concept
                <select
                  value={newFactDraft.concept_id}
                  onChange={(e) =>
                    setNewFactDraft((prev) => ({
                      ...prev,
                      concept_id: e.target.value,
                    }))
                  }
                >
                  <option value="">Select concept</option>
                  {learningConceptOptions.map((node) => (
                    <option key={`fact_concept_${node.id}`} value={node.id}>
                      {node.label || node.id}
                    </option>
                  ))}
                </select>
              </label>
              <label style={{ fontSize: "0.78rem" }}>
                Fact Name
                <input
                  value={newFactDraft.name}
                  onChange={(e) =>
                    setNewFactDraft((prev) => ({ ...prev, name: e.target.value }))
                  }
                  placeholder="e.g. Bayes theorem statement"
                />
              </label>
              <label style={{ fontSize: "0.78rem" }}>
                Fact Description
                <input
                  value={newFactDraft.description}
                  onChange={(e) =>
                    setNewFactDraft((prev) => ({
                      ...prev,
                      description: e.target.value,
                    }))
                  }
                  placeholder="Concrete fact or formula"
                />
              </label>
              <label style={{ fontSize: "0.78rem" }}>
                Visibility
                <select
                  value={newFactDraft.visibility}
                  onChange={(e) =>
                    setNewFactDraft((prev) => ({
                      ...prev,
                      visibility: e.target.value,
                    }))
                  }
                >
                  <option value="global">global</option>
                  <option value="enrolled-only">enrolled-only</option>
                  <option value="professor-only">professor-only</option>
                </select>
              </label>
              <button
                className="btn-solid"
                style={{ width: "auto", padding: "0.45rem 0.8rem" }}
                onClick={createGraphFact}
                disabled={busy || !token}
              >
                Create Fact
              </button>
            </div>
            {authoringStatus && (
              <div
                style={{
                  marginBottom: "0.8rem",
                  fontSize: "0.82rem",
                  color: "var(--text-secondary)",
                }}
              >
                {authoringStatus}
              </div>
            )}

            <div
              style={{
                display: "grid",
                gap: "0.55rem",
                gridTemplateColumns: "2fr 3fr 1fr auto",
                alignItems: "end",
                marginBottom: "1rem",
                padding: "0.8rem",
                borderRadius: "8px",
                background: "var(--bg-secondary)",
                border: "1px solid var(--border-light)",
              }}
            >
              <label style={{ fontSize: "0.78rem" }}>
                Concept Name
                <input
                  value={newConceptDraft.name}
                  onChange={(e) =>
                    setNewConceptDraft((prev) => ({ ...prev, name: e.target.value }))
                  }
                  placeholder="e.g. Bayesian Inference"
                />
              </label>
              <label style={{ fontSize: "0.78rem" }}>
                Description
                <input
                  value={newConceptDraft.description}
                  onChange={(e) =>
                    setNewConceptDraft((prev) => ({
                      ...prev,
                      description: e.target.value,
                    }))
                  }
                  placeholder="Short teaching description"
                />
              </label>
              <label style={{ fontSize: "0.78rem" }}>
                Category
                <input
                  value={newConceptDraft.category}
                  onChange={(e) =>
                    setNewConceptDraft((prev) => ({ ...prev, category: e.target.value }))
                  }
                  placeholder="general"
                />
              </label>
              <button
                className="btn-solid"
                style={{ width: "auto", padding: "0.45rem 0.8rem" }}
                onClick={createGraphConcept}
                disabled={busy || !token}
              >
                Create Concept
              </button>
            </div>
            {conceptCreateStatus && (
              <div
                style={{
                  marginBottom: "0.8rem",
                  fontSize: "0.82rem",
                  color: "var(--text-secondary)",
                }}
              >
                {conceptCreateStatus}
              </div>
            )}

            <div
              style={{
                display: "grid",
                gap: "0.55rem",
                gridTemplateColumns: "2fr 2fr 1fr 1fr auto",
                alignItems: "end",
                marginBottom: "0.9rem",
                padding: "0.8rem",
                borderRadius: "8px",
                background: "var(--bg-secondary)",
                border: "1px solid var(--border-light)",
              }}
            >
              <label style={{ fontSize: "0.78rem" }}>
                Edge Source
                <select
                  value={graphEdgeDraft.source_id}
                  onChange={(e) =>
                    setGraphEdgeDraft((prev) => ({
                      ...prev,
                      source_id: e.target.value,
                    }))
                  }
                >
                  <option value="">Select source</option>
                  {learningConceptOptions.map((node) => (
                    <option key={`edge_src_${node.id}`} value={node.id}>
                      {node.label || node.id}
                    </option>
                  ))}
                </select>
              </label>
              <label style={{ fontSize: "0.78rem" }}>
                Edge Target
                <select
                  value={graphEdgeDraft.target_id}
                  onChange={(e) =>
                    setGraphEdgeDraft((prev) => ({
                      ...prev,
                      target_id: e.target.value,
                    }))
                  }
                >
                  <option value="">Select target</option>
                  {learningConceptOptions.map((node) => (
                    <option key={`edge_tgt_${node.id}`} value={node.id}>
                      {node.label || node.id}
                    </option>
                  ))}
                </select>
              </label>
              <label style={{ fontSize: "0.78rem" }}>
                Relation
                <select
                  value={graphEdgeDraft.relation}
                  onChange={(e) =>
                    setGraphEdgeDraft((prev) => ({
                      ...prev,
                      relation: e.target.value,
                    }))
                  }
                >
                  <option value="REQUIRES">REQUIRES</option>
                  <option value="EXTENDS">EXTENDS</option>
                  <option value="CONTRASTS">CONTRASTS</option>
                </select>
              </label>
              <label style={{ fontSize: "0.78rem" }}>
                Weight
                <input
                  type="number"
                  min="0.1"
                  max="3"
                  step="0.1"
                  value={graphEdgeDraft.weight}
                  onChange={(e) =>
                    setGraphEdgeDraft((prev) => ({
                      ...prev,
                      weight: e.target.value,
                    }))
                  }
                />
              </label>
              <button
                className="btn-solid"
                style={{ width: "auto", padding: "0.45rem 0.8rem" }}
                onClick={createGraphEdge}
                disabled={busy || !token}
              >
                Create Edge
              </button>
            </div>
            <div
              style={{
                marginBottom: "0.9rem",
                padding: "0.75rem",
                borderRadius: "8px",
                border: "1px solid var(--border-light)",
                background: "var(--bg-secondary)",
              }}
            >
              <h4 style={{ margin: "0 0 0.55rem", fontSize: "0.85rem" }}>
                Existing Concept Edges
              </h4>
              {conceptualGraphEdges.length > 0 ? (
                <div style={{ display: "grid", gap: "0.35rem", maxHeight: "220px", overflowY: "auto" }}>
                  {conceptualGraphEdges.map((edge, idx) => (
                    <div
                      key={`${edge.source}_${edge.target}_${edge.relation}_${idx}`}
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        gap: "0.6rem",
                        alignItems: "center",
                        padding: "0.45rem 0.6rem",
                        background: "var(--surface-primary)",
                        border: "1px solid var(--border-light)",
                        borderRadius: "6px",
                      }}
                    >
                      <div style={{ fontSize: "0.79rem" }}>
                        <strong>{learningConceptLabelById[edge.source] || edge.source}</strong>
                        {" -> "}
                        <strong>{learningConceptLabelById[edge.target] || edge.target}</strong>
                        <span style={{ color: "var(--text-secondary)", marginLeft: "0.45rem" }}>
                          {edge.relation} (w={Number(edge.weight || 1).toFixed(1)})
                        </span>
                      </div>
                      <button
                        className="btn-solid"
                        style={{
                          width: "auto",
                          padding: "0.2rem 0.45rem",
                          fontSize: "0.72rem",
                          background: "#fff1f2",
                          color: "#9f1239",
                          border: "1px solid #fecdd3",
                        }}
                        onClick={() => deleteGraphEdge(edge)}
                        disabled={busy || !token}
                      >
                        Delete
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="feed-empty" style={{ textAlign: "left", padding: 0, margin: 0 }}>
                  No concept-level edges available.
                </p>
              )}
              {graphEdgeStatus && (
                <div
                  style={{
                    marginTop: "0.6rem",
                    fontSize: "0.8rem",
                    color: "var(--text-secondary)",
                  }}
                >
                  {graphEdgeStatus}
                </div>
              )}
            </div>

            <div
              style={{
                marginBottom: "0.9rem",
                padding: "0.75rem",
                borderRadius: "8px",
                border: "1px solid var(--border-light)",
                background: "var(--bg-secondary)",
              }}
            >
              <h4 style={{ margin: "0 0 0.45rem", fontSize: "0.85rem" }}>
                Relationship Canvas (Conceptual)
              </h4>
              <p style={{ fontSize: "0.76rem", color: "var(--text-secondary)", margin: "0 0 0.55rem" }}>
                Click a node to prefill edge source/target in order. This canvas reflects REQUIRES/EXTENDS/CONTRASTS links.
              </p>
              <div
                style={{
                  display: "flex",
                  gap: "0.45rem",
                  flexWrap: "wrap",
                  alignItems: "center",
                  marginBottom: "0.55rem",
                }}
              >
                <button
                  className="btn-solid"
                  style={{ width: "auto", padding: "0.28rem 0.6rem", fontSize: "0.72rem" }}
                  onClick={() => setCanvasSelectionMode((prev) => !prev)}
                >
                  {canvasSelectionMode ? "Selection: Multi" : "Selection: Single"}
                </button>
                <button
                  className="btn-solid"
                  style={{ width: "auto", padding: "0.28rem 0.6rem", fontSize: "0.72rem" }}
                  onClick={() => setSelectedCanvasNodes([])}
                >
                  Clear Selection
                </button>
                <button
                  className="btn-solid"
                  style={{ width: "auto", padding: "0.28rem 0.6rem", fontSize: "0.72rem" }}
                  onClick={createBulkEdgesFromSelection}
                  disabled={busy || !token || selectedCanvasNodes.length < 2}
                >
                  Bulk Create (Chain)
                </button>
                <button
                  className="btn-solid"
                  style={{ width: "auto", padding: "0.28rem 0.6rem", fontSize: "0.72rem" }}
                  onClick={deleteBulkEdgesFromSelection}
                  disabled={busy || !token || selectedCanvasNodes.length < 2}
                >
                  Bulk Delete ({String(graphEdgeDraft.relation || "REQUIRES").toUpperCase()})
                </button>
                <button
                  className="btn-solid"
                  style={{ width: "auto", padding: "0.28rem 0.6rem", fontSize: "0.72rem" }}
                  onClick={undoLastEdgeChange}
                  disabled={busy || !token || edgeUndoStack.length === 0}
                >
                  Undo Edge Change
                </button>
                <button
                  className="btn-solid"
                  style={{ width: "auto", padding: "0.28rem 0.6rem", fontSize: "0.72rem" }}
                  onClick={redoLastEdgeChange}
                  disabled={busy || !token || edgeRedoStack.length === 0}
                >
                  Redo Edge Change
                </button>
                <span style={{ fontSize: "0.74rem", color: "var(--text-secondary)" }}>
                  Selected: {selectedCanvasNodes.length} node(s)
                </span>
              </div>
              {relationshipCanvas.nodes.length > 0 ? (
                <svg
                  ref={relationshipSvgRef}
                  viewBox={`0 0 ${relationshipCanvas.width} ${relationshipCanvas.height}`}
                  onMouseMove={handleCanvasMouseMove}
                  onMouseUp={handleCanvasMouseUp}
                  onMouseLeave={handleCanvasMouseUp}
                  style={{ width: "100%", height: "260px", border: "1px solid var(--border-light)", borderRadius: "6px", background: "var(--surface-primary)", cursor: draggedCanvasNodeId ? "grabbing" : "default" }}
                >
                  <defs>
                    <marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
                      <polygon points="0 0, 8 3, 0 6" fill="#64748b" />
                    </marker>
                  </defs>
                  {relationshipCanvas.edges.map((edge, idx) => (
                    <g key={`canvas_edge_${idx}`}>
                      <line
                        x1={edge.sourcePos.x}
                        y1={edge.sourcePos.y}
                        x2={edge.targetPos.x}
                        y2={edge.targetPos.y}
                        stroke="#94a3b8"
                        strokeWidth="1.4"
                        markerEnd="url(#arrowhead)"
                      />
                    </g>
                  ))}
                  {relationshipCanvas.nodes.map((node) => {
                    const isSource = graphEdgeDraft.source_id === node.id;
                    const isTarget = graphEdgeDraft.target_id === node.id;
                    const isSelected = selectedCanvasNodes.includes(node.id);
                    const fill = isSource
                      ? "#cffafe"
                      : isTarget
                        ? "#fee2e2"
                        : isSelected
                          ? "#dbeafe"
                          : "#e2e8f0";
                    return (
                      <g
                        key={`canvas_node_${node.id}`}
                        onClick={(evt) => handleCanvasSelectNode(node.id, evt)}
                        onMouseDown={(evt) => handleCanvasNodeMouseDown(node.id, evt)}
                        style={{ cursor: draggedCanvasNodeId === node.id ? "grabbing" : "pointer" }}
                      >
                        <circle
                          cx={node.x}
                          cy={node.y}
                          r={isSelected ? "20" : "18"}
                          fill={fill}
                          stroke={isSelected ? "#1d4ed8" : "#334155"}
                          strokeWidth={isSelected ? "1.8" : "1.2"}
                        />
                        <text
                          x={node.x}
                          y={node.y + 3}
                          textAnchor="middle"
                          fontSize="9"
                          fill="#0f172a"
                          pointerEvents="none"
                        >
                          {(node.label || "").slice(0, 8)}
                        </text>
                      </g>
                    );
                  })}
                </svg>
              ) : (
                <p className="feed-empty" style={{ textAlign: "left", padding: 0, margin: 0 }}>
                  Canvas will appear once conceptual edges exist.
                </p>
              )}
            </div>

            <div
              style={{
                marginBottom: "0.9rem",
                padding: "0.75rem",
                borderRadius: "8px",
                border: "1px solid var(--border-light)",
                background: "var(--bg-secondary)",
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: "0.8rem",
                }}
              >
                <h4 style={{ margin: 0, fontSize: "0.85rem" }}>
                  Curriculum Path Edges (Governed Separately)
                </h4>
                <button
                  className="btn-solid"
                  style={{ width: "auto", padding: "0.3rem 0.7rem" }}
                  onClick={() => setActiveTab("learning_path")}
                >
                  Manage In Learning Paths
                </button>
              </div>
              <p style={{ fontSize: "0.76rem", color: "var(--text-secondary)", margin: "0.5rem 0" }}>
                CURRICULUM_PATH edges are read-only in Graph Editor to prevent accidental curriculum policy drift.
              </p>
              {curriculumGraphEdges.length > 0 ? (
                <div style={{ display: "grid", gap: "0.35rem", maxHeight: "160px", overflowY: "auto" }}>
                  {curriculumGraphEdges.map((edge, idx) => (
                    <div
                      key={`curr_${edge.source}_${edge.target}_${idx}`}
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        gap: "0.6rem",
                        alignItems: "center",
                        padding: "0.42rem 0.6rem",
                        background: "var(--surface-primary)",
                        border: "1px solid var(--border-light)",
                        borderRadius: "6px",
                        fontSize: "0.78rem",
                      }}
                    >
                      <div>
                        <strong>{learningConceptLabelById[edge.source] || edge.source}</strong>
                        {" -> "}
                        <strong>{learningConceptLabelById[edge.target] || edge.target}</strong>
                      </div>
                      <span style={{ color: "var(--text-secondary)" }}>
                        w={Number(edge.weight || 1).toFixed(1)}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="feed-empty" style={{ textAlign: "left", padding: 0, margin: 0 }}>
                  No curriculum path edges currently present.
                </p>
              )}
            </div>

            {graphData ? (
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))",
                  gap: "1.5rem",
                  marginTop: "1.5rem",
                }}
              >
                {graphData.nodes?.map((node, i) => (
                  <div
                    key={i}
                    style={{
                      padding: "1rem",
                      background: "var(--surface-primary)",
                      borderRadius: "8px",
                      border: "1px solid var(--border-light)",
                      borderLeft: `6px solid ${node.level === "CONCEPT" ? "var(--accent)" : "var(--border-light)"}`,
                      position: "relative",
                    }}
                  >
                    <div
                      style={{
                        fontWeight: 600,
                        fontSize: "1.1rem",
                        marginBottom: "0.3rem",
                      }}
                    >
                      {node.label || node.id}
                    </div>
                    <div
                      style={{
                        fontSize: "0.75rem",
                        color: "var(--text-secondary)",
                        textTransform: "uppercase",
                        letterSpacing: "0.5px",
                        marginBottom: "0.5rem",
                      }}
                    >
                      {node.level || "Node Entity"}
                    </div>

                    {node.level === "CONCEPT" && (
                      <div
                        style={{
                          display: "grid",
                          gap: "0.4rem",
                          marginBottom: "0.6rem",
                        }}
                      >
                        <input
                          value={graphNodeDrafts[node.id]?.name || ""}
                          onChange={(e) =>
                            handleGraphDraftChange(node.id, "name", e.target.value)
                          }
                          placeholder="Concept name"
                          style={{
                            fontSize: "0.82rem",
                            border: "1px solid var(--border-light)",
                            borderRadius: "4px",
                            padding: "0.35rem 0.5rem",
                          }}
                        />
                        <textarea
                          value={graphNodeDrafts[node.id]?.description || ""}
                          onChange={(e) =>
                            handleGraphDraftChange(node.id, "description", e.target.value)
                          }
                          placeholder="Concept description"
                          style={{
                            minHeight: "54px",
                            fontSize: "0.78rem",
                            border: "1px solid var(--border-light)",
                            borderRadius: "4px",
                            padding: "0.35rem 0.5rem",
                            resize: "vertical",
                          }}
                        />
                        <button
                          className="btn-solid"
                          style={{ width: "auto", padding: "0.25rem 0.55rem", fontSize: "0.74rem" }}
                          onClick={() => saveGraphConceptDraft(node.id)}
                          disabled={!token || busy}
                        >
                          Save Concept
                        </button>
                      </div>
                    )}

                    {/* Placeholder Editor Tags */}
                    <div
                      style={{
                        display: "flex",
                        gap: "0.5rem",
                        marginTop: "1rem",
                        borderTop: "1px solid var(--border-light)",
                        paddingTop: "0.5rem",
                      }}
                    >
                      {(() => {
                        const flags = graphNodeFlags[node.id] || {
                          highPriority: false,
                          outOfScope: false,
                        };
                        const isConceptNode = node.level === "CONCEPT";
                        return (
                          <>
                      <label
                        style={{
                          fontSize: "0.75rem",
                          display: "flex",
                          alignItems: "center",
                          gap: "0.3rem",
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={Boolean(flags.highPriority)}
                          disabled={!isConceptNode}
                          onChange={(e) =>
                            handleGraphFlagToggle(node, "highPriority", e.target.checked)
                          }
                        />{" "}
                        High Priority
                      </label>
                      <label
                        style={{
                          fontSize: "0.75rem",
                          display: "flex",
                          alignItems: "center",
                          gap: "0.3rem",
                          color: "var(--text-tertiary)",
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={Boolean(flags.outOfScope)}
                          disabled={!isConceptNode}
                          onChange={(e) =>
                            handleGraphFlagToggle(node, "outOfScope", e.target.checked)
                          }
                        />{" "}
                        Out of Scope
                      </label>
                          </>
                        );
                      })()}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div
                style={{
                  padding: "3rem",
                  textAlign: "center",
                  border: "2px dashed var(--border-light)",
                  borderRadius: "8px",
                }}
              >
                <p style={{ color: "var(--text-tertiary)", margin: 0 }}>
                  Fetch node data to visualize graph dimensions.
                </p>
              </div>
            )}
            {graphStatus && (
              <div
                style={{
                  marginTop: "0.75rem",
                  fontSize: "0.82rem",
                  color: "var(--text-secondary)",
                }}
              >
                {graphStatus}
              </div>
            )}
          </div>
        )}

        {/* PD-2: Individual Student Drill-Down */}
        {activeTab === "students" && (
          <div className="widget">
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: "1.5rem",
              }}
            >
              <div>
                <h3 style={{ marginBottom: 0 }}>Student-Wise Reflection</h3>
                <p
                  style={{
                    fontSize: "0.8rem",
                    color: "var(--text-tertiary)",
                    margin: "0.2rem 0 0",
                  }}
                >
                  Per-student view across mastery, activity, risk concepts, and
                  pending HITL workload.
                </p>
              </div>
              <button
                className="btn-solid"
                style={{ width: "auto", padding: "0.4rem 1rem" }}
                onClick={async () => {
                  await loadStudentWiseData();
                }}
                disabled={busy || !token}
              >
                Fetch Roster
              </button>
            </div>

            {studentWiseRows.length > 0 ? (
              <div style={{ display: "flex", gap: "2rem" }}>
                <div
                  style={{
                    flex: "1",
                    minWidth: "220px",
                    borderRight: "1px solid var(--border-light)",
                    paddingRight: "1rem",
                  }}
                >
                  {studentWiseRows.map((s, i) => (
                    <button
                      key={i}
                      onClick={() => setSelectedStudent(s)}
                      style={{
                        width: "100%",
                        textAlign: "left",
                        padding: "0.75rem 1rem",
                        background:
                          selectedStudentDetails?.id === s.id
                            ? "var(--bg-secondary)"
                            : "transparent",
                        border: "none",
                        borderLeft:
                          selectedStudentDetails?.id === s.id
                            ? "3px solid var(--brand)"
                            : "3px solid transparent",
                        cursor: "pointer",
                        borderRadius: "0 4px 4px 0",
                        marginBottom: "0.5rem",
                        fontWeight:
                          selectedStudentDetails?.id === s.id ? 600 : 400,
                      }}
                    >
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          gap: "0.5rem",
                        }}
                      >
                        <span>👤 {s.name}</span>
                        {s.pendingHitl > 0 && (
                          <span
                            style={{
                              fontSize: "0.7rem",
                              padding: "0.1rem 0.4rem",
                              borderRadius: "12px",
                              background: "#fee2e2",
                              color: "#b91c1c",
                            }}
                          >
                            HITL {s.pendingHitl}
                          </span>
                        )}
                      </div>
                      <div
                        style={{
                          fontSize: "0.72rem",
                          marginTop: "0.25rem",
                          color: "var(--text-tertiary)",
                        }}
                      >
                        {s.mastery === null
                          ? "Mastery n/a"
                          : `Mastery ${s.mastery.toFixed(1)}%`}{" "}
                        · Low band {s.lowConfidence}
                      </div>
                    </button>
                  ))}
                </div>
                <div style={{ flex: "3" }}>
                  {selectedStudentDetails ? (
                    <div>
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "baseline",
                          borderBottom: "1px solid var(--border-light)",
                          paddingBottom: "0.5rem",
                          marginBottom: "1rem",
                        }}
                      >
                        <h4 style={{ marginTop: 0, fontSize: "1.3rem" }}>
                          {selectedStudentDetails.name}
                        </h4>
                        <span
                          style={{
                            color: "var(--text-secondary)",
                            fontSize: "0.9rem",
                          }}
                        >
                          {selectedStudentDetails.email}
                        </span>
                      </div>

                      <div
                        style={{
                          display: "grid",
                          gridTemplateColumns: "repeat(4, minmax(120px, 1fr))",
                          gap: "0.75rem",
                          marginBottom: "1rem",
                        }}
                      >
                        <div
                          style={{
                            padding: "0.75rem",
                            border: "1px solid var(--border-light)",
                            borderRadius: "8px",
                            background: "var(--surface-primary)",
                          }}
                        >
                          <div
                            style={{
                              fontSize: "0.72rem",
                              color: "var(--text-tertiary)",
                            }}
                          >
                            Mastery
                          </div>
                          <div style={{ fontSize: "1.15rem", fontWeight: 700 }}>
                            {selectedStudentDetails.mastery === null
                              ? "n/a"
                              : `${selectedStudentDetails.mastery.toFixed(1)}%`}
                          </div>
                        </div>
                        <div
                          style={{
                            padding: "0.75rem",
                            border: "1px solid var(--border-light)",
                            borderRadius: "8px",
                            background: "var(--surface-primary)",
                          }}
                        >
                          <div
                            style={{
                              fontSize: "0.72rem",
                              color: "var(--text-tertiary)",
                            }}
                          >
                            Low-Confidence Concepts
                          </div>
                          <div style={{ fontSize: "1.15rem", fontWeight: 700 }}>
                            {selectedStudentDetails.lowConfidence}
                          </div>
                        </div>
                        <div
                          style={{
                            padding: "0.75rem",
                            border: "1px solid var(--border-light)",
                            borderRadius: "8px",
                            background: "var(--surface-primary)",
                          }}
                        >
                          <div
                            style={{
                              fontSize: "0.72rem",
                              color: "var(--text-tertiary)",
                            }}
                          >
                            Activity Count
                          </div>
                          <div style={{ fontSize: "1.15rem", fontWeight: 700 }}>
                            {selectedStudentDetails.activityCount}
                          </div>
                        </div>
                        <div
                          style={{
                            padding: "0.75rem",
                            border: "1px solid var(--border-light)",
                            borderRadius: "8px",
                            background: "var(--surface-primary)",
                          }}
                        >
                          <div
                            style={{
                              fontSize: "0.72rem",
                              color: "var(--text-tertiary)",
                            }}
                          >
                            Status
                          </div>
                          <div
                            style={{
                              fontSize: "0.95rem",
                              fontWeight: 700,
                              color: selectedStudentDetails.inactive
                                ? "#b91c1c"
                                : "#166534",
                            }}
                          >
                            {selectedStudentDetails.inactive
                              ? "Inactive"
                              : "Active"}
                          </div>
                        </div>
                      </div>

                      <h5
                        style={{ fontSize: "0.9rem", marginBottom: "0.5rem" }}
                      >
                        Student-Wise Detail Table
                      </h5>
                      <div
                        style={{ overflowX: "auto", marginBottom: "1.5rem" }}
                      >
                        <table
                          style={{
                            width: "100%",
                            borderCollapse: "collapse",
                            fontSize: "0.85rem",
                          }}
                        >
                          <thead>
                            <tr
                              style={{
                                background: "var(--bg-secondary)",
                                textAlign: "left",
                              }}
                            >
                              <th style={{ padding: "0.5rem" }}>Student</th>
                              <th style={{ padding: "0.5rem" }}>Mastery</th>
                              <th style={{ padding: "0.5rem" }}>
                                Low Confidence
                              </th>
                              <th style={{ padding: "0.5rem" }}>
                                Pending HITL
                              </th>
                              <th style={{ padding: "0.5rem" }}>Last Active</th>
                            </tr>
                          </thead>
                          <tbody>
                            <tr
                              style={{
                                borderBottom: "1px solid var(--border-light)",
                              }}
                            >
                              <td style={{ padding: "0.5rem" }}>
                                {selectedStudentDetails.name}
                              </td>
                              <td style={{ padding: "0.5rem" }}>
                                {selectedStudentDetails.mastery === null
                                  ? "n/a"
                                  : `${selectedStudentDetails.mastery.toFixed(1)}%`}
                              </td>
                              <td style={{ padding: "0.5rem" }}>
                                {selectedStudentDetails.lowConfidence}
                              </td>
                              <td style={{ padding: "0.5rem" }}>
                                {selectedStudentDetails.pendingHitl}
                              </td>
                              <td style={{ padding: "0.5rem" }}>
                                {selectedStudentDetails.lastActive}
                              </td>
                            </tr>
                          </tbody>
                        </table>
                      </div>

                      <div
                        style={{
                          padding: "1rem",
                          background: "var(--bg-secondary)",
                          borderRadius: "8px",
                          border: "1px solid var(--border-light)",
                          marginBottom: "1rem",
                        }}
                      >
                        <h5
                          style={{ margin: "0 0 0.5rem", fontSize: "0.9rem" }}
                        >
                          At-Risk Concepts
                        </h5>
                        {selectedStudentDetails.riskConcepts.length > 0 ? (
                          <ul
                            style={{
                              margin: 0,
                              paddingLeft: "1.2rem",
                              fontSize: "0.85rem",
                            }}
                          >
                            {selectedStudentDetails.riskConcepts
                              .slice(0, 8)
                              .map((concept, idx) => (
                                <li
                                  key={idx}
                                  style={{ marginBottom: "0.25rem" }}
                                >
                                  {typeof concept === "string"
                                    ? concept
                                    : concept?.name ||
                                      concept?.concept_id ||
                                      "Concept"}
                                </li>
                              ))}
                          </ul>
                        ) : (
                          <p
                            className="feed-empty"
                            style={{ textAlign: "left", padding: 0, margin: 0 }}
                          >
                            No explicit risk concepts available from backend
                            payload yet.
                          </p>
                        )}
                      </div>

                      <div
                        style={{
                          padding: "1.5rem",
                          background: "var(--bg-secondary)",
                          borderRadius: "8px",
                          border: "1px solid var(--border-light)",
                        }}
                      >
                        <h5
                          style={{ margin: "0 0 0.5rem", fontSize: "0.9rem" }}
                        >
                          Private Professor Notes
                        </h5>
                        <p
                          style={{
                            fontSize: "0.8rem",
                            color: "var(--text-tertiary)",
                            marginBottom: "0.5rem",
                          }}
                        >
                          Invisible to the student. Saves as overlay attribute.
                        </p>
                        <textarea
                          value={noteDraftByStudent[selectedStudentDetails.id] || ""}
                          onChange={(e) =>
                            setNoteDraftByStudent((prev) => ({
                              ...prev,
                              [selectedStudentDetails.id]: e.target.value,
                            }))
                          }
                          placeholder="Record engagement markers, struggle points, or manual appraisal..."
                          style={{
                            width: "100%",
                            minHeight: "100px",
                            padding: "0.75rem",
                            border: "1px solid var(--border-light)",
                            borderRadius: "4px",
                            resize: "vertical",
                          }}
                        ></textarea>
                        <div
                          style={{ textAlign: "right", marginTop: "0.5rem" }}
                        >
                          <button
                            className="btn-solid"
                            style={{ width: "auto", padding: "0.4rem 1rem" }}
                            onClick={handleSaveProfessorNote}
                            disabled={busy || !token}
                          >
                            Save Note
                          </button>
                        </div>
                        {noteStatus && (
                          <div
                            style={{
                              marginTop: "0.55rem",
                              fontSize: "0.8rem",
                              color: "var(--text-secondary)",
                            }}
                          >
                            {noteStatus}
                          </div>
                        )}

                        <div
                          style={{
                            marginTop: "0.8rem",
                            borderTop: "1px solid var(--border-light)",
                            paddingTop: "0.6rem",
                          }}
                        >
                          <div
                            style={{
                              fontSize: "0.8rem",
                              fontWeight: 600,
                              color: "var(--text-secondary)",
                              marginBottom: "0.45rem",
                            }}
                          >
                            Note History
                          </div>
                          {(noteHistoryByStudent[selectedStudentDetails.id] || []).length > 0 ? (
                            <div
                              style={{
                                display: "grid",
                                gap: "0.35rem",
                                maxHeight: "160px",
                                overflowY: "auto",
                              }}
                            >
                              {(noteHistoryByStudent[selectedStudentDetails.id] || [])
                                .slice(0, 8)
                                .map((item, idx) => (
                                  <div
                                    key={`${item.created_at || ""}_${idx}`}
                                    style={{
                                      display: "flex",
                                      justifyContent: "space-between",
                                      alignItems: "center",
                                      gap: "0.5rem",
                                      padding: "0.4rem 0.5rem",
                                      border: "1px solid var(--border-light)",
                                      borderRadius: "6px",
                                      background: "var(--surface-primary)",
                                    }}
                                  >
                                    <div style={{ minWidth: 0 }}>
                                      <div
                                        style={{
                                          fontSize: "0.73rem",
                                          color: "var(--text-secondary)",
                                        }}
                                      >
                                        {item.created_at
                                          ? new Date(item.created_at).toLocaleString()
                                          : "n/a"}
                                      </div>
                                      <div
                                        style={{
                                          fontSize: "0.76rem",
                                          whiteSpace: "nowrap",
                                          overflow: "hidden",
                                          textOverflow: "ellipsis",
                                          maxWidth: "290px",
                                        }}
                                      >
                                        {item.annotation || "(empty note)"}
                                      </div>
                                    </div>
                                    <button
                                      className="btn-solid"
                                      style={{ width: "auto", padding: "0.2rem 0.45rem", fontSize: "0.72rem" }}
                                      onClick={() =>
                                        setNoteDraftByStudent((prev) => ({
                                          ...prev,
                                          [selectedStudentDetails.id]: item.annotation || "",
                                        }))
                                      }
                                    >
                                      Load
                                    </button>
                                  </div>
                                ))}
                            </div>
                          ) : (
                            <p className="feed-empty" style={{ textAlign: "left", padding: 0, margin: 0 }}>
                              No saved note versions yet.
                            </p>
                          )}
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div
                      style={{
                        display: "flex",
                        height: "100%",
                        alignItems: "center",
                        justifyContent: "center",
                        color: "var(--text-tertiary)",
                        background: "var(--bg-secondary)",
                        borderRadius: "8px",
                        border: "2px dashed var(--border-light)",
                      }}
                    >
                      Select a roster profile to inspect graph overlay
                      parameters.
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div
                style={{
                  padding: "3rem",
                  textAlign: "center",
                  border: "2px dashed var(--border-light)",
                  borderRadius: "8px",
                }}
              >
                <p className="feed-empty" style={{ margin: 0 }}>
                  Roster unloaded. Fetch students above.
                </p>
              </div>
            )}
          </div>
        )}

        {/* PD-5: Learning Path Configuration */}
        {activeTab === "learning_path" && (
          <div className="widget">
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: "1rem",
              }}
            >
              <div>
                <h3 style={{ marginBottom: 0 }}>Recommended Traversal Path</h3>
                <p
                  style={{
                    fontSize: "0.8rem",
                    color: "var(--text-tertiary)",
                    margin: "0.4rem 0 0",
                  }}
                >
                  Define the core sequence weights for TA and Curriculum agents.
                </p>
              </div>
              <div style={{ display: "flex", gap: "1rem" }}>
                <button
                  className="btn-solid"
                  style={{
                    background: "var(--bg-secondary)",
                    color: "var(--text-primary)",
                    border: "1px solid var(--border-light)",
                    width: "auto",
                    padding: "0.4rem 1rem",
                  }}
                  onClick={loadLearningPathData}
                  disabled={busy || !token}
                >
                  Fetch Active Priority
                </button>
                <button
                  className="btn-solid"
                  style={{ width: "auto", padding: "0.4rem 1rem" }}
                  onClick={publishLearningPath}
                  disabled={busy || !token}
                >
                  Publish Propagation
                </button>
              </div>
            </div>

            <div
              style={{
                marginTop: "2rem",
                padding: "2rem",
                background: "var(--bg-secondary)",
                borderRadius: "8px",
                border: "1px solid var(--border-light)",
              }}
            >
              <div style={{ marginBottom: "1rem" }}>
                <h4
                  style={{
                    margin: "0 0 0.5rem",
                    fontSize: "0.85rem",
                    textTransform: "uppercase",
                    color: "var(--text-secondary)",
                  }}
                >
                  Add Concepts
                </h4>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem" }}>
                  {availableLearningConcepts.length > 0 ? (
                    availableLearningConcepts.slice(0, 40).map((node) => (
                      <button
                        key={node.id}
                        className="btn-solid"
                        style={{
                          width: "auto",
                          padding: "0.25rem 0.5rem",
                          background: "var(--surface-primary)",
                          color: "var(--text-primary)",
                          border: "1px solid var(--border-light)",
                          fontSize: "0.75rem",
                        }}
                        onClick={() => addConceptToLearningPath(node.id)}
                        disabled={!token || busy}
                      >
                        + {node.label || node.id}
                      </button>
                    ))
                  ) : (
                    <span style={{ fontSize: "0.78rem", color: "var(--text-tertiary)" }}>
                      No additional concepts available.
                    </span>
                  )}
                </div>
              </div>

              <div style={{ marginBottom: "1rem" }}>
                <h4
                  style={{
                    margin: "0 0 0.5rem",
                    fontSize: "0.85rem",
                    textTransform: "uppercase",
                    color: "var(--text-secondary)",
                  }}
                >
                  Prerequisite Dependencies
                </h4>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "2fr 2fr 1fr auto",
                    gap: "0.5rem",
                    alignItems: "end",
                    marginBottom: "0.65rem",
                  }}
                >
                  <label style={{ fontSize: "0.78rem" }}>
                    Source concept
                    <select
                      value={edgeDraftSource}
                      onChange={(e) => setEdgeDraftSource(e.target.value)}
                    >
                      <option value="">Select source</option>
                      {learningConceptOptions.map((node) => (
                        <option key={`src_${node.id}`} value={node.id}>
                          {node.label || node.id}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label style={{ fontSize: "0.78rem" }}>
                    Target concept
                    <select
                      value={edgeDraftTarget}
                      onChange={(e) => setEdgeDraftTarget(e.target.value)}
                    >
                      <option value="">Select target</option>
                      {learningConceptOptions.map((node) => (
                        <option key={`tgt_${node.id}`} value={node.id}>
                          {node.label || node.id}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label style={{ fontSize: "0.78rem" }}>
                    Weight
                    <input
                      type="number"
                      min="0.1"
                      max="2"
                      step="0.1"
                      value={edgeDraftWeight}
                      onChange={(e) => setEdgeDraftWeight(e.target.value)}
                    />
                  </label>
                  <button
                    className="btn-solid"
                    style={{ width: "auto", padding: "0.35rem 0.7rem" }}
                    onClick={addLearningPathEdge}
                    disabled={!token || busy}
                  >
                    Add Edge
                  </button>
                </div>

                {learningPathEdges.length > 0 ? (
                  <div style={{ display: "grid", gap: "0.35rem" }}>
                    {learningPathEdges.map((edge, idx) => (
                      <div
                        key={`${edge.source_id}_${edge.target_id}_${idx}`}
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          gap: "0.5rem",
                          padding: "0.45rem 0.65rem",
                          border: "1px solid var(--border-light)",
                          borderRadius: "6px",
                          background: "var(--surface-primary)",
                        }}
                      >
                        <div style={{ fontSize: "0.8rem" }}>
                          <strong>{learningConceptLabelById[edge.source_id] || edge.source_id}</strong>
                          {" -> "}
                          <strong>{learningConceptLabelById[edge.target_id] || edge.target_id}</strong>
                          <span style={{ color: "var(--text-secondary)", marginLeft: "0.45rem" }}>
                            (w={Number(edge.weight || 0.7).toFixed(1)})
                          </span>
                        </div>
                        <button
                          className="btn-solid"
                          style={{
                            width: "auto",
                            padding: "0.2rem 0.45rem",
                            fontSize: "0.72rem",
                            background: "#fff1f2",
                            color: "#9f1239",
                            border: "1px solid #fecdd3",
                          }}
                          onClick={() =>
                            removeLearningPathEdge(edge.source_id, edge.target_id)
                          }
                        >
                          Remove
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="feed-empty" style={{ textAlign: "left", padding: 0 }}>
                    No prerequisite dependencies configured.
                  </p>
                )}
              </div>

              <div
                style={{
                  display: "grid",
                  gap: "0.55rem",
                  paddingBottom: "1rem",
                }}
              >
                {learningSequence.length > 0 ? (
                  learningSequence.map((topic, index) => (
                    <div
                      key={`${topic}_${index}`}
                      draggable
                      onDragStart={() => setDraggingSeqIndex(index)}
                      onDragEnd={() => setDraggingSeqIndex(null)}
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={() => {
                        moveLearningNode(draggingSeqIndex, index);
                        setDraggingSeqIndex(null);
                      }}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        gap: "0.6rem",
                        background: "var(--surface-primary)",
                        border: "1px solid var(--border-light)",
                        borderRadius: "6px",
                        padding: "0.55rem 0.75rem",
                      }}
                    >
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: "0.55rem",
                        }}
                      >
                        <span
                          style={{
                            fontSize: "0.72rem",
                            color: "var(--text-tertiary)",
                            width: "1.3rem",
                          }}
                        >
                          {index + 1}.
                        </span>
                        <span style={{ fontWeight: 600, fontSize: "0.84rem" }}>
                          {learningConceptLabelById[topic] || topic}
                        </span>
                      </div>

                      <div style={{ display: "flex", gap: "0.35rem" }}>
                        <button
                          className="btn-solid"
                          style={{ width: "auto", padding: "0.2rem 0.45rem", fontSize: "0.72rem" }}
                          onClick={() =>
                            index > 0 && moveLearningNode(index, index - 1)
                          }
                          disabled={index === 0 || busy}
                        >
                          Up
                        </button>
                        <button
                          className="btn-solid"
                          style={{ width: "auto", padding: "0.2rem 0.45rem", fontSize: "0.72rem" }}
                          onClick={() =>
                            index < learningSequence.length - 1 &&
                            moveLearningNode(index, index + 1)
                          }
                          disabled={index === learningSequence.length - 1 || busy}
                        >
                          Down
                        </button>
                        <button
                          className="btn-solid"
                          style={{
                            width: "auto",
                            padding: "0.2rem 0.45rem",
                            fontSize: "0.72rem",
                            background: "#fff1f2",
                            color: "#9f1239",
                            border: "1px solid #fecdd3",
                          }}
                          onClick={() => removeConceptFromLearningPath(topic)}
                          disabled={busy}
                        >
                          Remove
                        </button>
                      </div>
                    </div>
                  ))
                ) : (
                  <p
                    className="feed-empty"
                    style={{ textAlign: "left", padding: 0 }}
                  >
                    No persisted learning path found yet. Fetch active priority
                    to load from backend.
                  </p>
                )}
              </div>
              <p
                style={{
                  fontSize: "0.8rem",
                  color: "var(--text-tertiary)",
                  textAlign: "center",
                  marginTop: "1rem",
                }}
              >
                Drag rows to reorder, then publish to persist curriculum sequencing.
              </p>
              {graphStatus && (
                <p
                  style={{
                    marginTop: "0.75rem",
                    marginBottom: 0,
                    fontSize: "0.82rem",
                    color: "var(--text-secondary)",
                    textAlign: "center",
                  }}
                >
                  {graphStatus}
                </p>
              )}
            </div>
          </div>
        )}

        {gradeDraft.open && (
          <div
            style={{
              position: "fixed",
              inset: 0,
              background: "rgba(15,23,42,0.35)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              padding: "1rem",
              zIndex: 90,
            }}
          >
            <div
              style={{
                width: "min(560px, 96vw)",
                background: "var(--surface-primary)",
                border: "1px solid var(--border-light)",
                borderRadius: "10px",
                padding: "1rem",
              }}
            >
              <h4 style={{ marginTop: 0, marginBottom: "0.5rem" }}>
                Manual Grade Submission
              </h4>
              <p style={{ fontSize: "0.8rem", color: "var(--text-secondary)" }}>
                Record ID: {gradeDraft.recordId}
              </p>
              <div style={{ display: "grid", gap: "0.65rem" }}>
                <label style={{ fontSize: "0.82rem" }}>
                  Action
                  <select
                    value={gradeDraft.action}
                    onChange={(e) =>
                      setGradeDraft((prev) => ({ ...prev, action: e.target.value }))
                    }
                  >
                    <option value="approve">Approve</option>
                    <option value="reject">Reject</option>
                  </select>
                </label>
                <label style={{ fontSize: "0.82rem" }}>
                  Grade override
                  <input
                    type="number"
                    min="0"
                    max="100"
                    step="0.1"
                    value={gradeDraft.modified_grade}
                    onChange={(e) =>
                      setGradeDraft((prev) => ({
                        ...prev,
                        modified_grade: e.target.value,
                      }))
                    }
                    disabled={gradeDraft.action === "reject"}
                    placeholder="Optional"
                  />
                </label>
                <label style={{ fontSize: "0.82rem" }}>
                  Feedback override
                  <textarea
                    value={gradeDraft.modified_feedback}
                    onChange={(e) =>
                      setGradeDraft((prev) => ({
                        ...prev,
                        modified_feedback: e.target.value,
                      }))
                    }
                    placeholder="Optional professor feedback"
                    style={{ minHeight: "92px", resize: "vertical" }}
                  />
                </label>
              </div>
              <div
                style={{
                  marginTop: "0.9rem",
                  display: "flex",
                  justifyContent: "flex-end",
                  gap: "0.5rem",
                }}
              >
                <button
                  className="btn-solid"
                  style={{
                    width: "auto",
                    padding: "0.35rem 0.75rem",
                    background: "var(--bg-secondary)",
                    color: "var(--text-primary)",
                    border: "1px solid var(--border-light)",
                  }}
                  onClick={() => setGradeDraft((prev) => ({ ...prev, open: false }))}
                >
                  Cancel
                </button>
                <button
                  className="btn-solid"
                  style={{ width: "auto", padding: "0.35rem 0.75rem" }}
                  onClick={submitManualGrade}
                  disabled={busy}
                >
                  Submit Grade
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
