# 🔐 OmniProf v3.0 — Phase 1: JWT Authentication Implementation

## ✅ Phase 1 Complete

This document summarizes the full implementation of JWT authentication for OmniProf v3.0.

---

## 📋 What Was Implemented

### 1. **JWT Handler** (`backend/auth/jwt_handler.py`)
- ✅ `create_access_token()` - Generate JWT tokens with user info
  - Payload includes: `user_id`, `role`, `course_ids`, `exp`, `iat`
  - Configurable expiration (default: 30 minutes)
  - Role validation (student | professor | admin)

- ✅ `verify_token()` - Decode and validate JWT tokens
  - Handles expired tokens
  - Raises proper JWT error exceptions

- ✅ `get_user_from_token()` - Extract user information from token

- ✅ Role-checking utilities:
  - `is_admin(token)` - Check admin privileges
  - `is_professor(token)` - Check professor/admin status
  - `has_course_access(token, course_id)` - Check course enrollment

### 2. **Authentication Schemas** (`backend/models/schema.py`)
Comprehensive Pydantic models for validation:
- ✅ `UserRegister` - Registration with email validation
- ✅ `UserLogin` - Login credentials
- ✅ `TokenResponse` - Access token response
- ✅ `UserResponse` - User information
- ✅ `TokenPayload` - JWT payload structure
- ✅ `QueryRequest` & `QueryResponse` - Structured query/response
- ✅ `ConceptCreate` & `ConceptResponse` - Concept management
- ✅ Additional schemas for courses, documents, and errors

### 3. **FastAPI Application Updates** (`backend/app.py`)

#### Authentication Endpoints
- ✅ `POST /auth/register` - User registration
  - Validates username uniqueness
  - Hashes password with bcrypt
  - Returns JWT token on success
  
- ✅ `POST /auth/login` - User login
  - Validates credentials
  - Returns JWT token on success
  
- ✅ `GET /auth/me` - Get current user info (protected)
  - Requires valid JWT token
  - Returns user details

#### Protected Endpoints
- ✅ All existing endpoints now require JWT authentication:
  - `GET /` - Health check (public, unchanged)
  - `POST /concept` - Create concept (protected)
  - `GET /graph` - Get knowledge graph (protected)
  - `GET /graph-view` - Graph visualization (protected)
  - `POST /ingest` - Document ingestion (protected)
  - `POST /query` - CRAG queries (protected)

#### JWT Dependency Injection
- ✅ `get_current_user()` - Extract user from Bearer token
- ✅ `get_admin_user()` - Verify admin role
- ✅ `get_professor_user()` - Verify professor/admin role
- ✅ Proper error handling with HTTP 401/403 responses

#### Security Utilities
- ✅ `hash_password()` - bcrypt password hashing
- ✅ `verify_password()` - bcrypt password verification
- ✅ HTTP Bearer token extraction from headers

### 4. **Dependencies**
Updated `backend/requirements.txt`:
- ✅ `PyJWT` - JWT token creation/verification
- ✅ `bcrypt` - Password hashing
- ✅ `pydantic` - Data validation

---

## 🚀 How to Use

### 1. Setup

```bash
# Install dependencies
pip install -r backend/requirements.txt

# Create .env file from example
cp .env.example .env

# Edit .env with your values
# IMPORTANT: Change SECRET_KEY to a random, secure value!
```

### 2. Generate a Secure Secret Key

```bash
# Option 1: Python
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Option 2: OpenSSL
openssl rand -hex 32
```

Update `.env`:
```env
SECRET_KEY=your-generated-random-string-here
```

### 3. Start the Server

```bash
cd backend
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

---

## 🧪 Testing Phase 1

### Using Swagger UI (Recommended)
```
http://localhost:8000/docs
```

### 1. Register a New User
**Endpoint:** `POST /auth/register`

**Request Body:**
```json
{
  "username": "john_doe",
  "email": "john@example.com",
  "password": "SecurePassword123!",
  "full_name": "John Doe",
  "role": "student",
  "course_ids": []
}
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user_id": "user_1",
  "username": "john_doe",
  "role": "student"
}
```

### 2. Login with Credentials
**Endpoint:** `POST /auth/login`

**Request Body:**
```json
{
  "username": "john_doe",
  "password": "SecurePassword123!"
}
```

**Response:** Same as register

### 3. Get Current User Info
**Endpoint:** `GET /auth/me`

**Headers:**
```
Authorization: Bearer <your_access_token>
```

**Response:**
```json
{
  "user_id": "user_1",
  "username": "john_doe",
  "email": "john@example.com",
  "full_name": "John Doe",
  "role": "student",
  "course_ids": [],
  "created_at": "..."
}
```

### 4. Access Protected Endpoint
**Endpoint:** `GET /graph`

**Headers:**
```
Authorization: Bearer <your_access_token>
```

### 5. Test Without Token (Should Fail)
Try accessing any protected endpoint without the Authorization header.

**Response (401 Unauthorized):**
```json
{
  "detail": "Not authenticated"
}
```

---

## 🔌 Using cURL

### Register
```bash
curl -X POST "http://localhost:8000/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "jane_doe",
    "email": "jane@example.com",
    "password": "SecurePassword123!",
    "full_name": "Jane Doe",
    "role": "professor"
  }'
```

### Login
```bash
curl -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "jane_doe",
    "password": "SecurePassword123!"
  }'
```

### Protected Endpoint (with token)
```bash
TOKEN="your_access_token_here"

curl -X GET "http://localhost:8000/auth/me" \
  -H "Authorization: Bearer $TOKEN"
```

### Query System (with token)
```bash
TOKEN="your_access_token_here"

curl -X POST "http://localhost:8000/query" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is the knowledge graph?",
    "use_graph": true,
    "use_vector": true,
    "confidence_threshold": 0.5
  }'
```

---

## 🔑 Token Format

### JWT Payload Example
```json
{
  "user_id": "user_1",
  "role": "student",
  "course_ids": ["course_101", "course_102"],
  "exp": 1712345678,
  "iat": 1712344378
}
```

**Token Expiration:** 30 minutes (configurable via `ACCESS_TOKEN_EXPIRE_MINUTES`)

### How to Decode a Token (for debugging)
```python
import jwt
import os
from dotenv import load_dotenv

load_dotenv()
SECRET_KEY = os.getenv("SECRET_KEY")

token = "your_token_here"
decoded = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
print(decoded)
```

Or use [jwt.io](https://jwt.io) (copy-paste your token)

---

## ⚙️ Configuration

### Key Settings in `.env`

| Setting | Default | Purpose |
|---------|---------|---------|
| `SECRET_KEY` | N/A | Sign JWT tokens (MUST change!) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 30 | Token validity duration |
| `GROQ_API_KEY` | N/A | LLM API access |
| `NEO4J_URI` | bolt://localhost:7687 | Graph database |
| `NEO4J_PASSWORD` | password | Default Neo4j password |

---

## 🔒 Security Notes

### ✅ Best Practices Implemented
1. Passwords hashed with bcrypt (not stored in plaintext)
2. JWT tokens signed with SECRET_KEY
3. Token expiration (30 minutes default)
4. Role-based access control (RBAC)
5. HTTP Bearer authentication
6. Input validation with Pydantic

### ⚠️ Important For Production

Before deploying to production:

1. **Generate a strong SECRET_KEY**
   ```bash
   openssl rand -hex 32
   ```

2. **Use HTTPS/TLS only**
   - Never send tokens over HTTP

3. **Implement token refresh**
   - Include refresh tokens for long-lived sessions

4. **Store users in database**
   - Current: In-memory (demo only)
   - TODO: Migrate to PostgreSQL or Neo4j

5. **Add rate limiting**
   - Prevent brute force attacks on login

6. **Implement JWT revocation**
   - Blacklist tokens on logout

7. **Use secure cookies**
   - HttpOnly, Secure, SameSite flags

---

## 📊 Current User Storage

### In-Memory Storage (Current)
```python
users_db = {
    "username": {
        "user_id": "user_1",
        "email": "user@example.com",
        "password": "hashed_password",
        "role": "student",
        "course_ids": ["course_101"],
        ...
    }
}
```

**Limitations:**
- Data lost on server restart
- Single instance only
- Not suitable for production

### Next Steps (Phase 2 or 3)
- ✅ Migrate to PostgreSQL
- ✅ Or store in Neo4j with proper schema
- ✅ Implement refresh tokens
- ✅ Add logout/token blacklist

---

## 🐛 Common Issues & Fixes

### Issue: "Invalid token"
- Check token hasn't expired
- Verify SECRET_KEY matches
- Ensure proper Bearer format: `Authorization: Bearer <token>`

### Issue: "401 Not authenticated"
- Token missing from Authorization header
- Use format: `Authorization: Bearer eyJ...`

### Issue: "Invalid username or password"
- Check credentials are correct
- Username is case-sensitive
- Ensure user is registered

### Issue: "Token has expired"
- Generate a new token via login
- Increase `ACCESS_TOKEN_EXPIRE_MINUTES` if needed
- TODO: Implement refresh tokens (Phase 2)

---

## 📚 API Documentation

Full interactive API docs available at:
```
http://localhost:8000/docs
```

Alternative ReDoc format:
```
http://localhost:8000/redoc
```

---

## ✨ What's Next (Phase 2)

After Phase 1 is tested and working:

1. **Database Integration**
   - Migrate users to PostgreSQL/Neo4j
   - Persist user data across restarts

2. **Role-Based Endpoints**
   - Professor dashboard
   - Admin controls
   - Student views

3. **Course Management**
   - Add courses to graph
   - Manage enrollments
   - Course-specific documents

4. **Enhanced Security**
   - Refresh tokens
   - Token blacklist on logout
   - Rate limiting

5. **Additional Features**
   - User profiles
   - Preferences/settings
   - User activity logging

---

## 📞 Support

For issues or questions:
1. Check `.env` configuration
2. Review test examples above
3. Check FastAPI logs for error details
4. Refer to [PyJWT docs](https://pyjwt.readthedocs.io/)

---

**Status:** ✅ Phase 1 Complete  
**Version:** 3.0.0  
**Date:** April 2026
