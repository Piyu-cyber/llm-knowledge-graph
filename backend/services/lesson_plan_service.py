import json
import os
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, List

from backend.db.graph_manager import GraphManager
from backend.services.llm_router import LLMRouter


graph_manager = GraphManager(data_dir=os.getenv("DATA_DIR", "data"))
llm_router = LLMRouter()


def _path() -> str:
    path = os.path.join(graph_manager.data_dir, "lesson_plans.json")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=2)
    return path


def _read_rows() -> Dict[str, Any]:
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_rows(rows: Dict[str, Any]) -> None:
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)


def _conflicts(new_nodes: List[Dict[str, Any]], existing_graph_summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    existing = existing_graph_summary.get("concepts", []) if isinstance(existing_graph_summary, dict) else []
    threshold = float(os.getenv("LESSON_PLAN_CONFLICT_SIMILARITY", "0.85"))
    conflicts: List[Dict[str, Any]] = []
    for node in new_nodes:
        if str(node.get("level", "")).upper() != "CONCEPT":
            continue
        node_name = str(node.get("name", "")).strip()
        node_requires = sorted(node.get("prerequisites", []) or [])
        for current in existing:
            similarity = SequenceMatcher(None, node_name.lower(), str(current.get("name", "")).lower()).ratio()
            if similarity < threshold:
                continue
            current_requires = sorted(current.get("prerequisites", []) or [])
            if node_requires != current_requires:
                conflicts.append(
                    {
                        "new_node": node_name,
                        "existing_node": current.get("name"),
                        "similarity": round(similarity, 4),
                        "new_prerequisites": node_requires,
                        "existing_prerequisites": current_requires,
                    }
                )
                break
    return conflicts


async def generate_lesson_plan(upload_id: str, new_nodes: list[dict], existing_graph_summary: dict, course_id: str) -> dict:
    conflicts = _conflicts(new_nodes, existing_graph_summary)
    lesson_plan: List[Dict[str, Any]] = []
    quiz_suggestions: List[Dict[str, Any]] = []
    try:
        lesson_prompt = {
            "course_id": course_id,
            "new_nodes": new_nodes,
            "existing_graph_summary": existing_graph_summary,
            "response_schema": {
                "lesson_plan": [
                    {
                        "title": "string",
                        "duration_minutes": 15,
                        "concepts": ["concept_id"],
                        "teaching_notes": "string",
                        "suggested_activities": ["string"],
                    }
                ]
            },
        }
        lesson_route = llm_router.route(
            "lesson_plan_generation",
            "Return only valid JSON for a lesson plan.\n" + json.dumps(lesson_prompt, indent=2),
            temperature=0.2,
            max_tokens=1400,
            use_cache=False,
        )
        parsed_lesson = json.loads(lesson_route.get("text", "{}"))
        lesson_plan = parsed_lesson.get("lesson_plan", []) if isinstance(parsed_lesson, dict) else []
    except Exception:
        lesson_plan = []

    try:
        quiz_prompt = {
            "concepts": [
                {
                    "concept_id": node.get("id") or node.get("name"),
                    "name": node.get("name"),
                    "description": node.get("description"),
                }
                for node in new_nodes
                if str(node.get("level", "")).upper() == "CONCEPT"
            ],
            "response_schema": {
                "quiz_suggestions": [
                    {
                        "concept_id": "string",
                        "type": "mc|short_answer",
                        "question": "string",
                        "options": ["string"],
                        "answer": "string",
                        "difficulty": "medium",
                    }
                ]
            },
        }
        quiz_route = llm_router.route(
            "lesson_plan_generation",
            "Generate quiz suggestions. Return only valid JSON.\n" + json.dumps(quiz_prompt, indent=2),
            temperature=0.2,
            max_tokens=1400,
            use_cache=False,
        )
        parsed_quiz = json.loads(quiz_route.get("text", "{}"))
        quiz_suggestions = parsed_quiz.get("quiz_suggestions", []) if isinstance(parsed_quiz, dict) else []
    except Exception:
        quiz_suggestions = []

    payload = {
        "upload_id": upload_id,
        "lesson_plan": lesson_plan,
        "quiz_suggestions": quiz_suggestions,
        "conflicts": conflicts,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    rows = _read_rows()
    rows[upload_id] = payload
    _write_rows(rows)
    return payload
