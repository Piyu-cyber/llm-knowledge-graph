import pytest
from typing import Any, Dict, cast

from backend.auth.rbac import UserContext
from backend.db.graph_manager import Neo4jGraphManager
from backend.services.cognitive_engine import CognitiveEngine
from backend.services.graph_service import GraphService


pytestmark = [pytest.mark.phase3, pytest.mark.phase3_acceptance]


class _FakeBackgroundTasks:
    def __init__(self):
        self.tasks = []

    def add_task(self, func, *args, **kwargs):
        self.tasks.append((func, args, kwargs))

    def run_all(self):
        for func, args, kwargs in self.tasks:
            func(*args, **kwargs)


def _make_graph(tmp_path):
    manager = Neo4jGraphManager(data_dir=str(tmp_path / "data"))
    service = GraphService(manager)

    module = service.create_module(name="ML", course_owner="cs101", visibility="enrolled-only")
    topic = service.create_topic(
        module_id=module["node_id"],
        name="Optimization",
        course_owner="cs101",
        visibility="enrolled-only",
    )

    foundation = service.create_concept(
        topic_id=topic["node_id"],
        name="Gradient Descent Foundations",
        course_owner="cs101",
        description="Foundational optimization and learning rate basics",
        visibility="enrolled-only",
    )
    intermediate = service.create_concept(
        topic_id=topic["node_id"],
        name="Optimization Dynamics",
        course_owner="cs101",
        description="Momentum and convergence intuition",
        visibility="enrolled-only",
    )
    advanced = service.create_concept(
        topic_id=topic["node_id"],
        name="Advanced Backpropagation",
        course_owner="cs101",
        description="Advanced neural optimization and backpropagation",
        visibility="enrolled-only",
    )

    assert service.add_prerequisite(advanced["node_id"], intermediate["node_id"])["status"] == "success"
    assert service.add_prerequisite(intermediate["node_id"], foundation["node_id"])["status"] == "success"

    return service, manager, foundation["node_id"], intermediate["node_id"], advanced["node_id"]


def test_phase3_overlay_initialized_async_on_enrollment(tmp_path):
    service, manager, foundation_id, intermediate_id, advanced_id = _make_graph(tmp_path)

    bg = _FakeBackgroundTasks()
    queued = service.enqueue_enrollment_overlay_init("student_1", "cs101", bg)

    assert queued["status"] == "queued"
    assert queued["overlays_created"] == 0
    assert manager.get_student_overlay("student_1", foundation_id) is None

    bg.run_all()

    overlays = [
        manager.get_student_overlay("student_1", foundation_id),
        manager.get_student_overlay("student_1", intermediate_id),
        manager.get_student_overlay("student_1", advanced_id),
    ]
    assert all(o is not None for o in overlays)
    overlays_nn = [cast(Dict[str, Any], o) for o in overlays]
    assert all(abs(float(o["theta"]) - 0.0) < 1e-9 for o in overlays_nn)
    assert all(abs(float(o["slip"]) - 0.1) < 1e-9 for o in overlays_nn)


def test_phase3_personalized_walk_low_vs_high_mastery(tmp_path):
    service, manager, foundation_id, intermediate_id, advanced_id = _make_graph(tmp_path)

    # Low mastery student should be pulled toward prerequisites.
    manager.create_student_overlay("student_low", foundation_id, theta=0.15, slip=0.1, guess=0.1)
    manager.create_student_overlay("student_low", intermediate_id, theta=0.20, slip=0.1, guess=0.1)
    manager.create_student_overlay("student_low", advanced_id, theta=0.30, slip=0.1, guess=0.1)

    # High mastery student should be pulled toward advanced concepts.
    manager.create_student_overlay("student_high", foundation_id, theta=0.95, slip=0.1, guess=0.1)
    manager.create_student_overlay("student_high", intermediate_id, theta=0.90, slip=0.1, guess=0.1)
    manager.create_student_overlay("student_high", advanced_id, theta=0.85, slip=0.1, guess=0.1)

    low_ctx = UserContext(user_id="student_low", role="student", course_ids=["cs101"])
    high_ctx = UserContext(user_id="student_high", role="student", course_ids=["cs101"])

    query = "advanced backpropagation optimization"
    low_results = service.personalized_graph_walk(query, low_ctx, student_id="student_low", top_k=3)
    high_results = service.personalized_graph_walk(query, high_ctx, student_id="student_high", top_k=3)

    low_ranks = {item["id"]: idx for idx, item in enumerate(low_results)}
    high_ranks = {item["id"]: idx for idx, item in enumerate(high_results)}

    assert foundation_id in low_ranks
    assert advanced_id in low_ranks
    assert foundation_id in high_ranks
    assert advanced_id in high_ranks

    assert low_ranks[foundation_id] < low_ranks[advanced_id]
    assert high_ranks[advanced_id] < high_ranks[foundation_id]


def test_phase3_bayesian_update_slip_vs_knowledge_gap_cases(tmp_path):
    service, manager, foundation_id, intermediate_id, advanced_id = _make_graph(tmp_path)

    engine = CognitiveEngine()
    engine.graph = manager
    engine.mastery_threshold = 0.8

    # Case 1: Slip (all prerequisites high).
    manager.create_student_overlay("student_case1", foundation_id, theta=0.95, slip=0.1, guess=0.1)
    manager.create_student_overlay("student_case1", intermediate_id, theta=0.92, slip=0.1, guess=0.1)
    manager.create_student_overlay("student_case1", advanced_id, theta=0.80, slip=0.10, guess=0.1)

    case1_before = manager.get_student_overlay("student_case1", advanced_id)
    case1 = engine.update_student_overlay("student_case1", advanced_id, answered_correctly=False)
    case1_after = manager.get_student_overlay("student_case1", advanced_id)
    assert case1_before is not None
    assert case1_after is not None

    assert case1["status"] == "success"
    assert case1["event_type"] == "slip"
    assert case1["updated_concept_id"] == advanced_id
    assert abs(float(case1_after["theta"]) - float(case1_before["theta"])) < 1e-9
    assert float(case1_after["slip"]) > float(case1_before["slip"])

    # Case 2: Knowledge gap with weak prerequisite.
    manager.create_student_overlay("student_case2", foundation_id, theta=0.35, slip=0.1, guess=0.1)
    manager.create_student_overlay("student_case2", intermediate_id, theta=0.90, slip=0.1, guess=0.1)
    manager.create_student_overlay("student_case2", advanced_id, theta=0.85, slip=0.1, guess=0.1)

    case2_prereq_before = manager.get_student_overlay("student_case2", foundation_id)
    case2_current_before = manager.get_student_overlay("student_case2", advanced_id)
    case2 = engine.update_student_overlay("student_case2", advanced_id, answered_correctly=False)
    case2_prereq_after = manager.get_student_overlay("student_case2", foundation_id)
    case2_current_after = manager.get_student_overlay("student_case2", advanced_id)
    assert case2_prereq_before is not None
    assert case2_current_before is not None
    assert case2_prereq_after is not None
    assert case2_current_after is not None

    assert case2["status"] == "success"
    assert case2["event_type"] == "knowledge_gap"
    assert case2["updated_concept_id"] == foundation_id
    assert float(case2_prereq_after["theta"]) < float(case2_prereq_before["theta"])
    assert abs(float(case2_current_after["theta"]) - float(case2_current_before["theta"])) < 1e-9

    # Case 3: Knowledge gap should penalize the weakest prerequisite.
    manager.create_student_overlay("student_case3", foundation_id, theta=0.70, slip=0.1, guess=0.1)
    manager.create_student_overlay("student_case3", intermediate_id, theta=0.20, slip=0.1, guess=0.1)
    manager.create_student_overlay("student_case3", advanced_id, theta=0.80, slip=0.1, guess=0.1)

    case3 = engine.update_student_overlay("student_case3", advanced_id, answered_correctly=False)

    assert case3["status"] == "success"
    assert case3["event_type"] == "knowledge_gap"
    assert case3["updated_concept_id"] == intermediate_id


def test_phase3_rbac_filters_professor_only_as_nonexistent(tmp_path):
    manager = Neo4jGraphManager(data_dir=str(tmp_path / "data"))
    service = GraphService(manager)

    module = service.create_module(name="Private", course_owner="cs101", visibility="professor-only")
    topic = service.create_topic(
        module_id=module["node_id"],
        name="Staff",
        course_owner="cs101",
        visibility="professor-only",
    )
    private_concept = service.create_concept(
        topic_id=topic["node_id"],
        name="Professor Rubric Key",
        course_owner="cs101",
        description="Professor-only internal grading heuristics",
        visibility="professor-only",
    )

    assert private_concept["status"] == "success"

    student_ctx = UserContext(user_id="student_9", role="student", course_ids=["cs101"])
    result = service.personalized_graph_walk(
        "professor rubric key",
        student_ctx,
        student_id="student_9",
        top_k=3,
    )

    assert result == []


def test_phase3_cross_course_structured_edges_disallowed(tmp_path):
    manager = Neo4jGraphManager(data_dir=str(tmp_path / "data"))
    service = GraphService(manager)

    module1 = service.create_module(name="Course1", course_owner="cs101", visibility="enrolled-only")
    topic1 = service.create_topic(module1["node_id"], "T1", course_owner="cs101", visibility="enrolled-only")
    concept1 = service.create_concept(topic1["node_id"], "C1", course_owner="cs101", visibility="enrolled-only")

    module2 = service.create_module(name="Course2", course_owner="math201", visibility="enrolled-only")
    topic2 = service.create_topic(module2["node_id"], "T2", course_owner="math201", visibility="enrolled-only")
    concept2 = service.create_concept(topic2["node_id"], "C2", course_owner="math201", visibility="enrolled-only")

    rel = service.add_prerequisite(concept1["node_id"], concept2["node_id"])
    assert rel["status"] == "error"
    assert "Cross-course" in rel["message"]
