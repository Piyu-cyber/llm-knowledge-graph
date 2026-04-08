import os

import pytest  # pyright: ignore[reportMissingImports]
from fastapi.testclient import TestClient

import backend.app as app_module
from backend.auth.jwt_handler import create_access_token
from backend.db.vector_store import LocalVectorStore
from backend.services.integrity_policy_service import IntegrityPolicyService
from backend.services.llm_router import LLMRouter
from backend.services.nondeterminism_service import NondeterminismService


pytestmark = [pytest.mark.phase6, pytest.mark.phase6_acceptance]


def _auth_header(role: str, user_id: str, course_ids=None):
    token = create_access_token(user_id=user_id, role=role, course_ids=course_ids or [])
    return {"Authorization": f"Bearer {token}"}


def test_phase6_vector_store_upsert_query_and_reload(tmp_path):
    store = LocalVectorStore(dim=4, data_dir=str(tmp_path), index_name="phase6")
    store.upsert("a", [1.0, 0.0, 0.0, 0.0], metadata={"course_id": "cs101"}, text="alpha")
    store.upsert("b", [0.0, 1.0, 0.0, 0.0], metadata={"course_id": "cs101"}, text="beta")

    hits = store.query([1.0, 0.0, 0.0, 0.0], top_k=2)
    assert len(hits) == 2
    assert hits[0]["id"] == "a"
    assert store.count() == 2

    reloaded = LocalVectorStore(dim=4, data_dir=str(tmp_path), index_name="phase6")
    assert reloaded.count() == 2
    reloaded_hits = reloaded.query([0.0, 1.0, 0.0, 0.0], top_k=1)
    assert reloaded_hits[0]["id"] == "b"


def test_phase6_nondeterminism_service_writes_artifact(tmp_path):
    router = LLMRouter()
    router.providers["groq"].available = False
    router.providers["cerebras"].available = False
    router.providers["nim"].available = False
    router.provider_callers["local"] = lambda _p: "stable-local"

    service = NondeterminismService(data_dir=str(tmp_path))
    result = service.run_router_diff(router, "ta_tutoring", "hello", runs=4)

    assert result["status"] == "success"
    assert result["runs"] == 4
    assert result["stable"] is True
    assert os.path.exists(result["artifact_path"])


def test_phase6_llmrouter_local_fallback_when_local_server_unavailable(monkeypatch):
    router = LLMRouter()

    def _boom(_prompt):
        raise RuntimeError("local down")

    monkeypatch.setattr(router.local_inference, "generate", _boom)

    result = router.route("intent_classification", "classify this")
    assert result["status"] == "success"
    assert result["provider"] == "local"
    assert str(result["text"]).startswith("[local]")


def test_phase6_integrity_policy_endpoints_apply_runtime_threshold(tmp_path, monkeypatch):
    policy_service = IntegrityPolicyService(data_dir=str(tmp_path))

    class _FakeIntegrityAgent:
        def __init__(self):
            self.min_token_threshold = 500

        def set_min_token_threshold(self, value: int):
            self.min_token_threshold = int(value)

    class _FakeGraph:
        def __init__(self):
            self.integrity_agent = _FakeIntegrityAgent()

    fake_graph = _FakeGraph()

    monkeypatch.setattr(app_module, "integrity_policy_service", policy_service)
    monkeypatch.setattr(app_module, "omniprof_graph", fake_graph)

    client = TestClient(app_module.app)
    prof_headers = _auth_header("professor", "prof_policy", ["cs101"])

    current = client.get("/integrity/policy", headers=prof_headers)
    assert current.status_code == 200
    assert current.json()["min_token_threshold"] >= 100

    updated = client.patch(
        "/integrity/policy",
        headers=prof_headers,
        json={"min_token_threshold": 777},
    )
    assert updated.status_code == 200
    payload = updated.json()
    assert payload["min_token_threshold"] == 777
    assert payload["applied_to_active_graph"] is True
    assert fake_graph.integrity_agent.min_token_threshold == 777


def test_phase6_nondeterminism_endpoint_generates_artifact(tmp_path, monkeypatch):
    router = LLMRouter()
    router.providers["groq"].available = False
    router.providers["cerebras"].available = False
    router.providers["nim"].available = False
    router.provider_callers["local"] = lambda _p: "stable-local"

    monkeypatch.setattr(app_module, "llm_router", router)
    monkeypatch.setattr(app_module, "nondeterminism_service", NondeterminismService(data_dir=str(tmp_path)))

    client = TestClient(app_module.app)
    admin_headers = _auth_header("admin", "admin_ndiff", ["cs101"])
    response = client.post(
        "/diagnostics/nondeterminism/run",
        headers=admin_headers,
        json={"task": "ta_tutoring", "prompt": "Explain BFS", "runs": 3},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["runs"] == 3
    assert payload["stable"] is True
    assert os.path.exists(payload["artifact_path"])
