# Phase 4, Part 2: TA Agent Implementation

## Overview

The **TA Agent** is a specialized LangGraph node that provides adaptive tutoring using a **Corrective RAG (CRAG) loop** with intelligent explanation depth adaptation and Socratic questioning.

**Key Features:**
- ✅ CRAG pipeline for knowledge retrieval
- ✅ Adaptive explanation depth based on `mastery_probability`
- ✅ Socratic questioning for low-mastery concepts (< 0.4)
- ✅ Automatic student overlay updates with cognitive engine
- ✅ Concept extraction and mastery tracking

---

## Architecture

### Agent Flow

```
┌─────────────────────────────────┐
│   Student Query (AgentState)    │
└──────────────┬──────────────────┘
               │
       ┌───────▼────────┐
       │  CRAG Loop     │
       │  (retrieve)    │
       │  - RAG search  │
       │  - Graph query │
       │  - Generate    │
       └───────┬────────┘
               │
       ┌───────▼──────────────┐
       │ Concept Extraction   │
       │ - NLP-based          │
       │ - Domain concepts    │
       └───────┬──────────────┘
               │
       ┌───────▼──────────────┐
       │ Mastery Retrieval    │
       │ - StudentOverlay     │
       │ - Per-concept        │
       └───────┬──────────────┘
               │
       ┌───────▼──────────────┐
       │ Explanation Depth    │
       │ - basic       (<0.6) │
       │ - intermediate(0.6-8)│
       │ - advanced    (>0.8) │
       └───────┬──────────────┘
               │
       ┌───────▼──────────────┐
       │ Socratic Check       │
       │ - mastery < 0.4?     │
       │ - gen question       │
       └───────┬──────────────┘
               │
       ┌───────▼──────────────┐
       │ Response Building    │
       │ - adapt depth        │
       │ - apply Socratic     │
       │ - recommend steps    │
       └───────┬──────────────┘
               │
       ┌───────▼──────────────┐
       │ Update Overlays      │
       │ - call cognitive_eng │
       │ - record interaction │
       └───────┬──────────────┘
               │
       ┌───────▼──────────────┐
       │ Return Updated State │
       │ (with response)      │
       └──────────────────────┘
```

---

## Implementation Details

### 1. CRAG Loop (`_run_crag_loop`)

**Purpose:** Retrieve relevant knowledge using Corrective RAG

**Process:**
1. Retrieve candidates from RAG + Graph
2. Score relevance of context
3. If score is low, refine and retry
4. Generate answer from best context

**Example:**
```python
query = "How does backpropagation work?"
crag_result = agent._run_crag_loop(query)

# Returns:
# {
#   "query": "How does backpropagation work?",
#   "answer": "...",
#   "confidence": 0.85,
#   "graph_results": [...],
#   "rag_results": [...]
# }
```

---

### 2. Concept Extraction (`_extract_concepts`)

**Purpose:** Extract domain concepts from query and answer

**Strategy:**
- Combined query + answer analysis
- LLM-based concept recognition
- Domain knowledge extraction

**Example:**
```python
query = "What's the difference between supervised and unsupervised learning?"
answer = "Supervised learning uses labeled data..."

concepts = agent._extract_concepts(query, answer)
# ["supervised_learning", "unsupervised_learning", "labeled_data", ...]
```

---

### 3. Mastery Retrieval (`_get_student_mastery`)

**Purpose:** Get student's mastery probability for each concept

**Query:**
```cypher
MATCH (s:StudentOverlay {user_id: $user_id})
MATCH (c:CONCEPT {name: $concept})
MATCH (s)-[:KNOWS]->(c)
RETURN s.mastery_probability as mastery
```

**Returns:**
```python
{
  "supervised_learning": 0.75,
  "unsupervised_learning": 0.35,
  "labeled_data": 0.85
}
```

---

### 4. Explanation Depth Adaptation

**Depth Levels:**

| Level | Mastery Range | Characteristics | Examples |
|-------|---------------|-----------------|----------|
| **basic** | < 0.6 | Simple language, analogies, concrete examples | "Think of supervised learning like learning with a teacher who corrects you..." |
| **intermediate** | 0.6-0.8 | Context, connections, moderate detail | "Supervised learning builds on labeled data to learn patterns, while unsupervised..." |
| **advanced** | > 0.8 | Deep reasoning, edge cases, applications, research | "Recent advances in semi-supervised learning leverage manifold assumptions..." |

**Algorithm:**
```python
def determine_explanation_depth(mastery_data):
    avg_mastery = mean(mastery_data.values())
    
    if avg_mastery < 0.6:
        return "basic"
    elif avg_mastery < 0.8:
        return "intermediate"
    else:
        return "advanced"
```

**Adaptations:**
- **Basic:** Simplify, add analogies, concrete examples
- **Advanced:** Deepen, add connections, discuss applications

---

### 5. Socratic Questioning

**Trigger Condition:**
- Primary concept mastery < 0.4
- Student has knowledge gap

**Example Flow:**

```
Student: "What is gradient descent?"
System: Detects low mastery (0.2) on "gradient_descent"

TA Agent Response:
"Before I explain gradient descent, let me ask you a question:
 
How do you think a system could find the best values of parameters 
to minimize errors in predictions? What tools or strategies might you use?"

[Guides student to discover concept through questioning]
```

**Socratic Response Generation:**
1. Generate probing question
2. Guide through key concepts
3. Ask follow-up questions
4. Avoid direct answers
5. Help student discover understanding

---

### 6. Student Overlay Updates

**Purpose:** Record interaction and update knowledge state

**Process:**
For each concept discussed:

```python
cognitive_engine.update_student_overlay(
    user_id=student_id,
    concept_id=concept,
    answered_correctly=True,        # Exposure to material + explanation
    difficulty=None                 # Auto-estimated from prerequisites
)
```

**Updates (via BKT):**
- `theta` (ability parameter)
- `slip` (careless error probability)
- `mastery_probability` = P(student knows concept)

---

## Usage

### As a LangGraph Node

```python
from backend.agents import TAAgent, AgentState
from datetime import datetime

# Initialize
ta_agent = TAAgent()

# Create state
state = AgentState(
    student_id="student_123",
    session_id="session_abc",
    current_input="How does neural networks learn?",
    messages=[]
)

# Process
updated_state = ta_agent.process(state)

# Output
print(updated_state.messages[-1]["content"])
# Adaptive response with appropriate depth + possibly Socratic question
```

### Standalone Usage

```python
# Get response details
ta_response = agent._build_adaptive_response(
    crag_result={...},
    concepts=["neural_network", "backpropagation"],
    mastery_data={"neural_network": 0.3, "backpropagation": 0.2},
    explanation_depth="basic",
    should_use_socratic=True,
    primary_concept="neural_network"
)

print(f"Depth: {ta_response.explanation_depth}")
print(f"Socratic: {ta_response.is_socratic}")
print(f"Question: {ta_response.socratic_question}")
print(f"Confidence: {ta_response.confidence}")
```

---

## Configuration

### Mastery Thresholds

```python
ta_agent.mastery_threshold_socratic = 0.4   # Use Socratic if < 0.4
ta_agent.mastery_threshold_basic = 0.6      # Basic depth if < 0.6
ta_agent.mastery_threshold_advanced = 0.8   # Advanced if >= 0.8
```

### LLM Model

```python
# Using Groq's Llama 3.3 70B for better reasoning
ta_agent.model = "llama-3.3-70b-versatile"
```

---

## Error Handling

**Graceful Degradation:**
- CRAG fails → Return default message
- Concept extraction fails → Use input query keywords
- Mastery lookup fails → Default to 0.5
- Overlay update fails → Log warning, continue

**Error Categories:**
1. **Non-Fatal:** Concept extraction, mastery lookup → continue with defaults
2. **Fatal:** CRAG loop, response building → fallback message
3. **Session-level:** Logged to state.error, error_count incremented

---

## Integration with LangGraph

### In Multi-Agent Workflow

```python
# Create LangGraph workflow
workflow = StateGraph(AgentState)

# Add TA Agent node
workflow.add_node("ta_agent", ta_agent.process)

# Routing logic
def should_use_ta_agent(state: AgentState) -> str:
    if state.current_intent == "academic_query":
        return "ta_agent"
    elif state.current_intent == "submission_defence":
        return "evaluator_agent"
    else:
        return "other_agent"

workflow.add_conditional_edges(
    "router",
    should_use_ta_agent,
    {
        "ta_agent": "ta_agent",
        "evaluator_agent": "evaluator_agent",
        "other_agent": "other_agent"
    }
)
```

---

## Cognitive Science Integration

### Bayesian Knowledge Tracing (BKT)

The TA Agent integrates with the Cognitive Engine's BKT model:

**Knowledge State (θ):**
- Probability student knows concept
- Updated based on interactions
- IRT 2-parameter logistic model

**Slip Probability:**
- P(incorrect despite knowing)
- Distinguishes careless errors from knowledge gaps

**Mastery Update:**
- Uses Bayesian reasoning
- Incorporates prerequisite structure
- Accounts for both slip and learning

### Adaptive Pedagogy

**Student-Centered Approach:**
1. **Assess:** Retrieve mastery_probability
2. **Adapt:** Personalize explanation depth
3. **Engage:** Use appropriate teaching strategy
4. **Update:** Record learning outcome
5. **Track:** Monitor progress over time

---

## Testing Example

```python
from backend.agents import TAAgent, AgentState

# Setup
agent = TAAgent()
state = AgentState(
    student_id="test_student",
    session_id="test_session",
    current_input="What is a neural network?",
    messages=[]
)

# Process
result = agent.process(state)

# Verify
assert len(result.messages) > 0
assert result.active_agent == "ta_agent"
assert result.graph_context.metadata.get("confidence", 0) > 0

# Check response characteristics
last_response = result.messages[-1]["content"]
print(f"✓ Response length: {len(last_response)} chars")
print(f"✓ Explanation depth: {result.graph_context.metadata.get('explanation_depth')}")
print(f"✓ Socratic approach: {result.graph_context.metadata.get('socratic')}")
```

---

## Files

| File | Purpose |
|------|---------|
| `backend/agents/ta_agent.py` | TA Agent implementation |
| `backend/agents/state.py` | State definitions (AgentState, EvalState, GraphContext) |
| `backend/agents/intent_classifier.py` | Intent classification & routing |
| `backend/agents/__init__.py` | Package exports |

---

## Next Steps (Phase 4, Part 3)

1. **Implement other specialized agents:**
   - AcademicQAAgent (alternative Q&A approach)
   - SubmissionEvaluator (grading and feedback)
   - CurriculumAdvisor (learning path recommendations)
   - ProgressTracker (analytics and reporting)

2. **Create LangGraph orchestration:**
   - Multi-agent workflow
   - State transitions
   - Agent coordination

3. **Implement Evaluator agent:**
   - Conversation quality assessment
   - Response rating
   - Improvement recommendations

4. **Add error recovery:**
   - Fallback mechanisms
   - User clarification prompts
   - Graceful degradation

5. **Performance optimization:**
   - Caching mastery lookups
   - Parallel concept extraction
   - Batch overlay updates

---

## Summary

The **TA Agent** brings together CRAG retrieval, adaptive pedagogy, and Bayesian knowledge modeling to provide personalized, context-aware tutoring. It intelligently adapts its teaching approach based on student mastery levels and applies Socratic questioning to deepen understanding when needed.

**Key Achievement:** Students receive explanations tailored to their knowledge state, with automatic tracking of learning progress through the cognitive engine integration.
