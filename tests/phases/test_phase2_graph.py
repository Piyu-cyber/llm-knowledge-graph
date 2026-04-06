import pytest

from backend.services.graph_service import GraphService


pytestmark = pytest.mark.phase2


class _TinyGraphManager:
    def __init__(self):
        self.nodes = {}
        self.counter = 0
        self.duplicates = set()

    def _new_id(self, prefix):
        self.counter += 1
        return f"{prefix}_{self.counter}"

    def create_module(self, name, course_owner, description="", visibility="global"):
        node_id = self._new_id("module")
        self.nodes[node_id] = {"name": name, "course_owner": course_owner, "level": "MODULE"}
        return {"status": "success", "node_id": node_id, "name": name}

    def create_topic(self, module_id, name, course_owner, description="", visibility="global"):
        node_id = self._new_id("topic")
        self.nodes[node_id] = {"name": name, "module_id": module_id, "course_owner": course_owner, "level": "TOPIC"}
        return {"status": "success", "node_id": node_id, "name": name}

    def create_concept(self, topic_id, name, course_owner, description="", source_doc_ref="", embedding=None, visibility="global", difficulty=0.0):
        node_id = self._new_id("concept")
        self.nodes[node_id] = {
            "name": name,
            "topic_id": topic_id,
            "course_owner": course_owner,
            "level": "CONCEPT",
            "difficulty": difficulty,
        }
        self.duplicates.add((topic_id, name))
        return {"status": "success", "node_id": node_id, "name": name, "embedding_dim": len(embedding) if embedding else 0}

    def create_fact(self, concept_id, name, course_owner, description="", source_doc_ref="", visibility="global"):
        node_id = self._new_id("fact")
        self.nodes[node_id] = {"name": name, "concept_id": concept_id, "course_owner": course_owner, "level": "FACT"}
        return {"status": "success", "node_id": node_id, "name": name}

    def add_prerequisite(self, source_concept_id, target_concept_id, weight=1.0):
        return {"status": "success", "source": source_concept_id, "target": target_concept_id, "weight": weight}

    def validate_graph_integrity(self):
        return {"status": "valid", "issue_count": 0}

    def check_duplicate_concept_in_topic(self, topic_id, name):
        return (topic_id, name) in self.duplicates


def test_phase2_create_hierarchy_and_relationships():
    graph = GraphService(_TinyGraphManager())

    module = graph.create_module("ML Fundamentals", "prof_ml")
    topic = graph.create_topic(module["node_id"], "Neural Networks", "prof_ml")
    concept = graph.create_concept(topic["node_id"], "Perceptron", "prof_ml", embedding=[0.2] * 32)
    fact = graph.create_fact(concept["node_id"], "Bias term improves fit", "prof_ml")
    prereq = graph.add_prerequisite(concept["node_id"], concept["node_id"], weight=0.7)

    assert module["status"] == "success"
    assert topic["status"] == "success"
    assert concept["embedding_dim"] == 32
    assert fact["status"] == "success"
    assert prereq["weight"] == 0.7


def test_phase2_validation_flags_duplicate_concept():
    graph = GraphService(_TinyGraphManager())
    module = graph.create_module("NLP", "prof_nlp")
    topic = graph.create_topic(module["node_id"], "Transformers", "prof_nlp")
    graph.create_concept(topic["node_id"], "Attention", "prof_nlp")

    result = graph.validate_before_adding_concept(topic["node_id"], "Attention")

    assert result["valid"] is False
    assert result["issues"][0]["type"] == "duplicate_name"
