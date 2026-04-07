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
import os
from typing import Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass, field

from backend.agents.state import AgentState
from backend.db.graph_manager import GraphManager

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
    
    def __init__(self, data_dir: Optional[str] = None):
        """
        Initialize Gamification Agent.
        
        Args:
            data_dir: Path to data directory for graph persistence
        """
        from dotenv import load_dotenv
        
        load_dotenv()
        
        # Use GraphManager which uses RustWorkX backend
        self.graph_manager = GraphManager(
            data_dir=data_dir or os.getenv("DATA_DIR", "data")
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
            # Get all overlays for this student and find visited modules
            overlays = self.graph_manager.get_all_student_overlays(student_id)
            visited_modules = {}
            
            for overlay in overlays:
                if not overlay.get('visited'):
                    continue
                
                concept_id = overlay.get('concept_id')
                if not concept_id:
                    continue
                
                # Navigate to module via concept -> topic -> module  
                concept = self.graph_manager.get_concept_by_id(concept_id)
                if not concept:
                    continue
                
                topic_id = concept.get('topic_id')
                if not topic_id:
                    continue
                
                topic = self.graph_manager.get_node_by_id(topic_id)
                if not topic:
                    continue
                
                module_id = topic.get('module_id')
                if module_id and not self.graph_manager.has_achievement(
                    student_id, 'explorer', module_id=module_id
                ):
                    visited_modules[module_id] = topic.get('name', 'Module')
            
            # Return first unearned explorer badge
            if visited_modules:
                module_id = list(visited_modules.keys())[0]
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
            # Get all overlays and find those with mastery > 0.8 but no badge yet
            overlays = self.graph_manager.get_all_student_overlays(student_id)
            achievements = []
            
            for overlay in overlays:
                mastery = overlay.get('mastery_probability', 0.0)
                if mastery <= 0.8:
                    continue
                
                concept_id = overlay.get('concept_id')
                if not concept_id:
                    continue
                
                # Check if already has mastery badge for this concept
                if not self.graph_manager.has_achievement(
                    student_id, 'mastery', concept_id=concept_id
                ):
                    achievements.append(Achievement(
                        student_id=student_id,
                        achievement_type="mastery",
                        concept_id=concept_id,
                        module_id=None
                    ))
            
            return achievements[:10]  # Limit to 10 per call
            
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
            # Find modules where all concepts are mastered (>= 0.7)
            overlays = self.graph_manager.get_all_student_overlays(student_id)
            
            # Group overlays by module
            module_concepts = {}  # module_id -> {concept_id -> mastery}
            
            for overlay in overlays:
                concept_id = overlay.get('concept_id')
                if not concept_id:
                    continue
                
                concept = self.graph_manager.get_concept_by_id(concept_id)
                if not concept:
                    continue
                
                topic_id = concept.get('topic_id')
                if not topic_id:
                    continue
                
                topic = self.graph_manager.get_node_by_id(topic_id)
                if not topic:
                    continue
                
                module_id = topic.get('module_id')
                if not module_id:
                    continue
                
                if module_id not in module_concepts:
                    module_concepts[module_id] = {}
                
                mastery = overlay.get('mastery_probability', 0.0)
                module_concepts[module_id][concept_id] = mastery
            
            # Check which modules are fully mastered
            for module_id, concept_masteries in module_concepts.items():
                all_mastered = all(
                    mastery >= 0.7 
                    for mastery in concept_masteries.values()
                )
                
                if all_mastered and not self.graph_manager.has_achievement(
                    student_id, 'module_complete', module_id=module_id
                ):
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
            achievement_id = str(uuid.uuid4())[:12]
            
            # Create achievement in GraphManager
            result = self.graph_manager.create_achievement(
                achievement.student_id,
                {
                    'id': achievement_id,
                    'achievement_type': achievement.achievement_type,
                    'concept_id': achievement.concept_id,
                    'module_id': achievement.module_id,
                    'earned_at': achievement.earned_at,
                    'private': True
                }
            )
            
            if result.get('status') == 'success':
                logger.info(f"Achievement written: {achievement_id}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Achievement writing error: {str(e)}")
            return False
    
    
    # ==================== Achievement Retrieval ====================
    
    def get_student_achievements(self, student_id: str) -> List[Dict]:
        """
        Get all achievements for a student (private).
        
        Uses GraphManager to retrieve achievements from JSON persistence.
        
        Args:
            student_id: Student user ID
        
        Returns:
            List of achievement dicts sorted by earned_at (newest first)
        """
        try:
            # Use GraphManager method to get student achievements
            achievements = self.graph_manager.get_student_achievements(student_id)
            
            # Sort by earned_at descending (newest first)
            return sorted(
                achievements,
                key=lambda x: x.get('earned_at', ''),
                reverse=True
            )
            
        except Exception as e:
            logger.warning(f"Achievement retrieval error: {str(e)}")
            return []
