#!/bin/bash
# OmniProf v3.0 — Phase 1 Quick Test Script
# Run this to test all authentication endpoints

set -e

BASE_URL="http://localhost:8000"
CONTENT_TYPE="Content-Type: application/json"

echo "🚀 OmniProf v3.0 — Authentication Testing"
echo "=========================================="
echo ""

# Test 1: Health Check (No Auth Required)
echo "✅ Test 1: Health Check (Public)"
curl -s -X GET "$BASE_URL/" | python -m json.tool
echo ""

# Test 2: Register New User
echo "✅ Test 2: Register New User"
REGISTER_RESPONSE=$(curl -s -X POST "$BASE_URL/auth/register" \
  -H "$CONTENT_TYPE" \
  -d '{
    "username": "testuser_'$(date +%s)'",
    "email": "test_'$(date +%s)'@example.com",
    "password": "TestPassword123!",
    "full_name": "Test User",
    "role": "student"
  }')

echo "$REGISTER_RESPONSE" | python -m json.tool

# Extract token from response
TOKEN=$(echo "$REGISTER_RESPONSE" | python -c "import sys, json; print(json.load(sys.stdin)['access_token'])")
USERNAME=$(echo "$REGISTER_RESPONSE" | python -c "import sys, json; print(json.load(sys.stdin)['username'])")

echo "✅ Token extracted: ${TOKEN:0:50}..."
echo ""

# Test 3: Get Current User Info
echo "✅ Test 3: Get Current User Info (Protected)"
curl -s -X GET "$BASE_URL/auth/me" \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool
echo ""

# Test 4: Login with Same Credentials
echo "✅ Test 4: Login with Registered Credentials"
LOGIN_RESPONSE=$(curl -s -X POST "$BASE_URL/auth/login" \
  -H "$CONTENT_TYPE" \
  -d "{
    \"username\": \"$USERNAME\",
    \"password\": \"TestPassword123!\"
  }")

echo "$LOGIN_RESPONSE" | python -m json.tool
echo ""

# Test 5: Test Protected Endpoint
echo "✅ Test 5: Access Protected Endpoint (/graph)"
curl -s -X GET "$BASE_URL/graph" \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool
echo ""

# Test 6: Test Without Token (Should Fail)
echo "✅ Test 6: Try Without Token (Should Fail with 403)"
curl -s -X GET "$BASE_URL/graph" | python -m json.tool
echo ""

echo "=========================================="
echo "✅ All tests completed!"
echo "=========================================="
echo ""
echo "Next Steps:"
echo "1. Try registering multiple users with different roles"
echo "2. Test token expiration (wait 30 minutes)"
echo "3. Try invalid password login"
echo "4. Check Swagger UI: http://localhost:8000/docs"
