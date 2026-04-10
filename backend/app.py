from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, status, BackgroundTasks, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import asyncio
import shutil
import os
import tempfile
import bcrypt
import jwt as pyjwt
import logging
import re
import time
import json
import uuid
from datetime import timedelta, datetime, timezone
from typing import Optional, Dict, Tuple, Any, List

from .services.graph_service import GraphService
from .services.llm_service import LLMService
from .services.rag_service import RAGService
from .services.crag_service import CRAGService
from .services.ingestion_service import IngestionService
from .services.cognitive_engine import CognitiveEngine
from .services.llm_router import LLMRouter
from .services.background_job_queue import BackgroundJobQueue
from .services.compliance_service import ComplianceService
from .services.integrity_policy_service import IntegrityPolicyService
from .services.nondeterminism_service import NondeterminismService
from .services.memory_service import MemoryService, EpisodicRecord
from .db.graph_manager import GraphManager
from .db.user_store import UserStore
from .auth.jwt_handler import create_access_token, verify_token, get_user_from_token
from .auth.rbac import UserContext
from .models.schema import (
    UserRegister, UserLogin, TokenResponse, UserResponse,
    QueryRequest, QueryResponse, ChatRequest, ChatResponse,
    ConceptCreate, ConceptResponse,
    EnrollmentRequest, EnrollmentResponse,
    InteractionRequest, InteractionResponse
)
from .agents import OmniProfGraph, AgentState
from .agents.summarisation_agent import process_old_interactions_background
from .agents.curriculum_agent import process_curriculum_change_background


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

    weak_concepts = [
        row.get("concept_name") for row in mastery_bands
        if row.get("confidence_band") == "low" and row.get("concept_name")
    ]
    medium_concepts = [
        row.get("concept_name") for row in mastery_bands
        if row.get("confidence_band") == "medium" and row.get("concept_name")
    ]

    recommended_trajectory: List[str] = []
    for name in weak_concepts[:3]:
        recommended_trajectory.append(f"Revisit fundamentals: {name}")
    if not recommended_trajectory:
        for name in medium_concepts[:3]:
            recommended_trajectory.append(f"Strengthen confidence: {name}")
    if not recommended_trajectory and mastery_bands:
        recommended_trajectory.append("Continue guided practice to maintain mastery momentum")

    return {
        "student_id": student_id,
        "course_id": course_id,
        "modules_explored": len(visited_modules),
        "concepts_visited": concepts_visited,
        "mastery": mastery_bands,
        "recommended_trajectory": recommended_trajectory,
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


def _json_path(name: str) -> str:
    return os.path.join(graph_manager.data_dir, name)


def _read_json_rows(name: str) -> List[Dict[str, Any]]:
    path = _json_path(name)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_json_rows(name: str, rows: List[Dict[str, Any]]) -> None:
    path = _json_path(name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)


def ensure_demo_platform_data() -> None:
    """Seed classroom feed/coursework/submissions overlays when absent for demo UX."""
    try:
        users = user_store.list_users()
        students = [u for u in users if u.get("role") == "student"]
        professors = [u for u in users if u.get("role") == "professor"]

        # Seed overlays for each known student-course pair when missing.
        for student in students:
            sid = str(student.get("user_id", "")).strip()
            if not sid:
                continue
            for cid in (student.get("course_ids") or ["cs101"]):
                graph_manager.initialize_student_overlays(sid, str(cid))

        # Add deterministic overlay variation for visible progress if all overlays are flat.
        all_overlays = [
            (nid, node)
            for nid, node in graph_manager.nodes_data.items()
            if node.get("node_type") == "StudentOverlay"
        ]
        for idx, (overlay_id, node) in enumerate(all_overlays):
            if node.get("mastery_probability") not in [None, 0.5] or node.get("visited"):
                continue
            mastery = [0.32, 0.48, 0.63, 0.79][idx % 4]
            visited = idx % 2 == 0
            graph_manager.update_student_overlay(
                overlay_id,
                updates={
                    "mastery_probability": mastery,
                    "visited": visited,
                    "slip": max(0.05, round(0.55 - mastery, 3)),
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                },
            )

        # Seed classroom announcements.
        announcements = _read_json_rows("class_announcements.json")
        if not announcements:
            author = professors[0].get("user_id") if professors else "user_default_professor"
            announcements = [
                {
                    "id": "ann_welcome",
                    "course_id": "cs101",
                    "title": "Welcome to OmniProf Classroom",
                    "body": "Weekly resources and reminders will appear here.",
                    "author_user_id": author,
                    "audience": "all",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
                {
                    "id": "ann_defence",
                    "course_id": "cs101",
                    "title": "Defence Workflow Active",
                    "body": "Assignments move into defence mode and professor review for final approval.",
                    "author_user_id": author,
                    "audience": "all",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            ]
            _write_json_rows("class_announcements.json", announcements)

        # Seed coursework definitions.
        coursework = _read_json_rows("coursework_items.json")
        if not coursework:
            coursework = [
                {
                    "id": "cw_quiz_retrieval",
                    "course_id": "cs101",
                    "title": "Quiz: Retrieval Basics",
                    "description": "Short quiz on chunking, embeddings, and reranking concepts.",
                    "due_date": "2026-04-12",
                    "max_points": 20,
                    "rubric": "Conceptual Accuracy",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
                {
                    "id": "cw_crag_report",
                    "course_id": "cs101",
                    "title": "Assignment: CRAG Critique",
                    "description": "Analyze confidence calibration and ambiguity behavior.",
                    "due_date": "2026-04-15",
                    "max_points": 30,
                    "rubric": "Reasoning Depth",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            ]
            _write_json_rows("coursework_items.json", coursework)

        # Seed simple discussion entries.
        discussions = _read_json_rows("class_discussions.json")
        if not discussions:
            discussions = [
                {
                    "id": "disc_confidence_vs_grade",
                    "course_id": "cs101",
                    "author": "student_demo",
                    "topic": "Difference between confidence score and final grade",
                    "replies": 4,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
                {
                    "id": "disc_defence_prep",
                    "course_id": "cs101",
                    "author": "student_foundation",
                    "topic": "How should we prepare for defence questions?",
                    "replies": 2,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            ]
            _write_json_rows("class_discussions.json", discussions)

        # Seed one submission in defence flow to populate professor/student panels.
        defence_rows = graph_manager._read_json_list(graph_manager._defence_records_path())
        if not defence_rows and students:
            student = students[0]
            record_id = f"sub_seed_{int(time.time())}"
            graph_manager.create_defence_record(
                {
                    "id": record_id,
                    "student_id": student.get("user_id"),
                    "course_id": "cs101",
                    "assignment_id": "cw_crag_report",
                    "submission_summary": "Seeded classroom submission",
                    "status": "pending_professor_review",
                    "transcript": [
                        {"role": "assistant", "content": "Explain your approach to CRAG confidence handling."},
                        {"role": "student", "content": "I analyzed retrieval confidence and ambiguity triggers."},
                    ],
                    "ai_recommended_grade": 84,
                    "ai_feedback": "Good structure, needs deeper error analysis.",
                    "integrity_score": 0.11,
                    "sdi": 18,
                    "sdi_visible": True,
                }
            )
            graph_manager.enqueue_hitl_review(
                {
                    "defence_record_id": record_id,
                    "submission_id": record_id,
                    "student_id": student.get("user_id"),
                    "course_id": "cs101",
                    "ai_recommended_grade": 84,
                    "ai_feedback": "Good structure, needs deeper error analysis.",
                    "transcript": [
                        {"role": "assistant", "content": "Explain your approach to CRAG confidence handling."},
                        {"role": "student", "content": "I analyzed retrieval confidence and ambiguity triggers."},
                    ],
                    "integrity": {"sdi": 18},
                }
            )
    except Exception as exc:
        logger.warning("Failed to seed demo platform data: %s", str(exc))


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
graph_manager = GraphManager()
graph_service = GraphService(graph_manager)
cognitive_engine = CognitiveEngine()
llm_router = LLMRouter(llm_service=llm_service)
background_job_queue = BackgroundJobQueue(data_dir=graph_manager.data_dir)
compliance_service = ComplianceService(data_dir=graph_manager.data_dir)
integrity_policy_service = IntegrityPolicyService(data_dir=graph_manager.data_dir)
nondeterminism_service = NondeterminismService(data_dir=graph_manager.data_dir)
memory_service = MemoryService(rag_service=rag_service)

# Seed persisted classroom/platform demo data so frontend renders real backend content.
ensure_demo_platform_data()

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
_background_worker_task: Optional[asyncio.Task] = None


def _run_async_job(coro) -> None:
    """Run async job in current loop when possible, else create a temporary loop."""
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(coro)

        def _log_async_result(done: asyncio.Task) -> None:
            try:
                _ = done.result()
            except Exception as exc:
                logger.warning("Background async job failed: %s", str(exc))

        task.add_done_callback(_log_async_result)
    except RuntimeError:
        asyncio.run(coro)


def _handle_curriculum_job(payload: Dict[str, Any]) -> None:
    args = payload.get("args", payload) if isinstance(payload, dict) else {}
    _run_async_job(
        process_curriculum_change_background(
            course_id=str(args.get("course_id", "")),
            change_type=str(args.get("change_type", "")),
            node_id=str(args.get("node_id", "")),
            node_type=str(args.get("node_type", "")),
            metadata=args.get("metadata", {}) if isinstance(args.get("metadata", {}), dict) else {},
        )
    )


def _handle_summarisation_job(_payload: Dict[str, Any]) -> None:
    _run_async_job(process_old_interactions_background())


def _handle_episodic_memory_job(payload: Dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        return
    student_id = str(payload.get("student_id", "")).strip()
    session_id = str(payload.get("session_id", "")).strip()
    message_text = str(payload.get("message", "")).strip()
    if not student_id or not session_id or not message_text:
        return

    vectors = rag_service.get_embeddings([message_text])
    if not vectors:
        return

    record = EpisodicRecord(
        student_id=student_id,
        session_id=session_id,
        message=message_text,
        embedding=vectors[0],
        timestamp_unix=int(payload.get("timestamp_unix", int(time.time()))),
        concept_node_ids=[str(c) for c in (payload.get("concept_node_ids", []) or []) if str(c).strip()],
        turn_number=int(payload.get("turn_number", 0)),
    )
    memory_service.write_episodic_record(record)


def _background_job_handlers() -> Dict[str, Any]:
    return {
        "curriculum_agent": _handle_curriculum_job,
        "summarisation_agent": _handle_summarisation_job,
        "episodic_memory_write": _handle_episodic_memory_job,
        "background_task": lambda _payload: None,
    }


async def _background_job_worker_loop() -> None:
    interval_s = float(os.getenv("BGJOB_WORKER_INTERVAL_SECONDS", "3"))
    while True:
        try:
            background_job_queue.run_due_jobs(handlers=_background_job_handlers(), max_jobs=50)
        except Exception as exc:
            logger.warning("Background worker drain failed: %s", str(exc))
        await asyncio.sleep(max(0.5, interval_s))


@app.on_event("startup")
async def start_background_workers() -> None:
    global _background_worker_task
    if _background_worker_task is None or _background_worker_task.done():
        _background_worker_task = asyncio.create_task(_background_job_worker_loop())


@app.on_event("shutdown")
async def stop_background_workers() -> None:
    global _background_worker_task
    if _background_worker_task is not None:
        _background_worker_task.cancel()
        try:
            await _background_worker_task
        except asyncio.CancelledError:
            pass
        _background_worker_task = None


def get_omniprof_graph() -> OmniProfGraph:
    """Initialize the heavy multi-agent graph only when chat is first used."""
    global omniprof_graph
    if omniprof_graph is None:
        logger.info("Initializing OmniProf graph on first chat request")
        policy = integrity_policy_service.get_policy()
        omniprof_graph = OmniProfGraph(min_token_threshold=policy.get("min_token_threshold", 500))
    return omniprof_graph


def _router_runtime_snapshot() -> Dict[str, Any]:
    """Cheap provider snapshot without triggering an LLM generation call."""
    status = llm_router.health_status()
    providers = status.get("providers", {})
    chosen_provider = None
    for provider_name in status.get("cloud_order", []):
        provider_state = providers.get(provider_name, {})
        if provider_state.get("available"):
            chosen_provider = provider_name
            break

    reduced_mode = chosen_provider is None
    return {
        "provider": chosen_provider,
        "reduced_mode": reduced_mode,
        "reduced_mode_notification": "Reduced mode active: no LLM providers currently available." if reduced_mode else None,
    }


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


@app.post("/professor/module", tags=["Professor"])
def create_professor_module(
    payload: Dict[str, Any],
    current_user: Dict = Depends(get_professor_user),
):
    """Create a module for a specific course."""
    try:
        course_id = str(payload.get("course_id", "")).strip()
        name = str(payload.get("name", "")).strip()
        description = str(payload.get("description", "")).strip()
        visibility = str(payload.get("visibility", "global")).strip() or "global"

        if not course_id or not name:
            raise HTTPException(status_code=400, detail="course_id and name are required")

        if current_user.get("role") != "admin" and course_id not in current_user.get("course_ids", []):
            raise HTTPException(status_code=403, detail="Forbidden for requested course")

        result = graph_service.create_module(
            name=name,
            course_owner=course_id,
            description=description,
            visibility=visibility,
        )
        if result.get("status") != "success":
            raise HTTPException(status_code=400, detail=result.get("message", "Failed to create module"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/professor/topic", tags=["Professor"])
def create_professor_topic(
    payload: Dict[str, Any],
    current_user: Dict = Depends(get_professor_user),
):
    """Create a topic under an existing module."""
    try:
        module_id = str(payload.get("module_id", "")).strip()
        name = str(payload.get("name", "")).strip()
        description = str(payload.get("description", "")).strip()
        visibility = str(payload.get("visibility", "global")).strip() or "global"

        if not module_id or not name:
            raise HTTPException(status_code=400, detail="module_id and name are required")

        module_node = graph_manager.nodes_data.get(module_id)
        if not module_node or module_node.get("level") != "MODULE":
            raise HTTPException(status_code=404, detail="Module not found")

        course_id = str(module_node.get("course_owner", "")).strip()
        if current_user.get("role") != "admin" and course_id not in current_user.get("course_ids", []):
            raise HTTPException(status_code=403, detail="Forbidden for requested course")

        result = graph_service.create_topic(
            module_id=module_id,
            name=name,
            course_owner=course_id,
            description=description,
            visibility=visibility,
        )
        if result.get("status") != "success":
            raise HTTPException(status_code=400, detail=result.get("message", "Failed to create topic"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/professor/fact", tags=["Professor"])
def create_professor_fact(
    payload: Dict[str, Any],
    current_user: Dict = Depends(get_professor_user),
):
    """Create a fact under an existing concept."""
    try:
        concept_id = str(payload.get("concept_id", "")).strip()
        name = str(payload.get("name", "")).strip()
        description = str(payload.get("description", "")).strip()
        visibility = str(payload.get("visibility", "global")).strip() or "global"

        if not concept_id or not name:
            raise HTTPException(status_code=400, detail="concept_id and name are required")

        concept_node = graph_manager.nodes_data.get(concept_id)
        if not concept_node or concept_node.get("level") != "CONCEPT":
            raise HTTPException(status_code=404, detail="Concept not found")

        course_id = str(concept_node.get("course_owner", "")).strip()
        if current_user.get("role") != "admin" and course_id not in current_user.get("course_ids", []):
            raise HTTPException(status_code=403, detail="Forbidden for requested course")

        result = graph_service.create_fact(
            concept_id=concept_id,
            name=name,
            course_owner=course_id,
            description=description,
            visibility=visibility,
        )
        if result.get("status") != "success":
            raise HTTPException(status_code=400, detail=result.get("message", "Failed to create fact"))
        return result
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
    course_id: Optional[str] = None,
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
        from .services.ingestion_service import MultiFormatExtractor
        
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
        
        # Get course_owner from query param, fallback to user mapping
        course_owner = course_id or current_user.get("user_id", "system")
        
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

        user_context = create_user_context(current_user)
        result = crag_service.retrieve(
            query_request.query,
            user_context=user_context,
            student_id=current_user.get("user_id"),
        )
        
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

        route_result = _router_runtime_snapshot()
        
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
                "course_ids": current_user.get("course_ids", []),
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

        # Always persist episodic memory asynchronously so semantic/episodic systems stay warm.
        retrieved_concepts = result_state.graph_context.retrieved_concepts if result_state.graph_context else []
        concept_names = [str(c.get("name", "")).strip() for c in (retrieved_concepts or []) if isinstance(c, dict) and str(c.get("name", "")).strip()]
        background_job_queue.enqueue(
            job_type="episodic_memory_write",
            payload={
                "student_id": student_id,
                "session_id": request.session_id,
                "message": f"Q: {request.message}\nA: {agent_response}",
                "concept_node_ids": concept_names,
                "turn_number": len(result_state.messages),
                "timestamp_unix": int(time.time()),
            },
        )

        # Periodically schedule summarisation/semantic-memory extraction in background.
        if len(result_state.messages) >= 6 and len(result_state.messages) % 3 == 0:
            background_job_queue.enqueue(
                job_type="summarisation_agent",
                payload={
                    "session_id": request.session_id,
                    "student_id": student_id,
                },
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
        course_ids = current_user.get("course_ids", [])
        if role == "admin":
            rows = graph_manager.list_hitl_queue()
        else:
            rows = graph_manager.list_hitl_queue(course_ids)

        # Build a normalized HITL queue from persisted queue rows + live defence records
        # so professor review does not depend on demo-seeded hardcoded queue entries.
        queue_by_record_id: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            record_id = str(row.get("defence_record_id") or row.get("submission_id") or "").strip()
            if record_id:
                queue_by_record_id[record_id] = row

        defence_rows = graph_manager._read_json_list(graph_manager._defence_records_path())
        pending_statuses = {"pending_professor_review", "pending_defence", "flagged", "pending_integrity_history"}
        merged_rows: List[Dict[str, Any]] = []
        for record in defence_rows:
            record_status = str(record.get("status", "")).strip().lower()
            if record_status not in pending_statuses:
                continue

            course_id = record.get("course_id")
            if role != "admin" and course_ids and course_id not in set(course_ids):
                continue

            record_id = str(record.get("id", "")).strip()
            queue_row = queue_by_record_id.get(record_id, {})

            sdi_value = queue_row.get("sdi")
            if sdi_value is None and isinstance(queue_row.get("integrity"), dict):
                sdi_value = queue_row.get("integrity", {}).get("sdi")
            if sdi_value is None:
                sdi_value = record.get("sdi")

            integrity_score = queue_row.get("integrity_score")
            if integrity_score is None:
                integrity_score = record.get("integrity_score")

            sdi_visible = queue_row.get("sdi_visible")
            if sdi_visible is None:
                sdi_visible = record.get("sdi_visible", False)
            sdi_visible = bool(sdi_visible)

            ai_feedback = queue_row.get("ai_feedback")
            if ai_feedback is None:
                ai_feedback = record.get("ai_feedback") or record.get("final_feedback") or ""

            merged_rows.append(
                {
                    **queue_row,
                    "queue_id": str(queue_row.get("queue_id") or record_id),
                    "defence_record_id": record_id,
                    "submission_id": queue_row.get("submission_id") or record_id,
                    "student_id": queue_row.get("student_id") or record.get("student_id"),
                    "course_id": queue_row.get("course_id") or course_id,
                    "ai_recommended_grade": queue_row.get("ai_recommended_grade", record.get("ai_recommended_grade")),
                    "ai_feedback": ai_feedback,
                    "transcript": queue_row.get("transcript") or record.get("transcript") or [],
                    "sdi": sdi_value,
                    "integrity_score": integrity_score,
                    "sdi_visible": sdi_visible,
                    "integrity_visibility": queue_row.get("integrity_visibility")
                    or record.get("integrity_visibility")
                    or "standard",
                    "status": queue_row.get("status") or record.get("status"),
                    "created_at": queue_row.get("created_at") or record.get("created_at"),
                    "updated_at": queue_row.get("updated_at") or record.get("updated_at"),
                }
            )

        merged_rows.sort(
            key=lambda r: str(r.get("updated_at") or r.get("created_at") or ""),
            reverse=True,
        )

        normalized = []
        for row in merged_rows:
            sdi_visible = bool(row.get("sdi_visible", False))
            normalized.append(
                {
                    **row,
                    "integrity": {
                        "sdi": row.get("sdi"),
                        "integrity_score": row.get("integrity_score"),
                        "sdi_visible": sdi_visible,
                        "visibility_mode": row.get("integrity_visibility", "standard"),
                    },
                    "integrity_display_mode": "full" if sdi_visible else "suppressed_cold_start",
                    "integrity_display_note": (
                        "SDI hidden until writing-history threshold is met."
                        if not sdi_visible
                        else "SDI visible."
                    ),
                }
            )
        return {"status": "success", "count": len(normalized), "items": normalized}
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


@app.get("/student/classroom-feed", tags=["Student"])
def get_student_classroom_feed(
    course_id: str,
    current_user: Dict = Depends(get_current_user),
):
    """Return classroom stream/coursework/discussion data backed by persisted backend store."""
    try:
        if current_user.get("role") not in ["student", "professor", "admin"]:
            raise HTTPException(status_code=403, detail="Student access required")

        student_id = str(current_user.get("user_id", ""))
        announcements = [
            row for row in _read_json_rows("class_announcements.json")
            if row.get("course_id") in [course_id, "global"]
        ]
        announcements.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)

        discussions = [
            row for row in _read_json_rows("class_discussions.json")
            if row.get("course_id") in [course_id, "global"]
        ]
        discussions.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)

        coursework = [
            row for row in _read_json_rows("coursework_items.json")
            if row.get("course_id") == course_id
        ]
        coursework.sort(key=lambda r: str(r.get("due_date", "")))

        submission_rows = graph_manager._read_json_list(graph_manager._defence_records_path())
        student_submissions = [
            row for row in submission_rows
            if row.get("course_id") == course_id and row.get("student_id") == student_id
        ]

        status_by_assignment: Dict[str, Dict[str, Any]] = {}
        for row in student_submissions:
            aid = str(row.get("assignment_id", "")).strip()
            if not aid:
                continue
            candidate = {
                "submission_id": row.get("id"),
                "status": row.get("status", "pending_defence"),
                "final_grade": row.get("final_grade"),
                "updated_at": row.get("updated_at") or row.get("created_at"),
            }
            existing = status_by_assignment.get(aid)
            if not existing or str(candidate.get("updated_at") or "") >= str(existing.get("updated_at") or ""):
                status_by_assignment[aid] = candidate

        enriched_coursework = []
        for item in coursework:
            aid = str(item.get("id", "")).strip()
            submission = status_by_assignment.get(aid)
            enriched_coursework.append(
                {
                    **item,
                    "student_status": submission.get("status") if submission else "open",
                    "student_submission_id": submission.get("submission_id") if submission else None,
                    "student_grade": submission.get("final_grade") if submission else None,
                }
            )

        progress = _build_student_progress(student_id, course_id)
        module_map: Dict[str, Dict[str, Any]] = {}
        for row in progress.get("mastery", []):
            module_name = row.get("module_name") or "Uncategorized"
            mod = module_map.setdefault(
                module_name,
                {
                    "module_name": module_name,
                    "concept_count": 0,
                    "visited_count": 0,
                    "avg_mastery": 0.0,
                },
            )
            mod["concept_count"] += 1
            if row.get("visited"):
                mod["visited_count"] += 1
            mod["avg_mastery"] += float(row.get("mastery_probability", 0.0))

        modules = []
        for _, mod in module_map.items():
            count = max(1, int(mod["concept_count"]))
            modules.append(
                {
                    "module_name": mod["module_name"],
                    "concept_count": mod["concept_count"],
                    "visited_count": mod["visited_count"],
                    "avg_mastery": round(float(mod["avg_mastery"]) / count, 3),
                    "completed": mod["visited_count"] >= mod["concept_count"],
                }
            )

        # Fallback: expose module skeleton from graph even when overlays are not yet present.
        if not modules:
            for node_id, node in graph_manager.nodes_data.items():
                if node.get("level") != "MODULE":
                    continue
                if node.get("course_owner") != course_id:
                    continue
                modules.append(
                    {
                        "module_name": node.get("name", node_id),
                        "concept_count": 0,
                        "visited_count": 0,
                        "avg_mastery": 0.0,
                        "completed": False,
                    }
                )

        modules.sort(key=lambda r: r["module_name"])

        return {
            "status": "success",
            "course_id": course_id,
            "announcements": announcements,
            "coursework": enriched_coursework,
            "discussions": discussions,
            "modules": modules,
            "submissions": student_submissions,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/student/submit-assignment", tags=["Student"])
async def submit_assignment(
    file: UploadFile = File(...),
    course_id: Optional[str] = None,
    assignment_id: Optional[str] = None,
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
                "assignment_id": assignment_id,
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
        sdi_visible = bool(record.get("sdi_visible", False))
        is_student = current_user.get("role") == "student"
        return {
            "status": "success",
            "submission_id": submission_id,
            "assignment_id": record.get("assignment_id"),
            "workflow_status": status_text,
            "pending_professor_approval": status_text in ["pending_professor_review", "pending_defence"],
            "final_grade": record.get("final_grade"),
            "transcript": record.get("transcript", []) or [],
            "final_feedback": record.get("final_feedback") or record.get("ai_feedback"),
            "integrity": {
                "integrity_score": None if (is_student and not sdi_visible) else record.get("integrity_score"),
                "sdi": None if (is_student and not sdi_visible) else record.get("sdi"),
                "sdi_visible": sdi_visible,
                "visibility_mode": record.get("integrity_visibility", "standard"),
                "cold_start_suppressed": not sdi_visible,
                "display_note": (
                    "Integrity signals are hidden until enough writing history is collected."
                    if (is_student and not sdi_visible)
                    else None
                ),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/student/submissions", tags=["Student"])
def list_student_submissions(
    course_id: Optional[str] = None,
    current_user: Dict = Depends(get_current_user),
):
    """List student submissions for classroom coursework cards/history."""
    try:
        if current_user.get("role") not in ["student", "admin", "professor"]:
            raise HTTPException(status_code=403, detail="Student access required")

        student_id = current_user.get("user_id")
        rows = graph_manager._read_json_list(graph_manager._defence_records_path())
        items = []
        for row in rows:
            if row.get("student_id") != student_id:
                continue
            if course_id and row.get("course_id") != course_id:
                continue
            items.append(
                {
                    "submission_id": row.get("id"),
                    "assignment_id": row.get("assignment_id"),
                    "course_id": row.get("course_id"),
                    "status": row.get("status"),
                    "final_grade": row.get("final_grade"),
                    "created_at": row.get("created_at"),
                    "updated_at": row.get("updated_at"),
                }
            )
        items.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
        return {"status": "success", "items": items}
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

        # Support synthetic queue IDs that map directly to defence records.
        if not queue_row:
            direct_record = graph_manager.get_defence_record(queue_id)
            if direct_record:
                queue_row = {
                    "queue_id": queue_id,
                    "defence_record_id": queue_id,
                    "submission_id": queue_id,
                    "student_id": direct_record.get("student_id"),
                    "course_id": direct_record.get("course_id"),
                    "ai_recommended_grade": direct_record.get("ai_recommended_grade"),
                    "ai_feedback": direct_record.get("ai_feedback"),
                    "status": direct_record.get("status"),
                }

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
            approved_grade = payload.get("ai_recommended_grade", queue_row.get("ai_recommended_grade"))
            approved_feedback = payload.get("ai_feedback", queue_row.get("ai_feedback"))
            updates["final_grade"] = approved_grade
            updates["final_feedback"] = approved_feedback
            updates["status"] = "approved"
        elif action == "modify_approve":
            updates["final_grade"] = payload.get("modified_grade", payload.get("ai_recommended_grade"))
            updates["final_feedback"] = payload.get("modified_feedback", payload.get("ai_feedback"))
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

        total_students = len(student_last_seen)
        avg_mastery_probability = 0.0
        if overlays:
            avg_mastery_probability = sum(float(o.get("mastery_probability", 0.0)) for o in overlays) / len(overlays)
        average_mastery_pct = round(avg_mastery_probability * 100.0, 1)

        # Frontend compatibility shape used by professor dashboard cards.
        struggling_concepts = [
            {"name": row.get("concept_name"), "slip": row.get("avg_slip")}
            for row in struggle[:10]
        ]
        inactive_ids = [row.get("student_id") for row in inactive_students if row.get("student_id")]

        return {
            "status": "success",
            "course_id": course_id,
            "total_students": total_students,
            "struggling_students": len(inactive_ids),
            "average_mastery": average_mastery_pct,
            "struggling_concepts": struggling_concepts,
            "inactive_students": inactive_ids,
            "inactive_students_detail": sorted(inactive_students, key=lambda r: r["days_since_engagement"], reverse=True),
            "topic_mastery_distribution": topic_distribution,
            "highest_struggle_concepts": struggle[:10],
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
                    "description": node.get("description", ""),
                    "visibility": node.get("visibility", "global"),
                    "priority": node.get("priority", "normal"),
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
            student_id = node.get("user_id")
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
                    "average_mastery": 0.0,
                    "mastery_pct": 0.0,
                    "low_confidence_count": 0,
                    "interactions": 0,
                    "at_risk_concepts": [],
                    "last_active": None,
                    "last_active_at": None,
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
            students_data[student_id]["interactions"] += 1
            if mastery < 0.4:
                students_data[student_id]["low_confidence_count"] += 1
            
            # Track struggling concepts (highest slip)
            if slip > 0.4:
                item = {
                    "concept_name": concept.get("name", concept_id),
                    "slip": slip
                }
                students_data[student_id]["struggling"].append(item)
                students_data[student_id]["at_risk_concepts"].append(item)
            
            # Track last active
            last_updated = node.get("last_updated") or node.get("created_at")
            if last_updated:
                try:
                    ts = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
                    if students_data[student_id]["last_active"] is None or ts > students_data[student_id]["last_active"]:
                        students_data[student_id]["last_active"] = last_updated
                        students_data[student_id]["last_active_at"] = last_updated
                except:
                    pass
        
        # Include enrolled students with no overlays yet so roster tables still work.
        professor_courses = set(current_user.get("course_ids", []))
        users_by_id = {
            str(u.get("user_id", "")): u
            for u in user_store.list_users()
            if str(u.get("user_id", "")).strip()
        }
        for uid, profile in users_by_id.items():
            if profile.get("role") != "student":
                continue
            if current_user.get("role") != "admin" and not (professor_courses & set(profile.get("course_ids", []))):
                continue
            if uid in students_data:
                continue
            students_data[uid] = {
                "student_id": uid,
                "name": profile.get("full_name") or profile.get("username") or uid,
                "email": profile.get("email"),
                "avg_mastery": 0.0,
                "average_mastery": 0.0,
                "mastery_pct": 0.0,
                "low_confidence_count": 0,
                "interactions": 0,
                "at_risk_concepts": [],
                "last_active": None,
                "last_active_at": None,
                "concepts": [],
                "struggling": [],
            }

        # Calculate averages
        for student_id in students_data:
            concepts = students_data[student_id]["concepts"]
            if concepts:
                avg_mastery = sum(c["mastery_probability"] for c in concepts) / len(concepts)
                mastery_pct = round(avg_mastery * 100.0, 1)
                students_data[student_id]["avg_mastery"] = mastery_pct
                students_data[student_id]["average_mastery"] = mastery_pct
                students_data[student_id]["mastery_pct"] = mastery_pct
            
            # Sort struggling by slip (descending)
            students_data[student_id]["struggling"].sort(key=lambda x: x["slip"], reverse=True)
            students_data[student_id]["struggling"] = students_data[student_id]["struggling"][:3]  # Top 3
            students_data[student_id]["at_risk_concepts"] = students_data[student_id]["struggling"]

            # Attach profile metadata when available.
            profile = users_by_id.get(student_id, {})
            if profile:
                students_data[student_id]["name"] = profile.get("full_name") or profile.get("username") or student_id
                students_data[student_id]["email"] = profile.get("email")
        
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
        for _, node in graph_manager.nodes_data.items():
            if node.get("node_type") == "StudentOverlay":
                student_id = node.get("user_id")
                if student_id:
                    students_set.add(student_id)

        users_by_id = {
            str(u.get("user_id", "")): u
            for u in user_store.list_users()
            if str(u.get("user_id", "")).strip()
        }
        # Fallback: include enrolled students from user store even if overlays are not present yet.
        if not students_set:
            professor_courses = set(current_user.get("course_ids", []))
            for user in user_store.list_users():
                if user.get("role") != "student":
                    continue
                user_courses = set(user.get("course_ids", []))
                if current_user.get("role") != "admin" and not (professor_courses & user_courses):
                    continue
                sid = str(user.get("user_id", "")).strip()
                if sid:
                    students_set.add(sid)

        students = []
        for sid in sorted(students_set):
            profile = users_by_id.get(str(sid), {})
            students.append(
                {
                    "id": sid,
                    "user_id": sid,
                    "username": profile.get("username"),
                    "name": profile.get("full_name") or profile.get("username") or sid,
                    "email": profile.get("email"),
                    "course_ids": profile.get("course_ids", []),
                }
            )
        
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


@app.get("/professor/classroom-announcements", tags=["Professor"])
def get_professor_announcements(
    course_id: str,
    current_user: Dict = Depends(get_professor_user),
):
    """List course announcements from persisted classroom feed."""
    try:
        if current_user.get("role") != "admin" and course_id not in current_user.get("course_ids", []):
            raise HTTPException(status_code=403, detail="Forbidden for requested course")
        rows = [r for r in _read_json_rows("class_announcements.json") if r.get("course_id") in [course_id, "global"]]
        rows.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
        return {"status": "success", "items": rows}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/professor/classroom-announcements", tags=["Professor"])
def create_professor_announcement(
    payload: Dict[str, Any],
    current_user: Dict = Depends(get_professor_user),
):
    """Create one announcement row for classroom feed."""
    try:
        course_id = str(payload.get("course_id", "")).strip()
        title = str(payload.get("title", "")).strip()
        body = str(payload.get("body", "")).strip()
        if not course_id or not title:
            raise HTTPException(status_code=400, detail="course_id and title are required")
        if current_user.get("role") != "admin" and course_id not in current_user.get("course_ids", []):
            raise HTTPException(status_code=403, detail="Forbidden for requested course")

        rows = _read_json_rows("class_announcements.json")
        item = {
            "id": f"ann_{uuid.uuid4().hex[:10]}",
            "course_id": course_id,
            "title": title,
            "body": body,
            "author_user_id": current_user.get("user_id"),
            "audience": str(payload.get("audience", "all")),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        rows.insert(0, item)
        _write_json_rows("class_announcements.json", rows)
        return {"status": "success", "item": item}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/professor/coursework", tags=["Professor"])
def get_professor_coursework(
    course_id: str,
    current_user: Dict = Depends(get_professor_user),
):
    """List coursework items with submission counts from defence records."""
    try:
        if current_user.get("role") != "admin" and course_id not in current_user.get("course_ids", []):
            raise HTTPException(status_code=403, detail="Forbidden for requested course")

        rows = [r for r in _read_json_rows("coursework_items.json") if r.get("course_id") == course_id]
        defence_rows = graph_manager._read_json_list(graph_manager._defence_records_path())
        counts: Dict[str, int] = {}
        for row in defence_rows:
            if row.get("course_id") != course_id:
                continue
            aid = str(row.get("assignment_id", "")).strip()
            if not aid:
                continue
            counts[aid] = counts.get(aid, 0) + 1
        for row in rows:
            row["submission_count"] = counts.get(str(row.get("id", "")), 0)
        rows.sort(key=lambda r: str(r.get("due_date", "")))
        return {"status": "success", "items": rows}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/professor/coursework", tags=["Professor"])
def create_professor_coursework(
    payload: Dict[str, Any],
    current_user: Dict = Depends(get_professor_user),
):
    """Create one coursework row for classroom feed."""
    try:
        course_id = str(payload.get("course_id", "")).strip()
        title = str(payload.get("title", "")).strip()
        due_date = str(payload.get("due_date", "")).strip()
        if not course_id or not title or not due_date:
            raise HTTPException(status_code=400, detail="course_id, title, and due_date are required")
        if current_user.get("role") != "admin" and course_id not in current_user.get("course_ids", []):
            raise HTTPException(status_code=403, detail="Forbidden for requested course")

        rows = _read_json_rows("coursework_items.json")
        item = {
            "id": f"cw_{uuid.uuid4().hex[:10]}",
            "course_id": course_id,
            "title": title,
            "description": str(payload.get("description", "")).strip(),
            "due_date": due_date,
            "max_points": int(payload.get("max_points", 20) or 20),
            "rubric": str(payload.get("rubric", "Conceptual Accuracy")),
            "created_by": current_user.get("user_id"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        rows.insert(0, item)
        _write_json_rows("coursework_items.json", rows)
        return {"status": "success", "item": item}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/professor/submissions", tags=["Professor"])
def get_professor_submissions(
    course_id: str,
    current_user: Dict = Depends(get_professor_user),
):
    """List course submissions for command-center assignment analytics."""
    try:
        if current_user.get("role") != "admin" and course_id not in current_user.get("course_ids", []):
            raise HTTPException(status_code=403, detail="Forbidden for requested course")
        rows = graph_manager._read_json_list(graph_manager._defence_records_path())
        items = []
        for row in rows:
            if row.get("course_id") != course_id:
                continue
            canonical_record_id = row.get("id") or row.get("record_id") or row.get("submission_id")
            items.append(
                {
                    "submission_id": canonical_record_id,
                    "record_id": canonical_record_id,
                    "student_id": row.get("student_id"),
                    "assignment_id": row.get("assignment_id"),
                    "status": row.get("status"),
                    "final_grade": row.get("final_grade"),
                    "created_at": row.get("created_at"),
                    "updated_at": row.get("updated_at"),
                }
            )
        items.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
        return {"status": "success", "items": items}
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
        record_id = str(payload.get("record_id", "")).strip()
        action = payload.get("action")  # "approve" or "reject"
        modified_grade = payload.get("modified_grade")
        modified_feedback = payload.get("modified_feedback")
        
        if not record_id or action not in ["approve", "reject"]:
            raise HTTPException(status_code=400, detail="Missing or invalid record_id/action")
        
        # Read defence records
        defence_records = graph_manager._read_json_list(graph_manager._defence_records_path())
        record = None
        for row in defence_records:
            variants = [
                str(row.get("record_id", "")).strip(),
                str(row.get("id", "")).strip(),
                str(row.get("submission_id", "")).strip(),
            ]
            if record_id in variants:
                record = row
                break
        
        if not record:
            raise HTTPException(status_code=404, detail="Record not found")

        record_course_id = str(record.get("course_id", "")).strip()
        if (
            current_user.get("role") != "admin"
            and record_course_id
            and record_course_id not in current_user.get("course_ids", [])
        ):
            raise HTTPException(status_code=403, detail="Forbidden for requested course")

        canonical_record_id = (
            str(record.get("id", "")).strip()
            or str(record.get("record_id", "")).strip()
            or str(record.get("submission_id", "")).strip()
            or record_id
        )
        # Normalize id fields to avoid format drift across historical rows.
        record["id"] = canonical_record_id
        record["record_id"] = canonical_record_id
        record["submission_id"] = canonical_record_id
        
        # Update based on action
        if action == "approve":
            record["professor_approved"] = True
            record["professor_grade"] = modified_grade if modified_grade is not None else record.get("ai_recommended_grade", 0.5)
            record["professor_feedback"] = modified_feedback or record.get("ai_feedback", "")
            record["final_grade"] = record.get("professor_grade")
            record["final_feedback"] = record.get("professor_feedback")
            record["status"] = "approved"
        elif action == "reject":
            record["professor_approved"] = False
            record["professor_grade"] = 0.0
            record["professor_feedback"] = modified_feedback or "Rejected by professor"
            record["final_grade"] = 0.0
            record["final_feedback"] = record.get("professor_feedback")
            record["status"] = "rejected_second_defence_required"
        
        record["professor_id"] = current_user.get("user_id", "")
        record["graded_at"] = datetime.now(timezone.utc).isoformat()
        record["updated_at"] = record["graded_at"]
        
        # Save
        graph_manager._write_json_list(graph_manager._defence_records_path(), defence_records)
        
        compliance_service.log_access(
            actor_user_id=current_user.get("user_id", ""),
            actor_role=current_user.get("role", "professor"),
            resource="defence_grading",
            target_user_id=record.get("student_id", ""),
        )
        
        return {"status": "success", "record_id": canonical_record_id, "action": action}
    
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


@app.get("/professor/annotate", tags=["Professor"])
def get_professor_annotations(
    student_id: Optional[str] = None,
    current_user: Dict = Depends(get_professor_user),
):
    """Retrieve professor private annotations, optionally filtered by student."""
    try:
        annotations_path = os.path.join(graph_manager.data_dir, "professor_annotations.json")
        annotations = graph_manager._read_json_list(annotations_path)

        filtered = [
            row
            for row in annotations
            if row.get("professor_id") == current_user.get("user_id")
        ]
        if student_id:
            filtered = [row for row in filtered if str(row.get("student_id")) == str(student_id)]

        filtered.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
        return {"status": "success", "items": filtered}
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


@app.post("/professor/graph-edge", tags=["Professor"])
def add_professor_graph_edge(
    payload: Dict[str, Any],
    current_user: Dict = Depends(get_professor_user),
):
    """Create or upsert a directed concept relationship edge."""
    try:
        source_id = str(payload.get("source_id", "")).strip()
        target_id = str(payload.get("target_id", "")).strip()
        relation = str(payload.get("relation", "REQUIRES")).strip().upper()
        weight = float(payload.get("weight", 1.0) or 1.0)

        if not source_id or not target_id:
            raise HTTPException(status_code=400, detail="source_id and target_id are required")

        source = graph_manager.get_concept_by_id(source_id)
        target = graph_manager.get_concept_by_id(target_id)
        if not source or not target:
            raise HTTPException(status_code=404, detail="Source or target concept not found")

        source_course = str(source.get("course_owner", "")).strip()
        target_course = str(target.get("course_owner", "")).strip()
        if source_course != target_course:
            raise HTTPException(status_code=400, detail="Cross-course edges are not allowed")
        if (
            current_user.get("role") != "admin"
            and source_course
            and source_course not in current_user.get("course_ids", [])
        ):
            raise HTTPException(status_code=403, detail="Forbidden for requested course")

        result = graph_manager.add_concept_relationship(
            source_id=source_id,
            target_id=target_id,
            relation=relation,
            weight=weight,
        )
        if result.get("status") != "success":
            raise HTTPException(status_code=400, detail=result.get("message", "Failed to add graph edge"))

        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/professor/graph-edge/delete", tags=["Professor"])
def remove_professor_graph_edge(
    payload: Dict[str, Any],
    current_user: Dict = Depends(get_professor_user),
):
    """Delete directed concept relationship edge(s)."""
    try:
        source_id = str(payload.get("source_id", "")).strip()
        target_id = str(payload.get("target_id", "")).strip()
        relation = str(payload.get("relation", "")).strip().upper()

        if not source_id or not target_id:
            raise HTTPException(status_code=400, detail="source_id and target_id are required")

        source = graph_manager.get_concept_by_id(source_id)
        target = graph_manager.get_concept_by_id(target_id)
        if not source or not target:
            raise HTTPException(status_code=404, detail="Source or target concept not found")

        source_course = str(source.get("course_owner", "")).strip()
        target_course = str(target.get("course_owner", "")).strip()
        if source_course != target_course:
            raise HTTPException(status_code=400, detail="Cross-course edges are not allowed")
        if (
            current_user.get("role") != "admin"
            and source_course
            and source_course not in current_user.get("course_ids", [])
        ):
            raise HTTPException(status_code=403, detail="Forbidden for requested course")

        result = graph_manager.remove_concept_relationship(
            source_id=source_id,
            target_id=target_id,
            relation=relation or None,
        )
        if result.get("status") != "success":
            raise HTTPException(status_code=404, detail=result.get("message", "Failed to remove graph edge"))

        return result
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


@app.post("/diagnostics/nondeterminism/run", tags=["Phase6"])
def run_nondeterminism_diff(
    payload: Dict[str, Any],
    current_user: Dict = Depends(get_admin_user),
):
    """Execute repeated route calls and persist a diff artifact for reproducibility checks."""
    task = str(payload.get("task", "ta_tutoring"))
    prompt = str(payload.get("prompt", ""))
    runs = int(payload.get("runs", 5))
    return nondeterminism_service.run_router_diff(llm_router, task, prompt, runs=runs)


@app.get("/integrity/policy", tags=["Phase6"])
def get_integrity_policy(
    current_user: Dict = Depends(get_professor_user),
):
    """Read current runtime integrity policy values."""
    return {"status": "success", **integrity_policy_service.get_policy()}


@app.patch("/integrity/policy", tags=["Phase6"])
def update_integrity_policy(
    payload: Dict[str, Any],
    current_user: Dict = Depends(get_professor_user),
):
    """Update integrity policy and propagate threshold to active graph when present."""
    if "min_token_threshold" not in payload:
        raise HTTPException(status_code=400, detail="min_token_threshold is required")

    try:
        policy = integrity_policy_service.set_min_token_threshold(
            int(payload["min_token_threshold"]),
            updated_by=current_user.get("user_id", "unknown"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    os.environ["INTEGRITY_MIN_TOKENS"] = str(policy["min_token_threshold"])

    applied_to_active_graph = False
    if omniprof_graph is not None and hasattr(omniprof_graph, "integrity_agent"):
        omniprof_graph.integrity_agent.set_min_token_threshold(policy["min_token_threshold"])
        applied_to_active_graph = True

    return {
        "status": "success",
        **policy,
        "applied_to_active_graph": applied_to_active_graph,
    }


@app.get("/background-jobs/stats", tags=["Phase6"])
def get_background_job_stats(
    current_user: Dict = Depends(get_admin_user),
):
    """Observe queue depth and dead-letter depth."""
    return {"status": "success", **background_job_queue.stats()}


@app.post("/background-jobs/drain", tags=["Phase6"])
def drain_background_jobs(
    max_jobs: int = Query(100, ge=1, le=5000),
    current_user: Dict = Depends(get_admin_user),
):
    """Process due background jobs and move repeated failures to dead-letter."""
    return background_job_queue.run_due_jobs(handlers=_background_job_handlers(), max_jobs=max_jobs)


@app.post("/background-jobs/replay-dead-letter", tags=["Phase6"])
def replay_dead_letter_jobs(
    limit: int = Query(100, ge=1, le=5000),
    reset_attempts: bool = Query(True),
    current_user: Dict = Depends(get_admin_user),
):
    """Replay dead-letter jobs back to active queue."""
    return background_job_queue.replay_dead_letter(limit=limit, reset_attempts=reset_attempts)


@app.get("/background-jobs/history", tags=["Phase6"])
def get_background_job_history(
    limit: int = Query(100, ge=1, le=1000),
    current_user: Dict = Depends(get_admin_user),
):
    """Recent queue scheduling/retry/dead-letter/replay events."""
    return background_job_queue.recent_history(limit=limit)


@app.get("/compliance/status", tags=["Phase6"])
def get_compliance_status(
    current_user: Dict = Depends(get_admin_user),
):
    """FERPA/GDPR readiness checks for encryption and audit logs."""
    return compliance_service.status()


@app.get("/observability/metrics", tags=["Phase6"])
def get_observability_metrics(
    current_user: Dict = Depends(get_admin_user),
):
    """Baseline operational metrics across router and background jobs."""
    return {
        "status": "success",
        "router": {
            "provider_dashboards": llm_router.provider_dashboards(),
            "error_budget": llm_router.error_budget(),
        },
        "background_jobs": background_job_queue.stats(),
    }


@app.get("/observability/traces", tags=["Phase6"])
def get_observability_traces(
    limit: int = Query(100, ge=1, le=1000),
    current_user: Dict = Depends(get_admin_user),
):
    """Recent route and queue execution traces."""
    return {
        "status": "success",
        "router": llm_router.recent_traces(limit=limit),
        "background_jobs": background_job_queue.recent_history(limit=limit),
    }


@app.get("/observability/error-budget", tags=["Phase6"])
def get_observability_error_budget(
    current_user: Dict = Depends(get_admin_user),
):
    """Service-level error budget view based on router outcomes."""
    return {"status": "success", **llm_router.error_budget()}


@app.get("/observability/providers", tags=["Phase6"])
def get_observability_provider_dashboards(
    current_user: Dict = Depends(get_admin_user),
):
    """Provider-level latency/failure dashboard."""
    return {"status": "success", "providers": llm_router.provider_dashboards()}


@app.get("/health/embeddings", tags=["Phase6"])
def get_embeddings_health(
    current_user: Dict = Depends(get_professor_user),
):
    """Report active embedding backend and basic vector sanity metrics."""
    try:
        emb = graph_service.embedding_service
        probe_vec = emb.embed_text("embedding health probe")
        nonzero = sum(1 for v in probe_vec if abs(float(v)) > 1e-12)
        return {
            "status": "success",
            "embedding_backend": emb.model_name,
            "embedding_dim_configured": emb.embedding_dim,
            "probe_vector_length": len(probe_vec),
            "probe_nonzero_values": nonzero,
            "healthy": bool(emb.model_name != "none" and nonzero > 0),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))