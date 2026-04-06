import pytest

from backend.services.cognitive_engine import CognitiveEngine


pytestmark = pytest.mark.phase5


def _engine_without_graph_init():
    engine = CognitiveEngine.__new__(CognitiveEngine)
    engine.discrimination_a = 1.7
    engine.min_theta = -4.0
    engine.max_theta = 4.0
    engine.learning_rate = 0.15
    engine.slip_threshold = 0.05
    engine.mastery_threshold = 0.8
    return engine


def test_phase5_irt_probability_bounded_and_monotonic():
    engine = _engine_without_graph_init()

    low = engine.irt_probability(theta=-2.0, difficulty=0.0)
    high = engine.irt_probability(theta=2.0, difficulty=0.0)

    assert 0.0 <= low <= 1.0
    assert 0.0 <= high <= 1.0
    assert high > low


def test_phase5_bayesian_update_increases_theta_on_correct_answer():
    engine = _engine_without_graph_init()

    new_theta, new_slip = engine.bayesian_update(
        theta=0.0,
        slip=0.1,
        difficulty=0.2,
        answered_correctly=True,
    )

    assert new_theta > 0.0
    assert new_slip < 0.1


def test_phase5_bayesian_update_decreases_theta_on_incorrect_answer():
    engine = _engine_without_graph_init()

    new_theta, new_slip = engine.bayesian_update(
        theta=0.3,
        slip=0.1,
        difficulty=0.1,
        answered_correctly=False,
    )

    assert new_theta < 0.3
    assert new_slip > 0.1
