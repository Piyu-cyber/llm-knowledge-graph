"""
JWT Authentication Handler for OmniProf v3.0
Handles token creation, verification, and validation
"""

import jwt
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import os
from dotenv import load_dotenv

load_dotenv()

# Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))


def create_access_token(
    user_id: str,
    role: str,
    course_ids: Optional[list] = None,
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a JWT access token with user information.
    
    Args:
        user_id: Unique user identifier
        role: User role (student | professor | admin)
        course_ids: List of course IDs the user has access to
        expires_delta: Custom expiration time (defaults to ACCESS_TOKEN_EXPIRE_MINUTES)
    
    Returns:
        Encoded JWT token as string
    """
    if expires_delta is None:
        expires_delta = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    if course_ids is None:
        course_ids = []
    
    # Validate role
    valid_roles = ["student", "professor", "admin"]
    if role not in valid_roles:
        raise ValueError(f"Invalid role. Must be one of: {', '.join(valid_roles)}")
    
    # Create token payload
    to_encode = {
        "user_id": user_id,
        "role": role,
        "course_ids": course_ids,
        "exp": datetime.utcnow() + expires_delta,
        "iat": datetime.utcnow()
    }
    
    # Encode token
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> Dict[str, Any]:
    """
    Verify and decode a JWT token.
    
    Args:
        token: JWT token string
    
    Returns:
        Decoded token payload as dictionary
    
    Raises:
        jwt.InvalidTokenError: If token is invalid or expired
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise jwt.InvalidTokenError("Token has expired")
    except jwt.InvalidTokenError as e:
        raise jwt.InvalidTokenError(f"Invalid token: {str(e)}")


def get_user_from_token(token: str) -> Dict[str, Any]:
    """
    Extract user information from token.
    
    Args:
        token: JWT token string
    
    Returns:
        Dictionary containing user_id, role, and course_ids
    """
    payload = verify_token(token)
    return {
        "user_id": payload.get("user_id"),
        "role": payload.get("role"),
        "course_ids": payload.get("course_ids", [])
    }


def is_admin(token: str) -> bool:
    """Check if token belongs to an admin user."""
    payload = verify_token(token)
    return payload.get("role") == "admin"


def is_professor(token: str) -> bool:
    """Check if token belongs to a professor."""
    payload = verify_token(token)
    return payload.get("role") in ["professor", "admin"]


def has_course_access(token: str, course_id: str) -> bool:
    """Check if user has access to specified course."""
    payload = verify_token(token)
    return course_id in payload.get("course_ids", []) or payload.get("role") == "admin"
