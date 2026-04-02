# 🚀 OmniProf — Hybrid CRAG (Corrective RAG) System

> **An Intelligent Knowledge Graph + RAG System for Document Understanding**

OmniProf is a **hybrid AI system** that combines:

* 📄 Document Ingestion
* 🧠 LLM-based Knowledge Extraction
* 🕸️ Graph-based Reasoning (Neo4j)
* 🔍 Retrieval-Augmented Generation (FAISS)
* 🔄 Corrective RAG (CRAG) Pipeline

to deliver **accurate, explainable, and context-aware answers** from documents.

---

# 🧠 Key Features

## 🔹 1. Hybrid CRAG Architecture

* Combines **Graph Retrieval + Vector Retrieval**
* Uses LLM to **evaluate relevance**
* Retries with refined queries when needed

---

## 🔹 2. Knowledge Graph Construction

* Extracts **concepts + relationships** from PDFs
* Stores them in **Neo4j**
* Supports:

  * Direct relationships
  * Multi-hop reasoning
  * Automatic semantic linking

---

## 🔹 3. Smart Auto-Linking 🔥

* Automatically connects related concepts using:

  * Abbreviation detection (e.g., *FOG → Fiber Optic Gyroscope*)
  * Word overlap
  * Semantic similarity
* Enhances graph completeness beyond LLM output

---

## 🔹 4. Vector Search (RAG)

* Uses **Sentence Transformers + FAISS**
* Efficient semantic retrieval
* Context chunking + similarity search

---

## 🔹 5. Anti-Hallucination System

* LLM evaluates:

  * Context relevance
  * Query alignment
* Rejects irrelevant context
* Prevents false answers

---

## 🔹 6. Query Disambiguation

* Resolves ambiguous queries:

  * "FOG" → "Fiber Optic Gyroscope"
* Improves retrieval accuracy

---

## 🔹 7. Confidence Scoring

* Each response includes:

  * Confidence level
  * Transparency in reasoning

---

# 🏗️ System Architecture

```text
                ┌──────────────┐
                │   PDF Input  │
                └──────┬───────┘
                       ↓
              ┌──────────────────┐
              │ Ingestion Service│
              └──────┬───────────┘
                     ↓
        ┌────────────────────────────┐
        │ LLM Concept Extraction     │
        └──────┬───────────┬────────┘
               ↓           ↓
        ┌──────────┐   ┌────────────┐
        │ Neo4j    │   │ FAISS RAG  │
        │ Graph DB │   │ Vector DB  │
        └────┬─────┘   └────┬───────┘
             ↓              ↓
        ┌──────────────────────────┐
        │   CRAG Retrieval Engine  │
        └──────────┬───────────────┘
                   ↓
            ┌──────────────┐
            │ Final Answer │
            └──────────────┘
```

---

# ⚙️ Tech Stack

| Component   | Technology           |
| ----------- | -------------------- |
| Backend     | FastAPI              |
| LLM         | Groq (LLaMA 3.1)     |
| Vector DB   | FAISS                |
| Embeddings  | SentenceTransformers |
| Graph DB    | Neo4j                |
| PDF Parsing | PyPDF                |
| Frontend    | HTML + JS            |

---

# 📂 Project Structure

```text
backend/
│
├── services/
│   ├── ingestion_service.py
│   ├── crag_service.py
│   ├── rag_service.py
│   ├── graph_service.py
│   └── llm_service.py
│
├── db/
│   └── neo4j_driver.py
│
└── main.py (FastAPI app)

frontend/
└── index.html

.env
requirements.txt
README.md
```

---

# 🔄 Pipeline Flow

## 📥 Ingestion

1. Upload PDF
2. Extract text
3. LLM extracts:

   * Concepts
   * Relationships
4. Store in:

   * Neo4j (graph)
   * FAISS (vector DB)
5. Auto-link concepts

---

## 🔍 Query Execution

1. User query received
2. Query disambiguation
3. Retrieve from:

   * Graph (Neo4j)
   * RAG (FAISS)
4. Build combined context
5. LLM evaluates relevance
6. Retry if needed
7. Generate final answer

---

# 📊 Example Output

```json
{
  "query": "What is FOG?",
  "answer": "Fiber Optic Gyroscope is a sensor used for measuring angular velocity...",
  "confidence": 0.87,
  "graph_results": [...],
  "rag_results": [...]
}
```

---

# 🔥 Unique Highlights

✔ Hybrid Graph + RAG reasoning
✔ Automatic knowledge graph enrichment
✔ Anti-hallucination mechanism
✔ Query refinement loop (CRAG)
✔ Explainable AI (graph + context shown)

---

# 🚀 How to Run

## 1. Clone Repo

```bash
git clone https://github.com/yourusername/omnipro
cd omnipro
```

---

## 2. Install Dependencies

```bash
pip install -r requirements.txt
```

---

## 3. Setup Environment

```env
GROQ_API_KEY=your_key
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
```

---

## 4. Run Backend

```bash
uvicorn main:app --reload
```

---

## 5. Open Frontend

* Open `index.html`
* Upload PDF
* Ask questions

---

# 📈 Future Improvements

* Multi-document memory support
* Graph embeddings integration
* Better UI graph visualization
* Async processing
* Authentication system

---

# 🎯 Use Cases

* Research paper analysis
* Technical documentation Q&A
* Knowledge graph generation
* AI-powered study assistant

---

# 👨‍💻 Author
Piyush Prashant | Priyanshu Mittal | Ankit Dash


---

# ⭐ Final Note

> OmniProf is not just a RAG system —
> it is a **hybrid reasoning engine** combining symbolic (graph) and semantic (vector) intelligence.

---
