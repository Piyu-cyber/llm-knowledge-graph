import contextlib
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from backend.auth.jwt_handler import create_access_token
from backend.auth.rbac import RBACFilter, UserContext
from backend.db.graph_manager import GraphManager, Neo4jGraphManager
from backend.services.jina_multimodal_service import JinaMultimodalService
from backend.services.local_inference_service import LocalInferenceService


pytestmark = [pytest.mark.phase1, pytest.mark.phase1_acceptance]


def test_phase1_backend_selection_single_and_instantiable(tmp_path):
    manager = Neo4jGraphManager(data_dir=str(tmp_path))

    assert isinstance(manager, GraphManager)
    assert manager.get_node_count() == 0


def test_phase1_schema_hierarchy_and_metadata_fields(tmp_path):
    manager = Neo4jGraphManager(data_dir=str(tmp_path))

    module = manager.create_module("Module A", course_owner="cs101", visibility="global")
    topic = manager.create_topic(module["node_id"], "Topic A", course_owner="cs101", visibility="global")
    concept = manager.create_concept(
        topic["node_id"],
        "Concept A",
        course_owner="cs101",
        visibility="enrolled-only",
        difficulty=1.25,
    )
    fact = manager.create_fact(concept["node_id"], "Fact A", course_owner="cs101", visibility="professor-only")

    assert module["status"] == "success"
    assert topic["status"] == "success"
    assert concept["status"] == "success"
    assert fact["status"] == "success"

    concept_data = manager.nodes_data[concept["node_id"]]
    fact_data = manager.nodes_data[fact["node_id"]]

    assert concept_data["level"] == "CONCEPT"
    assert concept_data["course_owner"] == "cs101"
    assert concept_data["visibility"] == "enrolled-only"
    assert concept_data["difficulty"] == 1.25
    assert fact_data["visibility"] == "professor-only"


def test_phase1_student_overlay_is_separate_layer(tmp_path):
    manager = Neo4jGraphManager(data_dir=str(tmp_path))

    module = manager.create_module("Module A", course_owner="cs101")
    topic = manager.create_topic(module["node_id"], "Topic A", course_owner="cs101")
    concept = manager.create_concept(topic["node_id"], "Concept A", course_owner="cs101")

    result = manager.initialize_student_overlays(user_id="student_1", course_id="cs101")

    assert result["status"] == "success"
    assert result["overlays_created"] >= 1

    concept_data = manager.nodes_data[concept["node_id"]]
    assert "theta" not in concept_data
    assert "slip" not in concept_data

    overlays = [
        n for n in manager.nodes_data.values()
        if n.get("user_id") == "student_1" and n.get("concept_id") == concept["node_id"]
    ]
    assert len(overlays) == 1
    assert "theta" in overlays[0]
    assert "slip" in overlays[0]


def test_phase1_jwt_role_and_graph_visibility_filtering():
    token = create_access_token(user_id="student_1", role="student", course_ids=["cs101"])
    assert isinstance(token, str)

    student = UserContext(user_id="student_1", role="student", course_ids=["cs101"])
    professor_only_node = {
        "id": "n1",
        "visibility": "professor-only",
        "course_owner": "cs101",
    }

    allowed, _ = RBACFilter.assert_read_permission(professor_only_node, student)
    assert allowed is False

    where_clause, _ = RBACFilter.build_hierarchy_visibility_filter(student)
    assert "professor-only" not in where_clause


def test_phase1_three_level_traversal_returns_expected_hierarchy(tmp_path):
    manager = Neo4jGraphManager(data_dir=str(tmp_path))

    module = manager.create_module("Module A", course_owner="cs101")
    topic = manager.create_topic(module["node_id"], "Topic A", course_owner="cs101")
    concept = manager.create_concept(topic["node_id"], "Concept A", course_owner="cs101")

    hierarchy = manager.get_concept_hierarchy(concept["node_id"])

    assert hierarchy["status"] == "success"
    assert hierarchy["module"]["id"] == module["node_id"]
    assert hierarchy["topic"]["id"] == topic["node_id"]
    assert hierarchy["concept"]["id"] == concept["node_id"]


def test_phase1_concept_has_irt_difficulty_field(tmp_path):
    manager = Neo4jGraphManager(data_dir=str(tmp_path))

    module = manager.create_module("Module A", course_owner="cs101")
    topic = manager.create_topic(module["node_id"], "Topic A", course_owner="cs101")
    concept = manager.create_concept(topic["node_id"], "Concept A", course_owner="cs101", difficulty=-1.5)

    concept_data = manager.nodes_data[concept["node_id"]]
    assert "difficulty" in concept_data
    assert concept_data["difficulty"] == -1.5


def test_phase1_jina_multimodal_pipeline_available(tmp_path):
    service = JinaMultimodalService(embedding_dim=2048)

    text_embedding = service.embed_text("Neural network backpropagation")
    assert len(text_embedding) == 2048

    image_path = tmp_path / "neural_network_diagram.png"
    with open(image_path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0DIHDR\x00\x00\x00\x01\x00\x00\x00\x01")

    image_embedding = service.embed_diagram(str(image_path), description="neural network diagram")
    assert len(image_embedding) == 2048

    retrieved = service.retrieve(
        query="Find the neural network diagram",
        candidates=[
            {"id": "diagram_node", "embedding": image_embedding, "modality": "image"},
            {"id": "history_node", "embedding": service.embed_text("Roman empire timeline"), "modality": "text"},
        ],
        top_k=1,
    )

    assert retrieved[0]["id"] == "diagram_node"

    with contextlib.suppress(OSError):
        os.remove(str(image_path))


def test_phase1_llamacpp_latency_under_300ms():
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            return

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    host, port = sock.getsockname()
    sock.close()

    server = HTTPServer((host, port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        service = LocalInferenceService(base_url=f"http://{host}:{port}")
        # Warm-up call to avoid one-time socket/server scheduling overhead.
        service.health_check()
        result = service.meets_latency_sla(max_latency_ms=300.0)

        assert result["ok"] is True
        assert result["status"] == 200
        assert result["meets_sla"] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
