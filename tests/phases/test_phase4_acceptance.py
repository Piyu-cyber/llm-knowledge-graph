import math
from datetime import datetime
from typing import Any, cast

import pytest

from backend.agents.evaluator_agent import EvaluatorAgent
from backend.agents.integrity_agent import IntegrityAgent
from backend.agents.state import AgentState, StateCheckpointStore
from backend.agents.summarisation_agent import SummarisationAgent
from backend.agents.ta_agent import TAAgent
from backend.db.graph_manager import Neo4jGraphManager
from backend.services.memory_service import EpisodicRecord, MemoryService


pytestmark = [pytest.mark.phase4, pytest.mark.phase4_acceptance]


def _make_agent_state(**kwargs):
    return cast(Any, AgentState)(**kwargs)


def test_phase4_dual_store_hybrid_decay_and_semantic_overlay(tmp_path):
    manager = Neo4jGraphManager(data_dir=str(tmp_path / "data"))
    memory = MemoryService(embedding_dim=2048)
    memory.graph_manager = manager

    now_ts = int(datetime.now().timestamp())
    old_ts = now_ts - (30 * 24 * 3600)

    query_vec = memory.embedding_service.embed_text("gradient descent prerequisites")

    old_overlap = EpisodicRecord(
        student_id="student_a",
        session_id="sess_old",
        message="We discussed prerequisite algebra for gradient descent.",
        embedding=cast(Any, query_vec),
        timestamp_unix=old_ts,
        concept_node_ids=["concept_prereq"],
        turn_number=1,
    )
    recent_non_overlap = EpisodicRecord(
        student_id="student_a",
        session_id="sess_new",
        message="A recent note about a different topic.",
        embedding=cast(Any, memory.embedding_service.embed_text("different topic")),
        timestamp_unix=now_ts,
        concept_node_ids=["concept_other"],
        turn_number=2,
    )

    assert memory.write_episodic_record(old_overlap) is True
    assert memory.write_episodic_record(recent_non_overlap) is True

    retrieved = memory.retrieve_episodic_memories(
        student_id="student_a",
        query_embedding=cast(Any, query_vec),
        current_concept_ids=["concept_prereq"],
        top_k=5,
        current_timestamp=now_ts,
    )

    overlap_row = [r for r in retrieved if "prerequisite algebra" in r.message][0]
    assert overlap_row.has_concept_overlap is True
    assert math.isclose(overlap_row.final_score, overlap_row.base_score, rel_tol=1e-6)

    # Semantic memory lives in student overlay graph and is retrievable by concept.
    sem = manager.create_semantic_node(
        student_id="student_a",
        fact="Gradient descent needs a learning rate.",
        concept_id="concept_prereq",
        confidence=0.93,
    )
    assert sem["status"] == "success"

    semantic_rows = memory.get_semantic_memories("student_a", ["concept_prereq"])
    assert any("learning rate" in (row.get("fact") or "") for row in semantic_rows)


def test_phase4_checkpoint_persist_and_restore(tmp_path):
    checkpoint_path = str(tmp_path / "checkpoints.json")
    store = StateCheckpointStore(checkpoint_path=checkpoint_path)

    state = _make_agent_state(
        student_id="student_c",
        session_id="sess_checkpoint",
        current_input="Explain recursion",
        metadata={"course_id": "cs101"},
    )
    state.add_message("student", "Explain recursion", intent="academic_query")
    state.current_intent = "academic_query"
    state.active_agent = "ta_agent"
    state.eval_state.confidence = 0.77

    store.save(state)

    # Simulate restart by constructing a fresh checkpoint store instance.
    store_after_restart = StateCheckpointStore(checkpoint_path=checkpoint_path)
    restored = store_after_restart.load("sess_checkpoint")

    assert restored is not None
    assert restored.student_id == "student_c"
    assert restored.current_intent == "academic_query"
    assert restored.active_agent == "ta_agent"
    assert restored.eval_state.confidence == pytest.approx(0.77)
    assert restored.messages[-1]["content"] == "Explain recursion"


def test_phase4_ta_personalization_low_vs_high_mastery(tmp_path):
    manager = Neo4jGraphManager(data_dir=str(tmp_path / "data"))

    module = manager.create_module("ML", course_owner="cs101")
    topic = manager.create_topic(module["node_id"], "Optimization", course_owner="cs101")
    concept = manager.create_concept(topic["node_id"], "Gradient Descent", course_owner="cs101")

    manager.create_student_overlay("student_low", concept["node_id"], theta=-2.0, slip=0.1, guess=0.1)
    manager.create_student_overlay("student_high", concept["node_id"], theta=2.0, slip=0.1, guess=0.1)

    agent = TAAgent(groq_api_key="")
    agent.graph_manager = manager
    agent._run_crag_loop = cast(Any, lambda query: {"answer": "Gradient descent updates parameters.", "confidence": 0.8, "graph_results": []})
    agent._extract_concepts = cast(Any, lambda query, answer: ["Gradient Descent"])
    agent._update_overlays = cast(Any, lambda *args, **kwargs: None)

    low_state = _make_agent_state(student_id="student_low", session_id="sess_low", current_input="Explain gradient descent")
    high_state = _make_agent_state(student_id="student_high", session_id="sess_high", current_input="Explain gradient descent")

    low_result = agent.process(low_state)
    high_result = agent.process(high_state)

    low_answer = low_result.messages[-1]["content"]
    high_answer = high_result.messages[-1]["content"]

    assert low_answer != high_answer
    assert "Hint:" in low_answer or "?" in low_answer
    assert low_result.graph_context.metadata.get("socratic") is True
    assert high_result.graph_context.metadata.get("explanation_depth") == "advanced"


def test_phase4_evaluator_integrity_hitl_and_professor_visibility(tmp_path):
    manager = Neo4jGraphManager(data_dir=str(tmp_path / "data"))

    evaluator = EvaluatorAgent(groq_api_key="")
    evaluator.graph_manager = manager

    def _fake_eval_llm(prompt: str, temperature: float = 0.7):
        if "Respond with JSON" in prompt:
            return '{"grade": 0.88, "feedback": "Clear defence and reasoning."}'
        if "Generate a follow-up Socratic question" in prompt:
            return "Why does your approach remain stable under noisy inputs?"
        return "Thanks, let's continue the defence."

    evaluator._call_llm = cast(Any, _fake_eval_llm)

    state = _make_agent_state(
        student_id="student_eval",
        session_id="sess_eval",
        current_input="My submission explains the optimization method.",
        metadata={"course_id": "cs101", "submission_id": "sub_1"},
    )

    # Turn 1 initializes evaluation.
    state = evaluator.process(state)
    state.current_input = "I chose this method because it converges quickly."
    state = evaluator.process(state)
    state.current_input = "It also avoids overfitting via regularization."
    state = evaluator.process(state)
    state.current_input = "stop now"
    state = evaluator.process(state)

    assert state.metadata.get("defence_record_id")

    integrity = IntegrityAgent(min_token_threshold=5000)
    integrity.graph_manager = manager
    integrity._get_prior_ta_interactions = cast(Any, lambda student_id: [{"content": "too short"}])

    state = integrity.process(state)

    queue = manager.list_hitl_queue(["cs101"])
    assert len(queue) >= 1
    latest = queue[-1]
    assert latest.get("defence_record_id") == state.metadata.get("defence_record_id")
    assert latest.get("transcript")
    assert latest.get("ai_recommended_grade") is not None
    assert state.metadata.get("sdi_visible") is False


def test_phase4_summarisation_anchor_retrieval_across_sessions(tmp_path):
    manager = Neo4jGraphManager(data_dir=str(tmp_path / "data"))

    module = manager.create_module("DS", course_owner="cs101")
    topic = manager.create_topic(module["node_id"], "Trees", course_owner="cs101")
    concept = manager.create_concept(topic["node_id"], "Binary Tree", course_owner="cs101")

    summariser = SummarisationAgent(groq_api_key="")
    summariser.graph_manager = manager

    # Archive a completed session outside request path.
    import asyncio
    payload = asyncio.run(
        summariser.archive_session_to_memory(
            student_id="student_sum",
            session_id="sess_old_topic",
            messages=[
                {"role": "student", "content": "I learned binary tree traversals today."},
                {"role": "assistant", "content": "Great, preorder and inorder are key."},
            ],
            concept_ids=[concept["node_id"]],
        )
    )

    assert payload["status"] == "success"

    anchors = manager.get_memory_anchors("student_sum", concept["node_id"])
    assert len(anchors) >= 1
