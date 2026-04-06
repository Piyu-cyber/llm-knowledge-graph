import pytest
from typing import Any, cast

from backend.agents.intent_classifier import AgentRouter, extract_intent_features, classify_with_state
from backend.agents.state import AgentState


pytestmark = pytest.mark.phase4


class _DummyClassifier:
    def __init__(self, intent="academic_query", confidence=0.82, reasoning="test"):
        self.intent = intent
        self.confidence = confidence
        self.reasoning = reasoning

    def classify(self, _message):
        return self.intent, self.confidence, self.reasoning


def test_phase4_router_maps_intents_to_expected_agents():
    assert AgentRouter.get_agent_for_intent("academic_query") == "academic_qa_agent"
    assert AgentRouter.get_agent_for_intent("submission_defence") == "submission_evaluator_agent"
    assert AgentRouter.get_agent_for_intent("curriculum_change") == "curriculum_advisor_agent"
    assert AgentRouter.get_agent_for_intent("progress_check") == "progress_tracker_agent"


def test_phase4_extract_intent_features_flags_progress_language():
    features = extract_intent_features("How am I doing and what have I mastered so far?")

    assert features["has_how_doing"] is True
    assert features["has_mastery"] is True


def test_phase4_classify_with_state_updates_routing_and_history():
    state = AgentState(student_id="student_1", session_id="sess_1", current_input="Can you explain recursion?")
    classifier = _DummyClassifier(intent="academic_query", confidence=0.9)

    updated = classify_with_state(state, cast(Any, classifier))

    assert updated.current_intent == "academic_query"
    assert updated.next_agent == "academic_qa_agent"
    assert updated.eval_state.confidence == 0.9
    assert len(updated.messages) == 1
    assert updated.messages[0]["role"] == "student"
