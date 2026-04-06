"""
OmniProf Summarisation Agent
Background task for creating memory anchors from old interactions.

Features:
- Creates memory anchors for interactions >= 7 days old
- Runs as FastAPI background task (non-blocking)
- Generates LLM-based summaries of interactions
- Links memories to concepts for future context retrieval
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import json

from backend.agents.state import AgentState
from backend.db.neo4j_driver import Neo4jGraphManager
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
    
    def __init__(self, neo4j_uri: Optional[str] = None,
                 neo4j_user: Optional[str] = None,
                 neo4j_password: Optional[str] = None,
                 groq_api_key: Optional[str] = None):
        """
        Initialize Summarisation Agent.
        
        Args:
            neo4j_uri: Neo4j database URI
            neo4j_user: Neo4j username
            neo4j_password: Neo4j password
            groq_api_key: Groq API key for LLM
        """
        import os
        from dotenv import load_dotenv
        
        load_dotenv()
        
        self.graph_manager = Neo4jGraphManager(
            uri=neo4j_uri or os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            user=neo4j_user or os.getenv("NEO4J_USER", "neo4j"),
            password=neo4j_password or os.getenv("NEO4J_PASSWORD", "password")
        )
        
        self.llm_service = LLMService(
            api_key=groq_api_key or os.getenv("GROQ_API_KEY")
        )
    
    
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
        
        Groups interactions by (student, session) for summarization.
        
        Args:
            cutoff_date: ISO timestamp cutoff (older than this)
        
        Returns:
            List of interaction dicts grouped by session
        """
        try:
            query = (
                "MATCH (student:User)-[r:HAS_INTERACTION]->(session:Session) "
                "WHERE session.created_at < $cutoff_date "
                "AND NOT EXISTS("
                "  MATCH (session)-[:SUMMARIZED_TO]->(mem:MemoryAnchor) "
                ") "
                "RETURN DISTINCT student.id as student_id, "
                "       session.id as session_id, "
                "       session.created_at as session_date "
                "ORDER BY session.created_at DESC"
            )
            
            result = self.graph_manager.db.run_query(
                query,
                {"cutoff_date": cutoff_date}
            )
            
            return result if result else []
            
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
                return memory_id
            
            return None
            
        except Exception as e:
            logger.error(f"Interaction processing error: {str(e)}")
            return None
    
    
    def _extract_session_metadata(self, student_id: str, session_id: str) -> tuple:
        """
        Extract concepts, confidence levels, and misconceptions from session.
        
        Args:
            student_id: Student ID
            session_id: Session ID
        
        Returns:
            Tuple of (concepts, confidence_dict, misconceptions)
        """
        try:
            # Get concepts discussed and confidence in this session
            query = (
                "MATCH (sessions:Session {id: $session_id}) "
                "MATCH (sessions)-[:DISCUSSED]->(concept:CONCEPT) "
                "MATCH (overlay:StudentOverlay {user_id: $student_id, concept_id: concept.id}) "
                "RETURN concept.id as concept_id, "
                "       concept.name as concept_name, "
                "       overlay.mastery_probability as confidence "
                "ORDER BY concept.id"
            )
            
            result = self.graph_manager.db.run_query(
                query,
                {"student_id": student_id, "session_id": session_id}
            )
            
            concepts = []
            confidence = {}
            
            for row in result:
                concept_id = row.get("concept_id")
                conf = row.get("confidence") or 0.0
                concepts.append(concept_id)
                confidence[concept_id] = conf
            
            # Extract misconceptions from evaluator notes
            misconceptions = self._get_session_misconceptions(student_id, session_id)
            
            return concepts, confidence, misconceptions
            
        except Exception as e:
            logger.warning(f"Metadata extraction error: {str(e)}")
            return [], {}, []
    
    
    def _get_session_misconceptions(self, student_id: str, session_id: str) -> List[str]:
        """
        Extract misconceptions from evaluation records in session.
        
        Args:
            student_id: Student ID
            session_id: Session ID
        
        Returns:
            List of misconception strings
        """
        try:
            query = (
                "MATCH (session:Session {id: $session_id}) "
                "MATCH (session)-[:CONTAINS]->(record:DefenceRecord) "
                "WHERE record.student_id = $student_id "
                "AND record.ai_feedback CONTAINS 'misconception' "
                "RETURN record.ai_feedback as feedback"
            )
            
            result = self.graph_manager.db.run_query(
                query,
                {"student_id": student_id, "session_id": session_id}
            )
            
            misconceptions = []
            for row in result:
                feedback = row.get("feedback", "")
                if "misconception" in feedback.lower():
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
