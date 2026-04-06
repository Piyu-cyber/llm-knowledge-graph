# 🚀 OmniProf — Hybrid CRAG (Corrective RAG) System

> **An Intelligent Knowledge Graph + Vector Search System for Document Understanding and Question Answering**

OmniProf is an advanced AI system that combines **Graph-based Reasoning** and **Vector-based Retrieval** to deliver accurate, explainable, and context-aware answers from documents. It leverages a **Corrective RAG (CRAG)** pipeline to ensure answer quality and prevent hallucinations.

---

## 📋 Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Technology Stack](#technology-stack)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Running the Application](#running-the-application)
- [API Endpoints](#api-endpoints)
- [Environment Configuration](#environment-configuration)
- [Troubleshooting](#troubleshooting)

---

## 📖 Overview

OmniProf provides a hybrid intelligence platform that combines:

- 📄 **Document Ingestion** — Process PDFs and extract relevant information
- 🧠 **LLM-based Knowledge Extraction** — Automatically identify concepts and relationships
- 🕸️ **Graph-based Reasoning** — Store and query relationships in Neo4j
- 🔍 **Vector Search (RAG)** — Semantic retrieval using FAISS and embeddings
- 🔄 **Corrective RAG Pipeline** — Evaluate and improve retrieval quality iteratively
- 🛡️ **Anti-Hallucination System** — Prevent false answers with relevance evaluation

---

## 🎯 Key Features

### 1. Hybrid CRAG Architecture
- Combines **Graph Retrieval + Vector Retrieval** for comprehensive information access
- Uses LLM to **evaluate relevance** of retrieved content
- Automatically **retries with refined queries** when needed

### 2. Knowledge Graph Construction
- Extracts **concepts and relationships** from documents
- Stores structured data in **Neo4j** for complex queries
- Supports direct relationships, multi-hop reasoning, and semantic linking

### 3. Smart Auto-Linking
- Automatically connects related concepts using:
  - Abbreviation detection (e.g., *FOG → Fiber Optic Gyroscope*)
  - Word overlap analysis
  - Semantic similarity matching
- Enhances graph completeness beyond initial LLM extraction

### 4. Vector Search & Semantic Retrieval
- Uses **Sentence Transformers + FAISS** for efficient similarity search
- Supports semantic query understanding
- Implements context chunking and ranking

### 5. Anti-Hallucination System
- Evaluates context relevance and query alignment
- Filters irrelevant context before generating responses
- Provides confidence scoring for each answer

### 6. Query Disambiguation
- Resolves ambiguous terms with graph context
- Improves retrieval accuracy through semantic understanding

### 7. Explainability & Confidence Scoring
- Each response includes confidence levels
- Provides transparency in reasoning process
- Traces sources and supporting evidence

---

## 🛠️ Technology Stack

| Component | Technology |
|-----------|-----------|
| **Backend Framework** | FastAPI (Python) |
| **Server** | Uvicorn |
| **Knowledge Graph** | Neo4j 5 |
| **Vector Database** | FAISS |
| **Document Processing** | PyPDF |
| **Embeddings** | Sentence Transformers |
| **LLM** | Groq API |
| **Containerization** | Docker & Docker Compose |

---

## 📁 Project Structure

```
omniprof/
├── frontend.html                 # Web interface
├── rag_index.faiss              # Vector search index
├── test_ingestion.py            # Testing script
├── readme.md                     # This file
│
├── backend/                      # Core application
│   ├── app.py                   # FastAPI application entry point
│   ├── requirements.txt          # Python dependencies
│   │
│   ├── auth/
│   │   └── jwt_handler.py       # JWT authentication utilities
│   │
│   ├── db/
│   │   ├── neo4j_driver.py      # Neo4j connection management
│   │   └── vector_store.py      # FAISS vector store operations
│   │
│   ├── models/
│   │   └── schema.py            # Data models and schemas
│   │
│   └── services/                # Business logic
│       ├── crag_service.py      # Corrective RAG pipeline
│       ├── graph_service.py     # Knowledge graph operations
│       ├── ingestion_service.py # Document ingestion
│       ├── llm_service.py       # LLM interactions
│       └── rag_service.py       # Vector search operations
│
└── docker/                       # Container configuration
    └── docker-compose.yml       # Docker services definition
```

---

## ⚙️ Prerequisites

Before you begin, ensure you have the following installed:

- **Python 3.9+** — [Download](https://www.python.org/downloads/)
- **Docker & Docker Compose** — [Download](https://www.docker.com/products/docker-desktop)
- **Git** — [Download](https://git-scm.com/)
- **Node.js** (optional, for frontend modifications) — [Download](https://nodejs.org/)

### Required API Keys

- **Groq API Key** — [Get from Groq console](https://console.groq.com)
- Neo4j credentials (default: `neo4j` / `password`)

---

## 📥 Installation

### Step 1: Clone or Navigate to Project Directory

```bash
cd "path/to/omniprof"
```

### Step 2: Set Up Python Virtual Environment

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate
```

### Step 3: Install Python Dependencies

```bash
cd backend
pip install -r requirements.txt
cd ..
```

### Step 4: Configure Environment Variables

Create a `.env` file in the project root:

```env
# Groq API Configuration
GROQ_API_KEY=your_groq_api_key_here

# Neo4j Configuration
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# Application Settings
DEBUG=False
LOG_LEVEL=INFO
```

**Note:** Replace `your_groq_api_key_here` with your actual Groq API key.

### Step 5: Start Neo4j Database

```bash
# Navigate to docker directory
cd docker

# Start Neo4j using Docker Compose
docker-compose up -d neo4j

# Wait for Neo4j to fully start (30-60 seconds)
# Verify Neo4j is running at: http://localhost:7474
```

---

## 🚀 Running the Application

### Step 1: Ensure Virtual Environment is Active

```bash
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate
```

### Step 2: Start the Backend Server

```bash
cd backend
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

**Output should show:**
```
Uvicorn running on http://127.0.0.1:8000
```

### Step 3: Access the Application

- **API Documentation (Swagger):** http://localhost:8000/docs
- **Frontend:** Open `frontend.html` in your web browser
- **Neo4j Browser:** http://localhost:7474 (username: `neo4j`, password: `password`)

---

## 📡 API Endpoints

### Health Check
```
GET /
Response: {"message": "OmniProf running 🚀"}
```

### Document Ingestion
```
POST /ingest
Content-Type: multipart/form-data
Body: PDF file (file parameter)
Response: Ingestion status and indexed documents
```

### Add Concept Manually
```
POST /concept
Body: {
  "name": "Concept Name",
  "description": "Brief description",
  "category": "Category"
}
```

### Query with CRAG Pipeline
```
POST /query
Body: {
  "query": "Your question here"
}
Response: {
  "answer": "Generated answer",
  "confidence": 0.85,
  "sources": ["..."],
  "reasoning": "..."
}
```

### Full API Documentation
Visit **http://localhost:8000/docs** for interactive Swagger documentation covering all endpoints.

---

## 🔧 Environment Configuration

The application uses environment variables for configuration. Create a `.env` file:

```env
# Groq LLM API
GROQ_API_KEY=your_api_key

# Neo4j Graph Database
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# Application Configuration
DEBUG=False
LOG_LEVEL=INFO
CORS_ORIGINS=["http://localhost:*", "http://127.0.0.1:*"]
```

---

## 🔍 System Architecture

```
                 ┌─────────────────────┐
                 │   Document Input    │
                 │   (PDF Files)       │
                 └──────────┬──────────┘
                            ↓
          ┌─────────────────────────────────┐
          │    Ingestion Service            │
          │  • Extract text from PDFs       │
          │  • Chunk content                │
          └──────────┬──────────────────────┘
                     ↓
      ┌──────────────────────────────────────────┐
      │  Knowledge Extraction                    │
      │  • Groq LLM processes chunks             │
      │  • Identifies concepts & relationships   │
      └─────┬──────────────────────────┬────────┘
            ↓                          ↓
    ┌──────────────────┐     ┌─────────────────────┐
    │  Graph Service   │     │  RAG Service        │
    │  • Neo4j Storage │     │  • FAISS Indexing   │
    │  • Relationships │     │  • Semantic Search  │
    └─────┬────────────┘     └──────┬──────────────┘
          │                         │
          └────────┬────────────────┘
                   ↓
        ┌──────────────────────────┐
        │  CRAG Pipeline           │
        │  • Retrieve from both    │
        │  • Evaluate relevance    │
        │  • Refine if needed      │
        │  • Generate response     │
        └──────────┬───────────────┘
                   ↓
        ┌──────────────────────────┐
        │  User Response           │
        │  + Confidence Score      │
        │  + Source Attribution    │
        └──────────────────────────┘
```

---

## 🐛 Troubleshooting

### Issue: Neo4j Connection Failed
**Solution:**
```bash
# Check if Neo4j container is running
docker ps

# Restart Neo4j
docker-compose down
docker-compose up -d neo4j

# Test connection
docker logs omniprof_neo4j
```

### Issue: Groq API Key Error
**Solution:**
- Verify your API key is correct in `.env`
- Ensure your Groq account has API access enabled
- Check API rate limits haven't been exceeded

### Issue: FAISS Index Not Found
**Solution:**
```bash
# Ingest documents first to create index
curl -X POST "http://localhost:8000/ingest" -F "file=@your_document.pdf"
```

### Issue: ModuleNotFoundError
**Solution:**
```bash
# Ensure virtual environment is activated
# Then reinstall dependencies
pip install -r backend/requirements.txt
```

### Issue: Port Already in Use
**Solution:**
```bash
# Change FastAPI port
uvicorn app:app --port 8001

# Change Neo4j port in docker-compose.yml and restart
```

---

## 📝 Usage Example

### 1. Ingest a Document
```bash
curl -X POST "http://localhost:8000/ingest" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@document.pdf"
```

### 2. Query the System
```bash
curl -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is the main topic of the document?"
  }'
```

### 3. View Results
The response will include the answer, confidence level, and sources.

---

## 🤝 Contributing

To contribute:
1. Create a feature branch: `git checkout -b feature/your-feature`
2. Commit changes: `git commit -m "Add your feature"`
3. Push to branch: `git push origin feature/your-feature`
4. Open a Pull Request

---

## 📄 License

This project is proprietary and confidential. All rights reserved.

---

## 💬 Support

For issues, questions, or suggestions:
- Check the [Troubleshooting](#troubleshooting) section
- Review API documentation at http://localhost:8000/docs
- Contact the development team

---

**Last Updated:** April 2026  
**Version:** 1.0.0
