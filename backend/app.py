from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthCredentials
import shutil
import os
import tempfile
import bcrypt
import jwt as pyjwt
import logging
from datetime import timedelta
from typing import Optional, Dict, Tuple

from backend.services.graph_service import GraphService
from backend.services.llm_service import LLMService
from backend.services.rag_service import RAGService
from backend.services.crag_service import CRAGService
from backend.services.ingestion_service import IngestionService
from backend.auth.jwt_handler import create_access_token, verify_token, get_user_from_token
from backend.auth.rbac import UserContext
from backend.models.schema import (
    UserRegister, UserLogin, TokenResponse, UserResponse,
    QueryRequest, QueryResponse, ConceptCreate, ConceptResponse,
    EnrollmentRequest, EnrollmentResponse
)


app = FastAPI(
    title="OmniProf v3.0",
    description="Hybrid CRAG System for Educational Knowledge Management",
    version="3.0.0"
)

# 🔐 Security setup
security = HTTPBearer()

# 🗄️ In-memory user store (TODO: migrate to Neo4j)
users_db: Dict[str, Dict] = {}


# ==================== Dependency Functions ====================
async def get_current_user(credentials: HTTPAuthCredentials = Depends(security)) -> Dict:
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


# ==================== AUTHENTICATION ENDPOINTS ====================

@app.post("/auth/register", response_model=TokenResponse, tags=["Authentication"])
def register(user_data: UserRegister):
    """
    Register a new user.
    
    Returns access token on successful registration.
    """
    try:
        # Check if user already exists
        if user_data.username in users_db:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already exists"
            )
        
        # Check email not already used
        for user in users_db.values():
            if user["email"] == user_data.email:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already registered"
                )
        
        # Create user
        user_id = f"user_{len(users_db) + 1}"
        users_db[user_data.username] = {
            "user_id": user_id,
            "username": user_data.username,
            "email": user_data.email,
            "password": hash_password(user_data.password),
            "full_name": user_data.full_name or user_data.username,
            "role": user_data.role,
            "course_ids": [],
            "created_at": os.popen("date").read().strip()
        }
        
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
        if credentials.username not in users_db:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password"
            )
        
        user = users_db[credentials.username]
        
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
        for username, user_data in users_db.items():
            if user_data["user_id"] == user_id:
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
    return {"message": "OmniProf v3.0 running 🚀", "version": "3.0.0"}


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
        
        # Enroll student in course
        result = graph_service.enroll_student(user_id, course_id)
        
        if result.get("status") == "error":
            raise HTTPException(
                status_code=500,
                detail=result.get("message", "Enrollment failed")
            )
        
        return EnrollmentResponse(
            status=result.get("status", "error"),
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