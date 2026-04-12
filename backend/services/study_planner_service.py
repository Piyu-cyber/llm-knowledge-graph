import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from backend.db.graph_manager import GraphManager
from backend.services.llm_router import LLMRouter


graph_manager = GraphManager(data_dir=os.getenv("DATA_DIR", "data"))
llm_router = LLMRouter()


def _path() -> str:
    path = os.path.join(graph_manager.data_dir, "study_plans.json")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=2)
    return path


def _read_cache() -> Dict[str, Any]:
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_cache(data: Dict[str, Any]) -> None:
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _assignment_rows(course_id: str, student_id: str) -> List[Dict[str, Any]]:
    coursework_path = os.path.join(graph_manager.data_dir, "coursework_items.json")
    rows = graph_manager._read_json_list(coursework_path)
    defence_rows = graph_manager._read_json_list(graph_manager._defence_records_path())
    submitted_assignment_ids = {
        str(row.get("assignment_id"))
        for row in defence_rows
        if row.get("student_id") == student_id and row.get("course_id") == course_id and row.get("assignment_id")
    }
    window_end = datetime.now(timezone.utc).date() + timedelta(days=7)
    upcoming: List[Dict[str, Any]] = []
    for row in rows:
        if row.get("course_id") != course_id:
            continue
        assignment_id = str(row.get("id", ""))
        if assignment_id in submitted_assignment_ids:
            continue
        due_raw = str(row.get("due_date", "")).strip()
        try:
            due_dt = datetime.fromisoformat(due_raw.replace("Z", "+00:00")).date()
        except Exception:
            continue
        if due_dt <= window_end:
            upcoming.append(row)
    upcoming.sort(key=lambda r: str(r.get("due_date", "")))
    return upcoming


def _fallback_blocks(overlays: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    blocks = []
    for overlay in overlays[:3]:
        concept_id = overlay.get("concept_id")
        concept = graph_manager.get_concept_by_id(concept_id) or {}
        blocks.append(
            {
                "title": f"Review {concept.get('name', concept_id)}",
                "description": "Focus on fundamentals and revisit weak areas before your next deadline.",
                "duration_minutes": 30,
                "priority": "high",
                "concept_ids": [concept_id] if concept_id else [],
            }
        )
    return blocks


async def generate_study_plan(student_id: str, course_id: str) -> dict:
    try:
        cache = _read_cache()
        cache_key = f"{student_id}_{_today()}"
        cached = cache.get(cache_key)
        if isinstance(cached, dict) and cached.get("course_id") == course_id:
            return cached

        overlays = graph_manager.get_student_concepts(student_id)
        overlays = [
            row
            for row in overlays
            if graph_manager.nodes_data.get(row.get("concept_id"), {}).get("course_owner") == course_id
        ]
        overlays.sort(key=lambda row: float(row.get("theta", 0.0)))
        upcoming = _assignment_rows(course_id, student_id)

        prompt = {
            "today": _today(),
            "course_id": course_id,
            "mastery": [
                {
                    "concept_id": row.get("concept_id"),
                    "concept_name": graph_manager.nodes_data.get(row.get("concept_id"), {}).get("name"),
                    "theta": float(row.get("theta", 0.0)),
                }
                for row in overlays[:12]
            ],
            "upcoming_assignments": [
                {
                    "id": row.get("id"),
                    "title": row.get("title"),
                    "due_date": row.get("due_date"),
                    "concept_ids": row.get("concept_ids", []),
                }
                for row in upcoming[:8]
            ],
            "response_schema": {
                "blocks": [
                    {
                        "title": "string",
                        "description": "string",
                        "duration_minutes": 30,
                        "priority": "high|medium|low",
                        "concept_ids": ["concept_id"],
                    }
                ]
            },
        }
        llm_result = llm_router.route(
            "study_planner",
            "Return only valid JSON for a daily study plan.\n" + json.dumps(prompt, indent=2),
            temperature=0.1,
            max_tokens=900,
            use_cache=False,
        )
        parsed = json.loads(llm_result.get("text", "{}"))
        blocks = parsed.get("blocks") if isinstance(parsed, dict) else parsed
        if not isinstance(blocks, list):
            blocks = _fallback_blocks(overlays)

        response = {
            "blocks": blocks,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "error": None,
            "course_id": course_id,
        }
        cache[cache_key] = response
        _write_cache(cache)
        return response
    except Exception:
        try:
            overlays = graph_manager.get_student_concepts(student_id)
            overlays = [
                row
                for row in overlays
                if graph_manager.nodes_data.get(row.get("concept_id"), {}).get("course_owner") == course_id
            ]
            overlays.sort(key=lambda row: float(row.get("theta", 0.0)))
            return {
                "blocks": _fallback_blocks(overlays),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "error": "reduced_mode",
                "course_id": course_id,
            }
        except Exception:
            return {"blocks": [], "generated_at": datetime.now(timezone.utc).isoformat(), "error": "reduced_mode"}
