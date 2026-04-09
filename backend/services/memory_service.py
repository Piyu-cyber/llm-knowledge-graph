"""
OmniProf Memory Service
Dual-store memory system: Episodic (FAISS) + Semantic (Neo4j)

Episodic Memory: Vector embeddings of chat interactions with temporal decay
Semantic Memory: Extracted facts and concepts linked to student overlays

Features:
- Temporal relevance scoring with exponential decay
- Concept overlap detection for temporal weight overrides
- Top-k retrieval with decay-weighted scoring
- Automatic cleanup and archival
"""

import logging
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from dataclasses import dataclass, field
import json
import math
import uuid

try:
    import faiss
except ImportError:
    faiss = None

from ..db.graph_manager import GraphManager
from .rag_service import RAGService
from .jina_multimodal_service import JinaMultimodalService

logger = logging.getLogger(__name__)


# ==================== Episodic Memory Classes ====================

@dataclass
class EpisodicRecord:
    """Single episodic memory: a chat interaction with embedding and metadata"""
    
    student_id: str
    session_id: str
    message: str
    embedding: np.ndarray  # Vector representation
    timestamp_unix: int  # Unix timestamp
    concept_node_ids: List[str] = field(default_factory=list)
    turn_number: int = 0
    record_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to serializable dict (for storage/retrieval)"""
        return {
            "student_id": self.student_id,
            "session_id": self.session_id,
            "message": self.message,
            "embedding": self.embedding.tolist() if isinstance(self.embedding, np.ndarray) else self.embedding,
            "timestamp_unix": self.timestamp_unix,
            "concept_node_ids": self.concept_node_ids,
            "turn_number": self.turn_number,
            "record_id": self.record_id or str(uuid.uuid4())[:12]
        }


@dataclass
class RetrievedEpisodicMemory:
    """Episodic memory record with relevance score"""
    
    record_id: str
    student_id: str
    session_id: str
    message: str
    concept_node_ids: List[str]
    timestamp_unix: int
    days_since: float
    base_score: float
    temporal_score: float
    has_concept_overlap: bool
    final_score: float
    
    def to_dict(self) -> Dict:
        """Convert to dict for context assembly"""
        return {
            "record_id": self.record_id,
            "message": self.message,
            "concepts": self.concept_node_ids,
            "days_since": self.days_since,
            "final_score": self.final_score,
            "concept_overlap": self.has_concept_overlap
        }


class MemoryService:
    """
    Manages episodic and semantic memory for students.
    
    Episodic Memory:
    - Stores chat interactions in FAISS vector index
    - Temporal decay function: score *= exp(-lambda * days_since)
    - Concept overlap override: if concepts match current query, use full weight
    - Top-k retrieval with weighted scoring
    
    Semantic Memory:
    - Stores learned facts in Neo4j SemanticNode
    - Linked to student overlays and concepts
    - Retrieved alongside graph RAG context
    """
    
    # Temporal decay parameter (default lambda=0.1)
    TEMPORAL_LAMBDA = 0.1
    
    # Number of memories to retrieve by default
    DEFAULT_TOP_K = 3
    
    # Memory index file path
    DEFAULT_INDEX_PATH = "data/episode_memory.faiss"
    
    def __init__(self,
                 rag_service: Optional['RAGService'] = None,
                 embedding_dim: int = 2048):
        """
        Initialize Memory Service.
        
        Args:
            rag_service: RAGService instance for embeddings
            embedding_dim: Vector embedding dimension (default 384 for Sentence Transformers)
        """
        import os
        from dotenv import load_dotenv
        
        load_dotenv()
        
        self.graph_manager = GraphManager()
        
        self.rag_service = rag_service or RAGService()
        self.embedding_dim = embedding_dim
        self.embedding_service = JinaMultimodalService(embedding_dim=self.embedding_dim)
        
        # Initialize FAISS index
        self.index = self._initialize_faiss_index()
        self.index_path = os.getenv("MEMORY_INDEX_PATH", self.DEFAULT_INDEX_PATH)
        
        # In-memory mapping of FAISS index IDs to record metadata
        # Format: {faiss_id: {record_id, student_id, session_id, ...}}
        self.index_metadata: Dict[int, Dict[str, Any]] = {}
        self.next_faiss_id = 0
        self.metadata_path = f"{self.index_path}.meta.json"
        
        # Load index if exists
        self._load_index()
    
    
    # ==================== FAISS Index Management ====================
    
    def _initialize_faiss_index(self) -> 'faiss.Index':
        """
        Initialize FAISS index for episodic memories.
        
        Uses L2 (Euclidean) distance for similarity search.
        
        Returns:
            FAISS index object
        """
        if not faiss:
            logger.warning("FAISS not installed, using in-memory fallback")
            return None
        
        try:
            # Create L2 index (Euclidean distance)
            index = faiss.IndexFlatL2(self.embedding_dim)
            logger.info(f"FAISS index initialized with dimension {self.embedding_dim}")
            return index
        except Exception as e:
            logger.error(f"FAISS index initialization failed: {str(e)}")
            return None
    
    
    def _load_index(self) -> None:
        """
        Load FAISS index from disk if it exists.
        
        Also restores index_metadata mapping.
        """
        if not self.index or not faiss:
            return
        
        try:
            import os
            if os.path.exists(self.index_path):
                self.index = faiss.read_index(self.index_path)
                if os.path.exists(self.metadata_path):
                    with open(self.metadata_path, "r", encoding="utf-8") as mf:
                        metadata_payload = json.load(mf)
                    self.index_metadata = {
                        int(k): v for k, v in (metadata_payload.get("index_metadata", {}) or {}).items()
                    }
                    self.next_faiss_id = int(metadata_payload.get("next_faiss_id", len(self.index_metadata)))
                logger.info(f"Loaded FAISS index from {self.index_path}")
        except Exception as e:
            logger.warning(f"Could not load FAISS index: {str(e)}")
    
    
    def _save_index(self) -> bool:
        """
        Save FAISS index to disk.
        
        Returns:
            Success status
        """
        if not self.index or not faiss:
            return False
        
        try:
            import os
            os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
            faiss.write_index(self.index, self.index_path)
            with open(self.metadata_path, "w", encoding="utf-8") as mf:
                json.dump(
                    {
                        "next_faiss_id": self.next_faiss_id,
                        "index_metadata": self.index_metadata,
                    },
                    mf,
                    indent=2,
                )
            logger.info(f"Saved FAISS index to {self.index_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save FAISS index: {str(e)}")
            return False
    
    
    # ==================== Episodic Memory Writing ====================

    def _fit_embedding_dim(self, embedding: np.ndarray) -> np.ndarray:
        """Pad/truncate vectors to configured embedding dimension."""
        vec = np.array(embedding, dtype=np.float32).flatten()
        if vec.shape[0] == self.embedding_dim:
            return vec
        if vec.shape[0] > self.embedding_dim:
            return vec[: self.embedding_dim]
        out = np.zeros((self.embedding_dim,), dtype=np.float32)
        out[: vec.shape[0]] = vec
        return out
    
    def write_episodic_record(self, record: EpisodicRecord) -> bool:
        """
        Write episodic memory record to FAISS index.
        
        Stores message embedding with metadata for later retrieval.
        
        Args:
            record: EpisodicRecord instance
        
        Returns:
            Success status
        """
        if not self.index or not faiss:
            logger.warning("FAISS index not available, skipping episodic write")
            return False
        
        try:
            # Normalize embedding for L2 distance
            embedding = record.embedding
            if isinstance(embedding, list):
                embedding = np.array(embedding, dtype=np.float32)
            
            # Ensure it's float32 and normalized
            embedding = self._fit_embedding_dim(np.array(embedding, dtype=np.float32)).reshape(1, -1)
            
            # Add to FAISS index
            self.index.add(embedding)
            
            # Store metadata
            faiss_id = self.next_faiss_id
            self.index_metadata[faiss_id] = {
                "record_id": record.record_id or str(uuid.uuid4())[:12],
                "student_id": record.student_id,
                "session_id": record.session_id,
                "message": record.message,
                "timestamp_unix": record.timestamp_unix,
                "concept_node_ids": record.concept_node_ids,
                "turn_number": record.turn_number
            }
            
            self.next_faiss_id += 1
            
            # Save index periodically
            if self.next_faiss_id % 50 == 0:
                self._save_index()
            
            logger.debug(f"Episodic record written: {record.record_id}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to write episodic record: {str(e)}")
            return False
    
    
    # ==================== Episodic Memory Retrieval ====================
    
    def retrieve_episodic_memories(self, 
                                   student_id: str,
                                   query_embedding: np.ndarray,
                                   current_concept_ids: List[str],
                                   top_k: int = None,
                                   current_timestamp: Optional[int] = None) -> List[RetrievedEpisodicMemory]:
        """
        Retrieve episodic memories with temporal decay and concept overlap weighting.
        
        Scoring:
        1. Base score from cosine similarity
        2. Apply temporal decay: score *= exp(-lambda * days_since)
        3. Override: if concept_node_ids overlap with current query, use full weight
        
        Args:
            student_id: Student ID to filter results
            query_embedding: Embedding vector to search for
            current_concept_ids: Concept IDs active in current query
            top_k: Number of results to return (default 3)
            current_timestamp: Current unix timestamp (default now)
        
        Returns:
            List of RetrievedEpisodicMemory objects sorted by final_score (descending)
        """
        if not self.index or not faiss or not self.index_metadata:
            logger.debug("No episodic memories available")
            return []

        if query_embedding is None:
            # Fall back to recency + concept overlap heuristic when no query vector is available.
            current_timestamp = current_timestamp or int(datetime.now().timestamp())
            rows: List[RetrievedEpisodicMemory] = []
            for idx, metadata in self.index_metadata.items():
                if metadata.get("student_id") != student_id:
                    continue
                memory_timestamp = int(metadata.get("timestamp_unix", current_timestamp))
                days_since = max(0.0, (current_timestamp - memory_timestamp) / (24 * 3600))
                memory_concepts = set(metadata.get("concept_node_ids", []))
                overlap = bool(memory_concepts & set(current_concept_ids))
                base = 0.6 if overlap else 0.35
                temporal = base * math.exp(-self.TEMPORAL_LAMBDA * days_since)
                final = base if overlap else temporal
                rows.append(
                    RetrievedEpisodicMemory(
                        record_id=metadata.get("record_id"),
                        student_id=metadata.get("student_id"),
                        session_id=metadata.get("session_id"),
                        message=metadata.get("message"),
                        concept_node_ids=metadata.get("concept_node_ids", []),
                        timestamp_unix=memory_timestamp,
                        days_since=days_since,
                        base_score=base,
                        temporal_score=temporal,
                        has_concept_overlap=overlap,
                        final_score=final,
                    )
                )
            rows.sort(key=lambda x: x.final_score, reverse=True)
            return rows[: (top_k or self.DEFAULT_TOP_K)]
        
        top_k = top_k or self.DEFAULT_TOP_K
        current_timestamp = current_timestamp or int(datetime.now().timestamp())
        
        try:
            # Normalize query embedding
            query = self._fit_embedding_dim(np.array(query_embedding, dtype=np.float32)).reshape(1, -1)
            
            # Search FAISS for top results (we'll filter by student later)
            k = min(top_k * 5, len(self.index_metadata))  # Get more to filter
            distances, indices = self.index.search(query, k)
            
            results = []
            
            for dist, idx in zip(distances[0], indices[0]):
                if idx not in self.index_metadata:
                    continue
                
                metadata = self.index_metadata[idx]
                
                # Filter by student_id
                if metadata.get("student_id") != student_id:
                    continue
                
                # Convert L2 distance to similarity score (cosine-like)
                # Lower L2 distance = higher similarity
                # Normalize: score in [0, 1]
                base_score = 1.0 / (1.0 + dist)  # Inverse similarity
                
                # Calculate temporal decay
                memory_timestamp = metadata.get("timestamp_unix")
                days_since = (current_timestamp - memory_timestamp) / (24 * 3600)
                days_since = max(0.0, days_since)
                
                # Temporal score: base_score * exp(-lambda * days_since)
                temporal_score = base_score * math.exp(-self.TEMPORAL_LAMBDA * days_since)
                
                # Check concept overlap
                memory_concepts = set(metadata.get("concept_node_ids", []))
                current_concepts = set(current_concept_ids)
                has_overlap = bool(memory_concepts & current_concepts)
                
                # Override: full weight if concepts match
                final_score = base_score if has_overlap else temporal_score
                
                result = RetrievedEpisodicMemory(
                    record_id=metadata.get("record_id"),
                    student_id=metadata.get("student_id"),
                    session_id=metadata.get("session_id"),
                    message=metadata.get("message"),
                    concept_node_ids=metadata.get("concept_node_ids", []),
                    timestamp_unix=memory_timestamp,
                    days_since=days_since,
                    base_score=base_score,
                    temporal_score=temporal_score,
                    has_concept_overlap=has_overlap,
                    final_score=final_score
                )
                
                results.append(result)
            
            # Sort by final_score descending
            results.sort(key=lambda x: x.final_score, reverse=True)
            
            # Return top-k
            return results[:top_k]
        
        except Exception as e:
            logger.error(f"Episodic retrieval error: {str(e)}")
            return []
    
    
    # ==================== Semantic Memory Retrieval ====================
    
    def get_semantic_memories(self, 
                             student_id: str,
                             concept_ids: List[str]) -> List[Dict[str, Any]]:
        """
        Retrieve semantic memory nodes linked to concepts.
        
        Semantic nodes are facts extracted during session summarization.
        
        Args:
            student_id: Student ID
            concept_ids: List of concept IDs to retrieve semantic nodes for
        
        Returns:
            List of semantic memory dicts
        """
        try:
            if not concept_ids:
                return []

            if not hasattr(self.graph_manager, "db"):
                rows: List[Dict[str, Any]] = []
                for concept_id in concept_ids:
                    if hasattr(self.graph_manager, "get_semantic_nodes"):
                        for item in self.graph_manager.get_semantic_nodes(student_id, concept_id):
                            rows.append(
                                {
                                    "id": item.get("id"),
                                    "fact": item.get("fact"),
                                    "confidence": item.get("confidence", 0.0),
                                    "concept_id": concept_id,
                                    "created_at": item.get("created_at"),
                                }
                            )
                rows.sort(key=lambda x: float(x.get("confidence", 0.0)), reverse=True)
                return rows
            
            # Query Neo4j for SemanticNode linked to concepts
            query = (
                "MATCH (student:User {id: $student_id}) "
                "MATCH (student)-[:LEARNED_FROM]->(sem:SemanticNode) "
                "UNWIND $concept_ids as concept_id "
                "MATCH (concept:CONCEPT {id: concept_id}) "
                "WHERE (sem)-[:EXTRACTED_FROM]->(concept) "
                "RETURN sem.id as id, sem.fact as fact, sem.confidence as confidence, "
                "       concept.id as concept_id, sem.created_at as created_at "
                "ORDER BY sem.confidence DESC"
            )
            
            result = self.graph_manager.db.run_query(
                query,
                {"student_id": student_id, "concept_ids": concept_ids}
            )
            
            return result if result else []
        
        except Exception as e:
            logger.warning(f"Semantic retrieval error: {str(e)}")
            return []
    
    
    # ==================== Memory Anchor Retrieval ====================
    
    def get_memory_anchors(self, 
                          student_id: str,
                          concept_ids: List[str]) -> List[Dict[str, Any]]:
        """
        Retrieve MemoryAnchor nodes matching concepts.
        
        Memory anchors are created from old interactions summarized
        by the SummarisationAgent.
        
        Args:
            student_id: Student ID
            concept_ids: Concept IDs to match
        
        Returns:
            List of memory anchor dicts
        """
        try:
            if not concept_ids:
                return []

            if not hasattr(self.graph_manager, "db"):
                rows: List[Dict[str, Any]] = []
                for concept_id in concept_ids:
                    if hasattr(self.graph_manager, "get_memory_anchors"):
                        rows.extend(self.graph_manager.get_memory_anchors(student_id, concept_id))
                rows.sort(key=lambda x: str(x.get("created_at", "")), reverse=True)
                return rows[:5]
            
            # Query Neo4j for MemoryAnchor linked to concepts
            query = (
                "MATCH (student:User {id: $student_id}) "
                "MATCH (student)-[:HAS_MEMORY]->(mem:MemoryAnchor) "
                "UNWIND $concept_ids as concept_id "
                "MATCH (concept:CONCEPT {id: concept_id}) "
                "WHERE (mem)-[:DISCUSSED]->(concept) "
                "RETURN mem.id as id, mem.session_date as session_date, "
                "       mem.summary_text as summary, mem.created_at as created_at "
                "ORDER BY mem.created_at DESC "
                "LIMIT 5"
            )
            
            result = self.graph_manager.db.run_query(
                query,
                {"student_id": student_id, "concept_ids": concept_ids}
            )
            
            return result if result else []
        
        except Exception as e:
            logger.warning(f"Memory anchor retrieval error: {str(e)}")
            return []
    
    
    # ==================== Context Assembly Utilities ====================
    
    def assemble_context_window(self,
                               student_id: str,
                               session_messages: List[Dict[str, str]],
                               query_embedding: np.ndarray,
                               current_concept_ids: List[str],
                               crag_context: Dict[str, Any],
                               student_overlay: Dict[str, Any]) -> Dict[str, Any]:
        """
        Assemble complete context window in priority order.
        
        Priority:
        1. Current session full message history
        2. Top-3 episodic memory records (decay-weighted)
        3. Memory anchors for matching concept nodes
        4. Graph RAG context (CRAG output)
        5. Student IRT overlay summary
        
        Args:
            student_id: Student ID
            session_messages: Current session conversation history
            query_embedding: Embedding of current query
            current_concept_ids: Concept IDs active in current turn
            crag_context: Context from CRAG retrieval
            student_overlay: Student's IRT overlay data
        
        Returns:
            Assembled context dict with all components
        """
        try:
            # 1. Session history
            context_window = {
                "session_history": session_messages,
                "session_messages_count": len(session_messages)
            }
            
            # 2. Episodic memories
            episodic = self.retrieve_episodic_memories(
                student_id=student_id,
                query_embedding=query_embedding,
                current_concept_ids=current_concept_ids,
                top_k=3
            )
            normalized_episodic: List[Dict[str, Any]] = []
            for m in episodic:
                if isinstance(m, dict):
                    normalized_episodic.append(m)
                elif hasattr(m, "to_dict"):
                    normalized_episodic.append(m.to_dict())
                else:
                    # Defensive fallback for unexpected row types.
                    normalized_episodic.append({"raw": str(m)})

            context_window["episodic_memories"] = normalized_episodic
            context_window["episodic_count"] = len(episodic)
            
            # 3. Memory anchors
            memory_anchors = self.get_memory_anchors(
                student_id=student_id,
                concept_ids=current_concept_ids
            )
            context_window["memory_anchors"] = memory_anchors
            context_window["memory_anchor_count"] = len(memory_anchors)
            
            # 4. CRAG context
            context_window["rag_context"] = crag_context
            
            # 5. Student overlay summary
            if student_overlay:
                overlay_summary = self._summarize_overlay(
                    student_overlay,
                    current_concept_ids
                )
                context_window["student_overlay"] = overlay_summary
            
            logger.debug(f"Context assembled: "
                        f"session={context_window['session_messages_count']}, "
                        f"episodic={context_window['episodic_count']}, "
                        f"anchors={context_window['memory_anchor_count']}")
            
            return context_window
        
        except Exception as e:
            logger.error(f"Context window assembly error: {str(e)}")
            return {"error": str(e)}
    
    
    def _summarize_overlay(self, student_overlay: Dict[str, Any], 
                          concept_ids: List[str]) -> Dict[str, Any]:
        """
        Summarize student overlay for relevant concepts.
        
        Extracts theta, mastery_probability, slip for each concept.
        
        Args:
            student_overlay: Full student overlay data
            concept_ids: Concepts to summarize
        
        Returns:
            Summary dict with concept-specific IRT parameters
        """
        try:
            if not student_overlay or not concept_ids:
                return {}
            
            summary = {
                "relevant_concepts": []
            }
            
            for concept_id in concept_ids[:10]:  # Limit to top 10 for efficiency
                overlay_data = student_overlay.get(concept_id, {})
                
                if overlay_data:
                    if isinstance(overlay_data, (int, float)):
                        summary["relevant_concepts"].append({
                            "concept_id": concept_id,
                            "theta": 0.0,
                            "slip": 0.1,
                            "mastery_probability": float(overlay_data),
                        })
                        continue

                    summary["relevant_concepts"].append({
                        "concept_id": concept_id,
                        "theta": overlay_data.get("theta", 0.0),
                        "slip": overlay_data.get("slip", 0.1),
                        "mastery_probability": overlay_data.get("mastery_probability", 0.5)
                    })
            
            return summary
        
        except Exception as e:
            logger.warning(f"Overlay summarization error: {str(e)}")
            return {}
