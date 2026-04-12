import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import backend.app as app_module
from backend.auth.jwt_handler import create_access_token
from backend.services.smart_notes_service import generate_session_notes


pytestmark = pytest.mark.phase7


def _auth_header(role: str, user_id: str, course_ids=None):
    token = create_access_token(user_id, role, course_ids or ["cs101"])
    return {"Authorization": f"Bearer {token}"}, token


def _seed_phase7_graph():
    manager = app_module.graph_manager
    concept = manager.get_concept_by_name("Phase7 Gradient Descent", course_id="cs101")
    if concept:
        concept_id = concept["id"]
    else:
        module = manager.create_module("Phase7 Module", course_owner="cs101")
        topic = manager.create_topic(module["node_id"], "Phase7 Topic", course_owner="cs101")
        concept = manager.create_concept(topic["node_id"], "Phase7 Gradient Descent", course_owner="cs101")
        concept_id = concept["node_id"]
    overlay = manager.get_student_overlay("student_phase7", concept_id)
    if not overlay:
        manager.create_student_overlay("student_phase7", concept_id, theta=0.2, slip=0.1, guess=0.1)
        overlay = manager.get_student_overlay("student_phase7", concept_id)
    if overlay:
        manager.update_student_overlay(overlay["id"], updates={"theta": 0.2, "mastery_probability": 0.32, "visited": True})

    coursework_path = app_module._json_path("coursework_items.json")
    coursework = manager._read_json_list(coursework_path)
    assignment = {
        "id": "phase7_assignment_1",
        "course_id": "cs101",
        "title": "Phase7 Assignment",
        "due_date": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
        "concept_ids": [concept_id],
    }
    coursework = [row for row in coursework if row.get("id") != assignment["id"]]
    coursework.append(assignment)
    with open(coursework_path, "w", encoding="utf-8") as f:
        json.dump(coursework, f, indent=2)
    return concept_id


@pytest.fixture
def client():
    return TestClient(app_module.app)


def test_study_plan_returns_blocks(client, monkeypatch):
    concept_id = _seed_phase7_graph()
    headers, _ = _auth_header("student", "student_phase7", ["cs101"])

    monkeypatch.setattr(
        "backend.services.study_planner_service.llm_router.route",
        lambda *args, **kwargs: {"text": json.dumps({"blocks": [{"title": "Review weak concept", "description": "Focus on fundamentals", "duration_minutes": 25, "priority": "high", "concept_ids": [concept_id]}]})},
    )

    response = client.get("/student/study-plan?course_id=cs101", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["blocks"], list)
    assert isinstance(payload["generated_at"], str)


def test_study_plan_cached(client, monkeypatch):
    _seed_phase7_graph()
    headers, _ = _auth_header("student", "student_phase7", ["cs101"])
    monkeypatch.setattr(
        "backend.services.study_planner_service.llm_router.route",
        lambda *args, **kwargs: {"text": json.dumps({"blocks": [{"title": "Cached block", "description": "Desc", "duration_minutes": 20, "priority": "medium", "concept_ids": []}]})},
    )
    first = client.get("/student/study-plan?course_id=cs101", headers=headers)
    second = client.get("/student/study-plan?course_id=cs101", headers=headers)
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["generated_at"] == second.json()["generated_at"]


def test_smart_notes_written(client, monkeypatch):
    _seed_phase7_graph()
    headers, _ = _auth_header("student", "student_phase7", ["cs101"])
    monkeypatch.setattr(
        "backend.services.smart_notes_service.llm_router.route",
        lambda *args, **kwargs: {"text": json.dumps({"concepts_covered": ["Phase7 Gradient Descent"], "key_definitions": {"gradient": "slope direction"}, "connections": ["Optimization links to gradients"], "follow_up_suggestions": ["Practice one more problem"]})},
    )
    asyncio.run(generate_session_notes("student_phase7", "sess_phase7", [{"role": "student", "content": "Explain gradient descent", "course_id": "cs101"}]))
    response = client.get("/student/notes?course_id=cs101", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload
    assert isinstance(payload[0]["concepts_covered"], list)


def test_hints_returns_hint(client, monkeypatch):
    concept_id = _seed_phase7_graph()
    headers, _ = _auth_header("student", "student_phase7", ["cs101"])
    monkeypatch.setattr(
        "backend.services.contextual_hints_service.llm_router.route",
        lambda *args, **kwargs: {"text": json.dumps({"hint": "What happens to the gradient when you are near the minimum?", "concept_referenced": concept_id, "confidence": 0.88})},
    )
    response = client.post(
        "/hints",
        headers=headers,
        json={
            "question_text": "How does gradient descent converge?",
            "draft_answer": "Gradient descent updates weights by moving in the opposite direction of the gradient over many iterative optimization steps so the loss gradually decreases and the model converges toward a local minimum with careful learning rate choices.",
            "concept_ids": [concept_id],
            "course_id": "cs101",
        },
    )
    assert response.status_code == 200
    assert response.json()["hint"]


def test_hints_rate_limit(client, monkeypatch):
    concept_id = _seed_phase7_graph()
    headers, _ = _auth_header("student", "student_phase7", ["cs101"])
    monkeypatch.setattr(
        "backend.services.contextual_hints_service.llm_router.route",
        lambda *args, **kwargs: {"text": json.dumps({"hint": "Revisit the update rule.", "concept_referenced": concept_id, "confidence": 0.7})},
    )
    body = {
        "question_text": "Rate limited question",
        "draft_answer": "This answer contains enough words to exceed the short draft guard and trigger the hint generation path for repeated requests in the test harness without relying on external providers or websocket chat sessions.",
        "concept_ids": [concept_id],
        "course_id": "cs101",
    }
    for _ in range(5):
        assert client.post("/hints", headers=headers, json=body).status_code == 200
    sixth = client.post("/hints", headers=headers, json=body)
    assert sixth.status_code == 429


def test_hints_short_draft_no_llm_call(client, monkeypatch):
    concept_id = _seed_phase7_graph()
    headers, _ = _auth_header("student", "student_short", ["cs101"])
    called = {"value": False}

    def _fake(*args, **kwargs):
        called["value"] = True
        return {"text": "{}"}

    monkeypatch.setattr("backend.services.contextual_hints_service.llm_router.route", _fake)
    response = client.post(
        "/hints",
        headers=headers,
        json={
            "question_text": "Short draft question",
            "draft_answer": "Too short for now.",
            "concept_ids": [concept_id],
            "course_id": "cs101",
        },
    )
    assert response.status_code == 200
    assert response.json()["hint"].startswith("Keep working")
    assert called["value"] is False


def test_cohort_alerts_structure(client):
    concept_id = _seed_phase7_graph()
    manager = app_module.graph_manager
    if not manager.get_student_overlay("student_phase7_b", concept_id):
        manager.create_student_overlay("student_phase7_b", concept_id, theta=0.1, slip=0.1, guess=0.1)
    headers, _ = _auth_header("professor", "prof_phase7", ["cs101"])
    response = client.get("/professor/cohort-alerts?course_id=cs101", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    if payload:
        assert {"concept_id", "struggling_pct", "urgent"}.issubset(payload[0].keys())


def test_lesson_plan_404_before_ready(client):
    headers, _ = _auth_header("professor", "prof_phase7", ["cs101"])
    response = client.get("/professor/lesson-plan/nonexistent_id", headers=headers)
    assert response.status_code == 404


def test_quiz_generation_returns_questions(client, monkeypatch):
    concept_id = _seed_phase7_graph()
    headers, _ = _auth_header("professor", "prof_phase7", ["cs101"])
    monkeypatch.setattr(
        "backend.services.quiz_generation_service.llm_router.route",
        lambda *args, **kwargs: {"text": json.dumps({"questions": [{"concept_id": concept_id, "type": "mc", "question": "What is gradient descent?", "options": ["A", "B", "C", "D"], "answer": "A", "difficulty": "easy"} for _ in range(3)]})},
    )
    response = client.post(
        "/professor/generate-quiz",
        headers=headers,
        json={"concept_ids": [concept_id], "difficulty": "easy", "count": 3, "course_id": "cs101"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 3
    assert all("question" in item and "answer" in item for item in payload)


def test_hitl_queue_includes_integrity_fields(client):
    headers, _ = _auth_header("professor", "prof_phase7", ["cs101"])
    app_module.graph_manager.enqueue_hitl_review(
        {
            "queue_id": "phase7_queue",
            "defence_record_id": "phase7_record",
            "course_id": "cs101",
            "student_id": "student_phase7",
            "style_deviation_index": 0.91,
            "evaluator_confidence": 0.77,
            "status": "flagged",
        }
    )
    response = client.get("/professor/hitl-queue", headers=headers)
    assert response.status_code == 200
    payload = response.json()["items"]
    assert payload
    assert "style_deviation_index" in payload[0]


def test_student_progress_includes_study_plan(client):
    _seed_phase7_graph()
    headers, _ = _auth_header("student", "student_phase7", ["cs101"])
    response = client.get("/student/progress?course_id=cs101", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert "study_plan_today" in payload
    assert "notes_count" in payload
