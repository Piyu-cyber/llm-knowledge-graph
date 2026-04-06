import pytest

from backend.auth.jwt_handler import (
    create_access_token,
    get_user_from_token,
    is_admin,
    is_professor,
    has_course_access,
)
from backend.models.schema import UserRegister, QueryRequest


pytestmark = pytest.mark.phase1


def test_phase1_jwt_roundtrip_and_role_helpers():
    token = create_access_token(
        user_id="student_1",
        role="student",
        course_ids=["cs101"],
    )

    payload = get_user_from_token(token)

    assert payload["user_id"] == "student_1"
    assert payload["role"] == "student"
    assert has_course_access(token, "cs101") is True
    assert is_admin(token) is False
    assert is_professor(token) is False


def test_phase1_invalid_role_rejected():
    with pytest.raises(ValueError):
        create_access_token(user_id="u1", role="invalid-role")


def test_phase1_schema_validation_examples():
    user = UserRegister(
        username="student_01",
        email="student01@example.com",
        password="strongpass123",
        full_name="Student One",
    )
    request = QueryRequest(query="Explain recursion with an example")

    assert user.username == "student_01"
    assert request.confidence_threshold == 0.5


def test_phase1_schema_rejects_short_query():
    with pytest.raises(Exception):
        QueryRequest(query="hi")
