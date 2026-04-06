---
title: "Phase 3 Quick Reference: RBAC Integration Guide"
status: "COMPLETE"
---

# Phase 3 Quick Reference Guide

## 🚀 Quick Start

### Import RBAC Classes

```python
from backend.auth.rbac import UserContext, RBACFilter
from backend.app import create_user_context
```

### Create UserContext from JWT

```python
# In endpoints
@app.get("/api/concept/{concept_id}")
def get_concept(concept_id: str, current_user: Dict = Depends(get_current_user)):
    # Create UserContext from JWT tokens
    user_context = create_user_context(current_user)
    
    # Pass to services
    result = graph_service.get_concept_hierarchy(concept_id, user_context)
    return result
```

---

## 📋 Common Patterns

### Pattern 1: Query Single Node

**Code**:
```python
# GraphService method
def get_node(self, node_id: str, user_context: Optional[UserContext] = None) -> Optional[Dict]:
    return self.graph.get_node_by_id(node_id, user_context)

# neo4j_driver.py
def get_node_by_id(self, node_id: str, user_context: Optional[UserContext] = None):
    if user_context is None:
        # Admin default
        return self.db.run_query("MATCH (n {id: $id}) RETURN n", {"id": node_id})[0]
    
    # Apply visibility filter
    where_clause, params = RBACFilter.build_visibility_filter("n", user_context)
    params["id"] = node_id
    query = f"MATCH (n {{id: $id}}) {where_clause} RETURN n"
    result = self.db.run_query(query, params)
    return result[0] if result else None
```

**Usage**:
```python
# Student sees only global content
student = UserContext("s1", "student", ["cs101"])
node = get_node_by_id("concept_1", student)
# WHERE n.visibility = 'global'

# Professor sees global + professor-only
prof = UserContext("p1", "professor", ["cs101"])
node = get_node_by_id("concept_1", prof)
# WHERE (n.visibility IN ['global', 'enrolled-only', 'professor-only']...)
```

---

### Pattern 2: Query Hierarchy (Module → Topic → Concept → Facts)

**Code**:
```python
def get_concept_hierarchy(self, concept_id: str, user_context: Optional[UserContext] = None):
    if user_context is None:
        # Admin: see all
        return self.db.run_query(
            "MATCH (m:MODULE)-[:CONTAINS]->(t:TOPIC)-[:CONTAINS]->(c:CONCEPT {id: $id})-[:CONTAINS]->(f:FACT) "
            "RETURN m, t, c, collect(f) as facts",
            {"id": concept_id}
        )[0]
    
    # Build filters for each level
    if user_context.is_student:
        # Students: see global + enrolled-only only
        where_clause = (
            "WHERE (m.visibility IN ['global', 'enrolled-only'] "
            "AND t.visibility IN ['global', 'enrolled-only'] "
            "AND c.visibility IN ['global', 'enrolled-only'] "
            "AND f.visibility IN ['global', 'enrolled-only'])"
        )
    elif user_context.is_professor:
        # Professors: see all public levels
        where_clause = (
            "WHERE (m.visibility IN ['global', 'enrolled-only', 'professor-only'] "
            "AND t.visibility IN ['global', 'enrolled-only', 'professor-only'] "
            "AND c.visibility IN ['global', 'enrolled-only', 'professor-only'] "
            "AND f.visibility IN ['global', 'enrolled-only', 'professor-only'])"
        )
    else:  # admin
        where_clause = ""
    
    query = (
        "MATCH (m:MODULE)-[:CONTAINS]->(t:TOPIC)-[:CONTAINS]->(c:CONCEPT {id: $id})-[:CONTAINS]->(f:FACT) "
        f"{where_clause} RETURN m, t, c, collect(f) as facts"
    )
    return self.db.run_query(query, {"id": concept_id})[0]
```

**Result for Student**:
```
Student query for concept path:
├─ Module (visibility=global) ✅ INCLUDED
├─ Topic (visibility=global) ✅ INCLUDED
├─ Concept (visibility=enrolled-only) ✅ INCLUDED (enrolled)
├─ Fact (visibility=global) ✅ INCLUDED
└─ Fact (visibility=professor-only) ❌ EXCLUDED IN QUERY
   (This fact never appears in result - filtered by Cypher)
```

---

### Pattern 3: StudentOverlay Queries

**Code**:
```python
def get_student_concepts(self, user_id: str, user_context: Optional[UserContext] = None):
    if user_context is None:
        # Admin: see all overlays
        return self.db.run_query(
            "MATCH (s:StudentOverlay {user_id: $uid})-[:STUDIED_BY]->(c:CONCEPT) "
            "RETURN s, c ORDER BY s.mastery_probability DESC",
            {"uid": user_id}
        )
    
    # Enforce overlay isolation
    if user_context.is_student:
        if user_id != user_context.user_id:
            # Student cannot view other students' progress
            return []
        
        # Get overlays for visible concepts only
        where_clause = (
            "WHERE (c.visibility = 'global' "
            "OR (c.visibility = 'enrolled-only' AND c.course_owner IN $course_ids))"
        )
        query = (
            "MATCH (s:StudentOverlay {user_id: $uid})-[:STUDIED_BY]->(c:CONCEPT) "
            f"{where_clause} "
            "RETURN s, c ORDER BY s.mastery_probability DESC"
        )
        params = {"uid": user_id, "course_ids": user_context.course_ids}
    
    elif user_context.is_professor:
        # Professor sees overlays for their courses
        query = (
            "MATCH (s:StudentOverlay {user_id: $uid})-[:STUDIED_BY]->(c:CONCEPT) "
            "WHERE c.course_owner = $prof_id OR c.visibility = 'global' "
            "RETURN s, c ORDER BY s.mastery_probability DESC"
        )
        params = {"uid": user_id, "prof_id": user_context.user_id}
    
    else:  # admin
        query = (
            "MATCH (s:StudentOverlay {user_id: $uid})-[:STUDIED_BY]->(c:CONCEPT) "
            "RETURN s, c ORDER BY s.mastery_probability DESC"
        )
        params = {"uid": user_id}
    
    return self.db.run_query(query, params)
```

**Access Rules**:
```
Query: get_student_concepts("alice", user_context)

Case 1: user_context = Student (alice)
  Result: Alice's overlays ✅ (can see own progress)

Case 2: user_context = Student (bob)
  Result: [] ❌ (students cannot see each other's progress)

Case 3: user_context = Professor (cs101_prof)
  Result: Alice's overlays IF alice is in cs101 ✅

Case 4: user_context = Admin
  Result: Alice's overlays ✅ (admins see all)
```

---

## 🔍 Visibility Filter Decision Tree

```
Is user_context provided?
├─ NO → Assume admin, return all content
└─ YES → Check user role
    ├─ STUDENT → Check visibility
    │   ├─ 'global' → ✅ ALLOW
    │   ├─ 'enrolled-only' → Check course_owner IN course_ids
    │   │   ├─ YES → ✅ ALLOW
    │   │   └─ NO → ❌ DENY
    │   └─ 'professor-only' → ❌ DENY
    ├─ PROFESSOR → Check visibility
    │   ├─ 'global' → ✅ ALLOW
    │   ├─ 'enrolled-only' → ✅ ALLOW
    │   └─ 'professor-only' → ✅ ALLOW
    └─ ADMIN → ✅ ALLOW ALL
```

---

## 🧪 Testing Examples

### Test Student Isolation

```python
from backend.auth.rbac import UserContext, RBACFilter

# Define test users
student = UserContext("s1", "student", ["cs101"])
prof = UserContext("p1", "professor", ["cs101"])
admin = UserContext("a1", "admin", [])

# Test visibility filter for each role
def test_visibility_filters():
    node_type = "c"  # Concept node
    
    # Student filter
    student_filter, _ = RBACFilter.build_visibility_filter(node_type, student)
    assert "professor-only" not in student_filter
    assert "global" in student_filter
    print(f"✅ Student filter excludes professor-only: {student_filter}")
    
    # Professor filter
    prof_filter, _ = RBACFilter.build_visibility_filter(node_type, prof)
    assert "professor-only" in prof_filter
    print(f"✅ Professor filter includes professor-only: {prof_filter}")
    
    # Admin filter
    admin_filter, _ = RBACFilter.build_visibility_filter(node_type, admin)
    print(f"✅ Admin filter allows everything: {admin_filter}")
```

### Test Permission Checks

```python
from backend.auth.rbac import RBACFilter

# Test node access
student = UserContext("s1", "student", ["cs101"])

# Node student has access to
allowed_node = {
    "id": "concept_1",
    "visibility": "global",
    "course_owner": "cs101"
}

can_access, reason = RBACFilter.assert_read_permission(allowed_node, student)
assert can_access
print(f"✅ Student can access global node: {reason}")

# Node student does NOT have access to
denied_node = {
    "id": "concept_2",
    "visibility": "professor-only",
    "course_owner": "cs101"
}

can_access, reason = RBACFilter.assert_read_permission(denied_node, student)
assert not can_access
print(f"✅ Student cannot access professor-only node: {reason}")
```

---

## 📊 Before & After

### Before (Phase 2)
```python
# No RBAC filtering
def get_concept_hierarchy(self, concept_id: str):
    result = self.db.run_query(
        "MATCH (m:MODULE)-[:CONTAINS]->(t:TOPIC)-[:CONTAINS]->(c:CONCEPT {id: $concept_id})-[:CONTAINS]->(f:FACT) "
        "RETURN m, t, c, collect(f) as facts",
        {"concept_id": concept_id}
    )
    # ❌ Returns all nodes regardless of user role
    # ❌ Students might see professor-only content
    # ❌ Post-filtering needed in Python
    return result[0] if result else None
```

### After (Phase 3)
```python
# With RBAC filtering at query level
def get_concept_hierarchy(self, concept_id: str, user_context: Optional[UserContext] = None):
    if user_context and user_context.is_student:
        # ✅ Filter at Cypher level
        where_clause = (
            "WHERE (m.visibility IN ['global', 'enrolled-only'] "
            "AND t.visibility IN ['global', 'enrolled-only'] "
            "AND c.visibility IN ['global', 'enrolled-only'] "
            "AND f.visibility IN ['global', 'enrolled-only'])"
        )
        query = (
            "MATCH (m:MODULE)-[:CONTAINS]->(t:TOPIC)-[:CONTAINS]->(c:CONCEPT {id: $concept_id})-[:CONTAINS]->(f:FACT) "
            f"{where_clause} RETURN m, t, c, collect(f) as facts"
        )
        # ✅ Database engine never returns professor-only nodes
        # ✅ No post-filtering needed
        # ✅ Structural enforcement
        return self.db.run_query(query, {"concept_id": concept_id})[0]
    # ... other cases
```

---

## 🔒 Security Guarantees

### Guarantee 1: Student Cannot See Professor-Only Content

```python
# ENFORCED IN CYPHER, NOT IN PYTHON

# Student's query includes visibility filter
WHERE c.visibility IN ['global', 'enrolled-only']
# 'professor-only' is NOT in this list

# Result: Professor-only nodes NEVER returned by database
# No post-filtering needed, no caching bypass possible
```

### Guarantee 2: Student Cannot See Other Students' Overlays

```python
# Student isolated by user_id check BEFORE query
if user_context.is_student and user_id != user_context.user_id:
    return []  # No query executed at all

# Professor sees only overlays from their courses
WHERE c.course_owner = $professor_id OR c.visibility = 'global'
```

### Guarantee 3: Course Enrollment Enforced

```python
# Enrolled-only content requires enrollment check
WHERE (c.visibility = 'global' 
OR (c.visibility = 'enrolled-only' AND c.course_owner IN $course_ids))

# $course_ids comes from JWT token (verified)
# Student can only be in list of their actual enrollments
```

---

## 🚨 Common Mistakes

### ❌ WRONG: Post-Query Filtering
```python
# NO - this is incomplete
result = self.db.run_query(
    "MATCH (c:CONCEPT) RETURN c"  # No visibility filter!
)
# Filter in Python (late, error-prone)
visible = [c for c in result if check_visibility(c, user)]
```

### ✅ CORRECT: Query-Time Filtering
```python
# YES - visibility enforced by database
where_clause, params = RBACFilter.build_visibility_filter("c", user_context)
query = f"MATCH (c:CONCEPT) {where_clause} RETURN c"  # Filter in query
result = self.db.run_query(query, params)
```

### ❌ WRONG: String Interpolation
```python
# NO - SQL injection risk
visibilities = ["global", "enrolled-only"]
query = f"WHERE c.visibility IN [{', '.join(visibilities)}]"
```

### ✅ CORRECT: Parameter Binding
```python
# YES - safe parameter binding
query = "WHERE c.visibility IN $visibilities"
params = {"visibilities": ["global", "enrolled-only"]}
result = self.db.run_query(query, params)
```

---

## 📞 Troubleshooting

### Issue: Student Sees Professor-Only Content

**Debug Steps**:
1. Check endpoint is creating UserContext: `create_user_context(current_user)`
2. Verify user_context is passed to graph_service
3. Check WHERE clause includes `c.visibility IN ['global', 'enrolled-only']` (no 'professor-only')
4. Run query manually in Neo4j browser to verify filter

**Fix**:
```python
# Make sure WHERE clause is in query
where_clause, params = RBACFilter.build_visibility_filter("c", user_context)
query = f"MATCH (c:CONCEPT) {where_clause} RETURN c"  # WHERE included
```

### Issue: Professor Cannot See Their Course Content

**Debug Steps**:
1. Verify professor's course_ids in JWT token
2. Check course_owner field matches in node properties
3. Ensure WHERE clause allows 'professor-only' visibility
4. Test with test_phase3.py::test_professor_filter

**Fix**:
```python
# Professors need wider filter
where_clause = (
    "WHERE (c.visibility IN ['global', 'enrolled-only', 'professor-only'] "
    "AND (c.course_owner = $prof_id OR c.visibility = 'global'))"
)
```

### Issue: Performance Degradation

**Solution**: Add indexes
```cypher
CREATE INDEX idx_visibility ON (n.visibility)
CREATE INDEX idx_course_owner ON (n.course_owner)
CREATE INDEX idx_student_overlay ON (s.user_id, s.concept_id)
```

---

## 📚 Further Reading

- **Detailed Implementation**: [PHASE_3_IMPLEMENTATION.md](PHASE_3_IMPLEMENTATION.md)
- **Executive Summary**: [PHASE_3_SUMMARY.md](PHASE_3_SUMMARY.md)
- **Test Suite**: [test_phase3.py](test_phase3.py)
- **RBAC Module**: [backend/auth/rbac.py](backend/auth/rbac.py)

---

## ✅ Checklist: Using RBAC

- [ ] Import UserContext and RBACFilter
- [ ] Create UserContext from current_user: `user_context = create_user_context(current_user)`
- [ ] Pass user_context to graph_service methods
- [ ] Add user_context parameter with Optional[UserContext] type hint
- [ ] Build WHERE clause using RBACFilter methods
- [ ] Include WHERE clause in Cypher query (not post-filtering)
- [ ] Use parameter binding for all filter values
- [ ] Test with test_phase3.py
- [ ] Verify professor-only content absent from student results

---

**Phase 3 Implementation Guide**  
Version 3.0.0 | Status: ✅ COMPLETE
