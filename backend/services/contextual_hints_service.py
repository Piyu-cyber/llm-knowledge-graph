import json
import os
from typing import Any, Dict, List

from backend.db.graph_manager import GraphManager
from backend.services.llm_router import LLMRouter


graph_manager = GraphManager(data_dir=os.getenv("DATA_DIR", "data"))
llm_router = LLMRouter()


async def generate_hint(student_id: str, question_text: str, draft_answer: str, concept_ids: list[str]) -> dict:
    if len((draft_answer or "").split()) < 20:
        return {
            "hint": "Keep working — add more detail to your answer before requesting a hint.",
            "concept_referenced": None,
            "confidence": 1.0,
        }
    concepts: List[Dict[str, Any]] = []
    for concept_id in concept_ids:
        concept = graph_manager.get_concept_by_id(concept_id)
        overlay = graph_manager.get_student_overlay(student_id, concept_id)
        if concept:
            concepts.append(
                {
                    "concept_id": concept_id,
                    "name": concept.get("name"),
                    "description": concept.get("description"),
                    "theta": float((overlay or {}).get("theta", 0.0)),
                }
            )
    try:
        payload = {
            "question_text": question_text,
            "draft_answer": draft_answer,
            "concepts": concepts,
            "response_schema": {
                "hint": "string",
                "concept_referenced": "string|null",
                "confidence": 0.0,
            },
        }
        route = llm_router.route(
            "contextual_hints",
            "Return one non-answer hint in valid JSON. Max 2 sentences.\n" + json.dumps(payload, indent=2),
            temperature=0.1,
            max_tokens=300,
            use_cache=False,
        )
        result = json.loads(route.get("text", "{}"))
        if not isinstance(result, dict):
            raise ValueError("Hint payload must be an object")
        return {
            "hint": str(result.get("hint", "Revisit the key concept and explain your reasoning step by step.")),
            "concept_referenced": result.get("concept_referenced"),
            "confidence": float(result.get("confidence", 0.6)),
        }
    except Exception:
        concept_ref = concepts[0]["name"] if concepts else None
        return {
            "hint": "Focus on the core concept your draft is missing and explain why it matters before finishing the answer.",
            "concept_referenced": concept_ref,
            "confidence": 0.35,
        }
