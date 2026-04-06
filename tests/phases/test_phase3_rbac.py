import pytest

from backend.auth.rbac import UserContext, RBACFilter, RBACValidator


pytestmark = pytest.mark.phase3


def test_phase3_student_visibility_excludes_professor_only():
    student = UserContext(user_id="s1", role="student", course_ids=["cs101"])
    where_clause, params = RBACFilter.build_hierarchy_visibility_filter(student)

    assert "professor-only" not in where_clause
    assert "global" in where_clause


def test_phase3_professor_overlay_filter_scopes_to_professor():
    professor = UserContext(user_id="p1", role="professor", course_ids=["cs101"])
    where_clause, params = RBACFilter.build_student_overlay_filter(professor)

    assert "professor_id" in where_clause
    assert params["professor_id"] == "p1"


def test_phase3_write_permissions():
    student = UserContext(user_id="s1", role="student", course_ids=["cs101"])
    professor = UserContext(user_id="p1", role="professor", course_ids=["cs101"])
    admin = UserContext(user_id="a1", role="admin", course_ids=[])

    student_allowed, _ = RBACFilter.assert_write_permission("p1", student)
    professor_allowed, _ = RBACFilter.assert_write_permission("p1", professor)
    admin_allowed, _ = RBACFilter.assert_write_permission("someone", admin)

    assert student_allowed is False
    assert professor_allowed is True
    assert admin_allowed is True


def test_phase3_visibility_assignment_rules():
    professor = UserContext(user_id="p1", role="professor", course_ids=["cs101"])

    allowed_global, _ = RBACValidator.can_assign_visibility("global", professor)
    allowed_prof_only, _ = RBACValidator.can_assign_visibility("professor-only", professor)

    assert allowed_global is True
    assert allowed_prof_only is False
