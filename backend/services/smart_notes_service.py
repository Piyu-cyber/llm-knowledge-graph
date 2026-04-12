import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from backend.db.graph_manager import GraphManager
from backend.services.llm_router import LLMRouter


graph_manager = GraphManager(data_dir=os.getenv("DATA_DIR", "data"))
llm_router = LLMRouter()


def _path() -> str:
    path = os.path.join(graph_manager.data_dir, "smart_notes.json")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump([], f, indent=2)
    return path


def _read_rows() -> List[Dict[str, Any]]:
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_rows(rows: List[Dict[str, Any]]) -> None:
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)


def _infer_course_id(student_id: str, session_id: str, messages: List[Dict[str, Any]]) -> str:
    for message in messages:
        for key in ("course_id",):
            value = message.get(key)
            if value:
                return str(value)
        metadata = message.get("metadata")
        if isinstance(metadata, dict) and metadata.get("course_id"):
            return str(metadata["course_id"])

    checkpoints_path = os.path.join(graph_manager.data_dir, "session_checkpoints.json")
    checkpoints = graph_manager._read_json_list(checkpoints_path)
    for row in reversed(checkpoints):
        if row.get("student_id") == student_id and row.get("session_id") == session_id and row.get("course_id"):
            return str(row.get("course_id"))

    defence_rows = graph_manager._read_json_list(graph_manager._defence_records_path())
    for row in reversed(defence_rows):
        if row.get("student_id") == student_id and row.get("session_id") == session_id and row.get("course_id"):
            return str(row.get("course_id"))
    return "unknown"


async def generate_session_notes(student_id: str, session_id: str, messages: list[dict]) -> dict:
    try:
        prompt = {
            "messages": messages[-20:],
            "schema": {
                "concepts_covered": ["string"],
                "key_definitions": {"term": "definition"},
                "connections": ["string"],
                "follow_up_suggestions": ["string"],
            },
        }
        route = llm_router.route(
            "smart_notes",
            "Extract structured tutoring notes. Return only JSON.\n" + json.dumps(prompt, indent=2),
            temperature=0.1,
            max_tokens=900,
            use_cache=False,
        )
        note = json.loads(route.get("text", "{}"))
        if not isinstance(note, dict):
            note = {}
    except Exception:
        note = {}

    note = {
        "student_id": student_id,
        "session_id": session_id,
        "course_id": _infer_course_id(student_id, session_id, messages),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "concepts_covered": list(note.get("concepts_covered", [])) if isinstance(note.get("concepts_covered", []), list) else [],
        "key_definitions": note.get("key_definitions", {}) if isinstance(note.get("key_definitions", {}), dict) else {},
        "connections": list(note.get("connections", [])) if isinstance(note.get("connections", []), list) else [],
        "follow_up_suggestions": list(note.get("follow_up_suggestions", [])) if isinstance(note.get("follow_up_suggestions", []), list) else [],
    }
    rows = _read_rows()
    rows.append(note)
    _write_rows(rows)
    return note
