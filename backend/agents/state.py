"""
OmniProf Agent State
Shared state for LangGraph multi-agent system
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime
import json
import os


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

    def to_dict(self) -> Dict[str, Any]:
        """Serialize state for persistent checkpointing."""
        return {
            "student_id": self.student_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp.isoformat(),
            "messages": self.messages,
            "current_input": self.current_input,
            "current_intent": self.current_intent,
            "active_agent": self.active_agent,
            "agent_history": self.agent_history,
            "graph_context": {
                "query_text": self.graph_context.query_text,
                "retrieved_concepts": self.graph_context.retrieved_concepts,
                "prerequisites": self.graph_context.prerequisites,
                "related_facts": self.graph_context.related_facts,
                "metadata": self.graph_context.metadata,
            },
            "crag_score": self.crag_score,
            "student_overlay_data": self.student_overlay_data,
            "eval_state": {
                "turn_count": self.eval_state.turn_count,
                "confidence": self.eval_state.confidence,
                "transcript": self.eval_state.transcript,
            },
            "should_transfer": self.should_transfer,
            "transfer_reason": self.transfer_reason,
            "next_agent": self.next_agent,
            "error": self.error,
            "error_count": self.error_count,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "AgentState":
        """Deserialize state from persistent checkpoint payload."""
        state = cls(
            student_id=str(payload.get("student_id", "")),
            session_id=str(payload.get("session_id", "")),
            timestamp=datetime.fromisoformat(payload.get("timestamp")) if payload.get("timestamp") else datetime.now(),
            messages=payload.get("messages", []) or [],
            current_input=str(payload.get("current_input", "")),
            current_intent=str(payload.get("current_intent", "")),
            active_agent=str(payload.get("active_agent", "")),
            agent_history=payload.get("agent_history", []) or [],
            crag_score=float(payload.get("crag_score", 0.0) or 0.0),
            student_overlay_data=payload.get("student_overlay_data", {}) or {},
            should_transfer=bool(payload.get("should_transfer", False)),
            transfer_reason=str(payload.get("transfer_reason", "")),
            next_agent=payload.get("next_agent"),
            error=payload.get("error"),
            error_count=int(payload.get("error_count", 0) or 0),
            metadata=payload.get("metadata", {}) or {},
        )

        graph_context = payload.get("graph_context", {}) or {}
        state.graph_context = GraphContext(
            query_text=str(graph_context.get("query_text", "")),
            retrieved_concepts=graph_context.get("retrieved_concepts", []) or [],
            prerequisites=graph_context.get("prerequisites", []) or [],
            related_facts=graph_context.get("related_facts", []) or [],
            metadata=graph_context.get("metadata", {}) or {},
        )

        eval_state = payload.get("eval_state", {}) or {}
        state.eval_state = EvalState(
            turn_count=int(eval_state.get("turn_count", 0) or 0),
            confidence=float(eval_state.get("confidence", 0.5) or 0.5),
            transcript=eval_state.get("transcript", []) or [],
        )
        return state


class StateCheckpointStore:
    """Simple JSON-backed checkpoint store for LangGraph session states."""

    def __init__(self, checkpoint_path: str = "data/session_checkpoints.json"):
        self.checkpoint_path = checkpoint_path
        parent = os.path.dirname(checkpoint_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    def _read_all(self) -> Dict[str, Dict[str, Any]]:
        if not os.path.exists(self.checkpoint_path):
            return {}
        try:
            with open(self.checkpoint_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _write_all(self, payload: Dict[str, Dict[str, Any]]) -> None:
        with open(self.checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def save(self, state: AgentState) -> None:
        all_states = self._read_all()
        all_states[state.session_id] = state.to_dict()
        self._write_all(all_states)

    def load(self, session_id: str) -> Optional[AgentState]:
        all_states = self._read_all()
        payload = all_states.get(session_id)
        if not payload:
            return None
        return AgentState.from_dict(payload)
