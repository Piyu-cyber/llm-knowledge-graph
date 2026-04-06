# OmniProf v3.0 - Implementation Guide

**AI-Driven Educational Platform with Multi-Agent Orchestration, Dual-Store Memory, and Adaptive Tutoring**


---

## Table of Contents

1. [System Overview](#system-overview)
2. [Architecture](#architecture)
3. [Prerequisites](#prerequisites)
4. [Installation](#installation)
5. [Configuration](#configuration)
6. [Running the System](#running-the-system)
7. [API Endpoints](#api-endpoints)
8. [Development Workflow](#development-workflow)
9. [Troubleshooting](#troubleshooting)
10. [Project Structure](#project-structure)

---

## System Overview

OmniProf is a comprehensive AI-driven educational platform that combines:

- **Multi-Agent Orchestration** (LangGraph) - Coordinated AI agents for tutoring, evaluation, integrity checking, and engagement
- **Dual-Store Memory** (FAISS + RustWorkX) - Episodic (vector-based) and semantic (fact-based) memory for personalized learning
- **Adaptive Tutoring** - CRAG pipeline with depth adaptation and Socratic questioning
- **Knowledge Tracing** - Bayesian Knowledge Tracing (BKT) to model student understanding
- **Gamification** - Achievement badges and progress tracking
- **Academic Integrity** - Writing fingerprint analysis and Style Deviation Index

### Key Features

✅ **Real-time Multi-Turn Chat** - `/chat` endpoint with full agent orchestration  
✅ **Adaptive Explanations** - Basic/Intermediate/Advanced based on mastery  
✅ **Context-Aware Responses** - Episodic memory + semantic facts + session history  
✅ **Knowledge State Tracking** - BKT parameters per concept  
✅ **Background Processing** - Curriculum propagation, session summarization  
✅ **Achievement System** - Student-private badges for motivation  

---

## Architecture

### System Layers

```
┌─────────────────────────────────────────┐
│         FastAPI REST Interface          │  ← /chat, /query, /auth endpoints
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│     LangGraph Multi-Agent Orchestration │  ← Intent routing, agent coordination
├────────────────┬────────────────────────┤
│ TAAgent        │ EvaluatorAgent         │  ← Tutoring & Evaluation
│ IntegrityAgent │ CognitiveEngineAgent   │  ← Integrity & Knowledge Updates
│ CurriculumAgent│ GamificationAgent      │  ← Curriculum & Achievements
│ SummarisationAgent (Background)         │  ← Memory Management
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│         Dual-Store Memory System        │
├────────────────┬────────────────────────┤
│ FAISS Index    │ RustWorkX Graph    │  ← Episodic + Semantic Memory
│ (Vector Search)│ (Knowledge + Overlays) │
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│      Core Services & Utilities          │
├────────────────┬────────────────────────┤
│ RAGService     │ CRAGService            │  ← Knowledge Retrieval
│ LLMService     │ GraphService           │  ← LLM + Graph Queries
│ CognitiveEngine│ IngestionService       │  ← Learning Models + Document Processing
└────────────────────────────────────────┘
```

### Data Flow: Chat Request → Response

```
POST /chat {message, session_id}
         ↓
    [JWT Authentication]
         ↓
[Create AgentState from session]
         ↓
[intent_classifier.classify(message)]
         ↓
        ┌─────────────────────────────────┐
        │ Route by Intent                 │
        ├─────────────────────────────────┤
        │ academic_query →  TAAgent       │
        │ submission_  →  EvaluatorAgent  │
        │ curriculum_  →  CurriculumAgent │
        │ progress_    →  ProgressAgent   │
        └─────────────────────────────────┘
         ↓
[Execute Agent with Context Window]
    (Session history + Episodic + Anchors + RAG + Overlay)
         ↓
[Generate Response + Update State]
         ↓
[Queue Background Tasks if Needed]
         ↓
ChatResponse {response, active_agent, achievements, metadata}
```

---

## Prerequisites

### System Requirements

- **Python**: 3.8+
- **Node.js**: 14+ (optional, for frontend)
- **RustWorkX**: For graph operations (installed via pip)
- **FAISS**: CPU or GPU version
- **Groq API**: For LLM access (llama-3.3-70b-versatile)

### External Services

1. **Groq API**
   - Sign up at [console.groq.com](https://console.groq.com)
   - Get API key for llama-3.3-70b-versatile model

2. **Sentence Transformers** (for embeddings)
   - Pre-trained model: `sentence-transformers/all-MiniLM-L6-v2` (384-dim)

3. **RustWorkX** (for knowledge graph)
   - Rust-backed Python library for graph operations
   - Data persists locally as JSON (no external database needed)

---

## Installation

### Step 1: Clone Repository

```bash
git clone <repository-url>
cd omniprof
```

### Step 2: Create Virtual Environment

```bash
# Using Python venv
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# OR using conda
conda create -n omniprof python=3.10
conda activate omniprof
```

### Step 3: Install Dependencies

```bash
# Install all dependencies (including RustWorkX)
pip install -r requirements.txt

# RustWorkX is included in requirements.txt
# For development tools:
pip install pytest pytest-cov black flake8
```

### Step 4: Create `.env` File

```bash
cp .env.example .env
# Edit .env with your configuration (see Configuration section)
```

### Step 5: Verify Installation

```bash
python -c "import faiss; import rustworkx; import groq; print('✅ All imports successful')"
```

---

## Configuration

### Environment Variables (`.env` file)

```bash
# ==================== Graph Persistence ====================
# Local directory where RustWorkX JSON data (nodes/edges) will be stored
GRAPH_DATA_DIR=data/graph

# ==================== LLM API ====================
GROQ_API_KEY=gsk_xxxxxxxxxxxxx  # Get from console.groq.com
GROQ_MODEL=llama-3.3-70b-versatile

# ==================== Embeddings ====================
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
EMBEDDING_DIM=384

# ==================== Vector Search ====================
MEMORY_INDEX_PATH=data/episode_memory.faiss
TEMPORAL_LAMBDA=0.1  # Decay constant for episodic memory

# ==================== Authentication ====================
JWT_SECRET_KEY=your_secret_key_here  # Use: python -c "import secrets; print(secrets.token_urlsafe(32))"
JWT_ALGORITHM=HS256
JWT_EXPIRATION_HOURS=24

# ==================== Server ====================
HOST=0.0.0.0
PORT=8000
LOG_LEVEL=INFO

# ==================== Optional: AWS/Cloud ====================
AWS_REGION=us-east-1  # For future cloud storage
```

### RustWorkX Graph (no external DB)

RustWorkX is used as an in-process, Rust-backed graph engine. Data persists locally as JSON files under the directory configured by `GRAPH_DATA_DIR` (default: `data/graph`). No external database installation is required.

### Initialize Graph Manager

Use the `GraphManager` to initialize and inspect the local graph store:

```bash
python -c "
from backend.db.graph_manager import GraphManager
manager = GraphManager(data_dir='data/graph')
print('✅ RustWorkX GraphManager initialized')
"
```

---

## Running the System

### Development Server

```bash
# Start FastAPI development server
uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000

# Server will be available at http://localhost:8000
# API docs at http://localhost:8000/docs
# ReDoc at http://localhost:8000/redoc
```

### Production Server

```bash
# Using Gunicorn (production ASGI server)
pip install gunicorn

gunicorn backend.app:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --log-level info
```

### Docker Deployment

```bash
# Build Docker image
docker build -t omniprof:latest .

# Run container (mount a persistent data directory for RustWorkX JSON files)
docker run -p 8000:8000 \
  -v $(pwd)/data/graph:/app/data/graph \
  -e GROQ_API_KEY=your_key \
  omniprof:latest
```

### Docker Compose (Full Stack)

```bash
# Start services (backend)
docker-compose up -d

# Check logs for backend
docker-compose logs -f backend
```

---

## API Endpoints

### Authentication

#### Register User

```bash
POST /auth/register
Content-Type: application/json

{
  "username": "student_001",
  "email": "student@example.com",
  "password": "secure_password",
  "full_name": "John Doe",
  "role": "student"  # "student" | "professor" | "admin"
}

# Response
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user_id": "user_123",
  "username": "student_001",
  "role": "student"
}
```

#### Login

```bash
POST /auth/login
Content-Type: application/json

{
  "username": "student_001",
  "password": "secure_password"
}

# Response: Same as register
```

#### Get Current User

```bash
GET /auth/me
Authorization: Bearer {access_token}

# Response
{
  "user_id": "user_123",
  "username": "student_001",
  "email": "student@example.com",
  "full_name": "John Doe",
  "role": "student",
  "course_ids": ["course_1", "course_2"],
  "created_at": "2026-04-06T10:00:00Z"
}
```

### Main Chat Interface (Phase 4-5)

#### Chat with Multi-Agent Orchestration

```bash
POST /chat
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "message": "Can you explain photosynthesis?",
  "session_id": "sess_abc123",
  "course_id": "bio_101"  # optional
}

# Response
{
  "response": "Photosynthesis is a process where plants convert sunlight into chemical energy...",
  "session_id": "sess_abc123",
  "active_agent": "ta_agent",
  "metadata": {
    "intent": "academic_query",
    "crag_score": 0.87,
    "achievements": [],
    "new_achievements_count": 0,
    "context_sources": {
      "session_history": 8,
      "episodic_memories": 3,
      "memory_anchors": 1
    }
  },
  "message_count": 9,
  "error": null
}
```

### Legacy Query Endpoint

```bash
POST /query
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "query": "What is photosynthesis?",
  "confidence_threshold": 0.5
}

# Response
{
  "query": "What is photosynthesis?",
  "answer": "...",
  "confidence": 0.87,
  "sources": ["biology_doc_1", "biology_doc_2"],
  "graph_results": [...],
  "rag_results": [...]
}
```

### Knowledge Management

#### Enroll in Course

```bash
POST /enrol
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "course_id": "bio_101"
}

# Response
{
  "status": "success",
  "student_id": "user_123",
  "course_id": "bio_101",
  "overlays_created": 24,
  "message": "Successfully enrolled in course"
}
```

#### Record Interaction

```bash
POST /interaction
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "concept_id": "photosynthesis_id",
  "answered_correctly": true,
  "difficulty": 0.6
}

# Response
{
  "status": "success",
  "user_id": "user_123",
  "concept_id": "photosynthesis_id",
  "answered_correctly": true,
  "event_type": "knowledge_gain",
  "previous": {
    "theta": 0.3,
    "mastery_probability": 0.45
  },
  "updated": {
    "theta": 0.5,
    "mastery_probability": 0.62
  }
}
```

#### Ingest Documents

```bash
POST /ingest
Authorization: Bearer {access_token}
Content-Type: multipart/form-data

file: @document.pdf  # Supports: PDF, DOCX, PPTX, TXT
```

#### Get Knowledge Graph

```bash
GET /graph
Authorization: Bearer {access_token}

# Response
{
  "modules": [...],
  "topics": [...],
  "concepts": [...],
  "edges": [...]
}
```

---

## Development Workflow

### Project Structure

```
omniprof/
├── backend/
│   ├── agents/                    # LangGraph agents
│   │   ├── ta_agent.py           # Adaptive tutoring
│   │   ├── evaluator_agent.py    # Submission evaluation
│   │   ├── integrity_agent.py    # Writing analysis
│   │   ├── cognitive_engine_agent.py  # BKT updates
│   │   ├── curriculum_agent.py   # Curriculum changes
│   │   ├── gamification_agent.py # Achievement tracking
│   │   ├── summarisation_agent.py # Session memory
│   │   ├── graph.py              # LangGraph orchestration
│   │   ├── state.py              # State definitions
│   │   ├── intent_classifier.py  # Intent routing
│   │   └── __init__.py
│   │
│   ├── services/                 # Core services
│   │   ├── memory_service.py     # Dual-store memory (FAISS + semantic)
│   │   ├── rag_service.py        # Vector retrieval
│   │   ├── crag_service.py       # Corrective RAG
│   │   ├── llm_service.py        # Groq LLM interface
│   │   ├── graph_service.py      # Neo4j queries
│   │   ├── cognitive_engine.py   # BKT implementation
│   │   ├── ingestion_service.py  # Document processing
│   │   └── __init__.py
│   │
│   ├── db/                       # Database layer
│   │   ├── neo4j_driver.py       # Neo4j connection
│   │   ├── neo4j_schema.py       # Schema definitions
│   │   └── __init__.py
│   │
│   ├── auth/                     # Authentication
│   │   ├── jwt_handler.py        # JWT tokens
│   │   ├── rbac.py               # Role-based access
│   │   └── __init__.py
│   │
│   ├── models/                   # Data models
│   │   ├── schema.py             # Pydantic models
│   │   └── __init__.py
│   │
│   ├── app.py                    # FastAPI application
│   └── __init__.py
│
├── data/                         # Data storage
│   ├── episode_memory.faiss      # FAISS vector index (auto-created)
│   └── documents/                # Ingested files
│
├── tests/                        # Test suite
│   ├── test_agents.py
│   ├── test_services.py
│   ├── test_memory.py
│   └── conftest.py
│
├── docker/                       # Docker configuration
│   ├── Dockerfile
│   └── docker-compose.yml
│
├── .env.example                  # Environment template
├── .gitignore
├── requirements.txt              # Python dependencies
├── README.md                      # This file
├── Phase_4_Part1.md             # Phase 4 Part 1 documentation
├── Phase_4_Part2.md             # Phase 4 Part 2 documentation
├── Phase_4_Part3.md             # Phase 4 Part 3 documentation
├── Phase_4_Part4.md             # Phase 4 Part 4 documentation
└── Phase_5_Memory_System.md     # Phase 5 documentation
```

### Adding New Features

#### Add New Agent

1. Create agent file: `backend/agents/new_agent.py`
2. Implement `process(state: AgentState) -> AgentState` method
3. Add to `OmniProfGraph` in `backend/agents/graph.py`
4. Update `backend/agents/__init__.py` exports
5. Add routing logic in `_route_by_intent()` if needed

#### Add New Service

1. Create service file: `backend/services/new_service.py`
2. Implement with logging and error handling
3. Add to `backend/services/__init__.py`
4. Integrate into agents/endpoints as needed

#### Add New API Endpoint

1. Add request/response models in `backend/models/schema.py`
2. Implement endpoint in `backend/app.py`
3. Add JWT authentication via `@app.post(... Depends(get_current_user))`
4. Test with `curl` or Postman

### Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_agents.py -v

# Run with coverage
pytest --cov=backend tests/

# Run specific test
pytest tests/test_agents.py::test_ta_agent_process -v
```

### Code Style

```bash
# Format code
black backend/

# Check linting
flake8 backend/ --max-line-length=100

# Type checking
mypy backend/ --ignore-missing-imports
```

### Logging

Configure logging in `backend/app.py`:

```python
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # or INFO, WARNING, ERROR
```

All agents include comprehensive logging:
```
logger.debug(f"TA Agent starting CRAG loop...")
logger.info(f"TA Agent completed with depth={depth}")
logger.warning(f"Could not retrieve embedding")
logger.error(f"Failed to update overlay: {error}")
```

---

## Troubleshooting

### Common Issues & Solutions

#### 1. Neo4j Connection Error

```
Error: Could not connect to bolt://localhost:7687
```

**Solution:**
```bash
# Check if Neo4j is running
docker ps | grep neo4j

# If not running, start it:
docker run --name neo4j -p 7687:7687 -p 7474:7474 \
  -e NEO4J_AUTH=neo4j/password neo4j:4.4-community

# Verify .env has correct credentials
cat .env | grep NEO4J_
```

#### 2. FAISS Import Error

```
ImportError: No module named 'faiss'
```

**Solution:**
```bash
# Install FAISS
pip install faiss-cpu

# Or for GPU:
pip install faiss-gpu
```

#### 3. Groq API Key Invalid

```
Error: Invalid API key for Groq
```

**Solution:**
```bash
# 1. Get new API key from https://console.groq.com
# 2. Update .env:
GROQ_API_KEY=gsk_your_new_key

# 3. Restart the server
```

#### 4. Out of Memory with FAISS

```
MemoryError: Cannot allocate X GB for FAISS index
```

**Solution:**
```bash
# Option 1: Use GPU (faster and less memory)
pip uninstall faiss-cpu
pip install faiss-gpu

# Option 2: Reduce batch size in memory_service.py
# Option 3: Archive old memories periodically
```

#### 5. Student Overlay Not Found

```
Error: No StudentOverlay for user X, concept Y
```

**Solution:**
```python
# Student must enroll in course first:
# POST /enrol with course_id

# Or manually create overlays:
from backend.services.graph_service import GraphService
gs = GraphService()
gs.enroll_student("user_123", "course_123")
```

#### 6. Vector Embedding Dimension Mismatch

```
Error: Embedding dimension 768 != expected 384
```

**Solution:**
```bash
# Check .env has correct model:
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
EMBEDDING_DIM=384

# Or use different model with matching dimension
# Popular models:
# - all-MiniLM-L6-v2 (384-dim, faster)
# - all-mpnet-base-v2 (768-dim, better quality)
```

#### 7. JWT Token Expired

```
Error: Token signature has expired
```

**Solution:**
```python
# Increase expiration in .env:
JWT_EXPIRATION_HOURS=72  # Instead of 24

# Or login again to get fresh token:
# POST /auth/login
```

### Debug Mode

Enable detailed logging:

```python
# In backend/app.py or .env
LOG_LEVEL=DEBUG

# Or manually:
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Database Debugging (inspect via Python API)

Use the `GraphManager` API to inspect and debug the graph store. Example:

```bash
python - <<'PY'
from backend.db.graph_manager import GraphManager
g = GraphManager(data_dir='data/graph')
print('nodes:', g.get_node_count())
print('edges:', g.get_edge_count())
# Example: search concepts or overlays
print(g.search_concepts('photosynthesis', limit=10))
PY
```

### Performance Tuning

```python
# In services:
# 1. Increase FAISS batch size for faster indexing
# 2. Cache frequently accessed queries
# 3. Optimize graph operations (caching, batching, and simple in-code indexes)
# 4. Profile with:

import cProfile
cProfile.run('ta_agent.process(state)')
```

---

## Next Steps

### Immediate Tasks

1. ✅ Install prerequisites and dependencies
2. ✅ Set up graph data directory and `.env` configuration
3. ✅ Run development server and verify API docs
4. ✅ Create test user and authenticate
5. ✅ Ingest sample documents
6. ✅ Test `/chat` endpoint with diverse intents

### Enhancement Ideas

- [ ] Frontend UI (React/Vue) for chat interface
- [ ] Student dashboard with progress analytics
- [ ] Professor tools for curriculum management
- [ ] Analytics dashboard for learning metrics
- [ ] Mobile app (React Native)
- [ ] Real-time WebSocket chat
- [ ] Collaborative learning features
- [ ] Advanced search with semantic similarity
- [ ] Custom knowledge graphs per course
- [ ] A/B testing for adaptive strategies

### Production Deployment

1. **Use environment-specific configs** (dev/staging/prod)
2. **Set up monitoring** (Prometheus, Grafana)
3. **Enable logging/audit trails** (ELK stack)
4. **Configure SSL/TLS** for HTTPS
5. **Set up database backups** (periodic data snapshots of `GRAPH_DATA_DIR`)
6. **Implement rate limiting** (FastAPI middleware)
7. **Use container orchestration** (Kubernetes)
8. **Set up CI/CD pipeline** (GitHub Actions, GitLab CI)

---

## Support & Documentation

- **API Documentation**: http://localhost:8000/docs (Swagger UI)
- **Phase 4 Documentation**: See `Phase_4_Part*.md` files
- **Phase 5 Memory System**: See `Phase_5_Memory_System.md`
- **Code Comments**: Comprehensive docstrings in all modules

---

## License

[Add appropriate license]

## Contributors

OmniProf v3.0 - Built with LangGraph, RustWorkX, FAISS, and Groq LLM

---

**Last Updated**: April 6, 2026  
**Maintained By**: [Your Name/Organization]  
**Latest Version**: 3.0.0
