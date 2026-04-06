import pytest

from backend.services.ingestion_service import IngestionService


pytestmark = pytest.mark.phase0


def test_phase0_ingestion_text_success(tmp_path, fake_services):
    llm, rag, graph = fake_services
    svc = IngestionService(llm, rag, graph)

    sample = tmp_path / "phase0.txt"
    sample.write_text("Intro to machine learning", encoding="utf-8")

    result = svc.ingest(str(sample), course_owner="prof_phase0")

    assert result["status"] == "success"
    assert result["validation"]["is_valid"] is True


def test_phase0_ingestion_empty_extraction_fails(tmp_path, fake_services_empty_llm):
    llm, rag, graph = fake_services_empty_llm
    svc = IngestionService(llm, rag, graph)

    sample = tmp_path / "phase0-empty.txt"
    sample.write_text("No extractable concepts", encoding="utf-8")

    result = svc.ingest(str(sample), course_owner="prof_phase0")

    assert result["status"] == "error"
    assert "Failed to extract concepts" in result["message"]
