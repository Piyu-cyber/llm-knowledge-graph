import json
from datetime import datetime, timezone

import pytest  # pyright: ignore[reportMissingImports]
from fastapi.testclient import TestClient

import backend.app as app_module
from backend.agents.state import AgentState
from backend.auth.jwt_handler import create_access_token
from backend.db.graph_manager import Neo4jGraphManager


pytestmark = [pytest.mark.phase5, pytest.mark.phase5_acceptance]


class _FakeGraph:
    def __init__(self, manager):
        self.manager = manager

    def invoke(self, state: AgentState) -> AgentState:
        text = state.current_input.lower()
        intent = "submission_defence" if any(k in text for k in ["defence", "defense", "submission"]) else "academic_query"
        state.metadata["intent"] = intent

        if intent == "submission_defence":
            rows = self.manager._read_json_list(self.manager._defence_records_path())
            target = None
            for row in reversed(rows):
                if row.get("student_id") == state.student_id and row.get("status") == "pending_defence":
                    target = row
                    break
            if target is None:
                target = {
                    "id": f"sub_{datetime.now().timestamp()}",
                    "student_id": state.student_id,
                    "course_id": state.metadata.get("course_id", "cs101"),
                    "status": "pending_defence",
                }
                self.manager.create_defence_record(target)

            transcript = [
                {"role": "student", "content": state.current_input},
                {"role": "assistant", "content": "Please justify your design trade-offs."},
            ]
            self.manager.update_defence_record(
                target["id"],
                {
                    "status": "pending_professor_review",
                    "submission_summary": "Student submitted assignment and completed defence.",
                    "transcript": transcript,
                    "ai_recommended_grade": 0.82,
                    "ai_grade_justification": "Sound reasoning with minor clarity gaps.",
                    "ai_feedback": "Good structure, clarify assumptions.",
                    "integrity_score": 0.91,
                    "integrity_sample_size": 8,
                },
            )
            self.manager.enqueue_hitl_review(
                {
                    "defence_record_id": target["id"],
                    "course_id": target.get("course_id") or "cs101",
                    "submission_summary": "Student submitted assignment and completed defence.",
                    "transcript": transcript,
                    "ai_recommended_grade": 0.82,
                    "ai_grade_justification": "Sound reasoning with minor clarity gaps.",
                    "ai_feedback": "Good structure, clarify assumptions.",
                    "integrity_score": 0.91,
                    "integrity_sample_size": 8,
                }
            )
            state.metadata["defence_record_id"] = target["id"]
            state.messages.append({"role": "assistant", "content": "Defence complete. Result is pending professor approval."})
            state.active_agent = "submission_evaluator_agent"
            return state

        state.messages.append({"role": "assistant", "content": "Let us explore gradient descent intuition and learning-rate stability."})
        state.active_agent = "ta_agent"
        return state


def _seed_graph(manager: Neo4jGraphManager):
    module = manager.create_module("ML", course_owner="cs101")
    topic = manager.create_topic(module["node_id"], "Optimization", course_owner="cs101")
    concept = manager.create_concept(topic["node_id"], "Gradient Descent", course_owner="cs101")

    manager.create_student_overlay("student_1", concept["node_id"], theta=0.2, slip=0.14, guess=0.1)
    overlay = manager.get_student_overlay("student_1", concept["node_id"])
    assert overlay is not None
    manager.update_student_overlay(overlay["id"], mastery_probability=0.62, visited=True)

    return concept["node_id"]


def _auth_header(role: str, user_id: str, course_ids=None):
    token = create_access_token(user_id=user_id, role=role, course_ids=course_ids or [])
    return {"Authorization": f"Bearer {token}"}, token


def test_phase5_student_dashboard_chat_stream_and_progress(tmp_path, monkeypatch):
    manager = Neo4jGraphManager(data_dir=str(tmp_path / "data"))
    _seed_graph(manager)
    fake_graph = _FakeGraph(manager)

    monkeypatch.setattr(app_module, "graph_manager", manager)
    monkeypatch.setattr(app_module, "omniprof_graph", fake_graph)

    _, token = _auth_header("student", "student_1", ["cs101"])
    client = TestClient(app_module.app)

    with client.websocket_connect(f"/ws/chat?token={token}&session_id=sess_1&course_id=cs101") as ws:
        ws.send_json({"message": "Explain gradient descent"})
        start = ws.receive_json()
        assert start["event"] == "start"
        assert start["active_topic_node_name"] == "Optimization"

        chunks = []
        while True:
            row = ws.receive_json()
            if row["event"] == "token":
                chunks.append(row["token"])
                continue
            assert row["event"] == "complete"
            break

        assert "gradient" in "".join(chunks).lower()

    headers, _ = _auth_header("student", "student_1", ["cs101"])
    resp = client.get("/student/progress?course_id=cs101", headers=headers)
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["modules_explored"] >= 1
    assert payload["concepts_visited"] >= 1
    assert payload["mastery"][0]["confidence_band"] in ["low", "medium", "high"]


def test_phase5_professor_hitl_actions_require_explicit_approve(tmp_path, monkeypatch):
    manager = Neo4jGraphManager(data_dir=str(tmp_path / "data"))
    _seed_graph(manager)

    record_id = "def_1"
    manager.create_defence_record(
        {
            "id": record_id,
            "student_id": "student_1",
            "course_id": "cs101",
            "status": "pending_professor_review",
            "submission_summary": "summary",
            "transcript": [{"role": "student", "content": "answer"}],
            "ai_recommended_grade": 0.7,
            "ai_grade_justification": "justification",
            "ai_feedback": "feedback",
            "integrity_score": 0.9,
            "integrity_sample_size": 4,
        }
    )
    queue = manager.enqueue_hitl_review(
        {
            "defence_record_id": record_id,
            "course_id": "cs101",
            "submission_summary": "summary",
            "transcript": [{"role": "student", "content": "answer"}],
            "ai_recommended_grade": 0.7,
            "ai_grade_justification": "justification",
            "ai_feedback": "feedback",
            "integrity_score": 0.9,
            "integrity_sample_size": 4,
        }
    )

    monkeypatch.setattr(app_module, "graph_manager", manager)

    client = TestClient(app_module.app)
    prof_headers, _ = _auth_header("professor", "prof_1", ["cs101"])

    reject_resp = client.post(
        f"/professor/hitl-queue/{queue['queue_id']}/action",
        headers=prof_headers,
        json={"action": "reject_second_defence", "review_note": "Needs another round."},
    )
    assert reject_resp.status_code == 200
    row = manager.get_defence_record(record_id)
    assert row is not None
    assert row.get("final_grade") is None

    approve_resp = client.post(
        f"/professor/hitl-queue/{queue['queue_id']}/action",
        headers=prof_headers,
        json={"action": "modify_approve", "modified_grade": 0.83, "modified_feedback": "Approved with edits."},
    )
    assert approve_resp.status_code == 200

    updated = manager.get_defence_record(record_id)
    assert updated is not None
    assert updated.get("status") == "approved"
    assert updated.get("final_grade") == 0.83


def test_phase5_full_acceptance_gate_student_to_professor_flow(tmp_path, monkeypatch):
    manager = Neo4jGraphManager(data_dir=str(tmp_path / "data"))
    concept_id = _seed_graph(manager)
    fake_graph = _FakeGraph(manager)

    monkeypatch.setattr(app_module, "graph_manager", manager)
    monkeypatch.setattr(app_module, "omniprof_graph", fake_graph)

    client = TestClient(app_module.app)

    student_headers, student_token = _auth_header("student", "student_1", ["cs101"])
    professor_headers, _ = _auth_header("professor", "prof_1", ["cs101"])

    # Student uploads assignment and enters evaluation mode.
    submit_resp = client.post(
        "/student/submit-assignment?course_id=cs101",
        headers=student_headers,
        files={"file": ("assignment.txt", b"my solution", "text/plain")},
    )
    assert submit_resp.status_code == 200
    submit_payload = submit_resp.json()
    assert submit_payload["evaluation_mode"] is True
    submission_id = submit_payload["submission_id"]

    # Student completes defence session through websocket chat.
    with client.websocket_connect(f"/ws/chat?token={student_token}&session_id=sess_2&course_id=cs101") as ws:
        ws.send_json({"message": "submission defence: here is my reasoning"})
        seen_complete = False
        while not seen_complete:
            row = ws.receive_json()
            if row.get("event") == "complete":
                seen_complete = True
                assert row.get("evaluation_mode") is True

    status_resp = client.get(f"/student/submissions/{submission_id}", headers=student_headers)
    assert status_resp.status_code == 200
    status_payload = status_resp.json()
    assert status_payload["pending_professor_approval"] is True

    # Professor sees queue record with integrity score and sample size.
    queue_resp = client.get("/professor/hitl-queue", headers=professor_headers)
    assert queue_resp.status_code == 200
    queue_items = queue_resp.json()["items"]
    assert len(queue_items) >= 1
    latest = queue_items[-1]
    assert latest.get("integrity_score") is not None
    assert latest.get("integrity_sample_size") is not None

    # Professor approves and grade gets recorded.
    approve_resp = client.post(
        f"/professor/hitl-queue/{latest['queue_id']}/action",
        headers=professor_headers,
        json={"action": "approve"},
    )
    assert approve_resp.status_code == 200

    post_status = client.get(f"/student/submissions/{submission_id}", headers=student_headers)
    assert post_status.status_code == 200
    assert post_status.json()["pending_professor_approval"] is False

    # Cohort overview is served from aggregate overlay data.
    cohort_resp = client.get("/professor/cohort-overview?course_id=cs101&inactivity_days=1", headers=professor_headers)
    assert cohort_resp.status_code == 200
    assert "topic_mastery_distribution" in cohort_resp.json()

    # Read-only graph visualisation renders full graph payload.
    graph_resp = client.get("/professor/graph-visualization?course_id=cs101", headers=professor_headers)
    assert graph_resp.status_code == 200
    graph_payload = graph_resp.json()
    assert graph_payload["read_only"] is True
    assert len(graph_payload["nodes"]) >= 3

    # Learning path configuration round-trip.
    lp_save = client.post(
        "/professor/learning-path",
        headers=professor_headers,
        json={
            "course_id": "cs101",
            "ordered_concept_ids": [concept_id],
            "partial_order_edges": [],
        },
    )
    assert lp_save.status_code == 200

    lp_get = client.get("/professor/learning-path?course_id=cs101", headers=professor_headers)
    assert lp_get.status_code == 200
    assert lp_get.json()["ordered_concept_ids"] == [concept_id]
