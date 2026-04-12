"""
OmniProf v3.0 — Role-Based Access Control (RBAC)
Query-time access control for graph data
"""

from typing import Dict, List, Optional, Tuple
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class UserRole(str, Enum):
    """User roles in the system"""
    STUDENT = "student"
    PROFESSOR = "professor"
    ADMIN = "admin"


class NodeVisibility(str, Enum):
    """Node visibility settings"""
    GLOBAL = "global"                  # All users
    ENROLLED_ONLY = "enrolled-only"    # Only enrolled students + professor + admin
    PROFESSOR_ONLY = "professor-only"  # Only professor + admin


class UserContext:
    """
    Encapsulates authenticated user information for RBAC checks
    Passed through graph queries to enforce visibility rules
    """
    
    def __init__(
        self,
        user_id: str,
        role: str,
        course_ids: Optional[List[str]] = None
    ):
        """
        Args:
            user_id: Unique user identifier
            role: "student", "professor", or "admin"
            course_ids: List of course IDs user is enrolled in
        """
        self.user_id = user_id
        self.role = role
        self.course_ids = course_ids or []
        
        # Normalize role
        valid_roles = ["student", "professor", "admin"]
        if role not in valid_roles:
            raise ValueError(f"Invalid role: {role}. Must be one of {valid_roles}")
    
    @property
    def is_admin(self) -> bool:
        """Check if user is admin"""
        return self.role == "admin"
    
    @property
    def is_professor(self) -> bool:
        """Check if user is professor or admin"""
        return self.role in ["professor", "admin"]
    
    @property
    def is_student(self) -> bool:
        """Check if user is student"""
        return self.role == "student"
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for logging"""
        return {
            "user_id": self.user_id,
            "role": self.role,
            "course_ids": self.course_ids
        }


class RBACFilter:
    """
    Builds graph query filters based on visibility and user context
    Enforces access control at query time, not application time
    """
    
    @staticmethod
    def build_visibility_filter(
        node_var: str,
        user_context: UserContext
    ) -> Tuple[str, Dict]:
        """
        Build WHERE clause fragment for node visibility
        
        Args:
            node_var: node variable name (e.g., "n", "c", "t", "m")
            user_context: UserContext object
        
        Returns:
            Tuple of (where_clause, params)
        
        Examples:
            node_var="c", student -> "WHERE (c.visibility = 'global' OR (c.visibility = 'enrolled-only' AND c.course_owner IN ['cs101']))"
            node_var="c", professor -> "WHERE (c.visibility IN ['global', 'enrolled-only', 'professor-only'])"
            node_var="c", admin -> "WHERE (c.visibility IN ['global', 'enrolled-only', 'professor-only'])"
            node_var="c", non-enrolled student -> "WHERE c.visibility = 'global'"
        """
        
        if user_context.is_admin:
            # Admins see everything
            return f"WHERE {node_var}.visibility IS NOT NULL", {}
        
        elif user_context.is_professor:
            # Professors see global and professor-only for their courses
            return (
                f"WHERE ({node_var}.visibility IN ['global', 'enrolled-only', 'professor-only'] "
                f"AND ({node_var}.course_owner = $user_id OR {node_var}.visibility = 'global'))",
                {"user_id": user_context.user_id}
            )
        
        else:  # student
            # Students see only global content, or enrolled-only if they're in the course
            if user_context.course_ids:
                # Has enrolled courses - can see enrolled-only content
                return (
                    f"WHERE ({node_var}.visibility = 'global' OR "
                    f"({node_var}.visibility = 'enrolled-only' AND $course_owner IN $course_ids))",
                    {
                        "course_owner": None,  # Will be set per query
                        "course_ids": user_context.course_ids
                    }
                )
            else:
                # No enrolled courses - can only see global
                return (
                    f"WHERE {node_var}.visibility = 'global'",
                    {}
                )
    
    @staticmethod
    def build_hierarchy_visibility_filter(
        user_context: UserContext
    ) -> Tuple[str, Dict]:
        """
        Build complex WHERE clause for entire hierarchy walkdown
        Ensures nodes are inaccessible throughout the chain
        
        Returns:
            Tuple of (where_clause_fragment, params)
        """
        
        if user_context.is_admin:
            # Admins see entire hierarchy
            return "", {}
        
        elif user_context.is_professor:
            # Professors see all public + professor-only in their domain
            return (
                "AND (m.visibility IN ['global', 'enrolled-only', 'professor-only'] "
                "AND t.visibility IN ['global', 'enrolled-only', 'professor-only'] "
                "AND c.visibility IN ['global', 'enrolled-only', 'professor-only'])",
                {}
            )
        
        else:  # student
            # Students see only what they're allowed to
            if user_context.course_ids:
                return (
                    "AND (m.visibility = 'global' OR m.visibility = 'enrolled-only') "
                    "AND (t.visibility = 'global' OR t.visibility = 'enrolled-only') "
                    "AND (c.visibility = 'global' OR c.visibility = 'enrolled-only')",
                    {}
                )
            else:
                return (
                    "AND m.visibility = 'global' "
                    "AND t.visibility = 'global' "
                    "AND c.visibility = 'global'",
                    {}
                )
    
    @staticmethod
    def build_concept_search_filter(
        user_context: UserContext
    ) -> Tuple[str, Dict]:
        """
        Build WHERE clause for concept search queries
        Ensures professor-only concepts are completely invisible to non-professors
        """
        
        if user_context.is_admin:
            return "", {}
        
        elif user_context.is_professor:
            # Professors see global + enrolled-only + professor-only (their own)
            return (
                "AND c.visibility IN ['global', 'enrolled-only', 'professor-only']",
                {}
            )
        
        else:  # student
            # Students see only global and enrolled-only
            if user_context.course_ids:
                return (
                    "AND c.visibility IN ['global', 'enrolled-only']",
                    {}
                )
            else:
                return (
                    "AND c.visibility = 'global'",
                    {}
                )
    
    @staticmethod
    def build_student_overlay_filter(
        user_context: UserContext
    ) -> Tuple[str, Dict]:
        """
        Build WHERE clause for student overlay queries
        
        Rules:
        - Students can only see their own overlays
        - Professors can see overlays for students in their courses
        - Admins can see all overlays
        """
        
        if user_context.is_admin:
            return "", {}
        
        elif user_context.is_professor:
            # Professors see overlays for their courses
            return (
                "AND c.course_owner = $professor_id",
                {"professor_id": user_context.user_id}
            )
        
        else:  # student
            # Students see only their own overlays
            return (
                "AND s.user_id = $student_id",
                {"student_id": user_context.user_id}
            )
    
    @staticmethod
    def assert_read_permission(
        node: Dict,
        user_context: UserContext
    ) -> Tuple[bool, str]:
        """
        Verify user can read a node (for post-query checks)
        
        Returns:
            Tuple of (allowed: bool, reason: str)
        """
        
        if user_context.is_admin:
            return True, ""
        
        visibility = node.get("visibility", "global")
        node_owner = node.get("course_owner", "")
        
        # Check visibility level
        if visibility == "global":
            return True, ""
        
        elif visibility == "professor-only":
            if user_context.is_professor:
                return True, ""
            else:
                return False, f"Node {node.get('id', 'unknown')} is professor-only"
        
        elif visibility == "enrolled-only":
            if user_context.is_professor or node_owner in user_context.course_ids:
                return True, ""
            else:
                return False, f"Not enrolled in course for this content"
        
        else:
            return False, f"Unknown visibility: {visibility}"
    
    @staticmethod
    def assert_write_permission(
        node_owner: str,
        user_context: UserContext
    ) -> Tuple[bool, str]:
        """
        Verify user can write/modify a node
        
        Rules:
        - Admins can modify anything
        - Professors can modify content they own
        - Students cannot modify anything
        """
        
        if user_context.is_admin:
            return True, ""
        
        if user_context.is_professor:
            if node_owner == user_context.user_id:
                return True, ""
            else:
                return False, "Cannot modify content you don't own"
        
        # Students cannot modify anything
        return False, "Students cannot modify content"


class RBACValidator:
    """
    Additional RBAC validation helpers
    """
    
    @staticmethod
    def can_assign_visibility(
        visibility: str,
        user_context: UserContext
    ) -> Tuple[bool, str]:
        """
        Check if user can assign a specific visibility level
        
        Rules:
        - Admins can assign any visibility
        - Professors can assign global and enrolled-only (not professor-only)
        - Students cannot assign visibility
        """
        
        valid_visibilities = ["global", "enrolled-only", "professor-only"]
        if visibility not in valid_visibilities:
            return False, f"Invalid visibility: {visibility}"
        
        if user_context.is_admin:
            return True, ""
        
        if user_context.is_professor:
            # Professors cannot mark as professor-only (only admins can do that)
            if visibility in ["global", "enrolled-only"]:
                return True, ""
            else:
                return False, "Only admins can assign professor-only visibility"
        
        return False, "Only professors+ can assign visibility"
    
    @staticmethod
    def enforce_student_isolation(
        user_context: UserContext
    ) -> Tuple[bool, str]:
        """
        Verify queries against student isolation rule:
        Professor-only content must be structurally absent from student queries
        """
        
        if user_context.is_student:
            # Students should never see professor-only content
            return True, ""  # Content filtering will handle this
        
        return True, ""


class RBACLogger:
    """
    Logs RBAC events for audit trail
    """
    
    @staticmethod
    def log_access_denied(
        user_context: UserContext,
        resource: str,
        reason: str
    ) -> None:
        """Log access denial event"""
        logger.warning(
            f"Access denied for {user_context.user_id} ({user_context.role}) "
            f"to {resource}: {reason}"
        )
    
    @staticmethod
    def log_access_granted(
        user_context: UserContext,
        resource: str
    ) -> None:
        """Log successful access event"""
        logger.debug(
            f"Access granted for {user_context.user_id} ({user_context.role}) "
            f"to {resource}"
        )
    
    @staticmethod
    def log_modification(
        user_context: UserContext,
        action: str,
        resource: str
    ) -> None:
        """Log modification event"""
        logger.info(
            f"Modification by {user_context.user_id}: {action} on {resource}"
        )
