"""
OmniProf Agent State
Shared state for LangGraph multi-agent system
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime


@dataclass
class EvalState:
    """Evaluation state tracking conversation metrics"""
    turn_count: int = 0                    # Number of conversation turns
    confidence: float = 0.5                # Current confidence level [0, 1]
    transcript: List[Dict[str, str]] = field(default_factory=list)  # Conversation history


@dataclass
class GraphContext:
    """Graph query context for semantic search"""
    query_text: str = ""                   # Original user query
    retrieved_concepts: List[Dict] = field(default_factory=list)  # Retrieved concept nodes
    prerequisites: List[Dict] = field(default_factory=list)  # Prerequisite chains
    related_facts: List[Dict] = field(default_factory=list)  # Related facts and details
    metadata: Dict[str, Any] = field(default_factory=dict)  # Additional metadata


@dataclass
class AgentState:
    """
    Shared state for LangGraph multi-agent orchestration.
    
    All agents in the graph read and update this state.
    Manages conversation context, knowledge graph references, and evaluation metrics.
    """
    
    # === Session Information ===
    student_id: str                        # Student user ID
    session_id: str                        # Unique session identifier
    timestamp: datetime = field(default_factory=datetime.now)  # Session start time
    
    # === Conversation Context ===
    messages: List[Dict[str, str]] = field(default_factory=list)  # Conversation history
    # Each message: {"role": "student|assistant", "content": "...", "intent": "..."}
    
    current_input: str = ""                # Current user input
    current_intent: str = ""               # Classified intent (academic_query|submission_defence|curriculum_change|progress_check)
    
    # === Agent Routing ===
    active_agent: str = ""                 # Currently active agent name
    # Possible agents: intent_classifier, academic_qa, submission_evaluator, curriculum_advisor, progress_tracker
    
    agent_history: List[str] = field(default_factory=list)  # History of agents used in session
    
    # === Knowledge Graph Context ===
    graph_context: GraphContext = field(default_factory=GraphContext)  # Retrieved graph information
    
    # === Learning Model State ===
    crag_score: float = 0.0                # Correctness Rating for Augmented Generation [0, 1]
    # Measures confidence in RAG responses with graph augmentation
    
    student_overlay_data: Dict[str, float] = field(default_factory=dict)  # Student's knowledge state
    # {concept_id: theta, concept_id: theta, ...}
    
    # === Evaluation and Metrics ===
    eval_state: EvalState = field(default_factory=EvalState)  # Conversation evaluation metrics
    
    # === Routing Decisions ===
    should_transfer: bool = False          # Whether to transfer to different agent
    transfer_reason: str = ""              # Reason for transfer
    
    next_agent: Optional[str] = None       # Which agent to route to next
    
    # === Error Handling ===
    error: Optional[str] = None            # Last error message if any
    error_count: int = 0                   # Number of errors in session
    
    # === Metadata ===
    metadata: Dict[str, Any] = field(default_factory=dict)  # Custom metadata
    
    def add_message(self, role: str, content: str, intent: str = ""):
        """
        Add a message to conversation history.
        
        Args:
            role: "student" or "assistant"
            content: Message content
            intent: Classified intent (for student messages)
        """
        message = {
            "role": role,
            "content": content,
            "intent": intent,
            "timestamp": datetime.now().isoformat()
        }
        self.messages.append(message)
        self.eval_state.turn_count += 1
    
    def get_conversation_summary(self) -> str:
        """Get formatted conversation history for context"""
        summary = []
        for msg in self.messages:
            role = "Student" if msg["role"] == "student" else "Assistant"
            summary.append(f"{role}: {msg['content']}")
        return "\n".join(summary)
    
    def get_last_n_messages(self, n: int = 5) -> List[Dict[str, str]]:
        """Get last n messages from conversation"""
        return self.messages[-n:] if len(self.messages) >= n else self.messages
    
    def update_overlay_data(self, concept_id: str, theta: float):
        """Update student's knowledge state for a concept"""
        self.student_overlay_data[concept_id] = theta
    
    def mark_transfer(self, next_agent: str, reason: str = ""):
        """Mark state for agent transfer"""
        self.should_transfer = True
        self.next_agent = next_agent
        self.transfer_reason = reason
        self.agent_history.append(next_agent)
    
    def clear_transfer_flag(self):
        """Clear transfer flag after routing"""
        self.should_transfer = False
        self.next_agent = None
        self.transfer_reason = ""
