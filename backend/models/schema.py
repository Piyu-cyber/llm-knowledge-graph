"""
Pydantic models/schemas for OmniProf v3.0
Includes authentication, user, and data validation schemas
"""

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from typing import Optional, List, Dict, Any
from enum import Enum


# ==================== User Roles ====================
class UserRole(str, Enum):
    """Valid user roles in the system"""
    STUDENT = "student"
    PROFESSOR = "professor"
    ADMIN = "admin"


# ==================== Authentication Schemas ====================
class UserRegister(BaseModel):
    """User registration request schema"""
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: Optional[str] = None
    role: UserRole = UserRole.STUDENT
    
    @field_validator("username")
    @classmethod
    def username_alphanumeric(cls, value: str) -> str:
        if not (value.isalnum() or "-" in value or "_" in value):
            raise ValueError("Username must be alphanumeric")
        return value


class UserLogin(BaseModel):
    """User login request schema"""
    username: str
    password: str


class TokenResponse(BaseModel):
    """Token response after successful authentication"""
    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: str
    role: UserRole


class UserResponse(BaseModel):
    """User information response"""
    user_id: str
    username: str
    email: str
    full_name: Optional[str] = None
    role: UserRole
    course_ids: List[str] = []
    created_at: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


class TokenPayload(BaseModel):
    """Token payload structure"""
    user_id: str
    role: UserRole
    course_ids: List[str] = []
    exp: int
    iat: int


# ==================== Course Schemas ====================
class CourseCreate(BaseModel):
    """Course creation schema"""
    course_code: str = Field(..., min_length=3)
    course_name: str = Field(..., min_length=5)
    description: Optional[str] = None
    professor_id: str
    semester: Optional[str] = None
    max_students: Optional[int] = None


class CourseResponse(BaseModel):
    """Course information response"""
    course_id: str
    course_code: str
    course_name: str
    description: Optional[str]
    professor_id: str
    semester: Optional[str]
    student_count: int = 0
    max_students: Optional[int]
    created_at: Optional[str]


# ==================== Document Schemas ====================
class DocumentIngest(BaseModel):
    """Document ingestion metadata"""
    filename: str
    file_type: str = "pdf"
    course_id: Optional[str] = None
    uploaded_by: str


class DocumentResponse(BaseModel):
    """Document information response"""
    document_id: str
    filename: str
    file_type: str
    course_id: Optional[str]
    uploaded_by: str
    indexed: bool
    chunk_count: int
    uploaded_at: Optional[str]


# ==================== Query Schemas ====================
class QueryRequest(BaseModel):
    """Query request schema"""
    query: str = Field(..., min_length=3, max_length=500)
    course_id: Optional[str] = None
    use_graph: bool = True
    use_vector: bool = True
    confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)


class QueryResponse(BaseModel):
    """Query response schema"""
    query: str
    answer: str
    confidence: float
    sources: List[str] = []
    graph_results: Optional[List[dict]] = []
    rag_results: Optional[List[dict]] = []
    reasoning: Optional[str] = None
    response_time_ms: Optional[float] = None


# ==================== Chat Endpoint Schemas ====================
class ChatRequest(BaseModel):
    """Chat request with message and session context"""
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: str = Field(..., description="Unique session identifier")
    course_id: Optional[str] = None


class ChatResponse(BaseModel):
    """Chat response with agent orchestration results"""
    response: str
    session_id: str
    active_agent: str
    metadata: Optional[Dict[str, Any]] = None
    message_count: int
    error: Optional[str] = None


# ==================== Concept Schemas ====================
class ConceptCreate(BaseModel):
    """Concept creation schema"""
    name: str = Field(..., min_length=2)
    description: Optional[str] = None
    category: Optional[str] = None
    course_id: Optional[str] = None


class ConceptResponse(BaseModel):
    """Concept information response"""
    concept_id: str
    name: str
    description: Optional[str]
    category: Optional[str]
    course_id: Optional[str]
    related: List[dict] = []


# ==================== Enrollment Schemas ====================
class EnrollmentRequest(BaseModel):
    """Student enrollment request schema"""
    course_id: str = Field(..., description="Course ID to enroll in")


class EnrollmentResponse(BaseModel):
    """Student enrollment response schema"""
    status: str
    student_id: str
    course_id: str
    overlays_created: int
    message: str


# ==================== Interaction Schemas ====================
class InteractionRequest(BaseModel):
    """Student interaction with a concept"""
    concept_id: str = Field(..., description="Concept ID")
    answered_correctly: bool = Field(..., description="Whether the response was correct")
    difficulty: Optional[float] = Field(
        None, 
        ge=-4.0, 
        le=4.0,
        description="Optional explicit difficulty parameter"
    )


class InteractionResponse(BaseModel):
    """Response after recording student interaction"""
    status: str
    user_id: str
    concept_id: str
    answered_correctly: bool
    event_type: str  # "correct", "slip", or "knowledge_gap"
    previous: dict  # {theta, slip}
    updated: dict   # {theta, slip, mastery_probability}
    difficulty: float


class StudyBlock(BaseModel):
    title: str
    description: str
    duration_minutes: int
    priority: str
    concept_ids: List[str] = []


class StudyPlanResponse(BaseModel):
    blocks: List[StudyBlock] = []
    generated_at: str
    error: Optional[str] = None


class SmartNote(BaseModel):
    session_id: str
    course_id: str
    created_at: str
    concepts_covered: List[str] = []
    key_definitions: Dict[str, str] = {}
    connections: List[str] = []
    follow_up_suggestions: List[str] = []


class HintRequest(BaseModel):
    question_text: str
    draft_answer: str
    concept_ids: List[str]
    course_id: str
    assignment_id: Optional[str] = None


class HintResponse(BaseModel):
    hint: str
    concept_referenced: Optional[str] = None
    confidence: float


class CohortAlert(BaseModel):
    concept_id: str
    concept_name: str
    struggling_pct: float
    struggling_count: int
    urgent: bool
    related_assignment: Optional[str] = None


class LessonSegment(BaseModel):
    title: str
    duration_minutes: int
    concepts: List[str] = []
    teaching_notes: str
    suggested_activities: List[str] = []


class QuizQuestion(BaseModel):
    concept_id: str
    type: str
    question: str
    options: Optional[List[str]] = None
    answer: str
    difficulty: str


class LessonPlanResponse(BaseModel):
    upload_id: str
    lesson_plan: List[LessonSegment] = []
    quiz_suggestions: List[QuizQuestion] = []
    conflicts: List[Dict[str, Any]] = []
    generated_at: str


class QuizGenerationRequest(BaseModel):
    concept_ids: List[str]
    difficulty: str
    count: int = Field(..., ge=1, le=20)
    course_id: str


# ==================== Error Schemas ====================
class ErrorResponse(BaseModel):
    """Error response schema"""
    detail: str
    status_code: int
    error_type: Optional[str] = None


# ==================== Status Schemas ====================
class HealthCheck(BaseModel):
    """Health check response"""
    status: str = "healthy"
    version: str = "3.0.0"
    services: dict = {}
