from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, status, BackgroundTasks, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import shutil
import os
import tempfile
import bcrypt
import jwt as pyjwt
import logging
import re
from datetime import timedelta, datetime, timezone
from typing import Optional, Dict, Tuple, Any, List

from backend.services.graph_service import GraphService
from backend.services.llm_service import LLMService
from backend.services.rag_service import RAGService
from backend.services.crag_service import CRAGService
from backend.services.ingestion_service import IngestionService
from backend.services.cognitive_engine import CognitiveEngine
from backend.services.llm_router import LLMRouter
from backend.services.background_job_queue import BackgroundJobQueue
from backend.services.compliance_service import ComplianceService
from backend.db.neo4j_driver import Neo4jGraphManager
from backend.db.user_store import UserStore
from backend.auth.jwt_handler import create_access_token, verify_token, get_user_from_token
from backend.auth.rbac import UserContext
from backend.models.schema import (
    UserRegister, UserLogin, TokenResponse, UserResponse,
    QueryRequest, QueryResponse, ChatRequest, ChatResponse,
    ConceptCreate, ConceptResponse,
    EnrollmentRequest, EnrollmentResponse,
    InteractionRequest, InteractionResponse
)
from backend.agents import OmniProfGraph, AgentState
from backend.agents.summarisation_agent import process_old_interactions_background
from backend.agents.curriculum_agent import process_curriculum_change_background


app = FastAPI(
    title="OmniProf v3.0",
    description="Hybrid CRAG System for Educational Knowledge Management",
    version="3.0.0"
)

# 🔐 Security setup
security = HTTPBearer()

# 🗄️ Persistent user store
user_store = UserStore(data_dir="data")


# ==================== Dependency Functions ====================
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict:
    """
    Verify JWT token and extract user information.
    This is used as a dependency to protect endpoints.
    """
    token = credentials.credentials
    try:
        user_data = get_user_from_token(token)
        return user_data
    except pyjwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_admin_user(current_user: Dict = Depends(get_current_user)) -> Dict:
    """Verify current user is an admin."""
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user


async def get_professor_user(current_user: Dict = Depends(get_current_user)) -> Dict:
    """Verify current user is a professor or admin."""
    if current_user.get("role") not in ["professor", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Professor access required"
        )
    return current_user


# ==================== Helper Functions ====================
def hash_password(password: str) -> str:
    """Hash password using bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash."""
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())


def ensure_default_users() -> None:
    """Create default student/professor users for local testing if absent."""
    seed_logger = logging.getLogger(__name__)
    defaults = [
        {
            "username": "student_demo",
            "email": "student_demo@omniprof.local",
            "password": "Student@123",
            "role": "student",
            "course_ids": ["cs101"],
            "user_id": "user_default_student",
            "full_name": "Demo Student",
        },
        {
            "username": "professor_demo",
            "email": "professor_demo@omniprof.local",
            "password": "Professor@123",
            "role": "professor",
            "course_ids": ["cs101"],
            "user_id": "user_default_professor",
            "full_name": "Demo Professor",
        },
    ]

    for account in defaults:
        if user_store.user_exists(account["username"]):
            continue
        if user_store.email_exists(account["email"]):
            seed_logger.warning(
                "Skipping default user seed for %s because email already exists",
                account["username"],
            )
            continue

        user_store.add_user(
            account["username"],
            {
                "user_id": account["user_id"],
                "username": account["username"],
                "email": account["email"],
                "password": hash_password(account["password"]),
                "full_name": account["full_name"],
                "role": account["role"],
                "course_ids": account["course_ids"],
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        seed_logger.info("Default test user seeded: %s", account["username"])


ensure_default_users()


def create_user_context(current_user: Dict) -> UserContext:
    """
    Create UserContext object from JWT token user data.
    
    Args:
        current_user: User dict from JWT token containing user_id, role, course_ids
    
    Returns:
        UserContext object for RBAC enforcement
    """
    return UserContext(
        user_id=current_user.get("user_id", ""),
        role=current_user.get("role", "student"),
        course_ids=current_user.get("course_ids", [])
    )


def _parse_iso_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        normalized = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        return None


def _active_topic_name_for_message(message: str, course_id: Optional[str]) -> Optional[str]:
    if not message:
        return None
    candidates = graph_manager.search_concepts(message, course_id=course_id)
    if not candidates:
        for token in str(message).split():
            cleaned = token.strip().lower()
            if len(cleaned) < 4:
                continue
            candidates = graph_manager.search_concepts(cleaned, course_id=course_id)
            if candidates:
                break
    if not candidates:
        return None
    topic_id = candidates[0].get("topic_id")
    topic = graph_manager.nodes_data.get(topic_id) if topic_id else None
    return topic.get("name") if topic else None


def _build_student_progress(student_id: str, course_id: Optional[str]) -> Dict[str, Any]:
    overlays = graph_manager.get_student_concepts(student_id)
    if course_id:
        overlays = [
            row for row in overlays
            if graph_manager.nodes_data.get(row.get("concept_id"), {}).get("course_owner") == course_id
        ]

    concepts_visited = 0
    visited_modules = set()
    mastery_bands = []

    for row in overlays:
        concept_id = row.get("concept_id")
        concept = graph_manager.nodes_data.get(concept_id, {})
        topic = graph_manager.nodes_data.get(concept.get("topic_id"), {}) if concept else {}
        module = graph_manager.nodes_data.get(topic.get("module_id"), {}) if topic else {}

        visited = bool(row.get("visited"))
        if visited:
            concepts_visited += 1
            if module.get("id"):
                visited_modules.add(module.get("id"))
            elif topic.get("module_id"):
                visited_modules.add(topic.get("module_id"))

        mastery = float(row.get("mastery_probability", 0.0))
        mastery = max(0.0, min(1.0, mastery))
        if mastery < 0.4:
            band = "low"
        elif mastery < 0.75:
            band = "medium"
        else:
            band = "high"

        mastery_bands.append(
            {
                "concept_id": concept_id,
                "concept_name": concept.get("name", concept_id),
                "topic_name": topic.get("name"),
                "module_name": module.get("name"),
                "mastery_probability": mastery,
                "confidence_band": band,
                "visited": visited,
            }
        )

    return {
        "student_id": student_id,
        "course_id": course_id,
        "modules_explored": len(visited_modules),
        "concepts_visited": concepts_visited,
        "mastery": mastery_bands,
    }


def _iter_stream_chunks(text: str):
    """Yield token-like chunks for websocket streaming (word+punctuation, preserving spaces)."""
    if not text:
        return

    # Default to token-style chunks; allow env override for character streaming.
    mode = os.getenv("WS_STREAM_CHUNK_MODE", "token").strip().lower()
    if mode == "char":
        for ch in text:
            yield ch
        return

    # Token-like split preserving punctuation and trailing whitespace.
    for chunk in re.findall(r"\w+|[^\w\s]|\s+", text):
        if chunk:
            yield chunk


# 🔹 CORS (frontend access)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔹 Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)
for noisy_logger in ["httpx", "sentence_transformers", "transformers", "watchfiles.main"]:
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)

# 🔹 Initialize shared services
rag_service = RAGService()
llm_service = LLMService()
graph_manager = Neo4jGraphManager()
graph_service = GraphService(graph_manager)
cognitive_engine = CognitiveEngine()
llm_router = LLMRouter(llm_service=llm_service)
background_job_queue = BackgroundJobQueue(data_dir=graph_manager.data_dir)
compliance_service = ComplianceService(data_dir=graph_manager.data_dir)

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

# 🔹 Lazy initialize OmniProf multi-agent orchestration graph
omniprof_graph: Optional[OmniProfGraph] = None


def get_omniprof_graph() -> OmniProfGraph:
    """Initialize the heavy multi-agent graph only when chat is first used."""
    global omniprof_graph
    if omniprof_graph is None:
        logger.info("Initializing OmniProf graph on first chat request")
        omniprof_graph = OmniProfGraph()
    return omniprof_graph


# ==================== AUTHENTICATION ENDPOINTS ====================

@app.post("/auth/register", response_model=TokenResponse, tags=["Authentication"])
def register(user_data: UserRegister):
    """
    Register a new user.
    
    Returns access token on successful registration.
    """
    try:
        # Check if user already exists
        if user_store.user_exists(user_data.username):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already exists"
            )
        
        # Check email not already used
        if user_store.email_exists(user_data.email):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
        
        # Create user
        user_id = f"user_{user_store.get_user_count() + 1}"
        user_store.add_user(user_data.username, {
            "user_id": user_id,
            "username": user_data.username,
            "email": user_data.email,
            "password": hash_password(user_data.password),
            "full_name": user_data.full_name or user_data.username,
            "role": user_data.role,
            "course_ids": [],
            "created_at": os.popen("date").read().strip()
        })
        
        # Generate token
        access_token = create_access_token(
            user_id=user_id,
            role=user_data.role,
            course_ids=[]
        )
        
        return TokenResponse(
            access_token=access_token,
            user_id=user_id,
            username=user_data.username,
            role=user_data.role
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {str(e)}"
        )


@app.post("/auth/login", response_model=TokenResponse, tags=["Authentication"])
def login(credentials: UserLogin):
    """
    Login user with username and password.
    
    Returns access token on successful login.
    """
    try:
        # Check user exists
        user = user_store.get_user_by_username(credentials.username)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password"
            )
        
        # Verify password
        if not verify_password(credentials.password, user["password"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password"
            )
        
        # Generate token
        access_token = create_access_token(
            user_id=user["user_id"],
            role=user["role"],
            course_ids=user.get("course_ids", [])
        )
        
        return TokenResponse(
            access_token=access_token,
            user_id=user["user_id"],
            username=user["username"],
            role=user["role"]
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Login failed: {str(e)}"
        )


@app.get("/auth/me", response_model=UserResponse, tags=["Authentication"])
def get_current_user_info(current_user: Dict = Depends(get_current_user)):
    """
    Get current authenticated user information.
    """
    try:
        user_id = current_user.get("user_id")
        
        # Find user by user_id
        user_data = user_store.get_user_by_id(user_id)
        if user_data:
            return UserResponse(
                user_id=user_data["user_id"],
                username=user_data["username"],
                email=user_data["email"],
                full_name=user_data.get("full_name"),
                role=user_data["role"],
                course_ids=user_data.get("course_ids", []),
                created_at=user_data.get("created_at")
            )
        
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching user: {str(e)}"
        )


# ==================== PROTECTED ENDPOINTS ====================

# 🔹 Health check (public)
@app.get("/", tags=["Health"])
def home():
    """Health check endpoint - public access"""
    return {"message": "OmniProf v3.0 running", "version": "3.0.0"}


# 🔹 Add concept manually (protected)
@app.post("/concept", response_model=ConceptResponse, tags=["Concepts"])
def add_concept(
    concept: ConceptCreate,
    current_user: Dict = Depends(get_current_user)
):
    """
    Create a new concept in the knowledge graph.
    Requires authentication.
    """
    try:
        if not concept.name.strip():
            raise HTTPException(status_code=400, detail="Concept name cannot be empty")

        result = graph_service.create_concept(
            concept.name,
            concept.description,
            category=concept.category
        )
        
        return ConceptResponse(
            concept_id=result.get("id", ""),
            name=concept.name,
            description=concept.description,
            category=concept.category,
            course_id=concept.course_id
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 🔹 Student enrollment (protected)
@app.post("/enrol", response_model=EnrollmentResponse, tags=["Enrollment"])
def enrol_student(
    enrollment: EnrollmentRequest,
    background_tasks: BackgroundTasks,
    current_user: Dict = Depends(get_current_user)
):
    """
    Enroll a student in a course by initializing StudentOverlay nodes.
    
    Creates StudentOverlay nodes for all concepts in the course with:
    - theta=0.0 (initial knowledge state)
    - slip=0.1 (slip probability)
    - visited=False (not yet visited)
    - mastery_probability=0.5 (initial mastery estimate)
    
    Requires authentication. Students can only enroll themselves.
    """
    try:
        # Only allow students to enroll themselves
        if current_user.get("role") not in ["student", "professor", "admin"]:
            raise HTTPException(
                status_code=403,
                detail="Only authenticated users can enroll"
            )
        
        user_id = current_user.get("user_id")
        course_id = enrollment.course_id
        
        if not user_id or not course_id:
            raise HTTPException(
                status_code=400,
                detail="User ID and course ID are required"
            )
        
        # Enroll student in course asynchronously to avoid blocking on large graphs
        result = graph_service.enqueue_enrollment_overlay_init(user_id, course_id, background_tasks)

        # Keep persistent user profile aligned with enrollment metadata.
        user_record = user_store.get_user_by_id(user_id)
        if user_record:
            username = user_record.get("username")
            current_courses = set(user_record.get("course_ids", []))
            current_courses.add(course_id)
            user_store.update_user(username, {"course_ids": sorted(current_courses)})
        
        if result.get("status") == "error":
            raise HTTPException(
                status_code=500,
                detail=result.get("message", "Enrollment failed")
            )
        
        return EnrollmentResponse(
            status="success" if result.get("status") in {"success", "queued"} else "error",
            student_id=user_id,
            course_id=course_id,
            overlays_created=result.get("overlays_created", 0),
            message=result.get("message", "Enrollment successful")
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Enrollment error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Enrollment failed: {str(e)}")


# 🔹 Record student interaction (protected)
@app.post("/interaction", response_model=InteractionResponse, tags=["Learning"])
def record_interaction(
    interaction: InteractionRequest,
    current_user: Dict = Depends(get_current_user)
):
    """
    Record a student's interaction with a concept and update their knowledge state.
    
    Uses Bayesian Knowledge Tracing (IRT 2-parameter logistic model) to update:
    - theta (knowledge state)
    - slip (careless error probability)
    - mastery_probability (estimated probability of mastery)
    
    Detects Slip events: If student has mastered all prerequisites (> 0.8) but
    failed this attempt, classifies as Slip (careless error), not Knowledge Gap.
    
    Requires authentication.
    """
    try:
        user_id = current_user.get("user_id")
        concept_id = interaction.concept_id
        
        if not user_id or not concept_id:
            raise HTTPException(
                status_code=400,
                detail="User ID and concept ID are required"
            )
        
        # Record interaction and update knowledge state
        result = cognitive_engine.update_student_overlay(
            user_id=user_id,
            concept_id=concept_id,
            answered_correctly=interaction.answered_correctly,
            difficulty=interaction.difficulty
        )
        
        if result.get("status") == "error":
            raise HTTPException(
                status_code=500,
                detail=result.get("message", "Failed to record interaction")
            )
        
        return InteractionResponse(
            status=result.get("status"),
            user_id=result.get("user_id"),
            concept_id=result.get("concept_id"),
            answered_correctly=result.get("answered_correctly"),
            event_type=result.get("event_type"),
            previous=result.get("previous"),
            updated=result.get("updated"),
            difficulty=result.get("difficulty")
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Interaction recording error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to record interaction: {str(e)}")


# 🔹 Get full graph (protected)
@app.get("/graph", tags=["Graph"])
def get_graph(current_user: Dict = Depends(get_current_user)):
    """
    Get the full knowledge graph.
    Requires authentication.
    """
    try:
        # Create user context for RBAC enforcement
        user_context = create_user_context(current_user)
        
        # Call graph service with user context
        result = graph_service.get_graph()
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 🔥 Graph visualization endpoint (protected)
@app.get("/graph-view", tags=["Graph"])
def graph_view(
    query: str,
    current_user: Dict = Depends(get_current_user)
):
    """
    Get graph visualization for a concept query.
    Requires authentication.
    """
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


# 🔥 File upload + ingestion (protected - multi-format support)
@app.post("/ingest", tags=["Ingestion"])
def ingest(
    file: UploadFile = File(...),
    current_user: Dict = Depends(get_current_user)
):
    """
    Ingest documents in multiple formats: PDF, DOCX, PPTX, or TXT.
    Extracts hierarchical knowledge structure and returns validation results.
    
    Supports:
    - PDF files (.pdf)
    - Word documents (.docx, .doc)
    - PowerPoint presentations (.pptx, .ppt)
    - Plain text files (.txt)
    
    Requires authentication. Returns ingestion results with validation errors (if any).
    """
    temp_path = None
    try:
        # Validate file format
        from backend.services.ingestion_service import MultiFormatExtractor
        
        file_format = MultiFormatExtractor.get_file_format(file.filename)
        if not file_format:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file format. Supported: PDF, DOCX, PPTX, TXT"
            )
        
        # Create temp file with appropriate extension
        _, ext = os.path.splitext(file.filename)
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            shutil.copyfileobj(file.file, tmp)
            temp_path = tmp.name
        
        # Get course_owner from current user (professors own content they ingest)
        course_owner = current_user.get("user_id", "system")
        
        # Process file with hierarchical extraction
        result = ingestion_service.ingest(
            file_path=temp_path,
            course_owner=course_owner
        )
        
        # Return enriched response with user info
        return {
            **result,
            "user_id": current_user.get("user_id"),
            "uploaded_by": current_user.get("username"),
            "filename": file.filename
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Cleanup temp file
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception as e:
                logger.warning(f"Failed to cleanup temp file: {str(e)}")


# 🔹 Query system (CRAG) - protected
@app.post("/query", response_model=QueryResponse, tags=["Query"])
def query_system(
    query_request: QueryRequest,
    current_user: Dict = Depends(get_current_user)
):
    """
    Query the CRAG system for answers.
    Requires authentication.
    """
    try:
        if not query_request.query or not query_request.query.strip():
            raise HTTPException(status_code=400, detail="Query cannot be empty")

        if len(query_request.query) > 500:
            raise HTTPException(status_code=400, detail="Query too long")

        result = crag_service.retrieve(query_request.query)
        
        return QueryResponse(
            query=query_request.query,
            answer=result.get("answer", ""),
            confidence=result.get("confidence", 0.0),
            sources=result.get("sources", []),
            graph_results=result.get("graph_results"),
            rag_results=result.get("rag_results"),
            reasoning=result.get("reasoning")
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 🔹 Multi-agent chat endpoint (MAIN INTERFACE) - protected
@app.post("/chat", response_model=ChatResponse, tags=["Chat"])
async def chat(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    current_user: Dict = Depends(get_current_user)
):
    """
    Multi-agent chat endpoint with full LangGraph orchestration.
    
    This is the PRIMARY INTERFACE for student interactions.
    Replaces /query endpoint with full AI agent coordination:
    
    Route by Intent:
    1. academic_query → TAAgent (CRAG) → Gamification → response
    2. submission_defence → EvaluatorAgent → Integrity → CognitiveEngine → Gamification → response + record
    3. curriculum_change → CurriculumAgent (background task) → response
    4. progress_check → ProgressAgent → analytics response
    
    Features:
    - Multi-turn conversation with session tracking
    - Real-time achievement tracking
    - Background academic integrity checks
    - Automatic curriculum propagation
    - Knowledge state updates via BKT
    
    Args:
        request: ChatRequest {message, session_id, course_id}
        background_tasks: FastAPI background task queue
        current_user: JWT-authenticated user
    
    Returns:
        ChatResponse with orchestration results and metadata
    """
    try:
        student_id = current_user.get("user_id")
        
        if not student_id:
            raise HTTPException(status_code=401, detail="Student ID not found in token")
        
        if not request.message or not request.message.strip():
            raise HTTPException(status_code=400, detail="Message cannot be empty")
        
        if len(request.message) > 2000:
            raise HTTPException(status_code=400, detail="Message too long (max 2000 chars)")

        route_result = llm_router.route("ta_tutoring", request.message)
        
        # Initialize agent state
        state = AgentState(
            student_id=student_id,
            session_id=request.session_id,
            current_input=request.message,
            messages=[],
            active_agent="",
            agent_history=[],
            metadata={
                "course_id": request.course_id,
                "user_role": current_user.get("role"),
                "achievements": [],
                "background_tasks": [],
                "restore_checkpoint": True,
                "llm_reduced_mode": bool(route_result.get("reduced_mode", False)),
            }
        )
        
        # Add message to conversation history
        state.messages.append({
            "role": "student",
            "content": request.message
        })
        
        # Execute LangGraph multi-agent workflow
        logger.info(f"Chat: Executing orchestration for {student_id} in session {request.session_id}")
        
        result_state = get_omniprof_graph().invoke(state)
        
        # Extract response from state
        agent_response = ""
        if result_state.messages:
            # Find last assistant message
            for msg in reversed(result_state.messages):
                if msg.get("role") == "assistant":
                    agent_response = msg.get("content", "")
                    break
        
        # Default response if no agent response generated
        if not agent_response:
            agent_response = f"Processing completed by {result_state.active_agent}."
        
        # Queue background tasks if needed
        background_task_data = result_state.metadata.get("background_task")
        if background_task_data:
            if background_task_data.get("agent") == "curriculum_agent":
                args = background_task_data.get("args", {})
                background_tasks.add_task(
                    process_curriculum_change_background,
                    **args
                )
                logger.info("Background task queued: curriculum propagation")
            elif background_task_data.get("agent") == "summarisation_agent":
                background_tasks.add_task(process_old_interactions_background)
                logger.info("Background task queued: session summarization")

            background_job_queue.enqueue(
                job_type=background_task_data.get("agent", "background_task"),
                payload=background_task_data,
            )
        
        # Build response
        response = ChatResponse(
            response=agent_response,
            session_id=request.session_id,
            active_agent=result_state.active_agent,
            metadata={
                "intent": result_state.metadata.get("intent"),
                "crag_score": result_state.metadata.get("crag_score"),
                "achievements": result_state.metadata.get("achievements", []),
                "new_achievements_count": result_state.metadata.get("new_achievements_count", 0),
                "cognition_updates": result_state.metadata.get("cognition_updates", []),
                "background_task_queued": bool(background_task_data),
                "reduced_mode": bool(route_result.get("reduced_mode", False)),
                "reduced_mode_notification": route_result.get("reduced_mode_notification"),
                "llm_provider": route_result.get("provider"),
            },
            message_count=len(result_state.messages),
            error=result_state.error if result_state.error_count > 0 else None
        )
        
        logger.info(f"Chat: Orchestration complete - agent={result_state.active_agent}, "
                   f"errors={result_state.error_count}, achievements={response.metadata.get('new_achievements_count', 0)}")
        
        return response
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat orchestration error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Chat processing failed: {str(e)}"
        )


# 🔹 Professor HITL queue viewer (protected)
@app.get("/professor/hitl-queue", tags=["Professor"])
def get_professor_hitl_queue(
    current_user: Dict = Depends(get_professor_user)
):
    """Return HITL defence review queue entries visible to professor/admin."""
    try:
        role = current_user.get("role", "student")
        if role == "admin":
            rows = graph_manager.list_hitl_queue()
        else:
            rows = graph_manager.list_hitl_queue(current_user.get("course_ids", []))
        return {"status": "success", "count": len(rows), "items": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws/chat")
async def websocket_chat(
    websocket: WebSocket,
    token: str = Query(...),
    session_id: str = Query(...),
    course_id: Optional[str] = Query(None),
):
    """Student websocket chat with token-style streaming chunks."""
    await websocket.accept()
    try:
        user = get_user_from_token(token)
        if user.get("role") not in ["student", "professor", "admin"]:
            await websocket.send_json({"event": "error", "message": "Unauthorized role"})
            await websocket.close(code=1008)
            return

        while True:
            payload = await websocket.receive_json()
            message = str(payload.get("message", "")).strip()
            if not message:
                await websocket.send_json({"event": "error", "message": "Message cannot be empty"})
                continue

            route_result = llm_router.route("ta_tutoring", message)

            state = AgentState(
                student_id=user.get("user_id", ""),
                session_id=session_id,
                current_input=message,
                messages=[{"role": "student", "content": message}],
                metadata={
                    "course_id": course_id,
                    "user_role": user.get("role"),
                    "restore_checkpoint": True,
                    "llm_reduced_mode": bool(route_result.get("reduced_mode", False)),
                },
            )
            result_state = get_omniprof_graph().invoke(state)

            response_text = ""
            for msg in reversed(result_state.messages):
                if msg.get("role") == "assistant":
                    response_text = msg.get("content", "")
                    break

            active_topic_name = _active_topic_name_for_message(message, course_id)
            evaluation_mode = result_state.metadata.get("intent") == "submission_defence"

            await websocket.send_json(
                {
                    "event": "start",
                    "active_topic_node_name": active_topic_name,
                    "evaluation_mode": evaluation_mode,
                    "reduced_mode": bool(route_result.get("reduced_mode", False)),
                    "reduced_mode_notification": route_result.get("reduced_mode_notification"),
                }
            )

            for token_chunk in _iter_stream_chunks(response_text):
                await websocket.send_json(
                    {
                        "event": "token",
                        "token": token_chunk,
                        "active_topic_node_name": active_topic_name,
                    }
                )

            await websocket.send_json(
                {
                    "event": "complete",
                    "response": response_text,
                    "active_agent": result_state.active_agent,
                    "active_topic_node_name": active_topic_name,
                    "evaluation_mode": evaluation_mode,
                    "reduced_mode": bool(route_result.get("reduced_mode", False)),
                    "reduced_mode_notification": route_result.get("reduced_mode_notification"),
                }
            )

    except WebSocketDisconnect:
        logger.info("WebSocket chat disconnected")
    except Exception as e:
        await websocket.send_json({"event": "error", "message": str(e)})
        await websocket.close(code=1011)


@app.get("/student/progress", tags=["Student"])
def get_student_progress(
    course_id: Optional[str] = None,
    current_user: Dict = Depends(get_current_user),
):
    """Student progress dashboard payload with mastery confidence bands."""
    try:
        if current_user.get("role") not in ["student", "professor", "admin"]:
            raise HTTPException(status_code=403, detail="Student access required")
        compliance_service.log_access(
            actor_user_id=current_user.get("user_id", ""),
            actor_role=current_user.get("role", "student"),
            resource="student_progress",
            target_user_id=current_user.get("user_id", ""),
        )
        payload = _build_student_progress(current_user.get("user_id", ""), course_id)
        return {"status": "success", **payload}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/student/achievements", tags=["Student"])
def get_student_achievements(current_user: Dict = Depends(get_current_user)):
    """Retrieve student achievements/badges."""
    try:
        if current_user.get("role") not in ["student", "professor", "admin"]:
            raise HTTPException(status_code=403, detail="Student access required")
        
        achievements = graph_manager.get_student_achievements(current_user.get("user_id", ""))
        return {"status": "success", "achievements": achievements}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/student/submit-assignment", tags=["Student"])
async def submit_assignment(
    file: UploadFile = File(...),
    course_id: Optional[str] = None,
    current_user: Dict = Depends(get_current_user),
):
    """Create submission record and start evaluation mode for defence chat."""
    try:
        if current_user.get("role") not in ["student", "admin"]:
            raise HTTPException(status_code=403, detail="Student access required")

        submission_id = f"sub_{datetime.now().timestamp()}"
        summary = f"Submission file: {file.filename}" if file.filename else "Submission uploaded"
        graph_manager.create_defence_record(
            {
                "id": submission_id,
                "student_id": current_user.get("user_id"),
                "course_id": course_id,
                "submission_summary": summary,
                "status": "pending_defence",
                "transcript": [],
                "ai_recommended_grade": None,
                "ai_feedback": "",
                "integrity_score": None,
                "integrity_sample_size": 0,
            }
        )

        return {
            "status": "success",
            "submission_id": submission_id,
            "evaluation_mode": True,
            "indicator": "You are being evaluated",
            "pending_professor_approval": False,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/student/submissions/{submission_id}", tags=["Student"])
def get_submission_status(
    submission_id: str,
    current_user: Dict = Depends(get_current_user),
):
    """Expose student-facing submission status including pending approval state."""
    try:
        record = graph_manager.get_defence_record(submission_id)
        if not record:
            raise HTTPException(status_code=404, detail="Submission not found")

        if current_user.get("role") == "student" and record.get("student_id") != current_user.get("user_id"):
            raise HTTPException(status_code=403, detail="Forbidden")

        compliance_service.log_access(
            actor_user_id=current_user.get("user_id", ""),
            actor_role=current_user.get("role", "student"),
            resource="student_submission_status",
            target_user_id=record.get("student_id"),
        )

        status_text = str(record.get("status", "pending_defence"))
        return {
            "status": "success",
            "submission_id": submission_id,
            "workflow_status": status_text,
            "pending_professor_approval": status_text in ["pending_professor_review", "pending_defence"],
            "final_grade": record.get("final_grade"),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/professor/hitl-queue/{queue_id}/action", tags=["Professor"])
def act_on_hitl_queue(
    queue_id: str,
    payload: Dict[str, Any],
    current_user: Dict = Depends(get_professor_user),
):
    """Approve, modify+approve, or reject a queued AI defence record."""
    try:
        action = str(payload.get("action", "")).strip().lower()
        if action not in ["approve", "modify_approve", "reject_second_defence"]:
            raise HTTPException(status_code=400, detail="Invalid action")

        queue_items = graph_manager.list_hitl_queue()
        queue_row = None
        for item in queue_items:
            if str(item.get("queue_id")) == str(queue_id):
                queue_row = item
                break

        if not queue_row:
            raise HTTPException(status_code=404, detail="Queue item not found")

        defence_record_id = queue_row.get("defence_record_id")
        updates = {
            "review_status": action,
            "reviewed_by": current_user.get("user_id"),
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "review_note": payload.get("review_note", ""),
        }

        if action == "approve":
            updates["final_grade"] = queue_row.get("ai_recommended_grade")
            updates["status"] = "approved"
        elif action == "modify_approve":
            updates["final_grade"] = payload.get("modified_grade")
            updates["final_feedback"] = payload.get("modified_feedback")
            updates["status"] = "approved"
        else:
            updates["status"] = "rejected_second_defence_required"

        graph_manager.update_hitl_queue_entry(queue_id, updates)
        if defence_record_id:
            graph_manager.update_defence_record(defence_record_id, updates)

        return {
            "status": "success",
            "queue_id": queue_id,
            "defence_record_id": defence_record_id,
            "action": action,
            "grade_recorded": action in ["approve", "modify_approve"],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/professor/cohort-overview", tags=["Professor"])
def get_cohort_overview(
    course_id: str,
    inactivity_days: int = 7,
    current_user: Dict = Depends(get_professor_user),
):
    """Return aggregated cohort statistics from overlay data in one pass."""
    try:
        if current_user.get("role") != "admin" and course_id not in current_user.get("course_ids", []):
            raise HTTPException(status_code=403, detail="Forbidden for requested course")

        compliance_service.log_access(
            actor_user_id=current_user.get("user_id", ""),
            actor_role=current_user.get("role", "professor"),
            resource="cohort_overview",
            target_user_id=None,
        )

        now = datetime.now(timezone.utc)
        overlays: List[Dict[str, Any]] = []
        concepts_by_topic: Dict[str, List[float]] = {}
        slip_by_concept: Dict[str, List[float]] = {}
        student_last_seen: Dict[str, datetime] = {}

        for _, node in graph_manager.nodes_data.items():
            if node.get("level") != "CONCEPT" and "concept_id" not in node:
                continue
            if "concept_id" not in node:
                continue
            concept = graph_manager.nodes_data.get(node.get("concept_id"), {})
            if concept.get("course_owner") != course_id:
                continue

            overlays.append(node)

            topic_id = concept.get("topic_id") or "unknown"
            concepts_by_topic.setdefault(topic_id, []).append(float(node.get("mastery_probability", 0.0)))

            concept_name = concept.get("name", node.get("concept_id"))
            slip_by_concept.setdefault(concept_name, []).append(float(node.get("slip", 0.0)))

            user_id = node.get("user_id")
            ts = _parse_iso_ts(node.get("last_updated") or node.get("created_at"))
            if user_id and ts and (user_id not in student_last_seen or ts > student_last_seen[user_id]):
                student_last_seen[user_id] = ts

        topic_distribution = []
        for topic_id, mastery_rows in concepts_by_topic.items():
            topic = graph_manager.nodes_data.get(topic_id, {})
            avg_mastery = sum(mastery_rows) / len(mastery_rows) if mastery_rows else 0.0
            topic_distribution.append(
                {
                    "topic_id": topic_id,
                    "topic_name": topic.get("name", topic_id),
                    "student_count": len(mastery_rows),
                    "avg_mastery_probability": round(avg_mastery, 4),
                }
            )

        struggle = []
        for concept_name, slips in slip_by_concept.items():
            if not slips:
                continue
            struggle.append(
                {
                    "concept_name": concept_name,
                    "avg_slip": round(sum(slips) / len(slips), 4),
                    "sample_size": len(slips),
                }
            )
        struggle.sort(key=lambda x: x["avg_slip"], reverse=True)

        inactive_students = []
        for user_id, seen_at in student_last_seen.items():
            delta_days = (now - seen_at).days
            if delta_days >= inactivity_days:
                inactive_students.append({"student_id": user_id, "days_since_engagement": delta_days})

        return {
            "status": "success",
            "course_id": course_id,
            "topic_mastery_distribution": topic_distribution,
            "highest_struggle_concepts": struggle[:10],
            "inactive_students": sorted(inactive_students, key=lambda r: r["days_since_engagement"], reverse=True),
            "overlay_count": len(overlays),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/professor/graph-visualization", tags=["Professor"])
def get_professor_graph_visualization(
    course_id: Optional[str] = None,
    current_user: Dict = Depends(get_professor_user),
):
    """Read-only graph visualization payload for professors."""
    try:
        if (
            course_id
            and current_user.get("role") != "admin"
            and course_id not in current_user.get("course_ids", [])
        ):
            raise HTTPException(status_code=403, detail="Forbidden for requested course")

        nodes = []
        for node_id, node in graph_manager.nodes_data.items():
            level = node.get("level", "")
            if level not in ["MODULE", "TOPIC", "CONCEPT", "FACT"]:
                continue
            if course_id and node.get("course_owner") != course_id:
                continue
            nodes.append(
                {
                    "id": node_id,
                    "label": node.get("name", node_id),
                    "level": level,
                    "visibility": node.get("visibility", "global"),
                }
            )

        node_ids = {n["id"] for n in nodes}
        edges = []
        for edge in graph_manager._edge_records():
            if edge.get("source") not in node_ids or edge.get("target") not in node_ids:
                continue
            data = edge.get("data", {})
            edges.append(
                {
                    "source": edge.get("source"),
                    "target": edge.get("target"),
                    "relation": data.get("relation", "RELATED"),
                    "weight": float(data.get("weight", 1.0)),
                }
            )

        return {
            "status": "success",
            "read_only": True,
            "nodes": nodes,
            "edges": edges,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/professor/learning-path", tags=["Professor"])
def save_learning_path(
    payload: Dict[str, Any],
    current_user: Dict = Depends(get_professor_user),
):
    """Persist ordered or partially ordered learning path for curriculum weighting."""
    try:
        course_id = str(payload.get("course_id", "")).strip()
        if not course_id:
            raise HTTPException(status_code=400, detail="course_id is required")
        if current_user.get("role") != "admin" and course_id not in current_user.get("course_ids", []):
            raise HTTPException(status_code=403, detail="Forbidden for requested course")

        result = graph_manager.set_learning_path(
            course_id=course_id,
            ordered_concept_ids=payload.get("ordered_concept_ids", []),
            partial_order_edges=payload.get("partial_order_edges", []),
        )
        if result.get("status") != "success":
            raise HTTPException(status_code=400, detail=result.get("message", "Failed to save learning path"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/professor/learning-path", tags=["Professor"])
def get_learning_path(
    course_id: str,
    current_user: Dict = Depends(get_professor_user),
):
    """Read existing learning path configuration for professor UI."""
    try:
        if current_user.get("role") != "admin" and course_id not in current_user.get("course_ids", []):
            raise HTTPException(status_code=403, detail="Forbidden for requested course")
        return graph_manager.get_learning_path(course_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/professor/cohort", tags=["Professor"])
def get_professor_cohort(
    course_id: str,
    current_user: Dict = Depends(get_professor_user),
):
    """Return per-student concept mastery summary for cohort."""
    try:
        if current_user.get("role") != "admin" and course_id not in current_user.get("course_ids", []):
            raise HTTPException(status_code=403, detail="Forbidden for requested course")
        
        compliance_service.log_access(
            actor_user_id=current_user.get("user_id", ""),
            actor_role=current_user.get("role", "professor"),
            resource="professor_cohort",
            target_user_id=None,
        )
        
        # Collect student data
        students_data = {}
        for node_id, node in graph_manager.nodes_data.items():
            if node.get("node_type") != "StudentOverlay":
                continue
            student_id = node.get("student_id")
            concept_id = node.get("concept_id")
            if not student_id or not concept_id:
                continue
            
            concept = graph_manager.get_concept_by_id(concept_id)
            if not concept or concept.get("course_owner") != course_id:
                continue
            
            if student_id not in students_data:
                students_data[student_id] = {
                    "student_id": student_id,
                    "avg_mastery": 0.0,
                    "last_active": None,
                    "concepts": [],
                    "struggling": []
                }
            
            mastery = float(node.get("mastery_probability", 0.0))
            slip = float(node.get("slip", 0.1))
            students_data[student_id]["concepts"].append({
                "concept_id": concept_id,
                "concept_name": concept.get("name", concept_id),
                "mastery_probability": mastery,
                "slip": slip
            })
            
            # Track struggling concepts (highest slip)
            if slip > 0.4:
                students_data[student_id]["struggling"].append({
                    "concept_name": concept.get("name", concept_id),
                    "slip": slip
                })
            
            # Track last active
            last_updated = node.get("last_updated") or node.get("created_at")
            if last_updated:
                try:
                    ts = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
                    if students_data[student_id]["last_active"] is None or ts > students_data[student_id]["last_active"]:
                        students_data[student_id]["last_active"] = last_updated
                except:
                    pass
        
        # Calculate averages
        for student_id in students_data:
            concepts = students_data[student_id]["concepts"]
            if concepts:
                avg_mastery = sum(c["mastery_probability"] for c in concepts) / len(concepts)
                students_data[student_id]["avg_mastery"] = round(avg_mastery, 3)
            
            # Sort struggling by slip (descending)
            students_data[student_id]["struggling"].sort(key=lambda x: x["slip"], reverse=True)
            students_data[student_id]["struggling"] = students_data[student_id]["struggling"][:3]  # Top 3
        
        return {"status": "success", "students": list(students_data.values())}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/professor/students", tags=["Professor"])
def get_professor_students(
    current_user: Dict = Depends(get_professor_user),
):
    """List all students enrolled in courses the professor teaches."""
    try:
        # Collect unique student IDs from StudentOverlay nodes
        students_set = set()
        for node_id, node in graph_manager.nodes_data.items():
            if node.get("node_type") == "StudentOverlay":
                student_id = node.get("student_id")
                if student_id:
                    students_set.add(student_id)
        
        # Convert to list and sort
        students = sorted(list(students_set))
        
        compliance_service.log_access(
            actor_user_id=current_user.get("user_id", ""),
            actor_role=current_user.get("role", "professor"),
            resource="professor_students",
            target_user_id=None,
        )
        
        return {"status": "success", "students": students}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/professor/grade", tags=["Professor"])
def grade_defence_record(
    payload: Dict[str, Any],
    current_user: Dict = Depends(get_professor_user),
):
    """Approve or reject a defence record; optionally with modified grade/feedback."""
    try:
        record_id = payload.get("record_id")
        action = payload.get("action")  # "approve" or "reject"
        modified_grade = payload.get("modified_grade")
        modified_feedback = payload.get("modified_feedback")
        
        if not record_id or action not in ["approve", "reject"]:
            raise HTTPException(status_code=400, detail="Missing or invalid record_id/action")
        
        # Read defence records
        defence_records = graph_manager._read_json_list(graph_manager._defence_records_path())
        record = next((r for r in defence_records if r.get("record_id") == record_id), None)
        
        if not record:
            raise HTTPException(status_code=404, detail="Record not found")
        
        # Update based on action
        if action == "approve":
            record["professor_approved"] = True
            record["professor_grade"] = modified_grade if modified_grade is not None else record.get("ai_recommended_grade", 0.5)
            record["professor_feedback"] = modified_feedback or record.get("ai_feedback", "")
        elif action == "reject":
            record["professor_approved"] = False
            record["professor_grade"] = 0.0
            record["professor_feedback"] = modified_feedback or "Rejected by professor"
        
        record["professor_id"] = current_user.get("user_id", "")
        record["graded_at"] = datetime.now(timezone.utc).isoformat()
        
        # Save
        graph_manager._write_json_list(graph_manager._defence_records_path(), defence_records)
        
        compliance_service.log_access(
            actor_user_id=current_user.get("user_id", ""),
            actor_role=current_user.get("role", "professor"),
            resource="defence_grading",
            target_user_id=record.get("student_id", ""),
        )
        
        return {"status": "success", "record_id": record_id, "action": action}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/professor/annotate", tags=["Professor"])
def annotate_student(
    payload: Dict[str, Any],
    current_user: Dict = Depends(get_professor_user),
):
    """Store professor private annotations for a student."""
    try:
        student_id = payload.get("student_id")
        annotation_text = payload.get("annotation")
        
        if not student_id:
            raise HTTPException(status_code=400, detail="Missing student_id")
        
        # Just store in a simple JSON file
        annotations_path = os.path.join(graph_manager.data_dir, "professor_annotations.json")
        annotations = graph_manager._read_json_list(annotations_path)
        
        # Remove old annotation for this student
        annotations = [a for a in annotations if a.get("student_id") != student_id or a.get("professor_id") != current_user.get("user_id")]
        
        # Add new annotation
        annotations.append({
            "student_id": student_id,
            "professor_id": current_user.get("user_id", ""),
            "annotation": annotation_text or "",
            "created_at": datetime.now(timezone.utc).isoformat()
        })
        
        graph_manager._write_json_list(annotations_path, annotations)
        
        compliance_service.log_access(
            actor_user_id=current_user.get("user_id", ""),
            actor_role=current_user.get("role", "professor"),
            resource="student_annotation",
            target_user_id=student_id,
        )
        
        return {"status": "success", "student_id": student_id}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/concept/{concept_id}", tags=["Concepts"])
def update_concept(
    concept_id: str,
    payload: Dict[str, Any],
    current_user: Dict = Depends(get_professor_user),
):
    """Update concept metadata (name, description, visibility, priority)."""
    try:
        concept = graph_manager.get_concept_by_id(concept_id)
        if not concept:
            raise HTTPException(status_code=404, detail="Concept not found")
        
        # Only allow professors to update
        if current_user.get("role") not in ["professor", "admin"]:
            raise HTTPException(status_code=403, detail="Professor role required")
        
        # Update allowed fields
        if "name" in payload:
            concept["name"] = payload["name"]
        if "description" in payload:
            concept["description"] = payload["description"]
        if "visibility" in payload:
            concept["visibility"] = payload["visibility"]
        if "priority" in payload:
            concept["priority"] = payload["priority"]
        
        concept["last_updated"] = datetime.now(timezone.utc).isoformat()
        
        # Save back to graph
        graph_manager.nodes_data[concept_id] = concept
        graph_manager._save_graph()
        
        compliance_service.log_access(
            actor_user_id=current_user.get("user_id", ""),
            actor_role=current_user.get("role", "professor"),
            resource="concept_update",
            target_user_id=None,
        )
        
        return {"status": "success", "concept_id": concept_id, "concept": concept}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/llm-router/health", tags=["Phase6"])
def get_llm_router_health(
    current_user: Dict = Depends(get_professor_user),
):
    """Expose provider health, availability, and backoff windows."""
    return llm_router.health_status()


@app.post("/llm-router/route", tags=["Phase6"])
def route_with_llm_router(
    payload: Dict[str, Any],
    current_user: Dict = Depends(get_professor_user),
):
    """Probe router behavior for specific task/prompt combinations."""
    task = str(payload.get("task", "ta_tutoring"))
    prompt = str(payload.get("prompt", ""))
    return llm_router.route(task, prompt)


@app.get("/background-jobs/stats", tags=["Phase6"])
def get_background_job_stats(
    current_user: Dict = Depends(get_admin_user),
):
    """Observe queue depth and dead-letter depth."""
    return {"status": "success", **background_job_queue.stats()}


@app.post("/background-jobs/drain", tags=["Phase6"])
def drain_background_jobs(
    current_user: Dict = Depends(get_admin_user),
):
    """Process due background jobs and move repeated failures to dead-letter."""
    handlers = {
        "curriculum_agent": lambda _payload: None,
        "summarisation_agent": lambda _payload: None,
        "background_task": lambda _payload: None,
    }
    return background_job_queue.run_due_jobs(handlers=handlers)


@app.get("/compliance/status", tags=["Phase6"])
def get_compliance_status(
    current_user: Dict = Depends(get_admin_user),
):
    """FERPA/GDPR readiness checks for encryption and audit logs."""
    return compliance_service.status()