"""Shared pytest fixtures for root-level tests."""

import pytest


class FakeLLMService:
    def __init__(self, empty=False):
        self.empty = empty

    def extract_concepts_hierarchical(self, _text):
        if self.empty:
            return {"nodes": [], "edges": []}

        return {
            "nodes": [
                {"name": "Module X", "level": "MODULE", "description": "module"},
                {"name": "Topic X", "level": "TOPIC", "description": "topic"},
                {"name": "Concept X", "level": "CONCEPT", "description": "concept"},
                {"name": "Fact X", "level": "FACT", "description": "fact"},
            ],
            "edges": [
                {"source": "Concept X", "target": "Topic X", "type": "RELATED"}
            ],
        }


class FakeRAGService:
    def __init__(self):
        self.reset_called = False
        self.ingested_text = None

    def reset(self):
        self.reset_called = True

    def ingest_documents(self, text):
        self.ingested_text = text


class FakeGraphService:
    def insert_from_llm_hierarchical(self, data, course_owner="system", source_doc="", file_format="Unknown"):
        if not data.get("nodes"):
            return {"status": "error", "message": "No nodes to insert"}

        return {
            "status": "success",
            "modules_added": 1,
            "topics_added": 1,
            "concepts_added": 2,
            "facts_added": 1,
            "relationships_added": 1,
        }

    def validate_graph(self):
        return {"status": "valid", "issue_count": 0, "issues": []}


@pytest.fixture
def fake_services():
    return FakeLLMService(empty=False), FakeRAGService(), FakeGraphService()


@pytest.fixture
def fake_services_empty_llm():
    return FakeLLMService(empty=True), FakeRAGService(), FakeGraphService()
