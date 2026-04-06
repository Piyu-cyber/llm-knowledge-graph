"""
OmniProf v3.0 — Cognitive Engine
Bayesian Knowledge Tracing (BKT) using IRT 2-parameter logistic model
Updates student knowledge state (theta) based on interactions
"""

import logging
import math
from typing import Dict, Tuple, Optional
from backend.db.neo4j_driver import Neo4jGraphManager
from backend.db.neo4j_schema import StudentOverlay

logger = logging.getLogger(__name__)


class CognitiveEngine:
    """
    Bayesian Knowledge Tracing using IRT 2-parameter logistic model.
    
    Updates student knowledge states based on interaction responses.
    Distinguishes between Slip (careless error despite knowledge) and 
    Knowledge Gap (lack of understanding).
    """
    
    def __init__(self):
        self.graph = Neo4jGraphManager()
        
        # IRT Model Parameters
        self.discrimination_a = 1.7  # Standard discrimination value
        self.min_theta = -4.0        # Lower bound for ability
        self.max_theta = 4.0         # Upper bound for ability
        
        # Bayesian Update Parameters
        self.learning_rate = 0.15    # How much to adjust theta per interaction
        self.slip_threshold = 0.05   # If P(slip) > this, classify as slip
        self.mastery_threshold = 0.8  # Prerequisite mastery for slip classification
    
    
    # ==================== IRT Model ====================
    
    def irt_probability(self, theta: float, difficulty: float) -> float:
        """
        Calculate probability of correct response using IRT 2-parameter logistic model.
        
        P(θ) = 1 / (1 + exp(-a * (θ - b)))
        
        Args:
            theta: Student ability parameter (knowledge state) [-4, 4]
            difficulty: Item difficulty parameter [-4, 4]
        
        Returns:
            Probability of correct response [0, 1]
        """
        try:
            exponent = -self.discrimination_a * (theta - difficulty)
            # Clamp exponent to prevent overflow
            exponent = max(-500, min(500, exponent))
            probability = 1.0 / (1.0 + math.exp(exponent))
            return max(0.0, min(1.0, probability))
        except Exception as e:
            logger.warning(f"IRT calculation error: {str(e)}, returning 0.5")
            return 0.5
    
    
    def irt_information(self, theta: float, difficulty: float) -> float:
        """
        Calculate Fisher Information for IRT model (how informative this item is).
        
        I(θ) = a² * P(θ) * (1 - P(θ))
        
        Higher information = item better differentiates at this ability level.
        """
        p = self.irt_probability(theta, difficulty)
        information = self.discrimination_a ** 2 * p * (1 - p)
        return max(0.0, information)
    
    
    # ==================== Bayesian Update ====================
    
    def bayesian_update(
        self,
        theta: float,
        slip: float,
        difficulty: float,
        answered_correctly: bool
    ) -> Tuple[float, float]:
        """
        Update student knowledge state using Bayesian update rule.
        
        Args:
            theta: Current knowledge state (ability parameter) [-4, 4]
            slip: Current slip probability [0, 1]
            difficulty: Concept difficulty (relative to student ability) [-4, 4]
            answered_correctly: Whether student answered correctly
        
        Returns:
            (new_theta, new_slip): Updated knowledge parameters
        """
        try:
            # Clamp inputs
            theta = max(self.min_theta, min(self.max_theta, theta))
            slip = max(0.0, min(1.0, slip))
            difficulty = max(self.min_theta, min(self.max_theta, difficulty))
            
            # Get probability of correct response at current theta
            p_correct = self.irt_probability(theta, difficulty)
            
            # Fisher Information (how informative is this item)
            info = self.irt_information(theta, difficulty)
            
            if answered_correctly:
                # ========== CORRECT RESPONSE ==========
                # Update theta: increase towards mastery
                # Magnitude depends on:
                # 1. How unexpected the correct answer was (lower P → bigger boost)
                # 2. Information value of the item at this level
                
                surprise = (1.0 - p_correct) * info / max(1.0, info)
                theta_adjustment = self.learning_rate * surprise
                new_theta = theta + theta_adjustment
                
                # Slip slightly decreases on success (we're less likely to slip)
                new_slip = slip * 0.95
                
                logger.debug(
                    f"Correct response: theta {theta:.2f} → {new_theta:.2f}, "
                    f"slip {slip:.3f} → {new_slip:.3f}"
                )
                
            else:
                # ========== INCORRECT RESPONSE ==========
                # Check if this is a slip or knowledge gap (handled by caller)
                # Here we just apply the incorrect update
                
                surprise = p_correct * info / max(1.0, info)
                theta_adjustment = -self.learning_rate * surprise
                new_theta = theta + theta_adjustment
                
                # Slip increases slightly on failure
                new_slip = slip * 1.10
                
                logger.debug(
                    f"Incorrect response: theta {theta:.2f} → {new_theta:.2f}, "
                    f"slip {slip:.3f} → {new_slip:.3f}"
                )
            
            # Clamp outputs to valid ranges
            new_theta = max(self.min_theta, min(self.max_theta, new_theta))
            new_slip = max(0.0, min(1.0, new_slip))
            
            return new_theta, new_slip
        
        except Exception as e:
            logger.error(f"Bayesian update error: {str(e)}")
            return theta, slip
    
    
    # ==================== Slip Event Detection ====================
    
    def is_slip_event(
        self,
        user_id: str,
        concept_id: str,
        theta: float,
        current_slip: float
    ) -> bool:
        """
        Detect if an incorrect response is a Slip (careless error) vs Knowledge Gap.
        
        Slip Event: Student has mastered all prerequisites (mastery > 0.8)
        but failed current item. Indicates careless error, not lack of knowledge.
        
        Args:
            user_id: Student user ID
            concept_id: Concept attempted
            theta: Student's knowledge state
            current_slip: Current slip probability
        
        Returns:
            True if classified as slip, False if knowledge gap
        """
        try:
            # Get all prerequisite concepts for this concept
            query = (
                "MATCH (c:CONCEPT {id: $concept_id})-[:REQUIRES*]->(prereq:CONCEPT) "
                "RETURN prereq.id as prereq_id"
            )
            result = self.graph.db.run_query(query, {"concept_id": concept_id})
            
            if not result:
                # No prerequisites, can't be a slip without prior mastery
                return False
            
            prereq_ids = [r.get("prereq_id") for r in result if r.get("prereq_id")]
            
            if not prereq_ids:
                return False
            
            # Check mastery of all prerequisites
            all_mastered = True
            for prereq_id in prereq_ids:
                # Get student's overlay for this prerequisite
                overlay_query = (
                    "MATCH (s:StudentOverlay {user_id: $user_id, concept_id: $concept_id}) "
                    "RETURN s.mastery_probability as mastery"
                )
                overlay_result = self.graph.db.run_query(
                    overlay_query,
                    {"user_id": user_id, "concept_id": prereq_id}
                )
                
                if overlay_result:
                    mastery = overlay_result[0].get("mastery", 0.0)
                    if mastery <= self.mastery_threshold:
                        all_mastered = False
                        break
                else:
                    # No overlay for prerequisite, can't determine mastery
                    all_mastered = False
                    break
            
            # Slip event if all prerequisites mastered but student failed
            is_slip = all_mastered and current_slip > self.slip_threshold
            
            logger.info(
                f"Slip detection for {user_id}/{concept_id}: "
                f"all_mastered={all_mastered}, "
                f"slip_prob={current_slip:.3f}, "
                f"classified_as={'SLIP' if is_slip else 'KNOWLEDGE_GAP'}"
            )
            
            return is_slip
        
        except Exception as e:
            logger.error(f"Slip event detection error: {str(e)}")
            return False
    
    
    # ==================== Student Overlay Update ====================
    
    def update_student_overlay(
        self,
        user_id: str,
        concept_id: str,
        answered_correctly: bool,
        difficulty: Optional[float] = None
    ) -> Dict:
        """
        Record a student interaction and update their knowledge state.
        
        Workflow:
        1. Read current StudentOverlay (theta, slip)
        2. Estimate concept difficulty from prerequisites
        3. Check for slip vs knowledge gap (if incorrect)
        4. Apply Bayesian update
        5. Update StudentOverlay in Neo4j
        6. Update mastery probability
        
        Args:
            user_id: Student user ID
            concept_id: Concept attempted
            answered_correctly: Whether response was correct
            difficulty: Optional explicit difficulty (else estimated from prerequisites)
        
        Returns:
            Dict with update status, new theta, classification (slip/gap), etc.
        """
        try:
            # Step 1: Read current StudentOverlay
            overlay_query = (
                "MATCH (s:StudentOverlay {user_id: $user_id, concept_id: $concept_id}) "
                "RETURN s.theta as theta, s.slip as slip, s.mastery_probability as mastery"
            )
            overlay_result = self.graph.db.run_query(
                overlay_query,
                {"user_id": user_id, "concept_id": concept_id}
            )
            
            if not overlay_result:
                logger.error(f"StudentOverlay not found for {user_id}/{concept_id}")
                return {
                    "status": "error",
                    "message": "StudentOverlay not found",
                    "user_id": user_id,
                    "concept_id": concept_id
                }
            
            current_theta = overlay_result[0].get("theta", 0.0)
            current_slip = overlay_result[0].get("slip", 0.1)
            
            # Step 2: Estimate difficulty if not provided
            if difficulty is None:
                # Simple heuristic: look at prerequisite mastery
                # Prerequisites well-mastered → this concept is harder
                # Prerequisites not mastered → this concept is easier
                prereq_query = (
                    "MATCH (c:CONCEPT {id: $concept_id})-[:REQUIRES*]->(prereq:CONCEPT) "
                    "RETURN AVG(COALESCE(overlay.mastery_probability, 0.5)) as avg_prereq_mastery"
                )
                prereq_result = self.graph.db.run_query(
                    prereq_query,
                    {"concept_id": concept_id}
                )
                
                avg_prereq_mastery = 0.5
                if prereq_result and prereq_result[0].get("avg_prereq_mastery"):
                    avg_prereq_mastery = prereq_result[0].get("avg_prereq_mastery", 0.5)
                
                # Difficulty scales with prerequisite mastery
                # If prerequisites are mastered, this concept is harder
                difficulty = (avg_prereq_mastery - 0.5) * 2.0
            
            # Step 3: Detect slip vs knowledge gap
            is_slip = False
            event_type = "correct" if answered_correctly else "attempt"
            
            if not answered_correctly:
                is_slip = self.is_slip_event(user_id, concept_id, current_theta, current_slip)
                event_type = "slip" if is_slip else "knowledge_gap"
            
            # Step 4: Apply Bayesian update
            if answered_correctly or not is_slip:
                # Standard update for correct or knowledge gap
                new_theta, new_slip = self.bayesian_update(
                    current_theta,
                    current_slip,
                    difficulty,
                    answered_correctly
                )
            else:
                # Slip event: don't reduce theta significantly
                # Student demonstrated they know it, just made a careless error
                _, new_slip = self.bayesian_update(
                    current_theta,
                    current_slip,
                    difficulty,
                    False
                )
                # Keep theta mostly the same for slip (slight increase for resilience)
                new_theta = current_theta + (0.02 * self.learning_rate)
            
            # Calculate new mastery probability from theta
            # Standard approach: mastery ≈ probability of correct on item at this theta
            # Using difficulty 0 means "average difficulty item"
            new_mastery = self.irt_probability(new_theta, 0.0)
            
            # Step 5: Update StudentOverlay in Neo4j
            update_query = (
                "MATCH (s:StudentOverlay {user_id: $user_id, concept_id: $concept_id}) "
                "SET s.theta = $new_theta, "
                "    s.slip = $new_slip, "
                "    s.mastery_probability = $new_mastery, "
                "    s.visited = true, "
                "    s.last_updated = datetime() "
                "RETURN s"
            )
            update_result = self.graph.db.run_query(
                update_query,
                {
                    "user_id": user_id,
                    "concept_id": concept_id,
                    "new_theta": new_theta,
                    "new_slip": new_slip,
                    "new_mastery": new_mastery
                }
            )
            
            if not update_result:
                logger.error(f"Failed to update StudentOverlay for {user_id}/{concept_id}")
                return {
                    "status": "error",
                    "message": "Failed to update StudentOverlay",
                    "user_id": user_id,
                    "concept_id": concept_id
                }
            
            logger.info(
                f"Updated {user_id}/{concept_id}: "
                f"θ {current_theta:.2f}→{new_theta:.2f}, "
                f"slip {current_slip:.3f}→{new_slip:.3f}, "
                f"mastery {current_theta:.3f}→{new_mastery:.3f} "
                f"[{event_type}]"
            )
            
            return {
                "status": "success",
                "user_id": user_id,
                "concept_id": concept_id,
                "answered_correctly": answered_correctly,
                "event_type": event_type,
                "previous": {
                    "theta": current_theta,
                    "slip": current_slip
                },
                "updated": {
                    "theta": new_theta,
                    "slip": new_slip,
                    "mastery_probability": new_mastery
                },
                "difficulty": difficulty
            }
        
        except Exception as e:
            logger.error(f"Update student overlay failed: {str(e)}")
            return {
                "status": "error",
                "message": str(e),
                "user_id": user_id,
                "concept_id": concept_id
            }
