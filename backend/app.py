from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import shutil
import os
import tempfile

from backend.services.graph_service import GraphService
from backend.services.llm_service import LLMService
from backend.services.rag_service import RAGService
from backend.services.crag_service import CRAGService
from backend.services.ingestion_service import IngestionService


app = FastAPI()

# 🔹 CORS (frontend access)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔹 Initialize shared services
rag_service = RAGService()
llm_service = LLMService()
graph_service = GraphService()

ingestion_service = IngestionService(
    llm_service=llm_service,
    rag_service=rag_service,
    graph_service=graph_service
)

crag_service = CRAGService(
    rag_service=rag_service,
    graph_service=graph_service,
    llm_service=llm_service
)


# 🔹 Health check
@app.get("/")
def home():
    return {"message": "OmniProf running 🚀"}


# 🔹 Add concept manually
@app.post("/concept")
def add_concept(name: str, description: str = ""):
    try:
        if not name.strip():
            raise HTTPException(status_code=400, detail="Concept name cannot be empty")

        return graph_service.create_concept(name, description)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 🔹 Get full graph
@app.get("/graph")
def get_graph():
    try:
        return graph_service.get_graph()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 🔥 Graph visualization endpoint
@app.get("/graph-view")
def graph_view(query: str):
    try:
        if not query.strip():
            return {"nodes": [], "edges": []}

        results = graph_service.search_concepts(query)

        if not results:
            return {"nodes": [], "edges": []}

        nodes = []
        edges = []

        main = results[0]

        # 🔹 Main node
        nodes.append({
            "id": main["name"],
            "label": main["name"]
        })

        # 🔹 Related nodes
        for rel in main.get("related", []):
            nodes.append({
                "id": rel["name"],
                "label": rel["name"]
            })

            edges.append({
                "source": main["name"],
                "target": rel["name"],
                "label": rel["relation"]
            })

        return {
            "nodes": nodes,
            "edges": edges
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 🔥 File upload + ingestion (FIXED CLEAN VERSION)
@app.post("/ingest")
def ingest(file: UploadFile = File(...)):
    try:
        if not file.filename.endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are allowed")

        # 🔹 Create temp file safely
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            shutil.copyfileobj(file.file, tmp)
            temp_path = tmp.name

        # 🔹 Process file
        result = ingestion_service.ingest(temp_path)

        # 🔹 Cleanup
        if os.path.exists(temp_path):
            os.remove(temp_path)

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 🔹 Query system (CRAG)
@app.get("/query")
def query_system(q: str):
    try:
        if not q or not q.strip():
            raise HTTPException(status_code=400, detail="Query cannot be empty")

        if len(q) > 500:
            raise HTTPException(status_code=400, detail="Query too long")

        return crag_service.retrieve(q)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))