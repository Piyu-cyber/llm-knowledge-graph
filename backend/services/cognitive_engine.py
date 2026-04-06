"""
OmniProf v3.0 — Cognitive Engine
Bayesian Knowledge Tracing (BKT) using IRT 2-parameter logistic model
Updates student knowledge state (theta) based on interactions
"""

import logging
import math
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from backend.db.neo4j_driver import Neo4jGraphManager

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
    
    
    # ==================== Slip vs Knowledge Gap ====================

    def _theta_to_mastery(self, theta: float) -> float:
        """Normalize theta-like values into [0, 1] mastery.

        Supports both mastery-style overlays (0..1) and IRT theta overlays (-4..4).
        """
        t = float(theta)
        if 0.0 <= t <= 1.0:
            return t
        exponent = max(-500.0, min(500.0, -1.7 * t))
        return 1.0 / (1.0 + math.exp(exponent))

    def _all_prerequisite_ids(self, concept_id: str) -> List[str]:
        """Get transitive prerequisite concept ids for a concept."""
        visited = set()
        queue = [concept_id]

        while queue:
            current = queue.pop(0)
            for prereq in self.graph.get_prerequisites(current):
                prereq_id = prereq.get("id")
                if not prereq_id or prereq_id in visited:
                    continue
                visited.add(prereq_id)
                queue.append(prereq_id)

        return list(visited)

    def _prerequisite_overlays(self, user_id: str, concept_id: str) -> List[Dict]:
        prereq_ids = self._all_prerequisite_ids(concept_id)
        overlays: List[Dict] = []
        for prereq_id in prereq_ids:
            overlay = self.graph.get_student_overlay(user_id, prereq_id)
            if overlay:
                overlays.append(overlay)
        return overlays

    def _classify_incorrect_event(self, user_id: str, concept_id: str) -> Tuple[str, Optional[str]]:
        overlays = self._prerequisite_overlays(user_id, concept_id)
        if not overlays:
            return "knowledge_gap", concept_id

        threshold = self.mastery_threshold
        all_high = all(self._theta_to_mastery(float(o.get("theta", 0.0))) >= threshold for o in overlays)
        if all_high:
            return "slip", concept_id

        weakest = min(overlays, key=lambda o: self._theta_to_mastery(float(o.get("theta", 0.0))))
        return "knowledge_gap", weakest.get("concept_id")

    def _estimate_concept_difficulty(self, concept_id: str, prereq_overlays: List[Dict]) -> float:
        concept = self.graph.nodes_data.get(concept_id, {})
        if "difficulty" in concept:
            return float(concept.get("difficulty", 0.0))

        if not prereq_overlays:
            return 0.0

        avg_mastery = sum(self._theta_to_mastery(float(o.get("theta", 0.0))) for o in prereq_overlays) / len(prereq_overlays)
        return max(-4.0, min(4.0, (avg_mastery - 0.5) * 2.0))

    # ==================== Student Overlay Update ====================

    def update_student_overlay(
        self,
        user_id: str,
        concept_id: str,
        answered_correctly: bool,
        difficulty: Optional[float] = None
    ) -> Dict:
        """Update student theta/slip using Bayesian update and slip-vs-gap classification."""
        try:
            current_overlay = self.graph.get_student_overlay(user_id, concept_id)
            if not current_overlay:
                create_result = self.graph.create_student_overlay(user_id, concept_id, theta=0.0, slip=0.1, guess=0.1)
                if create_result.get("status") != "success":
                    return {
                        "status": "error",
                        "message": "StudentOverlay not found",
                        "user_id": user_id,
                        "concept_id": concept_id,
                    }
                current_overlay = self.graph.get_student_overlay(user_id, concept_id)

            current_theta = float(current_overlay.get("theta", 0.0))
            current_slip = float(current_overlay.get("slip", 0.1))
            prereq_overlays = self._prerequisite_overlays(user_id, concept_id)

            effective_difficulty = difficulty
            if effective_difficulty is None:
                effective_difficulty = self._estimate_concept_difficulty(concept_id, prereq_overlays)

            event_type = "correct" if answered_correctly else "knowledge_gap"
            updated_concept_id = concept_id

            if answered_correctly:
                new_theta, new_slip = self.bayesian_update(
                    current_theta,
                    current_slip,
                    effective_difficulty,
                    True,
                )

                self.graph.update_student_overlay(
                    current_overlay["id"],
                    theta=new_theta,
                    visited=True,
                )
                current_node = self.graph.nodes_data[current_overlay["id"]]
                current_node["slip"] = new_slip
                current_node["last_updated"] = datetime.now().isoformat()
            else:
                event_type, target_concept_id = self._classify_incorrect_event(user_id, concept_id)
                updated_concept_id = target_concept_id or concept_id

                if event_type == "slip":
                    new_theta = current_theta
                    new_slip = min(1.0, current_slip + 0.05)
                    self.graph.update_student_overlay(
                        current_overlay["id"],
                        theta=new_theta,
                        visited=True,
                    )
                    current_node = self.graph.nodes_data[current_overlay["id"]]
                    current_node["slip"] = new_slip
                    current_node["last_updated"] = datetime.now().isoformat()
                else:
                    target_overlay = self.graph.get_student_overlay(user_id, updated_concept_id)
                    if not target_overlay:
                        create_result = self.graph.create_student_overlay(user_id, updated_concept_id, theta=0.0, slip=0.1, guess=0.1)
                        if create_result.get("status") != "success":
                            return {
                                "status": "error",
                                "message": "Failed to initialize prerequisite overlay",
                                "user_id": user_id,
                                "concept_id": updated_concept_id,
                            }
                        target_overlay = self.graph.get_student_overlay(user_id, updated_concept_id)

                    target_theta = float(target_overlay.get("theta", 0.0))
                    target_slip = float(target_overlay.get("slip", 0.1))
                    new_theta, new_slip = self.bayesian_update(
                        target_theta,
                        target_slip,
                        effective_difficulty,
                        False,
                    )
                    self.graph.update_student_overlay(
                        target_overlay["id"],
                        theta=new_theta,
                        visited=True,
                    )
                    target_node = self.graph.nodes_data[target_overlay["id"]]
                    target_node["slip"] = new_slip
                    target_node["last_updated"] = datetime.now().isoformat()

                    # Keep current concept marked as visited, but do not penalize theta.
                    self.graph.update_student_overlay(current_overlay["id"], visited=True)

            self.graph._save_graph()

            result_overlay = self.graph.get_student_overlay(user_id, updated_concept_id)
            return {
                "status": "success",
                "user_id": user_id,
                "concept_id": concept_id,
                "updated_concept_id": updated_concept_id,
                "answered_correctly": answered_correctly,
                "event_type": event_type,
                "previous": {
                    "theta": current_theta,
                    "slip": current_slip,
                },
                "updated": {
                    "theta": float(result_overlay.get("theta", current_theta)) if result_overlay else current_theta,
                    "slip": float(result_overlay.get("slip", current_slip)) if result_overlay else current_slip,
                    "mastery_probability": float(result_overlay.get("mastery_probability", 0.5)) if result_overlay else 0.5,
                },
                "difficulty": float(effective_difficulty),
            }
        except Exception as e:
            logger.error(f"Update student overlay failed: {str(e)}")
            return {
                "status": "error",
                "message": str(e),
                "user_id": user_id,
                "concept_id": concept_id,
            }
