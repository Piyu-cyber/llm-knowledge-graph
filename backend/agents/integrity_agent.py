"""
OmniProf Integrity Agent
Analyzes writing style for academic integrity assessment.

Features:
- Builds writing fingerprint from prior TA interactions
- Computes Style Deviation Index (SDI) 0-100
- Flags anomalous input when SDI > 85
- Suppresses SDI until 500+ tokens of history
"""

import logging
import os
import re
from typing import Dict, List, Optional, Tuple
from statistics import mean, stdev

from backend.agents.state import AgentState
from backend.db.neo4j_driver import Neo4jGraphManager
from backend.db.neo4j_schema import CypherQueries

logger = logging.getLogger(__name__)


class WritingFingerprint:
    """Represents a student's writing style baseline"""
    
    def __init__(self,
                 avg_sentence_length: float,
                 vocabulary_richness: float,
                 punctuation_pattern: Dict[str, float],
                 avg_word_length: float,
                 token_count: int):
        """
        Args:
            avg_sentence_length: Average words per sentence
            vocabulary_richness: Type/token ratio (unique words / total words)
            punctuation_pattern: Dict of punctuation -> frequency ratio
            avg_word_length: Average characters per word
            token_count: Total tokens in baseline
        """
        self.avg_sentence_length = avg_sentence_length
        self.vocabulary_richness = vocabulary_richness
        self.punctuation_pattern = punctuation_pattern
        self.avg_word_length = avg_word_length
        self.token_count = token_count
    
    def to_dict(self) -> Dict:
        """Convert to serializable dict"""
        return {
            "avg_sentence_length": self.avg_sentence_length,
            "vocabulary_richness": self.vocabulary_richness,
            "punctuation_pattern": self.punctuation_pattern,
            "avg_word_length": self.avg_word_length,
            "token_count": self.token_count
        }


class IntegrityAgent:
    """
    Academic Integrity Assessment Agent.
    
    Analyzes writing style deviations to detect potential academic dishonesty.
    
    Workflow:
    1. Build writing fingerprint from prior TA interactions (>= 500 tokens)
    2. On evaluation turn, analyze student response
    3. Compute Style Deviation Index (SDI)
    4. If SDI > 85, flag as anomalous
    5. Update DefenceRecord with integrity_score
    """
    
    def __init__(self, neo4j_uri: Optional[str] = None,
                 neo4j_user: Optional[str] = None,
                 neo4j_password: Optional[str] = None,
                 min_token_threshold: Optional[int] = None):
        """
        Initialize Integrity Agent.
        
        Args:
            neo4j_uri: Neo4j database URI
            neo4j_user: Neo4j username
            neo4j_password: Neo4j password
        """
        from dotenv import load_dotenv
        
        load_dotenv()
        
        self.graph_manager = Neo4jGraphManager(
            uri=neo4j_uri or os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            user=neo4j_user or os.getenv("NEO4J_USER", "neo4j"),
            password=neo4j_password or os.getenv("NEO4J_PASSWORD", "password")
        )
        
        # Detection thresholds
        self.sdi_anomaly_threshold = 85      # Flag if SDI > 85
        self.min_token_threshold = int(min_token_threshold if min_token_threshold is not None else os.getenv("INTEGRITY_MIN_TOKENS", "500"))
    
    
    # ==================== Main Agent Entry Point ====================
    
    def process(self, state: AgentState) -> AgentState:
        """
        Main entry point for Integrity Agent as LangGraph node.
        
        Workflow:
        1. Retrieve prior TA interaction history (all messages from previous sessions)
        2. Build writing fingerprint if >= 500 tokens
        3. Analyze current response in evaluation
        4. Compute Style Deviation Index
        5. Update DefenceRecord with integrity_score and anomaly flag
        6. Return updated state
        
        Args:
            state: Current agent state (from evaluator_agent)
        
        Returns:
            Updated agent state with integrity analysis
        """
        try:
            logger.info(f"IntegrityAgent analyzing student {state.student_id}")
            
            # Step 1: Retrieve prior TA interaction history
            prior_messages = self._get_prior_ta_interactions(state.student_id)
            
            # Step 2: Extract text and build fingerprint
            prior_text = "\n".join([m.get("content", "") for m in prior_messages])
            prior_token_count = len(prior_text.split())
            
            logger.debug(f"Prior interactions: {len(prior_messages)} messages, "
                        f"{prior_token_count} tokens")
            
            # Step 3: Check if we have enough history
            has_sufficient_history = prior_token_count >= self.min_token_threshold
            
            integrity_score = 1.0  # Default: honest
            anomalous_input = False
            sdi = None
            
            if has_sufficient_history:
                # Build fingerprint
                baseline = self._build_fingerprint(prior_text)
                
                # Get current response from latest evaluation turn
                current_response = self._get_current_evaluation_response(state)
                
                if current_response:
                    # Compute SDI
                    sdi = self._compute_style_deviation_index(baseline, current_response)
                    
                    logger.debug(f"Style Deviation Index: {sdi:.1f}")
                    
                    # Convert SDI to integrity score [0, 1]
                    # Higher SDI = lower integrity score
                    integrity_score = max(0.0, 1.0 - (sdi / 100.0))
                    
                    # Flag if anomalous
                    anomalous_input = sdi > self.sdi_anomaly_threshold
                    
                    logger.info(f"Integrity score: {integrity_score:.2f}, "
                               f"anomalous: {anomalous_input}")
            else:
                logger.debug(f"Insufficient history ({prior_token_count} tokens, "
                            f"need {self.min_token_threshold}), suppressing SDI")
                # Set to moderate if can't assess
                integrity_score = 0.8
            
            # Step 4: Update DefenceRecord
            defence_record_id = state.metadata.get("defence_record_id")
            if defence_record_id:
                status = "flagged" if anomalous_input else "approved"
                self._update_defence_record(
                    defence_record_id,
                    status,
                    integrity_score,
                    anomalous_input
                )
                
                logger.info(f"DefenceRecord {defence_record_id} updated with "
                           f"integrity_score={integrity_score:.2f}")

                # Write completed defence package into HITL queue.
                record = self.graph_manager.get_defence_record(defence_record_id) if hasattr(self.graph_manager, "get_defence_record") else None
                if record and hasattr(self.graph_manager, "enqueue_hitl_review"):
                    self.graph_manager.enqueue_hitl_review(
                        {
                            "defence_record_id": defence_record_id,
                            "student_id": state.student_id,
                            "course_id": record.get("course_id", state.metadata.get("course_id")),
                            "transcript": record.get("transcript", []),
                            "ai_recommended_grade": record.get("ai_recommended_grade", state.metadata.get("ai_recommended_grade", 0.0)),
                            "integrity_score": integrity_score,
                            "sdi": sdi,
                            "sdi_visible": has_sufficient_history,
                            "status": status,
                        }
                    )
            
            # Step 5: Update state
            state.metadata["integrity_score"] = integrity_score
            state.metadata["anomalous_input"] = anomalous_input
            state.metadata["sdi_visible"] = has_sufficient_history
            if sdi is not None:
                state.metadata["sdi"] = sdi
            
            # Mark completion
            state.mark_transfer(
                "cognitive_engine_agent",
                "Integrity assessment complete"
            )
            
            state.active_agent = "integrity_agent"
            return state
            
        except Exception as e:
            logger.error(f"IntegrityAgent error: {str(e)}", exc_info=True)
            state.error = str(e)
            state.error_count += 1
            return state
    
    
    # ==================== Prior Interaction Retrieval ====================
    
    def _get_prior_ta_interactions(self, student_id: str) -> list:
        """
        Retrieve all prior TA Agent interactions for student.
        
        Queries for all messages where:
        - active_agent == "ta_agent"
        - role == "assistant" (TA's response)
        
        Args:
            student_id: Student user ID
        
        Returns:
            List of message dicts with content
        """
        try:
            # In practice, this would query the conversation history database
            # For now, we return empty (would be populated by calling application)
            # This simulates: SELECT content FROM interactions WHERE student_id=? AND agent="ta_agent"
            
            query = """
            MATCH (s:StudentOverlay {user_id: $user_id})
            MATCH (s)-[:STUDIED_BY]->(c:CONCEPT)
            RETURN c.name as topic
            """
            
            # Fallback for local/test runs: allow explicit samples from metadata-driven stores.
            if hasattr(self.graph_manager, "_read_json_list") and hasattr(self.graph_manager, "_defence_records_path"):
                rows = self.graph_manager._read_json_list(self.graph_manager._defence_records_path())
                samples: List[Dict] = []
                for row in rows:
                    if str(row.get("student_id")) != str(student_id):
                        continue
                    transcript = row.get("transcript", [])
                    if isinstance(transcript, str):
                        try:
                            import json
                            transcript = json.loads(transcript)
                        except Exception:
                            transcript = []
                    for turn in transcript:
                        if turn.get("role") == "student":
                            samples.append({"content": turn.get("content", "")})
                if samples:
                    return samples

            logger.debug(f"Retrieving prior TA interactions for {student_id}")
            
            # TODO: Implement actual message history query
            # Would integrate with conversation storage (database or file)
            return []
            
        except Exception as e:
            logger.warning(f"Prior interaction retrieval error: {str(e)}")
            return []
    
    
    # ==================== Fingerprint Building ====================
    
    def _build_fingerprint(self, text: str) -> WritingFingerprint:
        """
        Build writing fingerprint from text.
        
        Extracts features:
        1. Average sentence length (words/sentence)
        2. Vocabulary richness (type/token ratio)
        3. Punctuation patterns (freq of . , ! ? etc)
        4. Average word length (chars/word)
        
        Args:
            text: Full text to analyze
        
        Returns:
            WritingFingerprint instance
        """
        try:
            if not text or len(text.strip()) == 0:
                return WritingFingerprint(0, 0, {}, 0, 0)
            
            # Tokenize
            sentences = re.split(r'[.!?]+', text)
            sentences = [s.strip() for s in sentences if s.strip()]
            
            words = text.lower().split()
            
            # Feature 1: Average sentence length
            sentence_lengths = [len(s.split()) for s in sentences]
            avg_sentence_length = mean(sentence_lengths) if sentence_lengths else 0
            
            # Feature 2: Vocabulary richness (type/token ratio)
            unique_words = set(words)
            vocabulary_richness = len(unique_words) / len(words) if words else 0
            
            # Feature 3: Punctuation pattern
            punctuation_chars = ['.', ',', '!', '?', ';', ':', '-', '(', ')']
            punct_counts = {c: text.count(c) for c in punctuation_chars}
            total_punct = sum(punct_counts.values())
            punctuation_pattern = {
                c: count / max(1, total_punct) for c, count in punct_counts.items()
            } if total_punct > 0 else {c: 0 for c in punctuation_chars}
            
            # Feature 4: Average word length
            word_lengths = [len(w.strip('.,!?;:')) for w in words]
            avg_word_length = mean(word_lengths) if word_lengths else 0
            
            token_count = len(words)
            
            fingerprint = WritingFingerprint(
                avg_sentence_length=avg_sentence_length,
                vocabulary_richness=vocabulary_richness,
                punctuation_pattern=punctuation_pattern,
                avg_word_length=avg_word_length,
                token_count=token_count
            )
            
            logger.debug(f"Fingerprint built: sent_len={avg_sentence_length:.1f}, "
                        f"vocab_rich={vocabulary_richness:.2f}, "
                        f"word_len={avg_word_length:.1f}")
            
            return fingerprint
            
        except Exception as e:
            logger.warning(f"Fingerprint building error: {str(e)}")
            return WritingFingerprint(0, 0, {}, 0, 0)
    
    
    # ==================== Style Deviation Index ====================
    
    def _compute_style_deviation_index(self,
                                       baseline: WritingFingerprint,
                                       current_text: str) -> float:
        """
        Compute Style Deviation Index (SDI) comparing current to baseline.
        
        SDI measures how different the current text is from the student's baseline.
        
        Formula:
        SDI = sqrt(
              W1 * (sent_len_dev)^2 +
              W2 * (vocab_rich_dev)^2 +
              W3 * (punct_dev)^2 +
              W4 * (word_len_dev)^2
        ) * 100
        
        Where dev = |current - baseline| / (baseline + epsilon)
        
        Args:
            baseline: WritingFingerprint from prior interactions
            current_text: Current response to analyze
        
        Returns:
            SDI score 0-100 (0=identical, 100=completely different)
        """
        try:
            if baseline.token_count == 0:
                return 0.0
            
            # Build current fingerprint
            current = self._build_fingerprint(current_text)
            
            # Compute deviations (normalized)
            epsilon = 0.01
            
            sent_len_dev = abs(current.avg_sentence_length - baseline.avg_sentence_length) / (baseline.avg_sentence_length + epsilon)
            vocab_dev = abs(current.vocabulary_richness - baseline.vocabulary_richness) / (baseline.vocabulary_richness + epsilon)
            word_len_dev = abs(current.avg_word_length - baseline.avg_word_length) / (baseline.avg_word_length + epsilon)
            
            # Punctuation pattern deviation (Euclidean distance)
            punct_dev = 0.0
            for punct, base_freq in baseline.punctuation_pattern.items():
                current_freq = current.punctuation_pattern.get(punct, 0)
                punct_dev += (current_freq - base_freq) ** 2
            punct_dev = punct_dev ** 0.5
            
            # Weighted combination
            w1, w2, w3, w4 = 0.25, 0.25, 0.25, 0.25  # Equal weights
            
            sdi = (w1 * sent_len_dev ** 2 +
                   w2 * vocab_dev ** 2 +
                   w3 * punct_dev ** 2 +
                   w4 * word_len_dev ** 2) ** 0.5
            
            sdi_score = min(100.0, sdi * 100.0)  # Scale to 0-100
            
            logger.debug(f"SDI components: sent_len={sent_len_dev:.2f}, "
                        f"vocab={vocab_dev:.2f}, punct={punct_dev:.2f}, "
                        f"word_len={word_len_dev:.2f} → SDI={sdi_score:.1f}")
            
            return sdi_score
            
        except Exception as e:
            logger.warning(f"SDI computation error: {str(e)}")
            return 0.0
    
    
    # ==================== Current Response Retrieval ====================
    
    def _get_current_evaluation_response(self, state: AgentState) -> Optional[str]:
        """
        Get the student's latest response during evaluation.
        
        Args:
            state: Current agent state
        
        Returns:
            Student's latest message content or None
        """
        try:
            # Get last student message
            for msg in reversed(state.messages):
                if msg.get("role") == "student":
                    return msg.get("content", "")
            return None
        except Exception as e:
            logger.warning(f"Current response retrieval error: {str(e)}")
            return None
    
    
    # ==================== Database Operations ====================
    
    def _update_defence_record(self,
                              record_id: str,
                              status: str,
                              integrity_score: float,
                              anomalous_input: bool) -> bool:
        """
        Update DefenceRecord with integrity assessment results.
        
        Args:
            record_id: DefenceRecord ID
            status: "approved" | "flagged"
            integrity_score: Score 0.0-1.0
            anomalous_input: Whether input was anomalous
        
        Returns:
            Success status
        """
        try:
            if hasattr(self.graph_manager, "update_defence_record"):
                result = self.graph_manager.update_defence_record(
                    record_id,
                    {
                        "status": status,
                        "integrity_score": integrity_score,
                        "anomalous_input": anomalous_input,
                    },
                )
                return result.get("status") == "success"

            query, params = CypherQueries.update_defence_record(
                record_id,
                status,
                integrity_score,
                anomalous_input
            )
            result = self.graph_manager.db.run_query(query, params)
            logger.info(f"DefenceRecord {record_id} updated: status={status}, "
                       f"integrity_score={integrity_score:.2f}")
            return bool(result)
        except Exception as e:
            logger.error(f"DefenceRecord update error: {str(e)}")
            return False
