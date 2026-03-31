from fastapi import FastAPI
from backend.services.graph_service import GraphService

app = FastAPI()

graph = GraphService()

@app.get("/")
def home():
    return {"message": "OmniProf running"}

@app.post("/concept")
def add_concept(name: str):
    return graph.create_concept(name)

@app.get("/graph")
def get_graph():
    return graph.get_graph()