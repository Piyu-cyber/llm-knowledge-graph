import pytest
from pydantic import ValidationError

from backend.models.schema import ChatRequest, InteractionRequest, UserRegister


pytestmark = pytest.mark.phase6


def test_phase6_chat_request_contract_accepts_valid_payload():
    req = ChatRequest(message="Explain dynamic programming", session_id="sess_42", course_id="cs101")

    assert req.message == "Explain dynamic programming"
    assert req.session_id == "sess_42"


def test_phase6_interaction_request_contract_enforces_difficulty_bounds():
    valid = InteractionRequest(concept_id="concept_1", answered_correctly=True, difficulty=1.5)
    assert valid.difficulty == 1.5

    with pytest.raises(ValidationError):
        InteractionRequest(concept_id="concept_1", answered_correctly=True, difficulty=6.0)


def test_phase6_user_register_contract_rejects_invalid_username():
    with pytest.raises(ValidationError):
        UserRegister(
            username="bad username with spaces",
            email="student@example.com",
            password="strongpass123",
            full_name="Bad Username",
        )
