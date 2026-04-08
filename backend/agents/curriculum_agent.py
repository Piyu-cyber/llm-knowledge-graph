"""
OmniProf Curriculum Agent
Background task agent for propagating curriculum changes to student overlays.

Features:
- Triggered when professor adds/removes/reweights knowledge graph nodes
- Propagates changes to all active StudentOverlay nodes for that course
- Re-weights adjacent edges based on professor-defined learning path
- Runs as FastAPI BackgroundTask (non-blocking)
"""

import logging
import os
import asyncio
from typing import Dict, List, Optional
from datetime import datetime

from backend.db.graph_manager import GraphManager
from backend.services.graph_service import GraphService

logger = logging.getLogger(__name__)


class CurriculumAgent:
    """
    Curriculum Change Propagation Agent.
    
    When professors modify the curriculum graph (add/remove/reweight nodes),
    this agent propagates those changes to all active student overlays.
    
    Workflow:
    1. Detect curriculum change (node add/remove/reweight)
    2. Find all StudentOverlay nodes for affected course
    3. For each overlay:
       - Update visibility/importance weights
       - Re-weight prerequisite edges
       - Update mastery thresholds if needed
    4. Log changes for audit trail
    
    Runs as background task to avoid blocking professor's update.
    """
    
    def __init__(self, data_dir: Optional[str] = None, **kwargs):
        """
        Initialize Curriculum Agent.
        
        Args:
            data_dir: Path to data directory for graph persistence
        """
        from dotenv import load_dotenv
        
        load_dotenv()
        
        # Use GraphManager which uses RustWorkX backend
        self.graph_manager = GraphManager(
            data_dir=data_dir or os.getenv("DATA_DIR", "data")
        )
        
        self.graph_service = GraphService(self.graph_manager)
    
    
    # ==================== Main Entry Point ====================
    
    async def process_curriculum_change(self,
                                       course_id: str,
                                       change_type: str,
                                       node_id: str,
                                       node_type: str,
                                       metadata: Optional[Dict] = None) -> Dict:
        """
        Process a curriculum change and propagate to student overlays.
        
        This is designed to run as a FastAPI BackgroundTask.
        
        Args:
            course_id: Course ID affected by change
            change_type: "add" | "remove" | "reweight"
            node_id: Node ID that changed
            node_type: "CONCEPT" | "TOPIC" | "MODULE"
            metadata: Optional metadata like new_weight, new_difficulty, etc.
        
        Returns:
            Dict with change summary and affected student count
        """
        try:
            logger.info(f"Processing curriculum change: {change_type} {node_type} {node_id}")
            
            # Step 1: Get all StudentOverlay nodes for this course
            student_overlays = self._get_course_student_overlays(course_id)
            logger.debug(f"Found {len(student_overlays)} student overlays for course {course_id}")
            
            # Step 2: Process change based on type
            affected_count = 0
            
            if change_type == "add":
                affected_count = await self._handle_node_added(
                    course_id, node_id, node_type, student_overlays, metadata or {}
                )
            
            elif change_type == "remove":
                affected_count = await self._handle_node_removed(
                    course_id, node_id, node_type, student_overlays, metadata or {}
                )
            
            elif change_type == "reweight":
                affected_count = await self._handle_node_reweighted(
                    course_id, node_id, node_type, student_overlays, metadata or {}
                )
            
            logger.info(f"Curriculum change processed: affected {affected_count} students")
            
            return {
                "status": "success",
                "change_type": change_type,
                "node_id": node_id,
                "course_id": course_id,
                "affected_students": affected_count,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Curriculum change processing error: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    
    # ==================== Change Handlers ====================
    
    async def _handle_node_added(self,
                                course_id: str,
                                node_id: str,
                                node_type: str,
                                student_overlays: List[Dict],
                                metadata: Dict) -> int:
        """
        Handle addition of a new curriculum node.
        
        When professor adds a new concept/topic/module:
        1. Create StudentOverlay entries (if CONCEPT)
        2. Update prerequisite chains
        3. Initialize mastery = 0.5
        
        Args:
            course_id: Affected course
            node_id: New node ID
            node_type: Node type
            student_overlays: List of affected StudentOverlay dicts
            metadata: Node metadata (difficulty, importance, etc.)
        
        Returns:
            Count of students affected
        """
        try:
            affected_count = 0
            
            if node_type == "CONCEPT":
                # Get enrolled students and create StudentOverlay for each
                enrolled_students = self.graph_manager.get_enrolled_students(course_id)
                
                for student_id in enrolled_students:
                    # Create StudentOverlay using GraphManager method
                    # This method already handles the "if missing" case
                    result = self.graph_manager.create_student_overlay(
                        user_id=student_id,
                        concept_id=node_id,
                        theta=0.0,
                        slip=0.1,
                        guess=0.1,
                        visited=False
                    )
                    if result.get('status') == 'success':
                        affected_count += 1
                        logger.debug(f"Created StudentOverlay for {student_id}/{node_id}")
            
            elif node_type in ["TOPIC", "MODULE"]:
                # For topics/modules, update existing prerequisites
                # Get child concepts and update their mastery thresholds
                pass
            
            return affected_count
            
        except Exception as e:
            logger.error(f"Node addition handler error: {str(e)}")
            return 0
    
    
    async def _handle_node_removed(self,
                                  course_id: str,
                                  node_id: str,
                                  node_type: str,
                                  student_overlays: List[Dict],
                                  metadata: Dict) -> int:
        """
        Handle removal of a curriculum node.
        
        When professor removes a node:
        1. Remove StudentOverlay entries (if CONCEPT)
        2. Update prerequisite chains
        3. Recompute dependent mastery thresholds
        
        Args:
            course_id: Affected course
            node_id: Removed node ID
            node_type: Node type
            student_overlays: List of affected StudentOverlay dicts
            metadata: Node metadata
        
        Returns:
            Count of students affected
        """
        try:
            affected_count = 0
            
            if node_type == "CONCEPT":
                # Remove StudentOverlay entries for all enrolled students
                enrolled_students = self.graph_manager.get_enrolled_students(course_id)
                
                for student_id in enrolled_students:
                    # Use GraphManager method to remove overlay
                    result = self.graph_manager.remove_student_overlay(student_id, node_id)
                    if result.get('status') == 'success':
                        affected_count += 1
                        logger.debug(f"Removed StudentOverlay for {student_id}/{node_id}")
                
                logger.debug(f"Removed StudentOverlay entries for {node_id}")
            
            return affected_count
            
        except Exception as e:
            logger.error(f"Node removal handler error: {str(e)}")
            return 0
    
    
    async def _handle_node_reweighted(self,
                                     course_id: str,
                                     node_id: str,
                                     node_type: str,
                                     student_overlays: List[Dict],
                                     metadata: Dict) -> int:
        """
        Handle reweighting of curriculum edges (learning path priority).
        
        When professor reweights edges (changes learning path order):
        1. Update edge weights in graph
        2. Recalculate difficulty for dependent concepts
        3. Update prerequisite mastery estimates
        
        Args:
            course_id: Affected course
            node_id: Node whose edges changed
            node_type: Node type
            student_overlays: List of affected StudentOverlay dicts
            metadata: New weights {"edge_id": new_weight, ...}
        
        Returns:
            Count of affected students
        """
        try:
            affected_count = 0
            
            # Update edge weights using GraphManager
            edge_updates = metadata.get("edges", {})
            
            for edge_id, new_weight in edge_updates.items():
                # Add or update prerequisite edge
                self.graph_manager.add_prerequisite(
                    concept_id=node_id,
                    prerequisite_id=edge_id,
                    weight=new_weight
                )
                affected_count = len(self.graph_manager.get_enrolled_students(course_id))
                logger.debug(f"Updated edge weight for {node_id}")
            
            return affected_count
            
        except Exception as e:
            logger.error(f"Node reweighting handler error: {str(e)}")
            return 0
    
    
    # ==================== Utility Methods ====================
    
    def _get_course_student_overlays(self, course_id: str) -> List[Dict]:
        """
        Get all enrolled students for a course.
        
        Returns list of student dicts for easy iteration
        in change handlers.
        
        Args:
            course_id: Course ID
        
        Returns:
            List of dicts with student_id (user_id)
        """
        try:
            # Get all enrolled students in this course
            enrolled_students = self.graph_manager.get_enrolled_students(course_id)
            
            # Return as list of dicts for easy access
            return [{"user_id": student_id} for student_id in enrolled_students]
            
        except Exception as e:
            logger.warning(f"Course student overlay retrieval error: {str(e)}")
            return []


# Background task helper for FastAPI integration
async def process_curriculum_change_background(
    course_id: str,
    change_type: str,
    node_id: str,
    node_type: str,
    metadata: Optional[Dict] = None
) -> Dict:
    """
    Wrapper function for FastAPI BackgroundTasks.
    
    Usage in FastAPI:
    ```python
    from fastapi import BackgroundTasks
    
    @app.post("/curriculum/modify")
    async def modify_curriculum(request: CurriculumModifyRequest,
                               background_tasks: BackgroundTasks):
        # Apply change immediately
        graph_service.modify_node(request.node_id, request.changes)
        
        # Schedule background propagation
        agent = CurriculumAgent()
        background_tasks.add_task(
            process_curriculum_change_background,
            course_id=request.course_id,
            change_type=request.change_type,
            node_id=request.node_id,
            node_type=request.node_type,
            metadata=request.metadata
        )
        
        return {"status": "change applied, propagating to students"}
    ```
    """
    agent = CurriculumAgent()
    return await agent.process_curriculum_change(
        course_id=course_id,
        change_type=change_type,
        node_id=node_id,
        node_type=node_type,
        metadata=metadata
    )
