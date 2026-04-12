import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from backend.db.graph_manager import GraphManager


graph_manager = GraphManager(data_dir=os.getenv("DATA_DIR", "data"))


def _path() -> str:
    path = os.path.join(graph_manager.data_dir, "cohort_alerts.json")
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


async def compute_cohort_alerts(course_id: str) -> list[dict]:
    students = graph_manager.get_enrolled_students(course_id)
    if not students:
        return []
    concepts = graph_manager.get_concept_nodes(course_id)
    coursework_rows = graph_manager._read_json_list(os.path.join(graph_manager.data_dir, "coursework_items.json"))
    window_end = datetime.now(timezone.utc).date() + timedelta(days=int(float(os.getenv("COHORT_ALERT_URGENT_DAYS", "7"))))
    threshold = float(os.getenv("COHORT_ALERT_THRESHOLD", "0.5"))
    results: List[Dict[str, Any]] = []
    for concept in concepts:
        struggling_count = 0
        for student_id in students:
            overlay = graph_manager.get_student_overlay(student_id, concept["id"])
            theta = float((overlay or {}).get("theta", 0.0))
            if theta < 0.5:
                struggling_count += 1
        struggling_pct = (struggling_count / len(students)) if students else 0.0
        if struggling_pct <= threshold:
            continue
        related_assignment = None
        urgent = False
        for row in coursework_rows:
            if row.get("course_id") != course_id:
                continue
            due_raw = str(row.get("due_date", "")).strip()
            try:
                due_dt = datetime.fromisoformat(due_raw.replace("Z", "+00:00")).date()
            except Exception:
                continue
            tagged = row.get("concept_ids", []) or []
            if concept["id"] in tagged and due_dt <= window_end:
                urgent = True
                related_assignment = row.get("title") or row.get("id")
                break
        results.append(
            {
                "concept_id": concept["id"],
                "concept_name": concept.get("name", concept["id"]),
                "struggling_pct": round(struggling_pct, 4),
                "struggling_count": struggling_count,
                "urgent": urgent,
                "related_assignment": related_assignment,
            }
        )
    results.sort(key=lambda row: row["struggling_pct"], reverse=True)
    cache = _read_cache()
    cache[f"{course_id}_{datetime.now(timezone.utc).date().isoformat()}"] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": results,
    }
    _write_cache(cache)
    return results
