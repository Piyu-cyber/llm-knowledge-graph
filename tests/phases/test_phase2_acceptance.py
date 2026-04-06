import json
import os

import pytest

from backend.db.graph_manager import Neo4jGraphManager
from backend.services.crag_grader_agent import CRAGGraderAgent
from backend.services.graph_service import GraphService
from backend.services.ingestion_service import IngestionService


pytestmark = [pytest.mark.phase2, pytest.mark.phase2_acceptance]


class _FakeRAG:
    def reset(self):
        return None

    def ingest_documents(self, _text):
        return None


class _RuleBasedLLM:
    def __init__(self):
        self.calls = 0

    def extract_concepts_hierarchical(self, text):
        self.calls += 1
        t = (text or "").strip().lower()

        if "cycle" in t:
            return {
                "nodes": [
                    {"name": "M", "level": "MODULE", "description": "m"},
                    {"name": "T", "level": "TOPIC", "description": "t"},
                    {"name": "A", "level": "CONCEPT", "description": "a"},
                    {"name": "A", "level": "CONCEPT", "description": "a-dup"},
                ],
                "edges": [
                    {"source": "A", "target": "A", "type": "REQUIRES"},
                ],
            }

        # content marker -> deterministic concept naming
        stem = "_".join(t.split())[:32] or "generic"

        return {
            "nodes": [
                {"name": f"Module_{stem}", "level": "MODULE", "description": "module"},
                {"name": f"Topic_{stem}", "level": "TOPIC", "description": "topic"},
                {"name": f"Concept_{stem}", "level": "CONCEPT", "description": "concept"},
                {"name": f"Fact_{stem}", "level": "FACT", "description": "fact"},
            ],
            "edges": [
                {"source": f"Topic_{stem}", "target": f"Module_{stem}", "type": "RELATED"},
                {"source": f"Concept_{stem}", "target": f"Topic_{stem}", "type": "RELATED"},
                {"source": f"Fact_{stem}", "target": f"Concept_{stem}", "type": "RELATED"},
            ],
        }


def _make_ingestion(tmp_path):
    manager = Neo4jGraphManager(data_dir=str(tmp_path / "data"))
    graph_service = GraphService(manager)
    llm = _RuleBasedLLM()
    ingestion = IngestionService(llm, _FakeRAG(), graph_service)
    ingestion.review_queue_path = str(tmp_path / "data" / "review_queue.json")
    ingestion.enable_prewrite_validation = True
    return ingestion, graph_service, manager, llm


def test_phase2_format_normalization_layer(tmp_path):
    ingestion, _graph, _manager, _llm = _make_ingestion(tmp_path)

    txt = tmp_path / "sample.txt"
    txt.write_text("This is module text content", encoding="utf-8")

    png = tmp_path / "diagram.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")

    txt_result = ingestion.normalize_to_content_units(str(txt))
    img_result = ingestion.normalize_to_content_units(str(png))

    assert txt_result["status"] == "success"
    assert txt_result["content_units"][0]["source_ref"] == "sample.txt"
    assert txt_result["content_units"][0]["position"] == 1
    assert txt_result["content_units"][0]["modality"] == "text"

    assert img_result["status"] == "success"
    assert img_result["content_units"][0]["source_ref"] == "diagram.png"
    assert img_result["content_units"][0]["modality"] == "image"
    assert len(img_result["content_units"][0]["embedding"]) == 2048


def test_phase2_single_llm_call_per_content_unit(tmp_path):
    ingestion, _graph, _manager, llm = _make_ingestion(tmp_path)

    units = [
        {"content": "docA text one", "modality": "text"},
        {"content": "docB text two", "modality": "text"},
        {"content": "", "modality": "image"},
    ]

    payload = ingestion.extract_graph_from_units(units)

    assert payload["llm_calls"] == 2
    assert llm.calls == 2
    assert len(payload["nodes"]) >= 2


def test_phase2_validation_logs_review_queue_on_failure(tmp_path):
    ingestion, _graph, _manager, _llm = _make_ingestion(tmp_path)

    bad_payload = {
        "nodes": [
            {"name": "X", "level": "CONCEPT"},
            {"name": "X", "level": "CONCEPT"},
            {"name": "T", "level": "TOPIC"},
        ],
        "edges": [
            {"source": "X", "target": "X", "type": "REQUIRES"},
        ],
    }

    issues = ingestion._prevalidate_extraction(bad_payload, "bad_doc.txt")

    assert len(issues) >= 2
    assert os.path.exists(ingestion.review_queue_path)

    with open(ingestion.review_queue_path, "r", encoding="utf-8") as f:
        queue = json.load(f)

    assert len(queue) >= 1
    assert queue[-1]["source_doc"] == "bad_doc.txt"


def test_phase2_incremental_reingestion_preserves_unrelated_overlay(tmp_path):
    ingestion, _graph_service, manager, _llm = _make_ingestion(tmp_path)

    doc_a = tmp_path / "docA.txt"
    doc_b = tmp_path / "docB.txt"
    doc_a.write_text("docA initial", encoding="utf-8")
    doc_b.write_text("docB baseline", encoding="utf-8")

    res_a = ingestion.ingest(str(doc_a), course_owner="course_1")
    res_b = ingestion.ingest(str(doc_b), course_owner="course_1")

    assert res_a["status"] == "success"
    assert res_b["status"] == "success"

    concept_b = [n for n in manager.nodes_data.items() if n[1].get("name") == "Concept_docb_baseline"][0]
    concept_b_id = concept_b[0]

    overlay = manager.create_student_overlay("student_1", concept_b_id, theta=0.2, slip=0.1, guess=0.1)
    overlay_before = manager.get_student_overlay("student_1", concept_b_id)

    doc_a.write_text("docA updated", encoding="utf-8")
    reingest = ingestion.ingest_incremental(str(doc_a), course_owner="course_1")

    assert reingest["status"] == "success"
    overlay_after = manager.get_student_overlay("student_1", concept_b_id)

    assert overlay["status"] == "success"
    assert overlay_before is not None
    assert overlay_after is not None
    assert overlay_before["id"] == overlay_after["id"]
    assert overlay_after["theta"] == overlay_before["theta"]


def test_phase2_crag_grader_routes_5_queries_under_sla():
    grader = CRAGGraderAgent(llm_service=None)

    cases = [
        ("neural network backpropagation", "backpropagation in neural network adjusts weights", "proceed"),
        ("quantum entanglement", "medieval history and empires", "expand"),
        ("graph traversal", "graph traversal and bfs overview", "proceed"),
        ("hash table collisions", "hash table collisions handling strategy", "proceed"),
        ("binary tree traversal", "tree basics include binary structure", "clarify"),
    ]

    for query, context, expected_route in cases:
        result = grader.grade(query, context)
        assert result["route"] == expected_route
        assert result["within_sla_100ms"] is True


def test_phase2_acceptance_gate_sample_course_ingestion(tmp_path):
    ingestion, _graph_service, manager, _llm = _make_ingestion(tmp_path)

    docs = []
    for module_idx in range(1, 4):
        for doc_idx in range(1, 8):
            p = tmp_path / f"mod{module_idx}_doc{doc_idx}.txt"
            p.write_text(f"mod module{module_idx} doc{doc_idx}", encoding="utf-8")
            docs.append(p)

    # Keep exactly 20 docs as acceptance minimum.
    docs = docs[:20]

    for p in docs:
        res = ingestion.ingest(str(p), course_owner="course_gate")
        assert res["status"] == "success"

    validation = manager.validate_graph_integrity()
    assert validation["status"] == "valid"
    assert validation["issue_count"] == 0
