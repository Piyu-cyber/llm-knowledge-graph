# Phase 4, Part 3: Evaluation, Integrity, and Grader Agents

## Overview

This phase completes the specialized agent suite with three critical components:

1. **Evaluator Agent** - Multi-turn submission defence evaluation
2. **Integrity Agent** - Academic integrity assessment via writing analysis
3. **Grader Agent** - CRAG service upgrade with intelligent confidence-based routing
4. **Cognitive Engine Agent** - Post-evaluation knowledge state updates

Together, these agents form a comprehensive assessment and learning loop.

---

## 11. Evaluator Agent

### Purpose

Conduct multi-turn conversational evaluation of student submissions through Socratic questioning.

### Architecture

```
Student Submission
        ↓
Initial Greeting (eval_turn=0)
        ↓
Least-Confident Concept Lookup
        ↓
Socratic Probing Question
        ↓
Student Response Analysis
        ↓
Confidence Update (all responses so far)
        ↓
Check Termination Conditions:
  ├─ confidence > 0.9? → TERMINATE
  ├─ turn_count >= 10? → TERMINATE
  ├─ student quit + turn>=3? → TERMINATE
  └─ else: Continue loop
        ↓
Generate Grade & Feedback
        ↓
Create DefenceRecord → Neo4j
        ↓
Transfer to IntegrityAgent
```

### Key Features

#### Multi-Turn Management
- **eval_state.turn_count**: Tracks conversation turns
- **eval_state.confidence**: Tracks assessment confidence [0, 1]
- **eval_state.transcript**: Full conversation history

#### Probing Strategy
```python
# Find least-mastered concept
least_confident = get_least_confident_concept(student_id)
# Query: "ORDER BY s.mastery_probability ASC LIMIT 1"

# Generate probing question
question = generate_probing_question(
    concept=least_confident,
    student_response=current_input,
    context=prior_messages
)
```

#### Confidence Tracking
```
base_confidence = 0.5

// Increase with each turn (diminishing)
confidence += min(0.1, turn_count * 0.05)

// Increase with detailed responses
if response_length > 100:
    confidence += 0.15

// Increase with more concepts probed
confidence += min(0.1, num_concepts * 0.05)
```

#### Termination Conditions

| Condition | Trigger |
|-----------|---------|
| **High Confidence** | eval_state.confidence > 0.9 |
| **Max Turns** | eval_state.turn_count >= 10 |
| **Student Exit** | Turn >= 3 AND keywords ("stop", "done", "finished") |

### DefenceRecord Schema

```python
DefenceRecord(
    student_id: str              # Student user ID
    submission_id: str           # Assignment/submission ID
    transcript: List[Dict]       # [{role: "student"|"evaluator", content: "..."}]
    ai_recommended_grade: float  # [0.0, 1.0]
    ai_feedback: str            # Detailed feedback
    integrity_score: float = 0.0  # Updated by Integrity Agent
    status: str = "pending_integrity_review"
    anomalous_input: bool = False # Updated by Integrity Agent
)
```

### Grade Generation

```python
// Analyze all student responses
response_summary = "\n".join([r.content for r in responses])

// Use LLM to assign grade
grade = evaluate_understanding(
    main_concept=least_confident,
    responses=response_summary
)

// Scoring scale
// 0.0-0.3: Does not understand
// 0.3-0.6: Partial understanding
// 0.6-0.8: Good understanding
// 0.8-1.0: Excellent understanding
```

### Usage

```python
from backend.agents import EvaluatorAgent, AgentState

evaluator = EvaluatorAgent()

state = AgentState(
    student_id="student_123",
    session_id="eval_session_456",
    current_input="Here's my answer to problem 1...",
    metadata={"submission_id": "submission_789"}
)

# First turn: initial greeting
result = evaluator.process(state)
# Returns: greeting message + updated eval_state

# Subsequent turns: probing
state.current_input = "...student response..."
result = evaluator.process(state)
# Returns: probing question or termination + DefenceRecord
```

---

## 12. Integrity Agent

### Purpose

Detect potential academic dishonesty by analyzing writing style consistency.

### Architecture

```
Prior TA Interactions
      ↓
Text Extraction (>= 500 tokens?)
      ↓
Build Writing Fingerprint
  - avg_sentence_length
  - vocabulary_richness
  - punctuation_pattern
  - avg_word_length
      ↓
Extract Current Response
      ↓
Compute Style Deviation Index (SDI)
      ↓
map SDI → integrity_score [0, 1]
      ↓
Flag if SDI > 85
      ↓
Update DefenceRecord
      ↓
Suppress SDI display if < 500 tokens
```

### WritingFingerprint

```python
class WritingFingerprint:
    avg_sentence_length: float      # words/sentence
    vocabulary_richness: float      # unique_words/total_words
    punctuation_pattern: Dict       # {'.': 0.45, ',': 0.35, '!': 0.20}
    avg_word_length: float         # chars/word
    token_count: int               # total tokens in baseline
```

### Features Extracted

| Feature | Calculation | Range |
|---------|-------------|-------|
| **Sentence Length** | avg(words per sentence) | [2, 50] |
| **Vocabulary Richness** | unique_words / total_words | [0.3, 1.0] |
| **Punctuation Pattern** | frequency distribution | [0, 1] for each type |
| **Word Length** | avg(chars per word) | [3, 15] |

### Style Deviation Index (SDI)

```
SDI = sqrt(
    W1 * (sent_len_dev)² +
    W2 * (vocab_dev)² +
    W3 * (punct_dev)² +
    W4 * (word_len_dev)²
) * 100

Where:
  dev = |current - baseline| / (baseline + ε)
  W1, W2, W3, W4 = 0.25 (equal weights)

Result:
  SDI = 0: identical writing
  SDI = 100: completely different style
```

### Integrity Score Mapping

```python
// Convert SDI to integrity score [0, 1]
integrity_score = 1.0 - (sdi / 100.0)

// Flag if anomalous
anomalous_input = sdi > 85  # threshold

// Status determination
if anomalous_input:
    status = "flagged"  # Requires manual review
else:
    status = "approved"  # Passes automated check
```

### Suppression Until Sufficient History

```python
min_tokens_threshold = 500

prior_token_count = len(prior_text.split())

if prior_token_count >= min_tokens_threshold:
    // Calculate and display SDI
    sdi = compute_sdi(baseline, current)
    integrity_score = 1.0 - (sdi / 100.0)
else:
    // Insufficient history - suppress SDI calculation
    // Default to moderate score
    integrity_score = 0.8
    sdi_visible = False
```

### Example

```
Prior interactions: 1200 tokens
  - avg_sentence: 14 words
  - vocab_richness: 0.65
  - word_length: 4.8 chars
  - punctuation: {'.': 0.4, ',': 0.3, '!': 0.1, ...}

Current response: 150 tokens
  - avg_sentence: 22 words  (+57%)
  - vocab_richness: 0.88    (+35%)
  - word_length: 6.2 chars   (+29%)
  - punctuation: {'.': 0.5, ',': 0.2, ...}

Deviations:
  sent_dev = |22-14| / (14+ε) ≈ 0.57
  vocab_dev = |0.88-0.65| / (0.65+ε) ≈ 0.35
  word_dev = |6.2-4.8| / (4.8+ε) ≈ 0.29

SDI = sqrt(0.25*(0.57)² + 0.25*(0.35)² + ...) * 100 ≈ 42.0

integrity_score = 1.0 - (42.0/100.0) = 0.58  [MODERATE]

→ Not flagged (SDI < 85)
→ Status: "approved"
```

### Usage

```python
from backend.agents import IntegrityAgent

integrity = IntegrityAgent()

state = AgentState(
    student_id="student_123",
    session_id="eval_session",
    messages=[...],
    metadata={"defence_record_id": "record_789"}
)

result = integrity.process(state)

# Result updates state.metadata with:
# - integrity_score: 0.58
# - anomalous_input: False
# - sdi: 42.0
# - sdi_visible: True
```

---

## 13. Grader Agent (CRAG Upgrade)

### Purpose

Intelligently route CRAG pipeline based on confidence in answer relevance.

### Evolution: GOOD/BAD → Scalar Score

**Before:**
```python
decision = _safe_evaluate(query, context)
if decision == "BAD":
    # retry
else:
    # generate answer
```

**After:**
```python
score = _safe_evaluate(query, context)  # float 0.0-1.0

if score > 0.7:
    # Proceed to generation
elif 0.5 <= score <= 0.7:
    # Ask clarifying question
else:  # score < 0.5
    # Add disclaimer, generate from base knowledge
```

### Scoring Scale

| Score Range | Interpretation | Action |
|-------------|----------------|--------|
| **0.9-1.0** | Directly relevant, course material | Generate answer |
| **0.7-0.9** | Highly relevant, supporting | Generate answer |
| **0.5-0.7** | Somewhat relevant, tangential | Ask clarifying question |
| **0.3-0.5** | Marginally relevant | Generate + disclaimer |
| **0.0-0.3** | Completely irrelevant | Decline + general knowledge |

### LLM Evaluation Updated

```python
def evaluate_relevance(self, query, context):
    prompt = f"""
    Rate relevance of context to query [0.0-1.0]
    
    0.9-1.0: Directly addresses with course material
    0.7-0.9: Highly relevant, some support
    0.5-0.7: Somewhat relevant, tangential
    0.3-0.5: Marginally relevant
    0.0-0.3: Completely irrelevant
    
    Respond with JSON: {{"score": <float>}}
    """
    
    # Parse response
    return float(data['score'])  # e.g. 0.65
```

### Routing Logic

```python
score = _safe_evaluate(refined_query, combined_context)

if score < 0.5:
    # Very low confidence: disclaimer + general knowledge
    answer = llm.generate_answer(query, combined_context)
    answer_with_disclaimer = (
        f"{answer}\n\n"
        f"⚠️ Note: This answer draws on general knowledge, "
        f"not course material. Please consult course documents."
    )
    return {"answer": answer_with_disclaimer, "score": score}

elif 0.5 <= score <= 0.7:
    # Medium confidence: ask clarifying question
    question = _generate_clarifying_question(query, combined_context)
    return {
        "answer": question,
        "type": "clarifying_question",
        "score": score
    }

else:  # score > 0.7
    # High confidence: proceed normally
    answer = llm.generate_answer(query, combined_context)
    return {"answer": answer, "score": score}
```

### Clarifying Question Generation

```python
def _generate_clarifying_question(query, context):
    prompt = f"""
    We have relevant material but need clarification.
    
    Student asked: {query}
    
    Generate ONE clarifying question to:
    - Understand their specific intent
    - Provide better information
    - Narrow down ambiguity
    
    Keep it to 1 sentence.
    """
    return llm.call(prompt)

# Example output:
# "Are you asking about the theoretical foundations 
#  or practical applications of Python decorators?"
```

### Response Structure

```python
# High confidence (> 0.7)
{
    "query": "What is a decorator in Python?",
    "answer": "A decorator is a function wrapper...",
    "confidence": 0.82,
    "grading_score": 0.82
}

# Medium confidence (0.5-0.7)
{
    "query": "What is a decorator in Python?",
    "answer": "Are you asking about practical usage or theory?",
    "type": "clarifying_question",
    "confidence": 0.65,
    "grading_score": 0.65
}

# Low confidence (< 0.5)
{
    "query": "What is a decorator in Python?",
    "answer": "A decorator is a design pattern... ⚠️ Note: This answer...",
    "confidence": 0.35,
    "grading_score": 0.35
}
```

---

## 14. Cognitive Engine Agent

### Purpose

Post-evaluation knowledge state update using Bayesian Knowledge Tracing.

### Workflow

```
Evaluation Complete
        ↓
Extract Probed Concepts
  from eval_transcript
        ↓
Determine Response Quality
  (from ai_recommended_grade)
        ↓
For Each Concept:
  ├─ Get current StudentOverlay (theta, slip)
  ├─ Get concept difficulty
  ├─ Determine: correct = grade > 0.7?
  ├─ Call bayesian_update(theta, slip, difficulty, correct)
  ├─ Update Neo4j StudentOverlay
  └─ Set mastery_probability = new_theta [0, 1]
        ↓
Return Updated State
```

### Concept Identification

```python
def _extract_probed_concepts(transcript):
    # Parse evaluator's probing questions
    concepts = []
    
    for turn in transcript:
        if turn['role'] == 'evaluator':
            question = turn['content']
            # Extract concept terms (simplified)
            words = question.lower().split()
            potential = [w for w in words 
                        if len(w) > 3 and w not in common_words]
            concepts.extend(potential)
    
    # Deduplicate, return top 3
    return list(set(concepts))[:3]
```

### Response Quality Classification

```python
ai_recommended_grade: float  # [0.0, 1.0]

if ai_recommended_grade > 0.7:
    answered_correctly = True   # Good/excellent response
elif ai_recommended_grade > 0.4:
    answered_correctly = None   # Partial (handle separately)
else:
    answered_correctly = False  # Poor response
```

### BKT Update Integration

```python
for concept_id in probed_concepts:
    # Read current state
    theta, slip = get_current_overlay(student_id, concept_id)
    difficulty = get_concept_difficulty(concept_id)
    
    # Update via BKT
    new_theta, new_slip = cognitive_engine.bayesian_update(
        theta=theta,
        slip=slip,
        difficulty=difficulty,
        answered_correctly=True  # or False/None
    )
    
    # Update mastery probability
    new_mastery = clamp(new_theta, 0.0, 1.0)
    
    # Write back
    update_student_overlay(
        student_id=student_id,
        concept_id=concept_id,
        theta=new_theta,
        slip=new_slip,
        mastery_probability=new_mastery
    )
```

### Neo4j Update Query

```cypher
MATCH (s:StudentOverlay 
       {user_id: $user_id, concept_id: $concept_id})
SET s.theta = $new_theta,
    s.slip = $new_slip,
    s.mastery_probability = $new_mastery,
    s.last_updated = datetime()
RETURN s
```

### Example Sequence

```
Turn 1 (TA Agent):
  Student learns "backpropagation"
  NO overlay update yet (learning, not assessment)

Turn 2-N (Evaluation):
  Evaluator probes: "How does backprop minimize error?"
  
  ai_recommended_grade = 0.75  (good response)
  
Cognitive Engine:
  concept_id = "backpropagation"
  current: theta=0.2 (low knowledge)
  difficulty = -0.5 (medium)
  answered_correctly = True (grade > 0.7)
  
  new_theta = bayesian_update(0.2, 0.1, -0.5, True)
            = 0.2 + learning_rate * surprise
            = 0.2 + 0.15 * 0.6
            = 0.29  (increased knowledge)
  
  new_mastery = 0.29
  StudentOverlay updated
```

### Usage

```python
from backend.agents import CognitiveEngineAgent

engine = CognitiveEngineAgent()

state = AgentState(
    student_id="student_123",
    eval_state=EvalState(
        turn_count=4,
        transcript=[...]
    ),
    metadata={
        "ai_recommended_grade": 0.75,
        "defence_record_id": "record_789"
    }
)

result = engine.process(state)

# Updates StudentOverlay for all probed concepts
# Sets metadata['knowledge_updated'] = True
```

---

## Integration Flow

### Complete Evaluation Sequence

```
1. Intent Classification
   input: "I'd like to defend my submission"
   output: intent = "submission_defence"
           → route to EvaluatorAgent

2. Evaluator Agent (turns 1-10)
   Turn 1: Initial greeting + first probing question
   Turn 2-N: Iterative Socratic probing
   Turn N: Check termination → create DefenceRecord
   output: DefenceRecord (pending_integrity_review)
           → transfer to IntegrityAgent

3. Integrity Agent
   input: DefenceRecord + prior TA interactions
   output: integrity_score, anomalous_input flag
           Update DefenceRecord status
           → transfer to CognitiveEngineAgent

4. Cognitive Engine Agent
   input: DefenceRecord + eval_transcript + ai_grade
   output: Updated StudentOverlay for all probed concepts
           theta, slip, mastery_probability
           → Complete learning loop
```

### State Metadata Accumulation

```python
state.metadata = {
    "submission_id": "sub_123",
    "defence_record_id": "rec_456",
    "ai_recommended_grade": 0.75,
    "ai_feedback": "Good understanding of...",
    "integrity_score": 0.92,
    "anomalous_input": False,
    "sdi": 35.0,
    "sdi_visible": True,
    "knowledge_updated": True,
    "update_timestamp": "2026-04-06T14:23:45.123Z"
}
```

---

## Testing Examples

### Evaluator Agent Test

```python
def test_evaluator_multi_turn():
    evaluator = EvaluatorAgent()
    
    # Turn 1: Initial submission
    state = AgentState(
        student_id="s1",
        session_id="eval_1",
        current_input="Here's my solution to problem 1..."
    )
    result = evaluator.process(state)
    assert "Tell me more" in result.messages[-1]["content"]
    assert result.eval_state.turn_count == 1
    
    # Turn 2: Student responds
    state.current_input = "I used approach X because..."
    result = evaluator.process(state)
    assert result.eval_state.turn_count == 2
    assert result.eval_state.confidence > 0.4
    
    # ... continue until termination
    
    # Verify DefenceRecord created
    assert "defence_record_id" in result.metadata
```

### Integrity Agent Test

```python
def test_integrity_detection():
    integrity = IntegrityAgent()
    
    # Simulate baseline (prior interactions)
    # avg_sent_len: 12 words
    # vocab_richness: 0.60
    
    # Current response (very different style)
    # avg_sent_len: 28 words (+133%)
    # vocab_richness: 0.92 (+53%)
    
    sdi = compute_sdi(baseline, current)
    assert sdi > 85  # Flagged as anomalous
    
    assert result.metadata["anomalous_input"] == True
    assert result.metadata["integrity_score"] < 0.2
```

### Cognitive Engine Agent Test

```python
def test_knowledge_update():
    engine = CognitiveEngineAgent()
    
    state = AgentState(
        student_id="s1",
        eval_state=EvalState(
            transcript=[
                {"role": "evaluator", "content": "How does backprop work?"},
                {"role": "student", "content": "It computes gradients..."}
            ]
        ),
        metadata={"ai_recommended_grade": 0.8}
    )
    
    result = engine.process(state)
    
    assert result.metadata["knowledge_updated"] == True
    
    # Verify Neo4j updates
    overlay = neo4j.query(
        "MATCH (s:StudentOverlay {user_id: $uid, concept_id: $cid}) RETURN s",
        {"uid": "s1", "cid": "backpropagation"}
    )
    assert overlay.mastery_probability > 0.5
```

---

## Files

| File | Purpose | Lines |
|------|---------|-------|
| `backend/agents/evaluator_agent.py` | Multi-turn eval | 500+ |
| `backend/agents/integrity_agent.py` | Writing analysis | 400+ |
| `backend/agents/cognitive_engine_agent.py` | BKT updates | 350+ |
| `backend/services/crag_service.py` | CRAG upgrade | Updated |
| `backend/services/llm_service.py` | Scalar scoring | Updated |
| `backend/db/neo4j_schema.py` | DefenceRecord | Added |
| `backend/agents/__init__.py` | Exports | Updated |

---

## Next Steps (Phase 4, Part 4)

1. **LangGraph Workflow**
   - Create multi-agent graph topology
   - Define state transitions and routing
   - Implement error handling and retries

2. **Session Management**
   - Persistent conversation state
   - Agent history tracking
   - Fallback mechanisms

3. **Integration Testing**
   - End-to-end evaluation flow
   - Integrity detection accuracy
   - Knowledge update verification

4. **Optimization**
   - Caching frequent queries
   - Batch Neo4j operations
   - Async evaluation processing

---

## Summary

**Phase 4, Part 3** delivers four specialized agents that complete the assessment and learning loop:

- **Evaluator** conducts intelligent multi-turn defence evaluation
- **Integrity** detects anomalous writing with fingerprint analysis
- **Grader** (CRAG) intelligently routes based on confidence
- **Cognitive Engine** updates student knowledge state via BKT

Together with TA Agent from Part 2, these agents form a comprehensive AI-powered tutoring and assessment system integrated with Neo4j knowledge graphs and Bayesian learning models.
