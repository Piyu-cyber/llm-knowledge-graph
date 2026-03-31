from fastapi import FastAPI

from backend.services.graph_service import GraphService
from backend.services.llm_service import LLMService
from backend.services.rag_service import RAGService
from backend.services.crag_service import CRAGService
from backend.services.ingestion_service import IngestionService

app = FastAPI()

# 🔹 Initialize shared services (IMPORTANT)
rag_service = RAGService()
llm_service = LLMService()
graph_service = GraphService()

# 🔥 FIX: pass graph_service
ingestion_service = IngestionService(
    llm_service,
    rag_service,
    graph_service
)

# 🔥 FIX: ensure CRAG uses same graph instance
crag_service = CRAGService(rag_service)
crag_service.graph = graph_service  # ✅ important

@app.get("/")
def home():
    return {"message": "OmniProf running 🚀"}


# 🔹 Add concept manually
@app.post("/concept")
def add_concept(name: str):
    return graph_service.create_concept(name)


# 🔹 Get all concepts
@app.get("/graph")
def get_graph():
    return graph_service.get_graph()


# 🔹 Ingest PDF (Graph + RAG)
@app.post("/ingest")
def ingest(file_path: str):
    return ingestion_service.ingest(file_path)


# 🔹 Query system (Graph + RAG + CRAG)
@app.get("/query")
def query_system(q: str):
    return crag_service.retrieve(q)