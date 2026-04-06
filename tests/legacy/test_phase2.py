#!/usr/bin/env python3
"""
Pytest suite for Phase 2 graph operations using current GraphService API.

This replaces the previous ad-hoc script that assumed an older constructor
and old graph service contracts.
"""

from backend.services.graph_service import GraphService


class _FakeDB:
    def run_query(self, _query):
        return [{"type": "CONCEPT", "count": 2}, {"type": "REQUIRES", "count": 1}]


class FakeGraphManager:
    def __init__(self):
        self.db = _FakeDB()
        self._id = 0
        self.nodes = {}
        self.duplicates = set()
        self.student_overlay = {}

    def _new_id(self, prefix):
        self._id += 1
        return f"{prefix}_{self._id}"

    def create_module(self, name, course_owner, description="", visibility="global"):
        node_id = self._new_id("module")
        self.nodes[node_id] = {"name": name, "course_owner": course_owner, "level": "MODULE"}
        return {"status": "success", "node_id": node_id, "name": name}

    def create_topic(self, module_id, name, course_owner, description="", visibility="global"):
        node_id = self._new_id("topic")
        self.nodes[node_id] = {
            "name": name,
            "course_owner": course_owner,
            "module_id": module_id,
            "level": "TOPIC",
        }
        return {"status": "success", "node_id": node_id, "name": name}

    def create_concept(self, topic_id, name, course_owner, description="", source_doc_ref="", embedding=None, visibility="global"):
        node_id = self._new_id("concept")
        self.nodes[node_id] = {
            "name": name,
            "course_owner": course_owner,
            "topic_id": topic_id,
            "level": "CONCEPT",
            "embedding_dim": len(embedding) if embedding else 0,
        }
        self.duplicates.add((topic_id, name))
        return {
            "status": "success",
            "node_id": node_id,
            "name": name,
            "embedding_dim": len(embedding) if embedding else 0,
        }

    def create_fact(self, concept_id, name, course_owner, description="", source_doc_ref="", visibility="global"):
        node_id = self._new_id("fact")
        self.nodes[node_id] = {
            "name": name,
            "course_owner": course_owner,
            "concept_id": concept_id,
            "level": "FACT",
        }
        return {"status": "success", "node_id": node_id, "name": name}

    def add_prerequisite(self, source_concept_id, target_concept_id, weight=1.0):
        return {"status": "success", "source": source_concept_id, "target": target_concept_id, "weight": weight}

    def add_extends_relationship(self, source_id, target_id):
        return {"status": "success", "source": source_id, "target": target_id}

    def add_contrasts_relationship(self, source_id, target_id):
        return {"status": "success", "source": source_id, "target": target_id}

    def create_student_overlay(self, user_id, concept_id, theta=0.0, slip=0.1, guess=0.1, visited=False):
        mastery_probability = theta * (1 - slip) + (1 - theta) * guess
        key = (user_id, concept_id)
        self.student_overlay[key] = {
            "theta": theta,
            "slip": slip,
            "guess": guess,
            "visited": visited,
            "mastery_probability": mastery_probability,
        }
        return {"status": "success", "mastery_probability": mastery_probability}

    def update_student_mastery(self, user_id, concept_id, new_theta):
        key = (user_id, concept_id)
        if key in self.student_overlay:
            self.student_overlay[key]["theta"] = new_theta
        return {"status": "success", "theta": new_theta}

    def mark_concept_visited(self, user_id, concept_id):
        key = (user_id, concept_id)
        if key in self.student_overlay:
            self.student_overlay[key]["visited"] = True
        return {"status": "success", "visited": True}

    def validate_graph_integrity(self):
        return {"status": "valid", "issue_count": 0, "issues": []}

    def check_duplicate_concept_in_topic(self, topic_id, name):
        return (topic_id, name) in self.duplicates

    def get_node_by_id(self, node_id, user_context=None):
        return self.nodes.get(node_id)

    def get_concept_hierarchy(self, concept_id, user_context=None):
        return {"concept_id": concept_id, "path": ["module", "topic", "concept"]}

    def get_student_concepts(self, user_id, user_context=None):
        return [{"user_id": user_id, "concept_id": k[1]} for k in self.student_overlay if k[0] == user_id]

    def insert_from_hierarchical_llm(self, data, course_owner="system"):
        return {"status": "success", "inserted": len(data.get("nodes", []))}

    def search_concepts_hierarchical(self, keyword, level=None, course_owner=None, visibility_filter=True):
        return [{"name": keyword, "level": level or "CONCEPT"}]

    def get_full_graph(self, course_owner=None, level_filter=None):
        return {"nodes": list(self.nodes.values()), "edges": []}

    def get_graph_statistics(self, course_owner=None):
        return {"total_nodes": len(self.nodes), "total_edges": 0}


def test_phase2_hierarchy_creation():
    graph = GraphService(FakeGraphManager())

    module = graph.create_module("Machine Learning Fundamentals", "prof_ml_001")
    topic = graph.create_topic(module["node_id"], "Neural Networks", "prof_ml_001")
    concept = graph.create_concept(topic["node_id"], "Perceptron", "prof_ml_001", embedding=[0.5] * 384)
    fact = graph.create_fact(concept["node_id"], "Perceptron has a bias term", "prof_ml_001")

    assert module["status"] == "success"
    assert topic["status"] == "success"
    assert concept["status"] == "success"
    assert concept["embedding_dim"] == 384
    assert fact["status"] == "success"


def test_phase2_relationships_and_student_tracking():
    graph = GraphService(FakeGraphManager())

    module = graph.create_module("ML", "prof")
    topic = graph.create_topic(module["node_id"], "NN", "prof")
    c1 = graph.create_concept(topic["node_id"], "Perceptron", "prof")
    c2 = graph.create_concept(topic["node_id"], "Backpropagation", "prof")

    prereq = graph.add_prerequisite(c2["node_id"], c1["node_id"], weight=0.95)
    overlay = graph.track_student_concept("student_1", c1["node_id"], theta=0.2, slip=0.1, guess=0.1)
    visited = graph.mark_concept_visited("student_1", c1["node_id"])
    updated = graph.update_student_mastery("student_1", c1["node_id"], new_theta=0.8)

    assert prereq["status"] == "success"
    assert overlay["status"] == "success"
    assert overlay["mastery_probability"] > 0
    assert visited["visited"] is True
    assert updated["status"] == "success"


def test_phase2_validation_and_bulk_import():
    graph = GraphService(FakeGraphManager())

    module = graph.create_module("NLP", "prof")
    topic = graph.create_topic(module["node_id"], "Transformers", "prof")
    graph.create_concept(topic["node_id"], "Attention", "prof")

    dup = graph.validate_before_adding_concept(topic["node_id"], "Attention")
    full = graph.validate_graph()

    llm_data = {
        "nodes": [
            {"name": "Module A", "level": "MODULE", "description": "desc"},
            {"name": "Topic A", "level": "TOPIC", "description": "desc"},
            {"name": "Concept A", "level": "CONCEPT", "description": "desc"},
            {"name": "Fact A", "level": "FACT", "description": "desc"},
        ],
        "edges": [{"source": "Concept A", "target": "Topic A", "type": "RELATED"}],
    }

    bulk = graph.insert_from_llm_hierarchical(llm_data, course_owner="prof", source_doc="doc.pdf", file_format="PDF")

    assert dup["valid"] is False
    assert full["status"] == "valid"
    assert bulk["status"] == "success"
    assert bulk["concepts_added"] >= 1
