"""
OmniProf Intent Classifier
Classifies student messages into intent categories using LLM
"""

import logging
import json
import re
from typing import Dict, Tuple
from backend.agents.state import AgentState
from backend.services.llm_router import LLMRouter

logger = logging.getLogger(__name__)


class IntentClassifier:
    """
    Classify student messages into semantic intent categories.
    
    Intents:
    - academic_query: Questions about course content, concepts, problems
    - submission_defence: Defending assignment/exam answers, requesting feedback
    - curriculum_change: Requesting curriculum adjustments, learning paths
    - progress_check: Requesting learning progress reports, mastery levels
    """
    
    VALID_INTENTS = {
        "academic_query",
        "submission_defence",
        "curriculum_change",
        "progress_check"
    }
    
    def __init__(self, groq_api_key: str = None):
        """
        Initialize the intent classifier.
        
        Args:
            groq_api_key: Groq API key (defaults to environment variable)
        """
        import os
        from dotenv import load_dotenv
        
        load_dotenv()
        
        self.router = LLMRouter()
    
    
    def classify(self, message: str) -> Tuple[str, float, str]:
        """
        Classify a student message into an intent category.
        
        Args:
            message: Student's input message
        
        Returns:
            Tuple of (intent, confidence, reasoning)
            where intent is one of VALID_INTENTS,
            confidence is [0, 1] float,
            and reasoning explains the classification.
        """
        try:
            prompt = self._build_classification_prompt(message)
            
            route_result = self.router.route(
                task="intent_classification",
                prompt=prompt,
                temperature=0.3,
                max_tokens=200,
                use_cache=False,
            )
            response_text = (route_result.get("text") or "").strip()
            
            # Parse the response
            intent, confidence, reasoning = self._parse_response(response_text, message)
            
            logger.info(
                f"Intent classification: '{message[:50]}...' → {intent} "
                f"(confidence: {confidence:.2f})"
            )
            
            return intent, confidence, reasoning
        
        except Exception as e:
            logger.error(f"Intent classification error: {str(e)}")
            # Default to academic_query if error
            return "academic_query", 0.5, f"Classification error: {str(e)}"
    
    
    def _build_classification_prompt(self, message: str) -> str:
        """Build the prompt for intent classification"""
        return f"""You are an educational intent classifier. Analyze the student's message and classify it into one of these categories:

1. academic_query: Questions about course concepts, how to solve problems, understanding topics
   Examples: "How does recursion work?", "Can you explain binary search?", "When do I use a hash table?"

2. submission_defence: Defending their answers, asking for feedback on their work, justifying solutions
   Examples: "I think my answer is correct because...", "Can you review my code?", "Why did I lose points on this?"

3. curriculum_change: Requesting curriculum modifications, different learning paths, personalized content
   Examples: "I want to skip this topic", "Can we focus more on X?", "I need a different approach"

4. progress_check: Requesting mastery levels, learning progress, what they've achieved
   Examples: "How am I doing?", "What's my progress in this course?", "What concepts have I mastered?"

Student Message: "{message}"

Respond in this exact format:
INTENT: [one of: academic_query, submission_defence, curriculum_change, progress_check]
CONFIDENCE: [0.0 to 1.0]
REASONING: [brief explanation of why this intent was chosen]"""
    
    
    def _parse_response(self, response_text: str, original_message: str) -> Tuple[str, float, str]:
        """
        Parse LLM response to extract intent, confidence, and reasoning.
        
        Returns:
            (intent, confidence, reasoning)
        """
        lines = response_text.strip().split('\n')
        
        intent = "academic_query"  # default
        confidence = 0.5
        reasoning = ""
        
        for line in lines:
            if line.startswith("INTENT:"):
                intent_str = line.replace("INTENT:", "").strip().lower()
                # Extract intent from response (might have quotes or extra text)
                for valid_intent in self.VALID_INTENTS:
                    if valid_intent in intent_str:
                        intent = valid_intent
                        break
            
            elif line.startswith("CONFIDENCE:"):
                try:
                    conf_str = line.replace("CONFIDENCE:", "").strip()
                    confidence = float(conf_str)
                    confidence = max(0.0, min(1.0, confidence))  # Clamp [0, 1]
                except ValueError:
                    confidence = 0.5
            
            elif line.startswith("REASONING:"):
                reasoning = line.replace("REASONING:", "").strip()
        
        # Validate final intent
        if intent not in self.VALID_INTENTS:
            intent = "academic_query"
        
        return intent, confidence, reasoning
    
    
    def classify_with_examples(self, message: str) -> Dict:
        """
        Classify message and return rich response with all details.
        
        Returns:
            {
                "message": original message,
                "intent": classified intent,
                "confidence": confidence score,
                "reasoning": explanation,
                "is_high_confidence": whether confidence > 0.7
            }
        """
        intent, confidence, reasoning = self.classify(message)
        
        return {
            "message": message,
            "intent": intent,
            "confidence": confidence,
            "reasoning": reasoning,
            "is_high_confidence": confidence > 0.7
        }


class AgentRouter:
    """
    Route messages to appropriate agents based on classified intent.
    """
    
    INTENT_TO_AGENT = {
        "academic_query": "academic_qa_agent",
        "submission_defence": "submission_evaluator_agent",
        "curriculum_change": "curriculum_advisor_agent",
        "progress_check": "progress_tracker_agent"
    }
    
    @staticmethod
    def get_agent_for_intent(intent: str) -> str:
        """
        Get the agent name for a given intent.
        
        Args:
            intent: Classified intent
        
        Returns:
            Agent name to route to
        """
        return AgentRouter.INTENT_TO_AGENT.get(intent, "academic_qa_agent")
    
    @staticmethod
    def should_escalate(confidence: float, error_count: int = 0) -> bool:
        """
        Determine if message should be escalated due to low confidence.
        
        Args:
            confidence: Classification confidence [0, 1]
            error_count: Number of previous errors in session
        
        Returns:
            True if should escalate to human
        """
        # Escalate if very low confidence or many errors
        return confidence < 0.4 or error_count > 3


def extract_intent_features(message: str) -> Dict[str, bool]:
    """
    Extract linguistic features to support intent classification.
    
    Args:
        message: Student message
    
    Returns:
        Dict of feature flags
    """
    message_lower = message.lower()
    
    return {
        # Academic query indicators
        "has_how_question": message_lower.startswith("how "),
        "has_what_question": message_lower.startswith("what "),
        "has_explain": "explain" in message_lower,
        "has_help": "help" in message_lower,
        "has_understand": "understand" in message_lower or "understand" in message_lower,
        
        # Submission defence indicators
        "has_defend": "defend" in message_lower or "justify" in message_lower,
        "has_why_lost_points": "why" in message_lower and ("lost" in message_lower or "points" in message_lower),
        "has_review": "review" in message_lower or "feedback" in message_lower,
        "has_my_answer": "my answer" in message_lower or "my solution" in message_lower,
        
        # Curriculum change indicators
        "has_curriculum": "curriculum" in message_lower or "syllabus" in message_lower,
        "has_skip": "skip" in message_lower,
        "has_focus": "focus" in message_lower or "focus on" in message_lower,
        "has_different_approach": "different" in message_lower and "approach" in message_lower,
        
        # Progress check indicators
        "has_progress": "progress" in message_lower,
        "has_mastery": "master" in message_lower or "mastered" in message_lower,
        "has_how_doing": "how am i doing" in message_lower,
        "has_achieved": "achieved" in message_lower or "accomplishment" in message_lower or "done" in message_lower,
    }


def classify_with_state(state: AgentState, classifier: IntentClassifier) -> AgentState:
    """
    Classify the current input in the state and update state accordingly.
    
    Args:
        state: Current agent state
        classifier: IntentClassifier instance
    
    Returns:
        Updated agent state with classified intent
    """
    if not state.current_input:
        logger.warning("No current input in state to classify")
        return state
    
    # Classify the message
    intent, confidence, reasoning = classifier.classify(state.current_input)
    
    # Update state
    state.current_intent = intent
    state.eval_state.confidence = confidence
    
    # Route to appropriate agent based on intent
    next_agent = AgentRouter.get_agent_for_intent(intent)
    state.next_agent = next_agent
    
    # Add message to history
    state.add_message(
        role="student",
        content=state.current_input,
        intent=intent
    )
    
    logger.info(
        f"Intent classified for student {state.student_id}: "
        f"{intent} (confidence: {confidence:.2f}) → routing to {next_agent}"
    )
    
    return state
