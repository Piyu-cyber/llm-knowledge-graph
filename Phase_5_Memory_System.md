# Phase 5: Dual-Store Memory System

## Overview

Phase 5 implements a comprehensive dual-store memory architecture that enhances the TA Agent with contextual learning from past interactions. The system combines **episodic memory** (vector-based chat history) with **semantic memory** (extracted facts and concepts) to provide rich, personalized context during tutoring interactions.

## architecture: Three-Tier Context Assembly

### 1. Episodic Memory Store (FAISS)
**File:** `backend/services/memory_service.py`

Stores vector embeddings of chat interactions with intelligent temporal scoring:

#### EpisodicRecord
- **message**: Original chat message text
- **embedding**: 384-dimensional vector (Sentence Transformers)
- **timestamp_unix**: Unix timestamp of interaction
- **session_id**: Associated session ID
- **concept_node_ids**: Concepts active in this turn
- **turn_number**: Conversation turn counter

#### Temporal Decay Scoring
$$\text{temporal\_score} = \text{base\_score} \times e^{-\lambda \times \text{days\_since}}$$

Where:
- λ = 0.1 (default temporal decay constant)
- days_since = (current_timestamp - memory_timestamp) / (24 × 3600)
- base_score = 1.0 / (1.0 + L2_distance) for normalized similarity

**Concept Overlap Override**: If current query's concept IDs overlap with a memory record's concepts, full weight is used regardless of age:
```
final_score = base_score if has_concept_overlap else temporal_score
```

#### FAISS Index
- L2 (Euclidean) distance metric for similarity
- Automatic indexing on every write
- Periodic persistence to disk (`data/episode_memory.faiss`)
- In-memory metadata mapping: faiss_id → record metadata

### 2. Semantic Memory (Neo4j)
**File:** `backend/db/neo4j_schema.py` + `backend/agents/summarisation_agent.py`

Stores extracted facts and learned concepts linked to student overlays:

#### SemanticNode Class
```python
class SemanticNode:
    student_id: str           # Student who learned this
    fact: str                 # Extracted fact/insight
    concept_id: str           # Related concept
    confidence: float         # 0.0-1.0 confidence
    source_session_id: str    # Where fact was extracted
    access_count: int         # Usage tracking
    last_accessed: str        # Last retrieval timestamp
```

#### Extraction Process
1. **SummarisationAgent** generates session summary via LLM
2. **_extract_facts_from_summary()** uses JSON extraction
3. Facts are mapped to concepts discussed in session
4. SemanticNode entries linked to student via `LEARNED_FROM` relationship
5. Linked to concepts via `EXTRACTED_FROM` relationship

#### Neo4j Relationships
```
(Student) -[:LEARNED_FROM]-> (SemanticNode) -[:EXTRACTED_FROM]-> (Concept)
```

**Access Tracking**: `access_count` and `last_accessed` updated on every retrieval

### 3. Context Window Assembly

**File:** `backend/agents/ta_agent.py` - `_assemble_context_window()`

Assembles context in strict priority order:

#### Priority Stack (High → Low)
1. **Session History** (Priority Level 0)
   - Full conversation thread
   - All messages from current session
   - Message count tracking

2. **Episodic Memories** (Priority Level 1)
   - Top-3 records from FAISS search
   - Decay-weighted by temporal relevance
   - Concept overlap detection active
   - Included if final_score > 0.0

3. **Memory Anchors** (Priority Level 2)
   - MemoryAnchor nodes from 7+ day old sessions
   - Filtered by matching concept IDs
   - Limited to 5 results max
   - Session summaries with concept lists

4. **Graph/RAG Context** (Priority Level 3)
   - CRAG pipeline output
   - Knowledge graph retrieval results
   - Concept relationships
   - Sources and references

5. **Student Overlay Summary** (Priority Level 4)
   - IRT parameters per relevant concept
   - θ (theta) - knowledge state
   - slip probability
   - mastery_probability

#### Context Assembly Workflow
```
query_text
    ↓
[Generate query embedding via RAG Service]
    ↓
[Run CRAG loop → Extract concepts → Get mastery_data]
    ↓
_assemble_context_window()
    ├─ Session history ✓
    ├─ retrieve_episodic_memories(top_k=3)
    ├─ get_memory_anchors(concept_ids)
    ├─ crag_context (already retrieved)
    └─ _summarize_overlay(student_overlay)
         └─ Extract θ, slip, mastery per concept
    ↓
[Assemble into context_window Dict]
    ↓
[Pass to _build_adaptive_response()]
```

## Implementation Details

### MemoryService API

#### Writing Episodic Records
```python
record = EpisodicRecord(
    student_id="stu_123",
    session_id="sess_456",
    message="Can you explain photosynthesis?",
    embedding=np.array([...]),  # 384-dim vector
    timestamp_unix=1712428800,
    concept_node_ids=["photosynthesis", "energy_transfer"],
    turn_number=5
)
memory_service.write_episodic_record(record)
```

#### Retrieving with Temporal Decay
```python
retrieved = memory_service.retrieve_episodic_memories(
    student_id="stu_123",
    query_embedding=query_vec,
    current_concept_ids=["photosynthesis"],
    top_k=3,
    current_timestamp=int(time.time())
)
# Returns: List[RetrievedEpisodicMemory] sorted by final_score DESC
```

#### Semantic Memory Retrieval
```python
semantics = memory_service.get_semantic_memories(
    student_id="stu_123",
    concept_ids=["photosynthesis", "ATP"]
)
# Returns: [{"id": "...", "fact": "...", "confidence": 0.85, ...}]
```

#### Memory Anchor Retrieval
```python
anchors = memory_service.get_memory_anchors(
    student_id="stu_123",
    concept_ids=["photosynthesis"]
)
# Returns: [MemoryAnchor dicts from 7+ day old sessions]
```

### TA Agent Integration

#### Context-Enriched Response
```python
def process(state: AgentState):
    # ...existing CRAG and concept extraction...
    
    # NEW: Assemble context window
    context_window = self._assemble_context_window(
        student_id=state.student_id,
        query_text=state.current_input,
        concept_ids=concepts,
        crag_context=crag_result,
        student_overlay=mastery_data,
        session_messages=state.messages
    )
    
    # NEW: Build response with context
    ta_response = self._build_adaptive_response(
        crag_result=crag_result,
        concepts=concepts,
        mastery_data=mastery_data,
        explanation_depth=explanation_depth,
        should_use_socratic=should_use_socratic,
        primary_concept=primary_concept,
        context_window=context_window  # ← NEW
    )
```

#### Answer Enhancement
New method `_enhance_answer_with_episodic_context()` personalizes responses:
1. Extracts top 2 episodic memories (score > 0.5)
2. Builds context prompt with previous interactions
3. Calls LLM for personalized enhancement
4. Adds references to student's learning journey

### Semantic Node Extraction

**SummarisationAgent enhancements:**

```python
async def _process_interaction(interaction):
    # ...existing anchor creation...
    
    # NEW: Extract and create semantic nodes
    self._extract_and_create_semantic_nodes(
        student_id=student_id,
        session_id=session_id,
        summary_text=summary,
        concept_ids=concepts
    )
```

**JSON-based fact extraction:**
```json
{
    "photosynthesis": [
        "Plants convert sunlight to chemical energy via chlorophyll",
        "Light-dependent reactions occur in thylakoids"
    ],
    "ATP": [
        "ATP is the primary energy currency in cells",
        "ATP is produced during light reactions"
    ]
}
```

## Key Features

### Temporal Intelligence
- ✅ Exponential decay prevents stale memories from dominating
- ✅ Concept overlap detection overrides age (recent relevant > old general)
- ✅ Days calculation accounts for actual calendar time

### Scalability
- ✅ FAISS index handles millions of vectors efficiently
- ✅ Periodic persistence prevents memory loss on restart
- ✅ Neo4j relationships indexed for fast semantic retrieval
- ✅ Top-k limiting prevents context window explosion

### Student Personalization
- ✅ Every interaction becomes future context
- ✅ Episodic memories provide learning continuity
- ✅ Semantic nodes capture extracted insights
- ✅ Concept overlap enables smart temporal overrides

### Error Resilience
- ✅ Graceful fallback if FAISS unavailable
- ✅ Try/except on embedding generation (returns base context)
- ✅ Semantic extraction failures don't block anchor creation
- ✅ Context assembly always returns minimal context on error

## Files Modified

### New Files
- `backend/services/memory_service.py` (600+ lines)
- `backend/services/__init__.py`
- `Phase_5_Memory_System.md` (this file)

### Modified Files
- `backend/agents/ta_agent.py`
  - Added MemoryService initialization
  - Added _assemble_context_window() (60+ lines)
  - Added _enhance_answer_with_episodic_context() (50+ lines)
  - Updated process() for context assembly step
  - Updated _build_adaptive_response() to accept context_window

- `backend/agents/summarisation_agent.py`
  - Added SemanticNode import
  - Added _extract_and_create_semantic_nodes() (80+ lines)
  - Added _extract_facts_from_summary() (50+ lines)
  - Added _write_semantic_node() (40+ lines)
  - Updated _process_interaction() to extract semantic facts

- `backend/db/neo4j_schema.py`
  - Added SemanticNode class (50+ lines)
  - Added CypherQueries.create_semantic_node()
  - Added CypherQueries.access_semantic_node()

## Dependencies

### New Package
- `faiss-cpu` or `faiss-gpu` - Vector similarity search
  ```bash
  pip install faiss-cpu  # or faiss-gpu for GPU acceleration
  ```

### Existing
- numpy - Vector operations
- Neo4j driver - Semantic storage
- Groq/LLM - Fact extraction
- RAG Service - Embedding generation

##  Configuration

### FAISS Index Path
Environment variable: `MEMORY_INDEX_PATH`
Default: `data/episode_memory.faiss`

### Temporal Decay Lambda
In `MemoryService`:
```python
TEMPORAL_LAMBDA = 0.1  # Adjust for slower/faster decay
```

### Top-K Retrieval
Default: `DEFAULT_TOP_K = 3` (top 3 episodic memories)

## Testing Scenarios

### Scenario 1: Student Asks Related Question
1. Student asks about ATP after 3 days
2. Previous discussion of ATP retrieved with high score
3. Episodic memory highlighted in response
4. Answer personalized with "You asked about this before..."

### Scenario 2: Concept Overlap Override
1. Memory from 30 days ago is about "photosynthesis"
2. Current query is also about "photosynthesis"
3. Despite age, memory gets full weight (concept match)
4. Old context appears in top-3 results

### Scenario 3: Semantic Learning
1. Session summarized after 7 days
2. "Plants use ATP as energy currency" extracted as fact
3. SemanticNode created linking student → fact → concepts
4. Future ATP queries include this student-specific learning

## Future Enhancements

- [ ] Clustering episodic memories by concept for efficiency
- [ ] Semantic memory compression (fact summarization)
- [ ] Multi-hop reasoning over semantic networks
- [ ] Confidence propagation through memory chains
- [ ] Active forgetting (pruning very old low-confidence memories)
- [ ] Memory importance scoring based on usage patterns
