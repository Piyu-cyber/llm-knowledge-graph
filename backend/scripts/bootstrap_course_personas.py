import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import bcrypt

# Ensure repo root is importable when running this file directly.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.db.graph_manager import GraphManager
from backend.db.user_store import UserStore
from backend.services.graph_service import GraphService
from backend.services.ingestion_service import IngestionService
from backend.services.llm_service import LLMService
from backend.services.rag_service import RAGService


def _resolve_source_data_dir(cli_value: str = "") -> Path:
    if cli_value:
        p = Path(cli_value).expanduser().resolve()
        if p.exists():
            return p

    # Typical layout:
    # <workspace>/Code/llm-knowledge-graph  (repo root)
    # <workspace>/data                        (source docs folder)
    candidate = REPO_ROOT.parents[1] / "data"
    if candidate.exists():
        return candidate

    # Fallback to repo-local data.
    return (REPO_ROOT / "data").resolve()


def _hash_password(raw_password: str) -> str:
    return bcrypt.hashpw(raw_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _persona_templates(course_id: str) -> List[Dict]:
    return [
        {
            "username": "student_foundation",
            "email": "student_foundation@omniprof.local",
            "full_name": "Aarav Foundation",
            "role": "student",
            "course_ids": [course_id],
            "password": "Student@123",
            "persona": {
                "learning_style": "needs_scaffolding",
                "pace": "slow_and_steady",
                "goal": "build core understanding",
                "support_needs": ["step_by_step_examples", "frequent_checks"],
            },
        },
        {
            "username": "student_balanced",
            "email": "student_balanced@omniprof.local",
            "full_name": "Maya Balanced",
            "role": "student",
            "course_ids": [course_id],
            "password": "Student@123",
            "persona": {
                "learning_style": "mixed",
                "pace": "moderate",
                "goal": "improve exam confidence",
                "support_needs": ["targeted_revision", "practice_questions"],
            },
        },
        {
            "username": "student_advanced",
            "email": "student_advanced@omniprof.local",
            "full_name": "Riya Advanced",
            "role": "student",
            "course_ids": [course_id],
            "password": "Student@123",
            "persona": {
                "learning_style": "challenge_seeking",
                "pace": "fast",
                "goal": "deep conceptual mastery",
                "support_needs": ["edge_cases", "project_driven_tasks"],
            },
        },
    ]


def _upsert_persona_users(user_store: UserStore, personas: List[Dict]) -> Dict[str, str]:
    created_or_existing: Dict[str, str] = {}
    now_iso = datetime.now(timezone.utc).isoformat()

    for persona in personas:
        username = persona["username"]
        existing = user_store.get_user_by_username(username)
        if existing:
            created_or_existing[username] = existing.get("user_id", "")
            continue

        user_id = f"user_{uuid.uuid4().hex[:12]}"
        user_store.add_user(
            username,
            {
                "user_id": user_id,
                "username": username,
                "email": persona["email"],
                "password": _hash_password(persona["password"]),
                "full_name": persona["full_name"],
                "role": persona["role"],
                "course_ids": persona["course_ids"],
                "created_at": now_iso,
                "persona": persona["persona"],
            },
        )
        created_or_existing[username] = user_id

    return created_or_existing


def _write_persona_profiles(data_dir: Path, personas: List[Dict], user_ids: Dict[str, str]) -> Path:
    out_path = data_dir / "student_personas.json"
    payload = []
    for p in personas:
        payload.append(
            {
                "user_id": user_ids.get(p["username"], ""),
                "username": p["username"],
                "full_name": p["full_name"],
                "course_ids": p["course_ids"],
                "persona": p["persona"],
            }
        )
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return out_path


def _reset_generated_artifacts() -> None:
    for relative_path in [
        REPO_ROOT / "data" / "knowledge_graph.json",
        REPO_ROOT / "data" / "nodes.json",
        REPO_ROOT / "data" / "edges.json",
        REPO_ROOT / "rag_index.faiss",
        REPO_ROOT / "rag_chunks.pkl",
    ]:
        if relative_path.exists():
            relative_path.unlink()


def _is_syllabus_file(pdf_path: Path) -> bool:
    return "syllabus" in pdf_path.name.lower()


def _build_course_guide(llm_service: LLMService, syllabus_text: str) -> str:
    guide_payload = llm_service.extract_concepts_hierarchical(syllabus_text)
    nodes = guide_payload.get("nodes", []) if isinstance(guide_payload, dict) else []
    guide_lines: List[str] = []

    for node in nodes:
        level = (node.get("level") or "").upper()
        if level not in {"MODULE", "TOPIC"}:
            continue
        name = (node.get("name") or "").strip()
        description = (node.get("description") or "").strip()
        if not name:
            continue
        if description:
            guide_lines.append(f"{level}: {name} - {description}")
        else:
            guide_lines.append(f"{level}: {name}")

    if not guide_lines:
        guide_lines.append(syllabus_text[:6000])

    return "\n".join(guide_lines)[:12000]


def _parse_guide_hierarchy(course_guide: str) -> Dict[str, str]:
    module_name = ""
    topic_name = ""
    for raw in (course_guide or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if not module_name and line.upper().startswith("MODULE:"):
            module_name = line.split(":", 1)[1].split(" - ", 1)[0].strip()
            continue
        if not topic_name and line.upper().startswith("TOPIC:"):
            topic_name = line.split(":", 1)[1].split(" - ", 1)[0].strip()
            continue
        if module_name and topic_name:
            break
    return {"module": module_name, "topic": topic_name}


def _align_hierarchy_to_syllabus(llm_data: Dict, course_guide: str) -> Dict:
    if not isinstance(llm_data, dict):
        llm_data = {"nodes": [], "edges": []}

    nodes = list(llm_data.get("nodes", []) or [])
    edges = list(llm_data.get("edges", []) or [])
    if not course_guide:
        return {"nodes": nodes, "edges": edges}

    anchors = _parse_guide_hierarchy(course_guide)
    module_name = anchors.get("module") or "Course Module"
    topic_name = anchors.get("topic") or "Course Topic"

    # Remove model-generated module/topic nodes and replace with syllabus anchors.
    kept_nodes = [n for n in nodes if (n.get("level", "").upper() not in {"MODULE", "TOPIC"})]
    kept_nodes.insert(0, {"name": module_name, "level": "MODULE", "description": "Anchored from syllabus guide"})
    kept_nodes.insert(1, {"name": topic_name, "level": "TOPIC", "description": "Anchored from syllabus guide"})

    concept_names = [n.get("name", "") for n in kept_nodes if n.get("level", "").upper() == "CONCEPT" and n.get("name")]
    guided_edges = [
        {"source": topic_name, "target": module_name, "type": "RELATED"},
    ]
    for cname in concept_names:
        guided_edges.append({"source": cname, "target": topic_name, "type": "RELATED"})

    # Keep existing concept-level relations where both endpoints still exist.
    valid_names = {n.get("name", "") for n in kept_nodes}
    for edge in edges:
        s = edge.get("source", "")
        t = edge.get("target", "")
        if s in valid_names and t in valid_names:
            guided_edges.append(edge)

    return {"nodes": kept_nodes, "edges": guided_edges}


def _heuristic_concepts_from_text(text: str, limit: int = 24) -> List[Dict]:
    concepts: List[Dict] = []
    seen = set()
    for raw in (text or "").splitlines():
        line = " ".join(raw.strip().split())
        if len(line) < 5 or len(line) > 90:
            continue
        if line.lower().startswith(("http", "figure", "table", "copyright")):
            continue
        if sum(ch.isalpha() for ch in line) < 4:
            continue
        cleaned = line.strip("-•*0123456789. ")
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        concepts.append(
            {
                "name": cleaned[:80],
                "level": "CONCEPT",
                "description": "Auto-derived concept from course document",
            }
        )
        if len(concepts) >= limit:
            break
    return concepts


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap course PDFs and seed student personas")
    parser.add_argument("--source-data-dir", default="", help="Folder containing syllabus/course PDFs")
    parser.add_argument("--course-id", default="cs101")
    parser.add_argument("--course-owner", default="user_default_professor")
    parser.add_argument(
        "--reset-artifacts",
        action="store_true",
        help="Delete existing graph and RAG artifacts before rebuilding from source PDFs",
    )
    parser.add_argument(
        "--ingest-mode",
        default="fast",
        choices=["rag-only", "fast", "full"],
        help="rag-only: index course docs in RAG only, fast: one extraction pass per PDF, full: existing multi-unit ingestion",
    )
    args = parser.parse_args()

    os.chdir(REPO_ROOT)
    if args.reset_artifacts:
        _reset_generated_artifacts()

    source_dir = _resolve_source_data_dir(args.source_data_dir)

    pdf_files = sorted(source_dir.glob("*.pdf"))
    syllabus_files = [pdf for pdf in pdf_files if _is_syllabus_file(pdf)]
    syllabus_files = sorted(syllabus_files)
    non_syllabus_files = [pdf for pdf in pdf_files if pdf not in syllabus_files]
    ordered_pdfs = syllabus_files + non_syllabus_files

    # Initialize existing services exactly like the app does.
    rag_service = RAGService()
    llm_service = LLMService()
    graph_manager = GraphManager()
    graph_service = GraphService(graph_manager)
    ingestion_service = IngestionService(
        llm_service=llm_service,
        rag_service=rag_service,
        graph_service=graph_service,
    )

    course_guide = ""
    if syllabus_files:
        syllabus_pdf = syllabus_files[0]
        try:
            syllabus_text, _ = ingestion_service.extractor.extract_text(str(syllabus_pdf))
            normalized_syllabus = ingestion_service._normalize_text(syllabus_text)
            course_guide = _build_course_guide(llm_service, normalized_syllabus)
        except Exception as e:
            print(f"Failed to build syllabus guide from {syllabus_pdf.name}: {e}")

    ingest_results = []
    for pdf in ordered_pdfs:
        is_syllabus = _is_syllabus_file(pdf)
        if args.ingest_mode == "rag-only":
            try:
                text, file_format = ingestion_service.extractor.extract_text(str(pdf))
                normalized = ingestion_service._normalize_text(text)
                rag_service.ingest_documents(
                    normalized,
                    guide_text="" if is_syllabus else course_guide,
                    source_name=pdf.name,
                )
                ingest_results.append(
                    {
                        "file": str(pdf),
                        "mode": "rag-only",
                        "result": {
                            "status": "success",
                            "file_format": file_format,
                            "rag_indexed": True,
                            "chars_indexed": len(normalized),
                        },
                    }
                )
            except Exception as e:
                ingest_results.append(
                    {
                        "file": str(pdf),
                        "mode": "rag-only",
                        "result": {"status": "error", "message": str(e)},
                    }
                )
            continue

        if args.ingest_mode == "full":
            result = ingestion_service.ingest(
                str(pdf),
                course_owner=args.course_owner,
                course_guide_text="" if is_syllabus else course_guide,
                source_doc_name=pdf.name,
            )
            ingest_results.append({"file": str(pdf), "mode": "full", "result": result})
            continue

        # Fast mode: one extraction pass per document for predictable runtime.
        try:
            text, file_format = ingestion_service.extractor.extract_text(str(pdf))
            normalized = ingestion_service._normalize_text(text)
            llm_data = llm_service.extract_concepts_hierarchical(normalized, guide="" if is_syllabus else course_guide)
            if not is_syllabus:
                llm_data = _align_hierarchy_to_syllabus(llm_data, course_guide)
                concept_count = len([n for n in llm_data.get("nodes", []) if (n.get("level") or "").upper() == "CONCEPT"])
                if concept_count == 0:
                    anchors = _parse_guide_hierarchy(course_guide)
                    topic_name = anchors.get("topic") or "Course Topic"
                    fallback_concepts = _heuristic_concepts_from_text(normalized)
                    llm_data["nodes"].extend(fallback_concepts)
                    llm_data["edges"].extend(
                        {
                            "source": concept.get("name", ""),
                            "target": topic_name,
                            "type": "RELATED",
                        }
                        for concept in fallback_concepts
                        if concept.get("name")
                    )
            insert_result = graph_service.insert_from_llm_hierarchical(
                data=llm_data,
                course_owner=args.course_owner,
                source_doc=pdf.name,
                file_format=file_format,
            )
            try:
                rag_service.ingest_documents(
                    normalized,
                    guide_text="" if is_syllabus else course_guide,
                    source_name=pdf.name,
                )
            except Exception:
                pass

            ingest_results.append(
                {
                    "file": str(pdf),
                    "mode": "fast",
                    "result": {
                        "status": insert_result.get("status", "success"),
                        "modules_added": insert_result.get("modules_added", 0),
                        "topics_added": insert_result.get("topics_added", 0),
                        "concepts_added": insert_result.get("concepts_added", 0),
                        "relationships_added": insert_result.get("relationships_added", 0),
                        "facts_added": insert_result.get("facts_added", 0),
                    },
                }
            )
        except Exception as e:
            ingest_results.append(
                {
                    "file": str(pdf),
                    "mode": "fast",
                    "result": {"status": "error", "message": str(e)},
                }
            )

    if course_guide:
        guide_path = REPO_ROOT / "data" / "course_guide_from_syllabus.txt"
        with open(guide_path, "w", encoding="utf-8") as f:
            f.write(course_guide)

    user_store = UserStore(data_dir=str(REPO_ROOT / "data"))
    personas = _persona_templates(args.course_id)
    user_ids = _upsert_persona_users(user_store, personas)

    enrollment_results = []
    for persona in personas:
        uid = user_ids.get(persona["username"], "")
        if not uid:
            continue
        enrollment_results.append(
            {
                "username": persona["username"],
                "enrollment": graph_service.enroll_student(uid, args.course_id),
            }
        )

    persona_file = _write_persona_profiles(REPO_ROOT / "data", personas, user_ids)

    summary = {
        "source_data_dir": str(source_dir),
        "pdf_files_found": [str(p) for p in pdf_files],
        "ingestion_results": ingest_results,
        "persona_user_ids": user_ids,
        "enrollment_results": enrollment_results,
        "persona_profile_file": str(persona_file),
    }

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
