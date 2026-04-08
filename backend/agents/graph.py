"""
OmniProf LangGraph Multi-Agent Workflow
Orchestrates all agents in a state machine for coordinated AI tutoring.

Workflow Routes:
1. academic_query → TAAgent → Gamification → return
2. submission_defence → EvaluatorAgent → (loop) → IntegrityAgent → CognitiveEngine → Gamification → return
3. curriculum_change → CurriculumAgent (background) → return
4. progress_check → ProgressAgent → return analytics
"""

import logging
from typing import Dict, List, Optional, Any

from langgraph.graph import StateGraph, START, END
from langgraph.types import Command

from backend.agents.state import AgentState, StateCheckpointStore
from backend.agents.intent_classifier import IntentClassifier, AgentRouter
from backend.agents.ta_agent import TAAgent, TAAgentResponse
from backend.agents.evaluator_agent import EvaluatorAgent
from backend.agents.integrity_agent import IntegrityAgent
from backend.agents.cognitive_engine_agent import CognitiveEngineAgent
from backend.agents.curriculum_agent import CurriculumAgent
from backend.agents.gamification_agent import GamificationAgent

logger = logging.getLogger(__name__)


# ==================== Agent Instances ====================

class OmniProfGraph:
    """
    Multi-agent orchestration graph for OmniProf.
    
    Coordinates all agents:
    - IntentClassifier: Determines request type
    - TAAgent: Adaptive tutoring with CRAG
    - EvaluatorAgent: Multi-turn submission evaluation
    - IntegrityAgent: Writing fingerprint analysis
    - CognitiveEngineAgent: BKT knowledge updates
    - CurriculumAgent: Curriculum change propagation
    - GamificationAgent: Achievement tracking
    
    State Flow:
    intent_classifier → router → [agent_select] → agent → [post_processing]
                                    ↓
                          gamification (if not curriculum_change) → END
    """
    
    def __init__(self, **kwargs):
        """Initialize graph and all agents"""
        checkpoint_path = kwargs.pop("checkpoint_path", "data/session_checkpoints.json")

        self.intent_classifier = IntentClassifier()
        self.router = AgentRouter()
        self.checkpoint_store = StateCheckpointStore(checkpoint_path=checkpoint_path)
        
        self.ta_agent = TAAgent(**kwargs)
        self.evaluator_agent = EvaluatorAgent(**kwargs)
        self.integrity_agent = IntegrityAgent(**kwargs)
        self.cognitive_agent = CognitiveEngineAgent(**kwargs)
        self.curriculum_agent = CurriculumAgent(**kwargs)
        self.gamification_agent = GamificationAgent(**kwargs)
        
        self.graph = self._build_graph()
    
    
    # ==================== Graph Building ====================
    
    def _build_graph(self) -> StateGraph:
        """
        Build the LangGraph state machine.
        
        Returns:
            Compiled StateGraph
        """
        # Create graph structure
        builder = StateGraph(AgentState)
        
        # Add nodes
        builder.add_node("intent_classifier", self._intent_classifier_node)
        builder.add_node("ta_agent", self._ta_agent_node)
        builder.add_node("evaluator_agent", self._evaluator_agent_node)
        builder.add_node("integrity_agent", self._integrity_agent_node)
        builder.add_node("cognitive_agent", self._cognitive_engine_node)
        builder.add_node("curriculum_agent", self._curriculum_agent_node)
        builder.add_node("gamification_agent", self._gamification_agent_node)
        builder.add_node("progress_agent", self._progress_agent_node)
        builder.add_node("error_handler", self._error_handler_node)
        
        # Add edges
        builder.add_edge(START, "intent_classifier")
        
        # Route from intent classifier
        builder.add_conditional_edges(
            "intent_classifier",
            self._route_by_intent,
            {
                "ta_agent": "ta_agent",
                "evaluator_agent": "evaluator_agent",
                "curriculum_agent": "curriculum_agent",
                "progress_agent": "progress_agent",
                "error": "error_handler"
            }
        )
        
        # TA Agent → Gamification → END
        builder.add_edge("ta_agent", "gamification_agent")
        builder.add_edge("gamification_agent", END)
        
        # Evaluator → Integrity → Cognitive → Gamification → END
        builder.add_conditional_edges(
            "evaluator_agent",
            self._check_evaluation_complete,
            {
                "continue": "evaluator_agent",  # Multi-turn loop
                "integrity": "integrity_agent"  # Move to next phase
            }
        )
        builder.add_edge("integrity_agent", "cognitive_agent")
        builder.add_edge("cognitive_agent", "gamification_agent")
        builder.add_edge("gamification_agent", END)
        
        # Curriculum Agent → END (no gamification, background task)
        builder.add_edge("curriculum_agent", END)
        
        # Progress Agent → END
        builder.add_edge("progress_agent", END)
        
        # Error Handler → END
        builder.add_edge("error_handler", END)
        
        # Compile
        return builder.compile()
    
    
    # ==================== Node Functions ====================
    
    def _intent_classifier_node(self, state: AgentState) -> AgentState:
        """
        Classify user intent from current_input.
        
        Args:
            state: Current agent state
        
        Returns:
            Updated state with recognized intent
        """
        try:
            logger.info(f"IntentClassifier: Processing input from {state.student_id}")
            
            # Classify intent
            intent, _, _ = self.intent_classifier.classify(state.current_input)
            
            state.metadata["intent"] = intent
            logger.debug(f"Classified intent: {intent}")
            
            return state
            
        except Exception as e:
            logger.error(f"IntentClassifier error: {str(e)}")
            state.error = str(e)
            state.error_count += 1
            return state
    
    
    def _ta_agent_node(self, state: AgentState) -> AgentState:
        """
        TA Agent: Adaptive tutoring with CRAG.
        
        Args:
            state: Current agent state
        
        Returns:
            Updated state with TA response
        """
        try:
            logger.info(f"TAAgent: Processing academic query for {state.student_id}")
            
            state = self.ta_agent.process(state)
            
            logger.debug(f"TAAgent complete: CRAG score {state.metadata.get('crag_score')}")
            
            return state
            
        except Exception as e:
            logger.error(f"TAAgent error: {str(e)}")
            state.error = str(e)
            state.error_count += 1
            return state
    
    
    def _evaluator_agent_node(self, state: AgentState) -> AgentState:
        """
        Evaluator Agent: Multi-turn submission evaluation.
        
        Args:
            state: Current agent state
        
        Returns:
            Updated state with evaluation
        """
        try:
            logger.info(f"EvaluatorAgent: Evaluating submission for {state.student_id}")
            
            state = self.evaluator_agent.process(state)
            
            confidence = state.eval_state.confidence if state.eval_state else 0.0
            logger.debug(f"EvaluatorAgent: Confidence {confidence:.2f}")
            
            return state
            
        except Exception as e:
            logger.error(f"EvaluatorAgent error: {str(e)}")
            state.error = str(e)
            state.error_count += 1
            return state
    
    
    def _integrity_agent_node(self, state: AgentState) -> AgentState:
        """
        Integrity Agent: Writing fingerprint analysis.
        
        Args:
            state: Current agent state
        
        Returns:
            Updated state with integrity analysis
        """
        try:
            logger.info(f"IntegrityAgent: Analyzing writing for {state.student_id}")
            
            state = self.integrity_agent.process(state)
            
            sdi = state.metadata.get("sdi", 0)
            logger.debug(f"IntegrityAgent: SDI score {sdi:.1f}")
            
            return state
            
        except Exception as e:
            logger.error(f"IntegrityAgent error: {str(e)}")
            state.error = str(e)
            state.error_count += 1
            return state
    
    
    def _cognitive_engine_node(self, state: AgentState) -> AgentState:
        """
        Cognitive Engine: Bayesian Knowledge Tracing updates.
        
        Args:
            state: Current agent state
        
        Returns:
            Updated state with BKT updates
        """
        try:
            logger.info(f"CognitiveEngineAgent: Updating knowledge state for {state.student_id}")
            
            state = self.cognitive_agent.process(state)
            
            concepts_updated = len(state.metadata.get("cognition_updates", []))
            logger.debug(f"CognitiveEngineAgent: Updated {concepts_updated} concepts")
            
            return state
            
        except Exception as e:
            logger.error(f"CognitiveEngineAgent error: {str(e)}")
            state.error = str(e)
            state.error_count += 1
            return state
    
    
    def _curriculum_agent_node(self, state: AgentState) -> AgentState:
        """
        Curriculum Agent: Background change propagation.
        
        Launches async background task, returns immediately.
        
        Args:
            state: Current agent state
        
        Returns:
            Updated state with background task queued
        """
        try:
            logger.info(f"CurriculumAgent: Queuing background task for {state.current_input}")
            
            # Extract curriculum change metadata
            change_data = state.metadata.get("curriculum_change", {})
            course_id = change_data.get("course_id", "")
            change_type = change_data.get("change_type", "")
            node_id = change_data.get("node_id", "")
            node_type = change_data.get("node_type", "")
            
            # Queue background task (actual execution happens in FastAPI)
            state.metadata["background_task"] = {
                "agent": "curriculum_agent",
                "function": "process_curriculum_change",
                "args": {
                    "course_id": course_id,
                    "change_type": change_type,
                    "node_id": node_id,
                    "node_type": node_type
                }
            }
            
            logger.debug(f"Background task queued: curriculum change {change_type}")
            
            return state
            
        except Exception as e:
            logger.error(f"CurriculumAgent error: {str(e)}")
            state.error = str(e)
            state.error_count += 1
            return state
    
    
    def _gamification_agent_node(self, state: AgentState) -> AgentState:
        """
        Gamification Agent: Achievement tracking.
        
        Runs after every sub-agent response (except curriculum).
        
        Args:
            state: Current agent state
        
        Returns:
            Updated state with new achievements
        """
        try:
            logger.info(f"GamificationAgent: Checking milestones for {state.student_id}")
            
            state = self.gamification_agent.process(state)
            
            achievements = state.metadata.get("new_achievements_count", 0)
            logger.debug(f"GamificationAgent: {achievements} new achievements")
            
            return state
            
        except Exception as e:
            logger.error(f"GamificationAgent error: {str(e)}")
            state.error = str(e)
            state.error_count += 1
            return state
    
    
    def _progress_agent_node(self, state: AgentState) -> AgentState:
        """
        Progress Agent: Retrieve learning analytics.
        
        Args:
            state: Current agent state
        
        Returns:
            Updated state with progress data
        """
        try:
            logger.info(f"ProgressAgent: Generating analytics for {state.student_id}")
            graph_manager = self.ta_agent.graph_manager
            
            # Retrieve student learning analytics from graph
            overlays = graph_manager.get_all_student_overlays(state.student_id)
            mastered = [o for o in overlays if o.get("mastery_probability", 0) >= 0.8]
            visited_modules = set()
            for o in overlays:
                node = graph_manager.get_concept_by_id(o.get("concept_id", ""))
                if node:
                    visited_modules.add(node.get("module_id", ""))
            
            state.metadata["progress_data"] = {
                "modules_explored": len(visited_modules),
                "concepts_visited": len([o for o in overlays if o.get("visited")]),
                "concepts_mastered": len(mastered),
                "average_mastery": sum(o.get("mastery_probability", 0) for o in overlays) / max(1, len(overlays)),
                "overlay_count": len(overlays)
            }
            
            state.active_agent = "progress_agent"
            
            return state
            
        except Exception as e:
            logger.error(f"ProgressAgent error: {str(e)}")
            state.error = str(e)
            state.error_count += 1
            return state
    
    
    def _error_handler_node(self, state: AgentState) -> AgentState:
        """
        Error handler for classification failures.
        
        Args:
            state: Current agent state
        
        Returns:
            Updated state with error message
        """
        logger.error(f"ErrorHandler: Failed to classify intent for {state.student_id}")
        
        state.active_agent = "error_handler"
        state.messages.append({
            "role": "assistant",
            "content": "I couldn't understand your request. Please try rephrasing."
        })
        
        return state
    
    
    # ==================== Routing Logic ====================
    
    def _route_by_intent(self, state: AgentState) -> str:
        """
        Route to agent based on classified intent.
        
        Args:
            state: Current agent state
        
        Returns:
            Next node name
        """
        intent = state.metadata.get("intent")
        
        if intent == "academic_query":
            return "ta_agent"
        elif intent == "submission_defence":
            return "evaluator_agent"
        elif intent == "curriculum_change":
            return "curriculum_agent"
        elif intent == "progress_check":
            return "progress_agent"
        else:
            logger.warning(f"Unknown intent: {intent}")
            return "error"
    
    
    def _check_evaluation_complete(self, state: AgentState) -> str:
        """
        Check if evaluator should continue or move to integrity check.
        
        Multi-turn evaluation continues until:
        - Confidence > 0.9, OR
        - Turn count >= 10, OR
        - Error encountered
        
        Args:
            state: Current agent state
        
        Returns:
            "continue" for next turn, "integrity" to move forward
        """
        eval_state = state.eval_state
        
        if not eval_state:
            return "integrity"
        
        # Termination conditions
        if eval_state.confidence >= 0.9:
            logger.info("Evaluation: High confidence reached, moving to integrity check")
            return "integrity"
        
        if eval_state.turn_count >= 10:
            logger.info("Evaluation: Max turns reached, moving to integrity check")
            return "integrity"
        
        if state.error:
            logger.warning("Evaluation: Error encountered, moving to integrity check")
            return "integrity"
        
        # Continue evaluation
        logger.debug(f"Evaluation: Turn {eval_state.turn_count}, confidence {eval_state.confidence:.2f}")
        return "continue"
    
    
    # ==================== Graph Execution ====================
    
    def invoke(self, state: AgentState) -> AgentState:
        """
        Execute graph with given initial state.
        
        Args:
            state: Initial agent state
        
        Returns:
            Final agent state after graph execution
        """
        try:
            logger.info(f"OmniProfGraph: Starting execution for {state.student_id}")

            if state.metadata.get("restore_checkpoint"):
                restored = self.checkpoint_store.load(state.session_id)
                if restored and restored.student_id == state.student_id:
                    restored.current_input = state.current_input
                    if not restored.messages or restored.messages[-1].get("content") != state.current_input:
                        restored.messages.append({"role": "student", "content": state.current_input})
                    restored.metadata.update(state.metadata)
                    state = restored
            
            # Run graph
            result = self.graph.invoke(state)

            # Persist checkpoint after each successful step for crash-safe resume.
            self.checkpoint_store.save(result)
            
            logger.info(f"OmniProfGraph: Completed execution, "
                       f"final_agent={result.active_agent}, "
                       f"errors={result.error_count}")
            
            return result
            
        except Exception as e:
            logger.error(f"OmniProfGraph execution error: {str(e)}", exc_info=True)
            state.error = str(e)
            state.error_count += 1
            try:
                self.checkpoint_store.save(state)
            except Exception:
                pass
            return state

    def load_checkpoint(self, session_id: str) -> Optional[AgentState]:
        """Load a saved session checkpoint by session_id."""
        return self.checkpoint_store.load(session_id)
    
    
    async def ainvoke(self, state: AgentState) -> AgentState:
        """
        Async execution of graph.
        
        Args:
            state: Initial agent state
        
        Returns:
            Final agent state after graph execution
        """
        try:
            logger.info(f"OmniProfGraph: Starting async execution for {state.student_id}")
            
            # Run graph asynchronously
            result = await self.graph.ainvoke(state)
            
            logger.info(f"OmniProfGraph: Completed async execution, "
                       f"final_agent={result.active_agent}")
            
            return result
            
        except Exception as e:
            logger.error(f"OmniProfGraph async execution error: {str(e)}", exc_info=True)
            state.error = str(e)
            state.error_count += 1
            return state


# ==================== Module-Level Graph Instance ====================

def get_graph_instance(**kwargs) -> OmniProfGraph:
    """
    Get or create the OmniProf graph instance.
    
    Args:
        **kwargs: Arguments to pass to OmniProfGraph
    
    Returns:
        OmniProfGraph instance
    """
    return OmniProfGraph(**kwargs)
