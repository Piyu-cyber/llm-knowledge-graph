from backend.services.ingestion_service import IngestionService
from backend.services.llm_service import LLMService
from backend.services.graph_service import GraphService


def main():
    print("📄 Extracting text...")
    ingest = IngestionService()
    text = ingest.extract_text("sample.pdf")

    print("🤖 Running LLM...")
    llm = LLMService()
    data = llm.extract_concepts(text)

    print("🧠 Inserting into Neo4j...")
    graph = GraphService()
    result = graph.insert_from_llm(data)

    print("✅ DONE")
    print(result)


if __name__ == "__main__":
    main()