"""
OmniProf Gamification Agent
LangGraph node for awarding achievement badges and tracking progress.

Features:
- Checks milestone conditions after every sub-agent response
- Awards badges: Explorer, Mastery, Module Complete
- Writes Achievement nodes to Neo4j
- Achievements are private (not visible to other students)
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass, field

from backend.agents.state import AgentState
from backend.db.neo4j_driver import Neo4jGraphManager

logger = logging.getLogger(__name__)


@dataclass
class Achievement:
    """Represents a single achievement/badge earned by student"""
    student_id: str
    achievement_type: str  # "explorer" | "mastery" | "module_complete"
    concept_id: Optional[str] = None
    module_id: Optional[str] = None
    earned_at: str = field(default_factory=lambda: datetime.now().isoformat())
    achievement_id: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Convert to serializable dict"""
        return {
            "student_id": self.student_id,
            "achievement_type": self.achievement_type,
            "concept_id": self.concept_id,
            "module_id": self.module_id,
            "earned_at": self.earned_at,
            "achievement_id": self.achievement_id
        }


class GamificationAgent:
    """
    Gamification Agent for tracking student achievements.
    
    Runs as a LangGraph node after every sub-agent response.
    Checks milestone conditions and awards badges.
    
    Milestone Conditions:
    1. Explorer: First concept visited in a module
    2. Mastery: mastery_probability > 0.8 on any concept
    3. Module Complete: All concepts in a module completed
    
    All achievements are stored in Neo4j and are private per student.
    """
    
    def __init__(self, neo4j_uri: Optional[str] = None,
                 neo4j_user: Optional[str] = None,
                 neo4j_password: Optional[str] = None):
        """
        Initialize Gamification Agent.
        
        Args:
            neo4j_uri: Neo4j database URI
            neo4j_user: Neo4j username
            neo4j_password: Neo4j password
        """
        import os
        from dotenv import load_dotenv
        
        load_dotenv()
        
        self.graph_manager = Neo4jGraphManager(
            uri=neo4j_uri or os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            user=neo4j_user or os.getenv("NEO4J_USER", "neo4j"),
            password=neo4j_password or os.getenv("NEO4J_PASSWORD", "password")
        )
    
    
    # ==================== Main Agent Entry Point ====================
    
    def process(self, state: AgentState) -> AgentState:
        """
        Main entry point for Gamification Agent as LangGraph node.
        
        Runs after each sub-agent response to check milestone conditions
        and award achievements.
        
        Args:
            state: Current agent state
        
        Returns:
            Updated agent state with new achievements in metadata
        """
        try:
            logger.info(f"GamificationAgent checking milestones for {state.student_id}")
            
            # Get current achievements count
            current_achievements = state.metadata.get("achievements", [])
            
            # Check each milestone type
            new_achievements = []
            
            # Check Explorer milestone
            explorer = self._check_explorer_milestone(state.student_id)
            if explorer:
                new_achievements.append(explorer)
            
            # Check Mastery milestone
            mastery_achievements = self._check_mastery_milestone(state.student_id)
            new_achievements.extend(mastery_achievements)
            
            # Check Module Complete milestone
            module_complete = self._check_module_complete_milestone(state.student_id)
            if module_complete:
                new_achievements.append(module_complete)
            
            # Write achievements to Neo4j
            for achievement in new_achievements:
                self._write_achievement(achievement)
                logger.info(f"Achievement awarded: {achievement.achievement_type} "
                           f"to {state.student_id}")
            
            # Update state
            state.metadata["achievements"] = current_achievements + new_achievements
            state.metadata["new_achievements_count"] = len(new_achievements)
            state.active_agent = "gamification_agent"
            
            logger.debug(f"Gamification: {len(new_achievements)} new achievements")
            
            return state
            
        except Exception as e:
            logger.error(f"GamificationAgent error: {str(e)}", exc_info=True)
            state.error = str(e)
            state.error_count += 1
            return state
    
    
    # ==================== Milestone Checks ====================
    
    def _check_explorer_milestone(self, student_id: str) -> Optional[Achievement]:
        """
        Check Explorer milestone: First concept visited in a module.
        
        Triggers when student first interacts with ANY concept
        in a module they haven't visited before.
        
        Args:
            student_id: Student user ID
        
        Returns:
            Achievement if new explorer badge, None otherwise
        """
        try:
            # Find modules where student has visited at least one concept
            # but hasn't earned explorer badge yet
            query = (
                "MATCH (student:User {id: $student_id}) "
                "MATCH (module:MODULE)-[:CONTAINS]->(concept:CONCEPT) "
                "MATCH (overlay:StudentOverlay {user_id: $student_id, concept_id: concept.id}) "
                "WHERE overlay.visited = true "
                "AND NOT EXISTS("
                "  MATCH (student)-[:EARNED]->(ach:Achievement "
                "       {achievement_type: 'explorer', module_id: module.id}) "
                ") "
                "RETURN DISTINCT module.id as module_id, module.name as module_name "
                "LIMIT 1"
            )
            
            result = self.graph_manager.db.run_query(
                query,
                {"student_id": student_id}
            )
            
            if result:
                module_id = result[0].get("module_id")
                return Achievement(
                    student_id=student_id,
                    achievement_type="explorer",
                    module_id=module_id,
                    concept_id=None
                )
            
            return None
            
        except Exception as e:
            logger.warning(f"Explorer milestone check error: {str(e)}")
            return None
    
    
    def _check_mastery_milestone(self, student_id: str) -> List[Achievement]:
        """
        Check Mastery milestone: mastery_probability > 0.8 on any concept.
        
        Awards one badge per concept mastered.
        
        Args:
            student_id: Student user ID
        
        Returns:
            List of Achievement objects for newly mastered concepts
        """
        try:
            # Find concepts with mastery > 0.8 but no mastery badge yet
            query = (
                "MATCH (student:User {id: $student_id}) "
                "MATCH (overlay:StudentOverlay {user_id: $student_id}) "
                "WHERE overlay.mastery_probability > 0.8 "
                "AND NOT EXISTS("
                "  MATCH (student)-[:EARNED]->(ach:Achievement "
                "       {achievement_type: 'mastery', concept_id: overlay.concept_id}) "
                ") "
                "RETURN overlay.concept_id as concept_id "
                "LIMIT 10"
            )
            
            result = self.graph_manager.db.run_query(
                query,
                {"student_id": student_id}
            )
            
            achievements = []
            for row in result:
                concept_id = row.get("concept_id")
                achievements.append(Achievement(
                    student_id=student_id,
                    achievement_type="mastery",
                    concept_id=concept_id,
                    module_id=None
                ))
            
            return achievements
            
        except Exception as e:
            logger.warning(f"Mastery milestone check error: {str(e)}")
            return []
    
    
    def _check_module_complete_milestone(self, student_id: str) -> Optional[Achievement]:
        """
        Check Module Complete milestone: All concepts in module completed.
        
        Module is "completed" when ALL concepts have mastery_probability >= 0.7.
        
        Args:
            student_id: Student user ID
        
        Returns:
            Achievement if module newly completed, None otherwise
        """
        try:
            # Find all modules and check completion
            query = (
                "MATCH (module:MODULE)-[:CONTAINS]->(concept:CONCEPT) "
                "WITH module, COUNT(concept) as total_concepts "
                "MATCH (module)-[:CONTAINS]->(c:CONCEPT) "
                "MATCH (overlay:StudentOverlay {user_id: $student_id, concept_id: c.id}) "
                "WHERE overlay.mastery_probability >= 0.7 "
                "WITH module, total_concepts, COUNT(overlay) as mastered_concepts "
                "WHERE mastered_concepts = total_concepts "
                "AND NOT EXISTS("
                "  MATCH (student:User {id: $student_id})-[:EARNED]->(ach:Achievement "
                "       {achievement_type: 'module_complete', module_id: module.id}) "
                ") "
                "RETURN module.id as module_id "
                "LIMIT 1"
            )
            
            result = self.graph_manager.db.run_query(
                query,
                {"student_id": student_id}
            )
            
            if result:
                module_id = result[0].get("module_id")
                return Achievement(
                    student_id=student_id,
                    achievement_type="module_complete",
                    module_id=module_id,
                    concept_id=None
                )
            
            return None
            
        except Exception as e:
            logger.warning(f"Module complete milestone check error: {str(e)}")
            return None
    
    
    # ==================== Achievement Writing ====================
    
    def _write_achievement(self, achievement: Achievement) -> bool:
        """
        Write Achievement node to Neo4j.
        
        Creates an Achievement node linked to the student.
        Achievements are private - only visible to that student.
        
        Args:
            achievement: Achievement instance
        
        Returns:
            Success status
        """
        try:
            import uuid
            achievement.achievement_id = str(uuid.uuid4())[:12]
            
            # Create achievement node and link to student
            query = (
                "MATCH (student:User {id: $student_id}) "
                "CREATE (ach:Achievement {"
                "  id: $achievement_id,"
                "  achievement_type: $achievement_type,"
                "  concept_id: $concept_id,"
                "  module_id: $module_id,"
                "  earned_at: $earned_at,"
                "  private: true"
                "}) "
                "CREATE (student)-[:EARNED]->(ach) "
                "RETURN ach"
            )
            
            result = self.graph_manager.db.run_query(
                query,
                {
                    "student_id": achievement.student_id,
                    "achievement_id": achievement.achievement_id,
                    "achievement_type": achievement.achievement_type,
                    "concept_id": achievement.concept_id,
                    "module_id": achievement.module_id,
                    "earned_at": achievement.earned_at
                }
            )
            
            if result:
                logger.info(f"Achievement written: {achievement.achievement_id}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Achievement writing error: {str(e)}")
            return False
    
    
    # ==================== Achievement Retrieval ====================
    
    def get_student_achievements(self, student_id: str) -> List[Dict]:
        """
        Get all achievements for a student (private).
        
        Args:
            student_id: Student user ID
        
        Returns:
            List of achievement dicts
        """
        try:
            query = (
                "MATCH (student:User {id: $student_id})-[:EARNED]->(ach:Achievement) "
                "RETURN ach.id as id, ach.achievement_type as type, "
                "       ach.concept_id as concept_id, ach.module_id as module_id, "
                "       ach.earned_at as earned_at "
                "ORDER BY ach.earned_at DESC"
            )
            
            result = self.graph_manager.db.run_query(
                query,
                {"student_id": student_id}
            )
            
            return result if result else []
            
        except Exception as e:
            logger.warning(f"Achievement retrieval error: {str(e)}")
            return []
