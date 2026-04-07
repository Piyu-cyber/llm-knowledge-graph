"""
OmniProf Summarisation Agent
Background task for creating memory anchors and semantic nodes from old interactions.

Features:
- Creates memory anchors for interactions >= 7 days old
- Extracts facts and creates semantic memory nodes from summaries
- Runs as FastAPI background task (non-blocking)
- Generates LLM-based summaries of interactions
- Links memories to concepts for future context retrieval
"""

import logging
import os
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import json

from backend.agents.state import AgentState
from backend.db.graph_manager import GraphManager
from backend.db.neo4j_schema import SemanticNode
from backend.services.llm_service import LLMService

logger = logging.getLogger(__name__)


@dataclass
class MemoryAnchor:
    """
    Represents long-term memory of a learning session.
    Created when interaction is 7+ days old.
    """
    student_id: str
    session_date: str
    concepts: List[str] = field(default_factory=list)
    confidence: Dict[str, float] = field(default_factory=dict)  # concept_id -> confidence
    misconceptions: List[str] = field(default_factory=list)
    summary_text: str = ""
    memory_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict:
        """Convert to serializable dict"""
        return {
            "student_id": self.student_id,
            "session_date": self.session_date,
            "concepts": self.concepts,
            "confidence": self.confidence,
            "misconceptions": self.misconceptions,
            "summary_text": self.summary_text,
            "memory_id": self.memory_id,
            "created_at": self.created_at
        }


class SummarisationAgent:
    """
    Summarisation Agent for creating long-term memory anchors.
    
    Runs as FastAPI BackgroundTask (non-blocking).
    Processes interactions that are 7+ days old.
    Creates MemoryAnchor nodes in Neo4j for future retrieval context.
    
    Process:
    1. Query all student interactions >= 7 days old
    2. Extract concepts discussed, confidence levels, misconceptions
    3. Generate LLM-based summary of learning
    4. Write MemoryAnchor node to Neo4j
    5. Link to student and related concepts
    """
    
    MEMORY_AGE_DAYS = 7
    BATCH_SIZE = 20  # Process interactions in batches
    
    def __init__(self, data_dir: Optional[str] = None,
                 groq_api_key: Optional[str] = None):
        """
        Initialize Summarisation Agent.
        
        Args:
            data_dir: Path to data directory for graph persistence
            groq_api_key: Groq API key for LLM
        """
        from dotenv import load_dotenv
        
        load_dotenv()
        
        # Use GraphManager which uses RustWorkX backend
        self.graph_manager = GraphManager(
            data_dir=data_dir or os.getenv("DATA_DIR", "data")
        )
        
        self.data_dir = self.graph_manager.data_dir
        self.llm_service = LLMService()
    
    
    # ==================== Background Task Entry Point ====================
    
    async def process_old_interactions(self) -> Dict[str, Any]:
        """
        Main background task entry point.
        
        Processes all old interactions (7+ days) for all students.
        Creates MemoryAnchor nodes in Neo4j.
        
        Returns:
            Summary dict with processing statistics
        """
        try:
            logger.info("SummarisationAgent: Starting old interaction processing")
            
            cutoff_date = (datetime.now() - timedelta(days=self.MEMORY_AGE_DAYS))
            cutoff_iso = cutoff_date.isoformat()
            
            # Find all old interactions
            old_interactions = self._get_old_interactions(cutoff_iso)
            logger.info(f"Found {len(old_interactions)} old interactions")
            
            # Process in batches
            total_memories_created = 0
            total_errors = 0
            
            for i in range(0, len(old_interactions), self.BATCH_SIZE):
                batch = old_interactions[i:i + self.BATCH_SIZE]
                
                for interaction in batch:
                    try:
                        result = await self._process_interaction(interaction)
                        if result:
                            total_memories_created += 1
                    except Exception as e:
                        logger.error(f"Error processing interaction: {str(e)}")
                        total_errors += 1
            
            logger.info(f"SummarisationAgent complete: "
                       f"{total_memories_created} memories created, "
                       f"{total_errors} errors")
            
            return {
                "status": "success",
                "memories_created": total_memories_created,
                "errors": total_errors,
                "cutoff_date": cutoff_iso
            }
            
        except Exception as e:
            logger.error(f"SummarisationAgent fatal error: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "error": str(e)
            }
    
    
    # ==================== Interaction Processing ====================
    
    def _get_old_interactions(self, cutoff_date: str) -> List[Dict]:
        """
        Get all interactions older than cutoff date.
        
        Reads from session_checkpoints.json and filters those that don't
        have a corresponding memory anchor yet. Groups by (student, session).
        
        Args:
            cutoff_date: ISO timestamp cutoff (older than this)
        
        Returns:
            List of dicts with {student_id, session_id, session_date}
        """
        try:
            # Read session checkpoints
            sessions_path = os.path.join(self.data_dir, "session_checkpoints.json")
            if not os.path.exists(sessions_path):
                return []
            
            with open(sessions_path, 'r', encoding='utf-8') as f:
                sessions = json.load(f)
            
            if not isinstance(sessions, list):
                sessions = [sessions]
            
            # Read existing memory anchors to check what's already summarized
            anchors_path = os.path.join(self.data_dir, "memory_anchors.json")
            summarized_sessions = set()
            
            if os.path.exists(anchors_path):
                try:
                    with open(anchors_path, 'r', encoding='utf-8') as f:
                        anchors = json.load(f)
                    if not isinstance(anchors, list):
                        anchors = [anchors]
                    # Track which sessions are already summarized
                    summarized_sessions = {a.get('session_id') for a in anchors if a.get('session_id')}
                except (json.JSONDecodeError, IOError):
                    pass
            
            # Filter sessions older than cutoff and not yet summarized
            old_interactions = []
            for session in sessions:
                session_id = session.get('session_id')
                student_id = session.get('student_id')
                session_date = session.get('timestamp') or session.get('created_at')
                
                # Skip if already summarized
                if session_id in summarized_sessions:
                    continue
                
                # Check if older than cutoff
                if session_date and session_date < cutoff_date:
                    old_interactions.append({
                        "student_id": student_id,
                        "session_id": session_id,
                        "session_date": session_date
                    })
            
            # Sort by date descending (newest old interactions first)
            old_interactions.sort(key=lambda x: x.get('session_date', ''), reverse=True)
            
            logger.debug(f"Found {len(old_interactions)} old unsummarized interactions")
            return old_interactions
            
        except Exception as e:
            logger.warning(f"Old interactions query error: {str(e)}")
            return []
    
    
    async def _process_interaction(self, interaction: Dict) -> Optional[str]:
        """
        Process single interaction session.
        
        Args:
            interaction: Session dict with student_id, session_id, session_date
        
        Returns:
            Memory anchor ID if successful, None otherwise
        """
        try:
            student_id = interaction.get("student_id")
            session_id = interaction.get("session_id")
            session_date = interaction.get("session_date")
            
            logger.debug(f"Processing session {session_id} for {student_id}")
            
            # Extract session concepts and metadata
            concepts, confidence, misconceptions = self._extract_session_metadata(
                student_id,
                session_id
            )
            
            # Generate summary via LLM
            summary = await self._generate_session_summary(
                student_id,
                session_id,
                concepts,
                misconceptions
            )
            
            # Create memory anchor
            memory = MemoryAnchor(
                student_id=student_id,
                session_date=session_date,
                concepts=concepts,
                confidence=confidence,
                misconceptions=misconceptions,
                summary_text=summary
            )
            
            # Write to Neo4j
            memory_id = self._write_memory_anchor(memory, session_id)
            
            if memory_id:
                logger.info(f"Memory created: {memory_id} for {student_id}")
                
                # Extract and create semantic nodes from summary
                self._extract_and_create_semantic_nodes(
                    student_id=student_id,
                    session_id=session_id,
                    summary_text=summary,
                    concept_ids=concepts
                )
                
                return memory_id
            
            return None
            
        except Exception as e:
            logger.error(f"Interaction processing error: {str(e)}")
            return None
    
    
    def _extract_session_metadata(self, student_id: str, session_id: str) -> tuple:
        """
        Extract concepts, confidence levels, and misconceptions from session.
        
        Reads from session_checkpoints.json and extracts concepts
        mentioned in the messages field.
        
        Args:
            student_id: Student ID
            session_id: Session ID
        
        Returns:
            Tuple of (concepts, confidence_dict, misconceptions)
        """
        try:
            # Read session from checkpoints
            sessions_path = os.path.join(self.data_dir, "session_checkpoints.json")
            if not os.path.exists(sessions_path):
                return [], {}, []
            
            with open(sessions_path, 'r', encoding='utf-8') as f:
                sessions = json.load(f)
            
            if not isinstance(sessions, list):
                sessions = [sessions]
            
            # Find the target session
            target_session = None
            for session in sessions:
                if session.get('session_id') == session_id and session.get('student_id') == student_id:
                    target_session = session
                    break
            
            if not target_session:
                return [], {}, []
            
            # Extract concepts from messages
            concepts = []
            confidence = {}
            messages = target_session.get('messages', [])
            
            # Parse messages to find mentioned concepts
            if isinstance(messages, list):
                for msg in messages:
                    content = msg.get('content', '')
                    # Simple extraction: look for concept mentions
                    # In real implementation, would use NLP to extract concepts
                    # For now, extract concept_id if present in metadata
                    if isinstance(msg, dict):
                        mentioned_concept = msg.get('concept_id') or msg.get('concept')
                        if mentioned_concept and mentioned_concept not in concepts:
                            concepts.append(mentioned_concept)
                            # Try to get confidence from StudentOverlay
                            overlay = self.graph_manager.get_student_overlay(student_id, mentioned_concept)
                            if overlay:
                                confidence[mentioned_concept] = overlay.get('mastery_probability', 0.5)
                            else:
                                confidence[mentioned_concept] = 0.5
            
            # Extract misconceptions from evaluation records
            misconceptions = self._get_session_misconceptions(student_id, session_id)
            
            return concepts, confidence, misconceptions
            
        except Exception as e:
            logger.warning(f"Metadata extraction error: {str(e)}")
            return [], {}, []
    
    
    def _get_session_misconceptions(self, student_id: str, session_id: str) -> List[str]:
        """
        Extract misconceptions from evaluation records in session.
        
        Reads from defence_records.json to find feedback containing
        "misconception" for the given student and session.
        
        Args:
            student_id: Student ID
            session_id: Session ID
        
        Returns:
            List of misconception strings
        """
        try:
            # Read defence records
            records_path = os.path.join(self.data_dir, "defence_records.json")
            if not os.path.exists(records_path):
                return []
            
            with open(records_path, 'r', encoding='utf-8') as f:
                records = json.load(f)
            
            if not isinstance(records, list):
                records = [records]
            
            misconceptions = []
            for record in records:
                # Filter by student_id and session_id
                if (record.get('student_id') != student_id or 
                    record.get('session_id') != session_id):
                    continue
                
                # Extract feedback with misconceptions
                feedback = record.get('ai_feedback', '')
                if feedback and 'misconception' in feedback.lower():
                    misconceptions.append(feedback[:100])  # First 100 chars
            
            return misconceptions
            
        except Exception as e:
            logger.warning(f"Misconception extraction error: {str(e)}")
            return []
    
    
    async def _generate_session_summary(self, student_id: str, session_id: str,
                                       concepts: List[str],
                                       misconceptions: List[str]) -> str:
        """
        Generate LLM-based summary of session.
        
        Args:
            student_id: Student ID
            session_id: Session ID
            concepts: Concepts discussed
            misconceptions: Misconceptions identified
        
        Returns:
            Summary text
        """
        try:
            # Build summary prompt
            prompt = (
                f"Summarize a tutoring session with the following information:\n"
                f"Concepts covered: {', '.join(concepts[:5])}\n"
                f"Key misconceptions: {', '.join(misconceptions[:3]) if misconceptions else 'None'}\n"
                f"Create a brief, student-friendly summary (2-3 sentences) of what was learned.\n"
                f"Focus on insights and progress, not specific technical details."
            )
            
            # Call LLM
            summary = self.llm_service.generate_response(
                prompt=prompt,
                system_prompt="You are a helpful educational assistant creating concise learning summaries."
            )
            
            return summary if summary else "Session completed with focus on conceptual understanding."
            
        except Exception as e:
            logger.warning(f"Summary generation error: {str(e)}")
            return "Session completed."
    
    
    # ==================== Memory Anchor Writing ====================
    
    def _write_memory_anchor(self, memory: MemoryAnchor, session_id: str) -> Optional[str]:
        """
        Write MemoryAnchor node to Neo4j.
        
        Creates MemoryAnchor node linked to student and session.
        Also links to related concept nodes for context retrieval.
        
        Args:
            memory: MemoryAnchor instance
            session_id: Session ID to link
        
        Returns:
            Memory anchor ID if successful, None otherwise
        """
        try:
            import uuid
            memory.memory_id = str(uuid.uuid4())[:12]

            if hasattr(self.graph_manager, "create_memory_anchor"):
                result = self.graph_manager.create_memory_anchor(
                    student_id=memory.student_id,
                    session_id=session_id,
                    summary=memory.summary_text,
                    key_concepts=memory.concepts,
                )
                if result.get("status") == "success":
                    return result.get("node_id")
                if not hasattr(self.graph_manager, "db"):
                    return None
            
            # Create memory anchor node
            query = (
                "MATCH (student:User {id: $student_id}) "
                "MATCH (session:Session {id: $session_id}) "
                "CREATE (mem:MemoryAnchor {"
                "  id: $memory_id,"
                "  session_date: $session_date,"
                "  summary_text: $summary_text,"
                "  misconceptions: $misconceptions,"
                "  created_at: $created_at"
                "}) "
                "CREATE (student)-[:HAS_MEMORY]->(mem) "
                "CREATE (session)-[:SUMMARIZED_TO]->(mem) "
                "RETURN mem.id"
            )
            
            result = self.graph_manager.db.run_query(
                query,
                {
                    "student_id": memory.student_id,
                    "session_id": session_id,
                    "memory_id": memory.memory_id,
                    "session_date": memory.session_date,
                    "summary_text": memory.summary_text,
                    "misconceptions": json.dumps(memory.misconceptions),
                    "created_at": memory.created_at
                }
            )
            
            if not result:
                return None
            
            # Link to related concepts
            for concept_id in memory.concepts:
                try:
                    link_query = (
                        "MATCH (mem:MemoryAnchor {id: $memory_id}) "
                        "MATCH (concept:CONCEPT {id: $concept_id}) "
                        "CREATE (mem)-[:DISCUSSED]->(concept)"
                    )
                    
                    self.graph_manager.db.run_query(
                        link_query,
                        {
                            "memory_id": memory.memory_id,
                            "concept_id": concept_id
                        }
                    )
                except Exception as e:
                    logger.warning(f"Concept linking error: {str(e)}")
            
            logger.info(f"MemoryAnchor written: {memory.memory_id}")
            return memory.memory_id
            
        except Exception as e:
            logger.error(f"MemoryAnchor writing error: {str(e)}")
            return None
    
    
    # ==================== Semantic Node Extraction ====================
    
    def _extract_and_create_semantic_nodes(self, 
                                          student_id: str,
                                          session_id: str,
                                          summary_text: str,
                                          concept_ids: List[str]) -> None:
        """
        Extract facts from summary and create semantic memory nodes.
        
        Uses LLM to extract key facts from the session summary,
        then creates SemanticNode entries in Neo4j linked to concepts.
        
        Args:
            student_id: Student ID
            session_id: Session ID
            summary_text: Generated session summary
            concept_ids: Concepts discussed in session
        """
        try:
            if not summary_text or not concept_ids:
                return
            
            # Extract facts from summary via LLM
            facts = self._extract_facts_from_summary(summary_text, concept_ids)
            
            if not facts:
                logger.debug("No facts extracted from summary")
                return
            
            # Create semantic nodes
            for concept_id, fact_list in facts.items():
                for fact in fact_list:
                    try:
                        semantic = SemanticNode(
                            student_id=student_id,
                            fact=fact,
                            concept_id=concept_id,
                            confidence=0.85,  # Confidence from LLM extraction
                            source_session_id=session_id
                        )
                        
                        # Write to Neo4j
                        self._write_semantic_node(semantic)
                        
                    except Exception as e:
                        logger.warning(f"Semantic node creation error: {str(e)}")
            
            logger.debug(f"Semantic nodes created for {student_id}: {len(facts)} concepts")
            
        except Exception as e:
            logger.error(f"Semantic extraction error: {str(e)}")
    
    
    def _extract_facts_from_summary(self, summary_text: str, 
                                   concept_ids: List[str]) -> Dict[str, List[str]]:
        """
        Extract key facts from session summary using LLM.
        
        Args:
            summary_text: Generated session summary
            concept_ids: Concepts to extract facts for
        
        Returns:
            Dict mapping concept_id to list of extracted facts
        """
        try:
            # Build extraction prompt
            prompt = (
                f"Extract the key facts and learnings from this tutoring session summary.\n\n"
                f"Summary: {summary_text}\n\n"
                f"Related concepts: {', '.join(concept_ids[:5])}\n\n"
                f"Return a JSON object mapping each concept to a list of 1-3 key facts learned:\n"
                f'{{"concept_id_1": ["fact 1", "fact 2"], "concept_id_2": ["fact 3"]}}\n\n'
                f"Only include facts that are explicitly mentioned in the summary."
            )
            
            # Call LLM
            response = self.llm_service.generate_response(
                prompt=prompt,
                system_prompt="You are an expert at extracting key facts from educational summaries. "
                            "Return only valid JSON without markdown formatting."
            )
            
            # Parse JSON response
            if not response:
                return {}
            
            facts_dict = json.loads(response)
            return facts_dict if isinstance(facts_dict, dict) else {}
            
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM response as JSON for fact extraction")
            return {}
        except Exception as e:
            logger.warning(f"Fact extraction error: {str(e)}")
            return {}
    
    
    def _write_semantic_node(self, semantic: SemanticNode) -> bool:
        """
        Write semantic node to Neo4j.
        
        Args:
            semantic: SemanticNode instance
        
        Returns:
            Success status
        """
        try:
            if hasattr(self.graph_manager, "create_semantic_node"):
                result = self.graph_manager.create_semantic_node(
                    student_id=semantic.student_id,
                    fact=semantic.fact,
                    concept_id=semantic.concept_id,
                    confidence=semantic.confidence,
                )
                return result.get("status") == "success"

            query = (
                "MATCH (student:User {id: $student_id}) "
                "MATCH (concept:CONCEPT {id: $concept_id}) "
                "CREATE (sem:SemanticNode {"
                "  id: $semantic_id,"
                "  fact: $fact,"
                "  confidence: $confidence,"
                "  source_session_id: $source_session_id,"
                "  created_at: $created_at,"
                "  access_count: 0"
                "}) "
                "CREATE (student)-[:LEARNED_FROM]->(sem) "
                "CREATE (sem)-[:EXTRACTED_FROM]->(concept) "
                "RETURN sem.id"
            )
            
            result = self.graph_manager.db.run_query(
                query,
                {
                    "student_id": semantic.student_id,
                    "concept_id": semantic.concept_id,
                    "semantic_id": semantic.id,
                    "fact": semantic.fact,
                    "confidence": semantic.confidence,
                    "source_session_id": semantic.source_session_id,
                    "created_at": semantic.created_at
                }
            )
            
            return bool(result)
            
        except Exception as e:
            logger.error(f"Semantic node writing error: {str(e)}")
            return False

    async def archive_session_to_memory(self,
                                        student_id: str,
                                        session_id: str,
                                        messages: List[Dict[str, str]],
                                        concept_ids: List[str]) -> Dict[str, Any]:
        """Archive a completed session outside real-time path into memory anchor + semantic facts."""
        try:
            text = "\n".join(m.get("content", "") for m in messages if m.get("content"))
            summary = text[:400] if text else "Session completed with conceptual discussion."

            memory = MemoryAnchor(
                student_id=student_id,
                session_date=datetime.now().isoformat(),
                concepts=concept_ids,
                confidence={cid: 0.5 for cid in concept_ids},
                misconceptions=[],
                summary_text=summary,
            )

            memory_id = self._write_memory_anchor(memory, session_id)
            if not memory_id:
                return {"status": "error", "message": "Failed to persist memory anchor"}

            self._extract_and_create_semantic_nodes(
                student_id=student_id,
                session_id=session_id,
                summary_text=summary,
                concept_ids=concept_ids,
            )

            return {
                "status": "success",
                "memory_id": memory_id,
                "concept_count": len(concept_ids),
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    
    # ==================== Memory Retrieval ====================
    
    def get_student_memories(self, student_id: str) -> List[Dict]:
        """
        Get all memory anchors for a student.
        
        Args:
            student_id: Student user ID
        
        Returns:
            List of memory dicts
        """
        try:
            query = (
                "MATCH (student:User {id: $student_id})-[:HAS_MEMORY]->(mem:MemoryAnchor) "
                "WITH mem "
                "OPTIONAL MATCH (mem)-[:DISCUSSED]->(concept:CONCEPT) "
                "RETURN mem.id as id, mem.session_date as session_date, "
                "       COLLECT(concept.id) as concepts, "
                "       mem.summary_text as summary, "
                "       mem.misconceptions as misconceptions, "
                "       mem.created_at as created_at "
                "ORDER BY mem.created_at DESC"
            )
            
            result = self.graph_manager.db.run_query(
                query,
                {"student_id": student_id}
            )
            
            return result if result else []
            
        except Exception as e:
            logger.warning(f"Memory retrieval error: {str(e)}")
            return []


# ==================== FastAPI Background Task Helper ====================

async def process_old_interactions_background() -> Dict[str, Any]:
    """
    Wrapper function for FastAPI BackgroundTasks.
    
    Usage in app.py:
        background_tasks.add_task(process_old_interactions_background)
    
    Returns:
        Processing result dict
    """
    agent = SummarisationAgent()
    return await agent.process_old_interactions()
