"""
Phase 3 — RBAC at Query Time: Test Suite
Validates visibility enforcement at Neo4j query level
"""

import pytest
from typing import Dict
from backend.auth.rbac import (
    UserContext, RBACFilter, RBACValidator, RBACLogger,
    UserRole, NodeVisibility
)


class TestUserContext:
    """Test UserContext creation and role checking"""
    
    def test_student_context_creation(self):
        """Create student user context"""
        user = UserContext(
            user_id="student_1",
            role="student",
            course_ids=["cs101", "math201"]
        )
        assert user.is_student
        assert not user.is_professor
        assert not user.is_admin
        assert "cs101" in user.course_ids
    
    def test_professor_context_creation(self):
        """Create professor user context"""
        user = UserContext(
            user_id="prof_1",
            role="professor",
            course_ids=["cs101", "cs102"]
        )
        assert user.is_professor
        assert not user.is_student
        assert not user.is_admin
    
    def test_admin_context_creation(self):
        """Create admin user context"""
        user = UserContext(
            user_id="admin_1",
            role="admin",
            course_ids=[]
        )
        assert user.is_admin
        assert not user.is_student
        assert user.is_professor
    
    def test_invalid_role_rejected(self):
        """Invalid role should raise error"""
        with pytest.raises(ValueError):
            UserContext(
                user_id="user_1",
                role="superuser",  # Invalid
                course_ids=[]
            )
    
    def test_context_to_dict(self):
        """Convert context to dictionary"""
        user = UserContext(
            user_id="student_1",
            role="student",
            course_ids=["cs101"]
        )
        data = user.to_dict()
        assert data["user_id"] == "student_1"
        assert data["role"] == "student"
        assert data["course_ids"] == ["cs101"]


class TestRBACFilter:
    """Test visibility filter generation"""
    
    def test_student_global_only_filter(self):
        """Student with no courses sees only global content"""
        user = UserContext(
            user_id="student_1",
            role="student",
            course_ids=[]
        )
        where_clause, params = RBACFilter.build_visibility_filter("c", user)
        assert "global" in where_clause
        assert "professor-only" not in where_clause
    
    def test_student_with_courses_filter(self):
        """Student with courses sees global + enrolled-only"""
        user = UserContext(
            user_id="student_1",
            role="student",
            course_ids=["cs101", "math201"]
        )
        where_clause, params = RBACFilter.build_visibility_filter("c", user)
        assert "global" in where_clause
        assert "enrolled-only" in where_clause
        assert "professor-only" not in where_clause
        assert params["course_ids"] == ["cs101", "math201"]
    
    def test_professor_filter(self):
        """Professors see global, enrolled-only, and professor-only"""
        user = UserContext(
            user_id="prof_1",
            role="professor",
            course_ids=["cs101", "cs102"]
        )
        where_clause, params = RBACFilter.build_visibility_filter("c", user)
        assert "'global'" in where_clause or "global" in where_clause
        assert "'enrolled-only'" in where_clause or "enrolled-only" in where_clause
        assert "'professor-only'" in where_clause or "professor-only" in where_clause
    
    def test_admin_filter(self):
        """Admins see everything"""
        user = UserContext(
            user_id="admin_1",
            role="admin",
            course_ids=[]
        )
        where_clause, params = RBACFilter.build_visibility_filter("c", user)
        # Admin filter should allow any visibility
        assert "IS NOT NULL" in where_clause or "visibility" in where_clause
    
    def test_hierarchy_filter_student(self):
        """Hierarchy filter for student excludes professor-only"""
        user = UserContext(
            user_id="student_1",
            role="student",
            course_ids=["cs101"]
        )
        where_clause, params = RBACFilter.build_hierarchy_visibility_filter(user)
        assert "professor-only" not in where_clause
        assert "global" in where_clause or "'global'" in where_clause
    
    def test_hierarchy_filter_professor(self):
        """Hierarchy filter for professor includes professor-only"""
        user = UserContext(
            user_id="prof_1",
            role="professor",
            course_ids=[]
        )
        where_clause, params = RBACFilter.build_hierarchy_visibility_filter(user)
        assert "professor-only" in where_clause
    
    def test_concept_search_filter_student(self):
        """Concept search hides professor-only from students"""
        user = UserContext(
            user_id="student_1",
            role="student",
            course_ids=["cs101"]
        )
        where_clause, params = RBACFilter.build_concept_search_filter(user)
        assert "global" in where_clause or "'global'" in where_clause
        assert "enrolled-only" in where_clause or "'enrolled-only'" in where_clause
        assert "professor-only" not in where_clause
    
    def test_student_overlay_filter_student(self):
        """Students can only see their own overlays"""
        user = UserContext(
            user_id="student_1",
            role="student",
            course_ids=["cs101"]
        )
        where_clause, params = RBACFilter.build_student_overlay_filter(user)
        assert "$student_id" in where_clause or "student_id" in where_clause
        assert params.get("student_id") == "student_1"
    
    def test_student_overlay_filter_professor(self):
        """Professors see overlays for their courses"""
        user = UserContext(
            user_id="prof_1",
            role="professor",
            course_ids=["cs101"]
        )
        where_clause, params = RBACFilter.build_student_overlay_filter(user)
        assert "$professor_id" in where_clause or "professor_id" in where_clause
        assert params.get("professor_id") == "prof_1"


class TestRBACValidator:
    """Test permission validators"""
    
    def test_visibility_assignment_permission_student(self):
        """Students cannot assign visibility"""
        user = UserContext(
            user_id="student_1",
            role="student",
            course_ids=["cs101"]
        )
        allowed, reason = RBACValidator.can_assign_visibility("global", user)
        assert not allowed
    
    def test_visibility_assignment_permission_professor(self):
        """Professors can assign global and enrolled-only"""
        user = UserContext(
            user_id="prof_1",
            role="professor",
            course_ids=["cs101"]
        )
        
        # Can assign global
        allowed, reason = RBACValidator.can_assign_visibility("global", user)
        assert allowed
        
        # Can assign enrolled-only
        allowed, reason = RBACValidator.can_assign_visibility("enrolled-only", user)
        assert allowed
        
        # Cannot assign professor-only
        allowed, reason = RBACValidator.can_assign_visibility("professor-only", user)
        assert not allowed
    
    def test_visibility_assignment_permission_admin(self):
        """Admins can assign any visibility"""
        user = UserContext(
            user_id="admin_1",
            role="admin",
            course_ids=[]
        )
        
        for visibility in ["global", "enrolled-only", "professor-only"]:
            allowed, reason = RBACValidator.can_assign_visibility(visibility, user)
            assert allowed, f"Admin should be able to assign {visibility}"
    
    def test_invalid_visibility_rejected(self):
        """Invalid visibility level rejected"""
        user = UserContext(
            user_id="admin_1",
            role="admin",
            course_ids=[]
        )
        allowed, reason = RBACValidator.can_assign_visibility("secret", user)
        assert not allowed


class TestPermissionChecks:
    """Test read/write permission checks"""
    
    def test_student_can_read_global_content(self):
        """Students can read global content"""
        user = UserContext(
            user_id="student_1",
            role="student",
            course_ids=["cs101"]
        )
        node = {
            "id": "concept_1",
            "name": "Python Basics",
            "visibility": "global"
        }
        allowed, reason = RBACFilter.assert_read_permission(node, user)
        assert allowed
    
    def test_student_cannot_read_professor_only(self):
        """Students cannot read professor-only content"""
        user = UserContext(
            user_id="student_1",
            role="student",
            course_ids=["cs101"]
        )
        node = {
            "id": "concept_1",
            "name": "Advanced Python",
            "visibility": "professor-only"
        }
        allowed, reason = RBACFilter.assert_read_permission(node, user)
        assert not allowed
    
    def test_student_can_read_enrolled_content(self):
        """Student can read enrolled-only content for own courses"""
        user = UserContext(
            user_id="student_1",
            role="student",
            course_ids=["cs101"]
        )
        node = {
            "id": "concept_1",
            "name": "Data Structures",
            "visibility": "enrolled-only",
            "course_owner": "cs101"
        }
        allowed, reason = RBACFilter.assert_read_permission(node, user)
        assert allowed
    
    def test_student_cannot_read_other_course_content(self):
        """Student cannot read enrolled-only from other courses"""
        user = UserContext(
            user_id="student_1",
            role="student",
            course_ids=["cs101"]  # Not enrolled in cs102
        )
        node = {
            "id": "concept_1",
            "name": "Web Development",
            "visibility": "enrolled-only",
            "course_owner": "cs102"
        }
        allowed, reason = RBACFilter.assert_read_permission(node, user)
        assert not allowed
    
    def test_professor_can_read_all_public(self):
        """Professors can read all public and professor-only content"""
        user = UserContext(
            user_id="prof_1",
            role="professor",
            course_ids=[]
        )
        
        for visibility in ["global", "enrolled-only", "professor-only"]:
            node = {"id": "concept_1", "visibility": visibility}
            allowed, reason = RBACFilter.assert_read_permission(node, user)
            assert allowed, f"Professor should read {visibility}"
    
    def test_admin_can_read_all(self):
        """Admins can read any content"""
        user = UserContext(
            user_id="admin_1",
            role="admin",
            course_ids=[]
        )
        
        for visibility in ["global", "enrolled-only", "professor-only"]:
            node = {"id": "concept_1", "visibility": visibility}
            allowed, reason = RBACFilter.assert_read_permission(node, user)
            assert allowed
    
    def test_student_cannot_write(self):
        """Students cannot modify any content"""
        user = UserContext(
            user_id="student_1",
            role="student",
            course_ids=["cs101"]
        )
        allowed, reason = RBACFilter.assert_write_permission("prof_1", user)
        assert not allowed
    
    def test_professor_can_write_own_content(self):
        """Professors can modify their own content"""
        user = UserContext(
            user_id="prof_1",
            role="professor",
            course_ids=["cs101"]
        )
        allowed, reason = RBACFilter.assert_write_permission("prof_1", user)
        assert allowed
    
    def test_professor_cannot_write_others_content(self):
        """Professors cannot modify other professors' content"""
        user = UserContext(
            user_id="prof_1",
            role="professor",
            course_ids=["cs101"]
        )
        allowed, reason = RBACFilter.assert_write_permission("prof_2", user)
        assert not allowed
    
    def test_admin_can_write_all(self):
        """Admins can modify any content"""
        user = UserContext(
            user_id="admin_1",
            role="admin",
            course_ids=[]
        )
        allowed, reason = RBACFilter.assert_write_permission("anyone", user)
        assert allowed


class TestRBACIntegration:
    """Integration tests for RBAC scenarios"""
    
    def test_student_isolation_academic_content(self):
        """
        Critical Test: Professor-only academic content must be
        structurally absent from student queries
        """
        student = UserContext(
            user_id="student_1",
            role="student",
            course_ids=["cs101"]
        )
        
        # Student's filters should completely exclude professor-only content
        where_clause, _ = RBACFilter.build_hierarchy_visibility_filter(student)
        
        # The WHERE clause must NOT allow professor-only
        # This is structural enforcement, not post-query filtering
        assert "professor-only" not in where_clause
    
    def test_professor_domain_isolation(self):
        """Professors see only their course content"""
        prof = UserContext(
            user_id="prof_cs101",
            role="professor",
            course_ids=["cs101"]
        )
        
        # Professor's overlay filter should restrict to their courses
        where_clause, params = RBACFilter.build_student_overlay_filter(prof)
        assert "$professor_id" in where_clause or "professor_id" in where_clause
    
    def test_enrollment_based_access(self):
        """Access control based on course enrollment"""
        student = UserContext(
            user_id="student_1",
            role="student",
            course_ids=["cs101", "math201"]  # Enrolled in two courses
        )
        
        # Can access enrolled-only content from both courses
        where_clause, params = RBACFilter.build_visibility_filter("c", student)
        assert "cs101" in params.get("course_ids", [])
        assert "math201" in params.get("course_ids", [])
    
    def test_multi_course_professor(self):
        """Professor teaching multiple courses"""
        prof = UserContext(
            user_id="prof_1",
            role="professor",
            course_ids=["cs101", "cs102", "cs201"]
        )
        
        # Professor can see content from all taught courses
        # (assuming course_owner field matches these course IDs)
        where_clause, params = RBACFilter.build_visibility_filter("c", prof)
        assert "professor-only" in where_clause


# ==================== Scenario Tests ====================

class TestRealWorldScenarios:
    """Test realistic educational scenarios"""
    
    def test_course_enrollment_scenario(self):
        """
        Scenario: Student enrolls in CS101, can see CS101 content
        but not CS102 content
        """
        # Student enrolled only in CS101
        student = UserContext(
            user_id="alice",
            role="student",
            course_ids=["cs101"]
        )
        
        # Content from CS101
        cs101_concept = {
            "id": "concept_loops",
            "name": "For Loops",
            "visibility": "enrolled-only",
            "course_owner": "cs101"
        }
        
        # Content from CS102
        cs102_concept = {
            "id": "concept_decorators",
            "name": "Decorators",
            "visibility": "enrolled-only",
            "course_owner": "cs102"
        }
        
        # Student can read CS101 content
        can_read_cs101, _ = RBACFilter.assert_read_permission(cs101_concept, student)
        assert can_read_cs101
        
        # Student cannot read CS102 content
        can_read_cs102, _ = RBACFilter.assert_read_permission(cs102_concept, student)
        assert not can_read_cs102
    
    def test_advanced_topic_restriction(self):
        """
        Scenario: Advanced topics are professor-only
        Students should never see them in any query result
        """
        student = UserContext(
            user_id="bob",
            role="student",
            course_ids=["cs101"]
        )
        
        prof = UserContext(
            user_id="prof_smith",
            role="professor",
            course_ids=["cs101"]
        )
        
        advanced_topic = {
            "id": "concept_meta",
            "name": "Metaclasses",
            "visibility": "professor-only"
        }
        
        # Student cannot read
        student_can_read, _ = RBACFilter.assert_read_permission(advanced_topic, student)
        assert not student_can_read
        
        # Professor can read
        prof_can_read, _ = RBACFilter.assert_read_permission(advanced_topic, prof)
        assert prof_can_read
    
    def test_public_content_accessibility(self):
        """
        Scenario: Global content accessible to everyone
        """
        users = [
            UserContext("student_1", "student", ["cs101"]),
            UserContext("prof_1", "professor", ["cs101"]),
            UserContext("admin_1", "admin", [])
        ]
        
        global_content = {
            "id": "intro_python",
            "name": "Introduction to Python",
            "visibility": "global"
        }
        
        for user in users:
            can_read, _ = RBACFilter.assert_read_permission(global_content, user)
            assert can_read, f"{user.role} should read global content"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
