"""
Pytest tests for ingestion service (current architecture).

This replaces the old ad-hoc script that used outdated constructor signatures.
"""

from backend.services.ingestion_service import IngestionService


def test_ingestion_text_file_success(tmp_path, fake_services):
    llm, rag, graph = fake_services
    svc = IngestionService(llm, rag, graph)

    sample = tmp_path / "sample.txt"
    sample.write_text("Machine learning uses data to train models.", encoding="utf-8")

    result = svc.ingest(str(sample), course_owner="prof_test")

    assert result["status"] == "success"
    assert result["file_format"] == "Text"
    assert result["concepts_added"] == 2
    assert result["relationships_added"] == 1
    assert result["validation"]["is_valid"] is True
    assert rag.reset_called is True
    assert rag.ingested_text is not None


def test_ingestion_unsupported_extension_returns_error(tmp_path, fake_services):
    llm, rag, graph = fake_services
    svc = IngestionService(llm, rag, graph)

    bad = tmp_path / "sample.xyz"
    bad.write_text("invalid format", encoding="utf-8")

    result = svc.ingest(str(bad), course_owner="prof_test")

    assert result["status"] == "error"
    assert "Unsupported file format" in result["message"]


def test_ingestion_llm_empty_nodes_returns_error(tmp_path, fake_services_empty_llm):
    llm, rag, graph = fake_services_empty_llm
    svc = IngestionService(llm, rag, graph)

    sample = tmp_path / "sample.txt"
    sample.write_text("short text", encoding="utf-8")

    result = svc.ingest(str(sample), course_owner="prof_test")

    assert result["status"] == "error"
    assert "Failed to extract concepts" in result["message"]