import time
from concurrent.futures import ThreadPoolExecutor

import pytest  # pyright: ignore[reportMissingImports]
from fastapi.testclient import TestClient

import backend.app as app_module
from backend.agents.state import AgentState
from backend.auth.jwt_handler import create_access_token
from backend.db.graph_manager import Neo4jGraphManager
from backend.services.background_job_queue import BackgroundJobQueue
from backend.services.compliance_service import ComplianceService
from backend.services.llm_router import LLMRouter


pytestmark = [pytest.mark.phase6, pytest.mark.phase6_acceptance]


class _FakeGraph:
    def invoke(self, state: AgentState) -> AgentState:
        state.messages.append({"role": "assistant", "content": "Tutor response generated."})
        state.active_agent = "ta_agent"
        state.metadata["intent"] = "academic_query"
        return state


def _auth_header(role: str, user_id: str, course_ids=None):
    token = create_access_token(user_id=user_id, role=role, course_ids=course_ids or [])
    return {"Authorization": f"Bearer {token}"}


def test_phase6_llmrouter_cascading_failover_and_recovery(monkeypatch):
    router = LLMRouter()

    # Force all clouds as eligible and then fail with simulated rate-limit.
    router.providers["groq"].available = True
    router.providers["cerebras"].available = True
    router.providers["nim"].available = True

    router.provider_callers["groq"] = lambda _p: (_ for _ in ()).throw(RuntimeError("429 groq"))
    router.provider_callers["cerebras"] = lambda _p: (_ for _ in ()).throw(RuntimeError("429 cerebras"))
    router.provider_callers["nim"] = lambda _p: (_ for _ in ()).throw(RuntimeError("429 nim"))
    router.provider_callers["local"] = lambda p: f"local:{p}"

    degraded = router.route("ta_tutoring", "teach me dynamic programming")
    assert degraded["status"] == "success"
    assert degraded["provider"] == "local"
    assert degraded["reduced_mode"] is True
    assert degraded["reduced_mode_notification"] is not None

    health = router.health_status()
    assert health["providers"]["groq"]["available"] is False
    assert health["providers"]["cerebras"]["available"] is False
    assert health["providers"]["nim"]["available"] is False

    # Backoff elapsed and cloud recovered.
    router.providers["groq"].backoff_until_unix = time.time() - 1
    router.provider_callers["groq"] = lambda p: f"groq:{p}"

    recovered = router.route("ta_tutoring", "teach me greedy algorithms")
    assert recovered["provider"] == "groq"
    assert recovered["reduced_mode"] is False


def test_phase6_router_reduced_mode_is_user_visible_in_chat(monkeypatch):
    router = LLMRouter()
    router.providers["groq"].available = True
    router.providers["cerebras"].available = True
    router.providers["nim"].available = True
    router.provider_callers["groq"] = lambda _p: (_ for _ in ()).throw(RuntimeError("429"))
    router.provider_callers["cerebras"] = lambda _p: (_ for _ in ()).throw(RuntimeError("429"))
    router.provider_callers["nim"] = lambda _p: (_ for _ in ()).throw(RuntimeError("429"))
    router.provider_callers["local"] = lambda _p: "local fallback"

    monkeypatch.setattr(app_module, "llm_router", router)
    monkeypatch.setattr(app_module, "omniprof_graph", _FakeGraph())

    client = TestClient(app_module.app)
    headers = _auth_header("student", "student_6", ["cs101"])

    resp = client.post(
        "/chat",
        headers=headers,
        json={"message": "Explain recursion", "session_id": "sess_p6", "course_id": "cs101"},
    )
    assert resp.status_code == 200
    meta = resp.json().get("metadata", {})
    assert meta.get("reduced_mode") is True
    assert "Reduced mode" in str(meta.get("reduced_mode_notification"))


def test_phase6_load_concurrency_30_sessions_ttft_and_latencies(tmp_path):
    router = LLMRouter()
    router.providers["groq"].available = False
    router.providers["cerebras"].available = False
    router.providers["nim"].available = False
    router.provider_callers["local"] = lambda p: f"local:{p}"

    tasks = [
        "ta_tutoring",
        "evaluator_defence",
        "curriculum_reasoning",
        "intent_classification",
        "memory_summarisation",
    ]

    def one_request(i: int):
        task = tasks[i % len(tasks)]
        return router.route(task, f"request-{i}")

    with ThreadPoolExecutor(max_workers=30) as pool:
        results = list(pool.map(one_request, range(60)))

    ttfts = [r["ttft_ms"] for r in results if r["status"] == "success"]
    under_500 = [x for x in ttfts if x < 500.0]
    assert len(ttfts) == 60
    assert len(under_500) >= int(0.8 * len(ttfts))

    # Memory and graph latency sampling under light contention.
    manager = Neo4jGraphManager(data_dir=str(tmp_path / "data"))
    m = manager.create_module("M", course_owner="cs101")
    t = manager.create_topic(m["node_id"], "T", course_owner="cs101")
    c1 = manager.create_concept(t["node_id"], "C1", course_owner="cs101")
    c2 = manager.create_concept(t["node_id"], "C2", course_owner="cs101")
    manager.add_prerequisite(c2["node_id"], c1["node_id"], weight=1.0)
    manager.create_student_overlay("student_perf", c1["node_id"], theta=0.1)

    start_mem = time.perf_counter()
    for _ in range(50):
        _ = manager.get_student_overlay("student_perf", c1["node_id"])
    mem_ms = ((time.perf_counter() - start_mem) * 1000.0) / 50

    start_graph = time.perf_counter()
    for _ in range(50):
        _ = manager.get_related_concepts(c2["node_id"])
    graph_ms = ((time.perf_counter() - start_graph) * 1000.0) / 50

    assert mem_ms < 500.0
    assert graph_ms < 500.0


def test_phase6_background_jobs_stability_and_dead_letter(tmp_path):
    queue = BackgroundJobQueue(data_dir=str(tmp_path / "jobs"), max_attempts=2)

    manager = Neo4jGraphManager(data_dir=str(tmp_path / "graph"))
    m = manager.create_module("M", course_owner="cs101")
    t = manager.create_topic(m["node_id"], "T", course_owner="cs101")
    c = manager.create_concept(t["node_id"], "C", course_owner="cs101")
    manager.create_student_overlay("student_bg", c["node_id"], theta=0.2)
    before = manager.get_student_overlay("student_bg", c["node_id"])
    assert before is not None

    for i in range(30):
        queue.enqueue("ok_job", {"idx": i})
    for i in range(8):
        queue.enqueue("fail_job", {"idx": i})

    def _ok(_payload):
        return None

    def _fail(_payload):
        raise RuntimeError("forced failure")

    handlers = {
        "ok_job": _ok,
        "fail_job": _fail,
    }

    base_now = time.time()
    for step in range(4):
        queue.run_due_jobs(handlers=handlers, now_unix=base_now + (step * 20))

    stats = queue.stats()
    assert stats["dead_letter_depth"] >= 8
    assert stats["queue_depth"] == 0

    after = manager.get_student_overlay("student_bg", c["node_id"])
    assert after is not None
    assert before["id"] == after["id"]
    assert before["concept_id"] == after["concept_id"]


def test_phase6_compliance_and_phase6_endpoints(tmp_path, monkeypatch):
    compliance = ComplianceService(data_dir=str(tmp_path / "compliance"))
    router = LLMRouter()
    jobs = BackgroundJobQueue(data_dir=str(tmp_path / "queue"), max_attempts=2)

    monkeypatch.setattr(app_module, "compliance_service", compliance)
    monkeypatch.setattr(app_module, "llm_router", router)
    monkeypatch.setattr(app_module, "background_job_queue", jobs)

    client = TestClient(app_module.app)
    admin_headers = _auth_header("admin", "admin_1", ["cs101"])
    prof_headers = _auth_header("professor", "prof_1", ["cs101"])

    health = client.get("/llm-router/health", headers=prof_headers)
    assert health.status_code == 200
    assert "providers" in health.json()

    route = client.post(
        "/llm-router/route",
        headers=prof_headers,
        json={"task": "intent_classification", "prompt": "classify intent"},
    )
    assert route.status_code == 200

    jobs.enqueue("missing_handler", {"x": 1})
    drained = client.post("/background-jobs/drain", headers=admin_headers)
    assert drained.status_code == 200

    stats = client.get("/background-jobs/stats", headers=admin_headers)
    assert stats.status_code == 200
    assert "dead_letter_depth" in stats.json()

    compliance_status = client.get("/compliance/status", headers=admin_headers)
    assert compliance_status.status_code == 200
    payload = compliance_status.json()
    assert payload["ferpa_gdpr_pass"] is True
    assert payload["audit_log_operational"] is True
