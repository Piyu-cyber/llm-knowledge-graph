# 🚀 OmniProf — CRAG-Based Intelligent Document Understanding System

## 🧠 Overview

OmniProf is an advanced AI-powered system designed to **ingest, understand, and reason over documents** using a hybrid architecture that combines:

* 📄 **RAG (Retrieval-Augmented Generation)** for unstructured data
* 🧩 **Knowledge Graph (Neo4j)** for structured relationships
* 🔁 **CRAG (Corrective RAG)** for intelligent query handling

The system enables users to upload PDFs and ask questions, receiving **context-aware, reliable, and explainable answers** with confidence scores.

---

## 🏗️ Architecture

```
PDF → Ingestion → LLM (Concept Extraction)
                      ↓
                Graph DB (Neo4j)
                      ↓
                  RAG (FAISS)

User Query → CRAG Engine → Graph + RAG → LLM → Answer + Confidence
```

---

## 🔥 Key Features

### ✅ 1. Hybrid Retrieval (CRAG Engine)

* Combines:

  * Graph-based retrieval (structured knowledge)
  * Vector search (semantic retrieval via FAISS)
* Performs **relevance evaluation + retry mechanism**

---

### ✅ 2. Knowledge Graph Integration

* Extracts concepts & relationships using LLM
* Stores in Neo4j
* Supports:

  * Concept search
  * Relationship traversal
  * Multi-hop expansion

---

### ✅ 3. RAG Pipeline (FAISS)

* Chunk-based document processing
* Embedding using `all-MiniLM-L6-v2`
* Fast semantic retrieval

---

### ✅ 4. Query Intelligence Layer

* 🔍 Query disambiguation
* 🧠 Summary query detection (hybrid: heuristic + LLM)
* ❓ Ambiguity detection with clarification options

---

### ✅ 5. Anti-Hallucination Mechanism

* Uses LLM-based relevance check:

```
GOOD → proceed  
BAD → retry / stop  
```

---

### ✅ 6. Confidence Scoring

Each response includes a confidence score based on:

* Graph retrieval presence
* RAG retrieval quality
* Relevance evaluation
* Query ambiguity

---

### ✅ 7. Graph Visualization (UI)

* Interactive graph using relationships
* Clickable nodes for exploration
* Enhances interpretability

---

## ⚙️ Tech Stack

| Layer      | Technology           |
| ---------- | -------------------- |
| Backend    | FastAPI              |
| LLM        | Groq (LLaMA 3.1)     |
| Embeddings | SentenceTransformers |
| Vector DB  | FAISS                |
| Graph DB   | Neo4j                |
| Frontend   | HTML + JS (vis.js)   |

---

## 📂 Project Structure

```
backend/
│
├── services/
│   ├── crag_service.py
│   ├── rag_service.py
│   ├── graph_service.py
│   ├── ingestion_service.py
│   ├── llm_service.py
│
├── db/
│   └── neo4j_driver.py
│
├── app.py
```

---

## 🚀 API Endpoints

### 🔹 Health Check

```
GET /
```

---

### 🔹 Upload & Ingest PDF

```
POST /ingest
```

---

### 🔹 Query System

```
GET /query?q=your_query
```

---

### 🔹 Graph Data

```
GET /graph
```

---

### 🔹 Graph Visualization

```
GET /graph-view?query=concept
```

---

## 🧪 Example Queries

* "What is B-Tree?"
* "Explain this document"
* "What is this proposal about?"
* "Difference between CNN and Transformer"

---

## 🧠 How It Works

### 🔹 Ingestion Pipeline

1. Extract text from PDF
2. Use LLM to extract:

   * Concepts
   * Relationships
3. Store in:

   * Graph DB (Neo4j)
   * Vector DB (FAISS)

---

### 🔹 Query Pipeline (CRAG)

1. Detect query type (summary / ambiguous / normal)
2. Retrieve:

   * Graph concepts
   * RAG chunks
3. Evaluate relevance
4. Retry if needed
5. Generate final answer
6. Compute confidence score

---

## ⚠️ Current Limitations

* ❌ FAISS index is in-memory (not persisted)
* ❌ No authentication
* ❌ No async optimization
* ❌ Limited metadata in RAG (no document/page tracking)

---

## 🚀 Future Improvements

* 💾 Persist FAISS index
* ⚡ Async API calls
* 📊 Better graph coverage
* 🧠 Multi-hop reasoning enhancement
* 🔐 Authentication layer
* 📁 Multi-document support

---

## 🎯 Project Highlights

* Hybrid AI system (Graph + RAG + LLM)
* Real-time reasoning with fallback logic
* Confidence-aware responses
* Interactive knowledge visualization

---

## 🧠 Research Inspiration

This project is inspired by:

* Retrieval-Augmented Generation (RAG)
* Knowledge Graph Reasoning
* Corrective RAG (CRAG)

---

## 👨‍💻 Author

Piyush Prashant | Ankit Dash |Priyanshu Mittal

---

## ⭐ Final Note

This project demonstrates a **production-style AI system design**, combining multiple paradigms:

> Graph reasoning + Vector search + LLM intelligence

---

🔥 *Built to go beyond basic chatbots — towards intelligent knowledge systems.*
