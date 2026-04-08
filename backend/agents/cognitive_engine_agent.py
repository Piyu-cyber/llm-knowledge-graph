"""
OmniProf Cognitive Engine Agent
Post-evaluation agent for updating student knowledge state via Bayesian Knowledge Tracing.

Features:
- Runs after every evaluation interaction
- Reads concept difficulty from RustWorkX graph
- Calls bayesian_update() with student response outcome
- Writes updated theta and slip parameters back to StudentOverlay
"""

import logging
import os
from typing import Optional

from backend.agents.state import AgentState
from backend.services.cognitive_engine import CognitiveEngine
from backend.db.graph_manager import GraphManager

logger = logging.getLogger(__name__)


class CognitiveEngineAgent:
    """
    Cognitive Engine Agent for post-evaluation knowledge state updates.
    
    Runs as a LangGraph node after evaluation interactions.
    
    Workflow:
    1. Identify the concept that was probed
    2. Determine if student response was correct/incorrect
    3. Read concept difficulty from local graph store
    4. Call bayesian_update() to compute new theta and slip
    5. Write updated parameters back to StudentOverlay
    6. Update mastery_probability
    
    This completes the learning assessment loop:
    TA Agent → Student learns → Evaluator Agent → Cognitive Engine Agent → Updated overlay
    """
    
    def __init__(self, data_dir: Optional[str] = None, **kwargs):
        """
        Initialize Cognitive Engine Agent.
        
        Args:
            data_dir: Path to data directory for graph persistence
        """
        from dotenv import load_dotenv
        
        load_dotenv()
        
        # Use GraphManager which uses RustWorkX backend
        self.graph_manager = GraphManager(
            data_dir=data_dir or os.getenv("DATA_DIR", "data")
        )
        
        self.cognitive_engine = CognitiveEngine()
    
    
    # ==================== Main Agent Entry Point ====================
    
    def process(self, state: AgentState) -> AgentState:
        """
        Main entry point for Cognitive Engine Agent as LangGraph node.
        
        This agent runs after Integrity Agent completes evaluation.
        Updates student knowledge state based on evaluation outcomes.
        
        Workflow:
        1. Extract evaluation outcome from metadata
        2. Get probed concepts and student responses
        3. Determine correctness of each response
        4. For each concept:
           a. Read current theta and slip
           b. Read concept difficulty
           c. Call bayesian_update()
           d. Write updated parameters back
        5. Return updated state
        
        Args:
            state: Current agent state (coming from integrity_agent)
        
        Returns:
            Updated agent state with portfolio updated
        """
        try:
            logger.info(f"CognitiveEngineAgent updating knowledge for student {state.student_id}")
            
            # Step 1: Extract evaluation data
            ai_recommended_grade = state.metadata.get("ai_recommended_grade", 0.5)
            eval_transcript = state.eval_state.transcript if hasattr(state, 'eval_state') else []
            
            logger.debug(f"Evaluation grade: {ai_recommended_grade:.2f}")
            
            # Step 2: Identify probed concepts and responses
            probed_concepts = self._extract_probed_concepts(eval_transcript)
            
            if not probed_concepts:
                logger.warning("No concepts identified in evaluation")
                state.active_agent = "cognitive_engine_agent"
                return state
            
            logger.debug(f"Probed concepts: {probed_concepts}")
            
            # Step 3: Determine response correctness
            # Use the recommended grade as a proxy for performance
            # Grade > 0.7 = correct/good responses
            # Grade 0.4-0.7 = partial understanding
            # Grade < 0.4 = incorrect/poor responses
            
            response_quality = ai_recommended_grade
            
            # Step 4: Update overlays for each concept
            for concept_id in probed_concepts:
                try:
                    self._update_concept_state(
                        student_id=state.student_id,
                        concept_id=concept_id,
                        response_quality=response_quality
                    )
                except Exception as e:
                    logger.error(f"Failed to update {concept_id}: {str(e)}")
                    # Continue with other concepts
            
            # Step 5: Mark completion
            state.active_agent = "cognitive_engine_agent"
            state.metadata["knowledge_updated"] = True
            state.metadata["update_timestamp"] = datetime.now().isoformat() if hasattr(datetime, 'now') else ""
            
            logger.info(f"Knowledge state updated for {len(probed_concepts)} concepts")
            
            return state
            
        except Exception as e:
            logger.error(f"CognitiveEngineAgent error: {str(e)}", exc_info=True)
            state.error = str(e)
            state.error_count += 1
            state.active_agent = "cognitive_engine_agent"
            return state
    
    
    # ==================== Concept Extraction ====================
    
    def _extract_probed_concepts(self, transcript: list) -> list:
        """
        Extract concept IDs from evaluation transcript.
        
        The evaluator probes concepts through questions.
        This extracts which concepts were asked about.
        
        Args:
            transcript: Evaluation transcript (list of turn dicts)
        
        Returns:
            List of concept IDs/names discussed
        """
        try:
            concepts = []
            
            # Parse evaluator's probing questions to extract concepts
            for turn in transcript:
                if turn.get("role") == "evaluator":
                    question = turn.get("content", "")
                    
                    # Simple extraction: look for concept mentions
                    # In production, use NLP or LLM
                    if question:
                        # Try to extract from question text
                        # This is a simplified approach
                        words = question.lower().split()
                        
                        # Filter potential concept terms (> 3 chars, not common words)
                        common_words = {"what", "how", "why", "when", "where", "your", "about"}
                        potential_concepts = [
                            w.strip(',.!?;:') for w in words
                            if len(w.strip(',.!?;:')) > 3 and w.strip(',.!?;:') not in common_words
                        ]
                        
                        concepts.extend(potential_concepts)
            
            # Remove duplicates, keep order
            seen = set()
            unique_concepts = []
            for c in concepts:
                if c not in seen:
                    seen.add(c)
                    unique_concepts.append(c)
            
            return unique_concepts[:3] if unique_concepts else []
            
        except Exception as e:
            logger.warning(f"Concept extraction error: {str(e)}")
            return []
    
    
    # ==================== Knowledge State Update ====================
    
    def _update_concept_state(self,
                             student_id: str,
                             concept_id: str,
                             response_quality: float) -> bool:
        """
        Update StudentOverlay for a concept using Bayesian Knowledge Tracing.
        
        Process:
        1. Get or create StudentOverlay (theta, slip)
        2. Read concept difficulty
        3. Determine if response was correct (quality > 0.7)
        4. Call bayesian_update()
        5. Write updated theta and slip back
        6. Recompute mastery probability
        
        Args:
            student_id: Student user ID
            concept_id: Concept ID/name
            response_quality: Indicator of response quality [0, 1]
        
        Returns:
            Success status
        """
        try:
            # Step 1: Get current overlay for this student-concept pair
            overlay = self.graph_manager.get_student_overlay(student_id, concept_id)
            
            # If overlay doesn't exist, create it with defaults
            if not overlay:
                logger.debug(f"Creating new StudentOverlay for {student_id}/{concept_id}")
                result = self.graph_manager.create_student_overlay(
                    user_id=student_id,
                    concept_id=concept_id,
                    theta=0.0,
                    slip=0.1,
                    guess=0.1,
                    visited=False
                )
                if result.get('status') != 'success':
                    logger.warning(f"Failed to create StudentOverlay for {student_id}/{concept_id}")
                    return False
                overlay = self.graph_manager.get_student_overlay(student_id, concept_id)
            
            overlay_id = overlay.get('id')
            current_theta = overlay.get('theta', 0.0)
            current_slip = overlay.get('slip', 0.1)
            
            # Step 2: Get concept difficulty from GraphManager
            concept = self.graph_manager.get_concept_by_id(concept_id)
            concept_difficulty = concept.get('difficulty', -0.5) if concept else -0.5
            
            # Step 3: Determine correctness from response quality
            answered_correctly = response_quality > 0.7
            
            logger.debug(f"Updating {concept_id}: theta={current_theta:.2f}, "
                        f"slip={current_slip:.2f}, correct={answered_correctly}, "
                        f"quality={response_quality:.2f}")
            
            # Step 4: Call bayesian_update
            new_theta, new_slip = self.cognitive_engine.bayesian_update(
                theta=current_theta,
                slip=current_slip,
                difficulty=concept_difficulty,
                answered_correctly=answered_correctly
            )
            
            # Step 5: Recompute mastery probability
            new_mastery = max(0.0, min(1.0, new_theta))
            
            # Step 6: Update the overlay using GraphManager update_student_overlay
            result = self.graph_manager.update_student_overlay(
                overlay_id,
                updates={
                    'theta': new_theta,
                    'slip': new_slip,
                    'mastery_probability': new_mastery
                }
            )
            
            if result.get('status') == 'success':
                logger.info(f"Updated {concept_id}: "
                           f"theta {current_theta:.2f}→{new_theta:.2f}, "
                           f"slip {current_slip:.3f}→{new_slip:.3f}, "
                           f"mastery {current_theta:.2f}→{new_mastery:.2f}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Concept state update error: {str(e)}")
            return False


from datetime import datetime
