import json
import os
from typing import Any, Dict, List

from backend.db.graph_manager import GraphManager
from backend.services.llm_router import LLMRouter


graph_manager = GraphManager(data_dir=os.getenv("DATA_DIR", "data"))
llm_router = LLMRouter()


async def generate_quiz(concept_ids: list[str], difficulty: str, count: int, course_id: str) -> list[dict]:
    concepts: List[Dict[str, Any]] = []
    for concept_id in concept_ids:
        concept = graph_manager.get_concept_by_id(concept_id)
        if concept and concept.get("course_owner") == course_id:
            concepts.append(
                {
                    "concept_id": concept_id,
                    "name": concept.get("name"),
                    "description": concept.get("description"),
                }
            )
    difficulty_map = {
        "easy": "focus on recall and definitions",
        "medium": "focus on application and short reasoning",
        "hard": "focus on synthesis and analysis",
    }
    try:
        prompt = {
            "difficulty": difficulty,
            "instruction": difficulty_map.get(difficulty, difficulty_map["medium"]),
            "count": count,
            "concepts": concepts,
            "response_schema": {
                "questions": [
                    {
                        "concept_id": "string",
                        "type": "mc|short_answer",
                        "question": "string",
                        "options": ["string"],
                        "answer": "string",
                        "difficulty": difficulty,
                    }
                ]
            },
        }
        route = llm_router.route(
            "quiz_generation",
            "Return only valid JSON.\n" + json.dumps(prompt, indent=2),
            temperature=0.2,
            max_tokens=1600,
            use_cache=False,
        )
        payload = json.loads(route.get("text", "{}"))
        questions = payload.get("questions", []) if isinstance(payload, dict) else []
        if isinstance(questions, list) and questions:
            return questions[:count]
    except Exception:
        pass

    fallback: List[Dict[str, Any]] = []
    for idx in range(count):
        concept = concepts[idx % max(1, len(concepts))] if concepts else {"concept_id": "unknown", "name": "Course concept"}
        fallback.append(
            {
                "concept_id": concept.get("concept_id"),
                "type": "short_answer" if idx % 2 else "mc",
                "question": f"Explain the main idea behind {concept.get('name')}.",
                "options": ["Definition", "Example", "Counterexample", "Proof"] if idx % 2 == 0 else None,
                "answer": f"{concept.get('name')} is a key concept in {course_id}.",
                "difficulty": difficulty,
            }
        )
    return fallback
