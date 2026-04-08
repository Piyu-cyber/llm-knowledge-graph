"""
OmniProf Evaluator Agent
LangGraph node for multi-turn submission defence evaluation.

Features:
- Conducts adaptive multi-turn conversational Socratic probe
- Tracks confidence and terminates on high confidence or max turns
- Probes least-confident concept nodes in student overlay
- Generates DefenceRecord with transcript, grade, feedback, integrity score
"""

import logging
import os
from typing import Dict, List, Optional
from datetime import datetime

from backend.agents.state import AgentState, EvalState
from backend.services.crag_service import CRAGService
from backend.services.cognitive_engine import CognitiveEngine
from backend.services.llm_service import LLMService
from backend.services.llm_router import LLMRouter
from backend.services.rag_service import RAGService
from backend.services.graph_service import GraphService
from backend.db.graph_manager import GraphManager
from backend.db.neo4j_schema import DefenceRecord

logger = logging.getLogger(__name__)


class EvaluatorAgent:
    """
    Evaluator Agent for submission defence evaluation.
    
    Multi-turn conversational evaluation:
    1. Analyze student submission/response
    2. Probe understanding via Socratic questions
    3. Assess mastery of key concepts
    4. Track confidence in evaluation
    5. Generate DefenceRecord with grade and feedback
    
    Termination Conditions:
    - eval_state.confidence > 0.9
    - eval_state.turn_count >= 10
    - Student explicitly ends after turn 3
    """
    
    def __init__(self,
                 groq_api_key: Optional[str] = None,
                 data_dir: Optional[str] = None,
                 **kwargs):
        """
        Initialize Evaluator Agent.
        
        Args:
            groq_api_key: Groq API key
            data_dir: Path to data directory for graph persistence
        """
        from dotenv import load_dotenv
        
        load_dotenv()
        
        # Initialize services using RustWorkX-based GraphManager
        self.graph_manager = GraphManager(
            data_dir=data_dir or os.getenv("DATA_DIR", "data")
        )
        
        self.llm_service = LLMService()
        self.llm_router = LLMRouter(llm_service=self.llm_service)
        self.rag_service = RAGService()
        self.graph_service = GraphService(self.graph_manager)
        self.cognitive_engine = CognitiveEngine()
        self.crag_service = CRAGService(
            rag_service=self.rag_service,
            graph_service=self.graph_service,
            llm_service=self.llm_service
        )
        
        # Evaluation parameters
        self.confidence_threshold = 0.9
        self.max_turns = 10
        self.min_turns_before_student_exit = 3
    
    
    # ==================== Main Agent Entry Point ====================
    
    def process(self, state: AgentState) -> AgentState:
        """
        Main entry point for Evaluator Agent as LangGraph node.
        
        Workflow:
        1. Check if this is continuation or new evaluation
        2. Identify least-confident concepts from student overlay
        3. Generate probing question for that concept
        4. Update eval_state (confidence, turn_count, transcript)
        5. Check termination conditions
        6. If terminating, create DefenceRecord
        7. Return updated state
        
        Args:
            state: Current agent state
        
        Returns:
            Updated agent state with evaluation response
        """
        try:
            logger.info(f"EvaluatorAgent processing for student {state.student_id}")
            
            # Step 1: Initialize evaluation if first turn
            if state.eval_state.turn_count == 0:
                state.eval_state.turn_count = 1
                # Initial greeting/evaluation start
                initial_message = self._generate_initial_greeting(state.current_input)
                state.add_message(
                    role="assistant",
                    content=initial_message,
                    intent="submission_defence"
                )
                state.eval_state.transcript.append({
                    "role": "student",
                    "content": state.current_input
                })
                state.active_agent = "evaluator_agent"
                logger.debug("Evaluation initialized")
                return state
            
            # Step 2: Get least-confident concept to probe
            least_confident = self._get_least_confident_concept(state.student_id)
            logger.debug(f"Probing concept: {least_confident}")
            
            # Step 3: Generate probing question
            probing_question = self._generate_probing_question(
                concept=least_confident,
                student_response=state.current_input,
                conversation_context=state.get_last_n_messages(5)
            )
            
            # Step 4: Update eval_state with conversation turn
            state.eval_state.turn_count += 1
            state.eval_state.transcript.append({
                "role": "student",
                "content": state.current_input
            })
            state.eval_state.transcript.append({
                "role": "evaluator",
                "content": probing_question
            })
            
            # Step 5: Update confidence based on responses so far
            confidence = self._update_confidence(
                turn_count=state.eval_state.turn_count,
                transcript=state.eval_state.transcript,
                probed_concepts=[least_confident]
            )
            state.eval_state.confidence = confidence
            
            # Step 6: Add response to state
            state.add_message(
                role="assistant",
                content=probing_question,
                intent="submission_defence"
            )
            
            # Step 7: Check termination conditions
            should_terminate, termination_reason = self._check_termination(
                state.eval_state,
                state.messages,
                state.current_input,
            )
            
            if should_terminate:
                logger.info(f"Evaluation terminating: {termination_reason}")
                
                # Step 8: Generate grade and feedback
                grade, feedback = self._generate_grade_and_feedback(
                    state.eval_state.transcript,
                    least_confident
                )
                
                # Step 9: Create DefenceRecord (leave integrity_score=0 for now, 
                # will be updated by IntegrityAgent
                record = DefenceRecord(
                    student_id=state.student_id,
                    submission_id=state.metadata.get("submission_id", "unknown"),
                    transcript=state.eval_state.transcript,
                    ai_recommended_grade=grade,
                    ai_feedback=feedback,
                    integrity_score=0.0,
                    status="pending_integrity_review",
                    anomalous_input=False
                )
                
                # Persist to local graph store
                self._write_defence_record(record, course_id=state.metadata.get("course_id", "unknown"))
                
                # Store record ID in state
                state.metadata["defence_record_id"] = record.id
                state.metadata["ai_recommended_grade"] = grade
                state.metadata["ai_feedback"] = feedback
                
                # Mark for transfer to IntegrityAgent
                state.mark_transfer(
                    "integrity_agent",
                    f"Evaluation complete after {state.eval_state.turn_count} turns"
                )
            
            state.active_agent = "evaluator_agent"
            return state
            
        except Exception as e:
            logger.error(f"EvaluatorAgent error: {str(e)}", exc_info=True)
            state.error = str(e)
            state.error_count += 1
            return state
    
    
    # ==================== Greeting & Initialization ====================
    
    def _generate_initial_greeting(self, student_submission: str) -> str:
        """
        Generate opening greeting for submission defence.
        
        Args:
            student_submission: Initial submission/answer to defend
        
        Returns:
            Friendly opening message
        """
        try:
            prompt = f"""
You are an academic tutor conducting a gentle submission defence evaluation.
The student has submitted this work:

{student_submission[:500]}

Generate a brief, encouraging opening message that:
1. Acknowledges their submission
2. Explains you'll ask some probing questions
3. Asks them to explain their thinking/approach
4. Sets a collaborative tone (not adversarial)

Keep it to 2-3 sentences.
"""
            
            greeting = self._call_llm(prompt)
            return greeting if greeting else "Thank you for your submission. Let's explore your thinking together."
            
        except Exception as e:
            logger.warning(f"Greeting generation error: {str(e)}")
            return "Let's discuss your submission in more detail."
    
    
    # ==================== Concept Probing ====================
    
    def _get_least_confident_concept(self, student_id: str) -> str:
        """
        Find the concept with lowest mastery_probability in student overlay.
        
        This is the concept we should probe to best evaluate understanding.
        
        Args:
            student_id: Student user ID
        
        Returns:
            Concept name/ID with lowest mastery
        """
        try:
            # Get all overlays for this student and find the least confident
            concept_id = self.graph_manager.get_least_confident_concept(student_id)
            if not concept_id:
                return "key concept"
            
            # Get concept details
            concept = self.graph_manager.get_concept_by_id(concept_id)
            concept_name = concept.get('name', concept_id) if concept else concept_id
            
            # Get current mastery
            overlay = self.graph_manager.get_student_overlay(student_id, concept_id)
            mastery = overlay.get('mastery_probability', 0.5) if overlay else 0.5
            
            logger.debug(f"Least confident concept: {concept_name} (mastery={mastery:.2f})")
            return concept_name
            
        except Exception as e:
            logger.warning(f"Least confident concept lookup error: {str(e)}")
            return "key concept"
    
    
    def _generate_probing_question(self,
                                   concept: str,
                                   student_response: str,
                                   conversation_context: List[Dict]) -> str:
        """
        Generate a probing Socratic question about a specific concept.
        
        Args:
            concept: Concept to probe
            student_response: Student's current response
            conversation_context: Previous messages in conversation
        
        Returns:
            Probing question
        """
        try:
            context = "\n".join([
                f"{m.get('role', 'user')}: {m.get('content', '')[:200]}"
                for m in conversation_context[-3:]
            ])
            
            prompt = f"""
Generate a follow-up Socratic question to probe the student's understanding of: {concept}

Their recent response: {student_response[:300]}

Previous context:
{context}

The question should:
- Target the specific concept directly
- Be open-ended (not yes/no)
- Probe for deeper understanding
- Be respectful and collaborative
- Help identify gaps in understanding

Return ONLY the question, no other text.
"""
            
            question = self._call_llm(prompt)
            return question if question else f"Can you explain more about {concept}?"
            
        except Exception as e:
            logger.warning(f"Probing question generation error: {str(e)}")
            return f"Can you give more detail about how {concept} applies here?"
    
    
    # ==================== Confidence Tracking ====================
    
    def _update_confidence(self,
                          turn_count: int,
                          transcript: List[Dict],
                          probed_concepts: List[str]) -> float:
        """
        Update evaluator's confidence in assessment based on responses.
        
        Confidence increases when:
        - Student demonstrates clear understanding
        - Concept probing reveals consistent knowledge
        - Multiple turns without gaps
        
        Args:
            turn_count: Number of evaluation turns so far
            transcript: Full conversation transcript
            probed_concepts: Concepts that have been tested
        
        Returns:
            Confidence score [0.0, 1.0]
        """
        try:
            # Start with base confidence
            confidence = 0.5
            
            # Increase confidence with each turn (up to a point)
            confidence += min(0.1, turn_count * 0.05)
            
            # Analyze last student response for clarity
            if transcript:
                last_student_response = None
                for msg in reversed(transcript):
                    if msg.get("role") == "student":
                        last_student_response = msg.get("content", "")
                        break
                
                if last_student_response:
                    # Simple heuristics: longer, detailed responses suggest understanding
                    words = len(last_student_response.split())
                    if words > 50:
                        confidence += 0.1
                    elif words > 100:
                        confidence += 0.15
            
            # More concepts probed = higher confidence
            confidence += min(0.1, len(probed_concepts) * 0.05)
            
            confidence = max(0.0, min(1.0, confidence))
            logger.debug(f"Updated confidence: {confidence:.2f}")
            
            return confidence
            
        except Exception as e:
            logger.warning(f"Confidence update error: {str(e)}")
            return 0.5
    
    
    # ==================== Termination Check ====================
    
    def _check_termination(self, eval_state: EvalState, messages: List[Dict], latest_student_input: str = "") -> tuple:
        """
        Check if evaluation should terminate.
        
        Termination conditions:
        1. eval_state.confidence > 0.9
        2. eval_state.turn_count >= 10
        3. Student says "stop" after turn 3
        
        Args:
            eval_state: Current evaluation state
            messages: Conversation messages
        
        Returns:
            (should_terminate, reason_string)
        """
        # Condition 1: High confidence
        if eval_state.confidence > self.confidence_threshold:
            return True, f"High confidence ({eval_state.confidence:.2f})"
        
        # Condition 2: Max turns reached
        if eval_state.turn_count >= self.max_turns:
            return True, f"Max turns reached ({eval_state.turn_count})"
        
        # Condition 3: Student wants to stop after turn 3
        if eval_state.turn_count >= self.min_turns_before_student_exit:
            candidate_text = (latest_student_input or "").lower()
            if not candidate_text and messages:
                for msg in reversed(messages):
                    if msg.get("role") == "student":
                        candidate_text = str(msg.get("content", "")).lower()
                        break
            exit_keywords = ["stop", "done", "finish", "that's all", "no more", "end"]
            if any(kw in candidate_text for kw in exit_keywords):
                return True, "Student requested to stop"
        
        return False, ""
    
    
    # ==================== Grade Generation ====================
    
    def _generate_grade_and_feedback(self,
                                     transcript: List[Dict],
                                     main_concept: str) -> tuple:
        """
        Generate overall grade and feedback from transcript.
        
        Args:
            transcript: Full evaluation transcript
            main_concept: Primary concept that was probed
        
        Returns:
            (grade: float [0, 1], feedback: str)
        """
        try:
            # Build summary of responses
            responses = [msg for msg in transcript if msg.get("role") == "student"]
            response_summary = "\n".join([r.get("content", "")[:200] for r in responses])
            
            prompt = f"""
Based on this submission defence evaluation, assign a grade and provide feedback.

Main concept probed: {main_concept}

Student responses:
{response_summary}

GRADE: Assess overall understanding on scale 0.0-1.0:
- 0.0-0.3: Does not understand
- 0.3-0.6: Partial understanding
- 0.6-0.8: Good understanding
- 0.8-1.0: Excellent understanding

Respond with JSON:
{{
  "grade": <float 0.0-1.0>,
  "feedback": "<constructive feedback string>"
}}

Return ONLY the JSON.
"""
            
            response = self._call_llm(prompt)
            
            # Parse JSON
            import json, re
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                grade = float(data.get("grade", 0.5))
                feedback = str(data.get("feedback", "Good submission."))
                return grade, feedback
            
            return 0.5, "Submission demonstrates understanding."
            
        except Exception as e:
            logger.warning(f"Grade generation error: {str(e)}")
            return 0.5, "Submission reviewed."
    
    
    # ==================== Database Operations ====================
    
    def _write_defence_record(self, record: DefenceRecord, course_id: str = "unknown") -> bool:
        """
        Write DefenceRecord to local graph store.
        
        Args:
            record: DefenceRecord instance
        
        Returns:
            Success status
        """
        try:
            payload = record.to_dict()
            payload["course_id"] = course_id or "unknown"
            result = self.graph_manager.create_defence_record(payload)
            return result.get("status") == "success"
        except Exception as e:
            logger.error(f"DefenceRecord creation error: {str(e)}")
            return False
    
    
    # ==================== Utilities ====================
    
    def _call_llm(self, prompt: str, temperature: float = 0.7) -> str:
        """
        Route evaluator prompts through centralized router.
        
        Args:
            prompt: Input prompt
            temperature: Model temperature
        
        Returns:
            Model response or empty string
        """
        try:
            route_result = self.llm_router.route(
                task="evaluator_defence",
                prompt=prompt,
                temperature=temperature,
                max_tokens=512,
                use_cache=False,
            )
            if route_result.get("status") == "success":
                return (route_result.get("text") or "").strip()
            return ""
        except Exception as e:
            logger.error(f"LLM call error: {str(e)}")
            return ""
