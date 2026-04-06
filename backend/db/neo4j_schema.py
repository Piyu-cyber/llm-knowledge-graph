"""
OmniProf v3.0 — Neo4j Schema Definition
Defines the 4-level hierarchy: Module -> Topic -> Concept -> Fact
Plus prerequisite relationships, student overlays, and validation
"""

import uuid
import json
from datetime import datetime
from enum import Enum
from typing import List, Dict, Optional, Tuple
from abc import ABC, abstractmethod


# ==================== Enums ====================
class NodeLevel(str, Enum):
    """Hierarchy levels"""
    MODULE = "MODULE"
    TOPIC = "TOPIC"
    CONCEPT = "CONCEPT"
    FACT = "FACT"


class Visibility(str, Enum):
    """Node visibility settings"""
    GLOBAL = "global"
    ENROLLED_ONLY = "enrolled-only"
    PROFESSOR_ONLY = "professor-only"


class EdgeType(str, Enum):
    """Relationship types"""
    CONTAINS = "CONTAINS"  # Parent to child in hierarchy
    REQUIRES = "REQUIRES"  # Prerequisite
    EXTENDS = "EXTENDS"  # Advanced concept
    CONTRASTS = "CONTRASTS"  # Contrasting concept
    RELATED = "RELATED"  # General relation
    STUDIED_BY = "STUDIED_BY"  # Student overlay link


# ==================== Base Node Schema ====================
class GraphNode:
    """Base class for all graph nodes"""
    
    def __init__(
        self,
        name: str,
        level: NodeLevel,
        course_owner: str,
        description: str = "",
        source_doc_ref: str = "",
        visibility: Visibility = Visibility.GLOBAL,
        embedding: Optional[List[float]] = None,
        node_id: Optional[str] = None
    ):
        self.id = node_id or str(uuid.uuid4())[:8]
        self.name = name.strip()
        self.level = level
        self.course_owner = course_owner
        self.description = description.strip()
        self.source_doc_ref = source_doc_ref
        self.visibility = visibility
        # 384-dim embeddings (Sentence Transformers default)
        self.embedding = embedding or []
        
    def to_dict(self) -> Dict:
        """Convert to Neo4j property dict"""
        return {
            "id": self.id,
            "name": self.name,
            "level": self.level.value,
            "course_owner": self.course_owner,
            "description": self.description,
            "source_doc_ref": self.source_doc_ref,
            "visibility": self.visibility.value,
            "embedding": self.embedding,
            "created_at": None,  # Will be set by Neo4j
        }


# ==================== Specialized Nodes ====================
class Module(GraphNode):
    """Module node - top level"""
    
    def __init__(
        self,
        name: str,
        course_owner: str,
        description: str = "",
        visibility: Visibility = Visibility.GLOBAL,
        node_id: Optional[str] = None
    ):
        super().__init__(
            name=name,
            level=NodeLevel.MODULE,
            course_owner=course_owner,
            description=description,
            visibility=visibility,
            node_id=node_id
        )


class Topic(GraphNode):
    """Topic node - second level"""
    
    def __init__(
        self,
        name: str,
        course_owner: str,
        module_id: str,
        description: str = "",
        visibility: Visibility = Visibility.GLOBAL,
        node_id: Optional[str] = None
    ):
        super().__init__(
            name=name,
            level=NodeLevel.TOPIC,
            course_owner=course_owner,
            description=description,
            visibility=visibility,
            node_id=node_id
        )
        self.module_id = module_id


class Concept(GraphNode):
    """Concept node - third level"""
    
    def __init__(
        self,
        name: str,
        course_owner: str,
        topic_id: str,
        description: str = "",
        source_doc_ref: str = "",
        visibility: Visibility = Visibility.GLOBAL,
        embedding: Optional[List[float]] = None,
        difficulty: float = 0.0,
        node_id: Optional[str] = None
    ):
        super().__init__(
            name=name,
            level=NodeLevel.CONCEPT,
            course_owner=course_owner,
            description=description,
            source_doc_ref=source_doc_ref,
            visibility=visibility,
            embedding=embedding,
            node_id=node_id
        )
        self.topic_id = topic_id
        self.difficulty = max(-4.0, min(4.0, float(difficulty)))

    def to_dict(self) -> Dict:
        """Convert to Neo4j property dict with IRT concept difficulty."""
        data = super().to_dict()
        data["difficulty"] = self.difficulty
        return data


class Fact(GraphNode):
    """Fact node - bottom level"""
    
    def __init__(
        self,
        name: str,
        course_owner: str,
        concept_id: str,
        description: str = "",
        source_doc_ref: str = "",
        visibility: Visibility = Visibility.GLOBAL,
        node_id: Optional[str] = None
    ):
        super().__init__(
            name=name,
            level=NodeLevel.FACT,
            course_owner=course_owner,
            description=description,
            source_doc_ref=source_doc_ref,
            visibility=visibility,
            node_id=node_id
        )
        self.concept_id = concept_id


# ==================== Student Overlay Node ====================
class StudentOverlay(GraphNode):
    """Tracks student progress on concepts (BKT model)"""
    
    def __init__(
        self,
        user_id: str,
        concept_id: str,
        theta: float = 0.0,
        slip: float = 0.1,
        guess: float = 0.1,
        visited: bool = False,
        mastery_probability: float = 0.0,
        last_updated: Optional[str] = None,
        overlay_id: Optional[str] = None
    ):
        # StudentOverlay is synthetic, not in hierarchy
        super().__init__(
            name=f"StudentOverlay_{user_id}_{concept_id}",
            level=NodeLevel.CONCEPT,  # Reuse for internal use
            course_owner=user_id,
            node_id=overlay_id
        )
        self.user_id = user_id
        self.concept_id = concept_id
        self.theta = max(0.0, min(1.0, theta))  # Clamp [0, 1]
        self.slip = max(0.0, min(1.0, slip))
        self.guess = max(0.0, min(1.0, guess))
        self.visited = visited
        self.mastery_probability = max(0.0, min(1.0, mastery_probability))
        self.last_updated = last_updated
    
    def to_dict(self) -> Dict:
        """Convert to Neo4j properties"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "concept_id": self.concept_id,
            "theta": self.theta,
            "slip": self.slip,
            "guess": self.guess,
            "visited": self.visited,
            "mastery_probability": self.mastery_probability,
            "last_updated": self.last_updated,
        }


# ==================== Defence Record ====================
class DefenceRecord:
    """Records a student's submission defence evaluation"""
    
    def __init__(
        self,
        student_id: str,
        submission_id: str,
        transcript: List[Dict[str, str]],
        ai_recommended_grade: float,
        ai_feedback: str,
        integrity_score: float = 0.0,
        status: str = "pending_review",
        anomalous_input: bool = False,
        record_id: Optional[str] = None
    ):
        """
        Args:
            student_id: Student user ID
            submission_id: Submission/assignment ID
            transcript: List of turn dicts {"role": "student"|"evaluator", "content": "..."}
            ai_recommended_grade: Score 0.0-1.0
            ai_feedback: Detailed feedback text
            integrity_score: Score 0.0-1.0 from Integrity Agent
            status: "pending_review" | "approved" | "flagged"
            anomalous_input: Whether writing style is anomalous
            record_id: Optional unique record ID
        """
        self.id = record_id or str(uuid.uuid4())[:12]
        self.student_id = student_id
        self.submission_id = submission_id
        self.transcript = transcript
        self.ai_recommended_grade = max(0.0, min(1.0, ai_recommended_grade))
        self.ai_feedback = ai_feedback
        self.integrity_score = max(0.0, min(1.0, integrity_score))
        self.status = status
        self.anomalous_input = anomalous_input
        self.created_at = datetime.now().isoformat() if hasattr(datetime, 'now') else ""
        self.turn_count = len(transcript)
    
    def to_dict(self) -> Dict:
        """Convert to Neo4j properties"""
        return {
            "id": self.id,
            "student_id": self.student_id,
            "submission_id": self.submission_id,
            "ai_recommended_grade": self.ai_recommended_grade,
            "ai_feedback": self.ai_feedback,
            "integrity_score": self.integrity_score,
            "status": self.status,
            "anomalous_input": self.anomalous_input,
            "turn_count": self.turn_count,
            "created_at": self.created_at,
            "transcript": json.dumps(self.transcript) if hasattr(json, 'dumps') else str(self.transcript)
        }


# ==================== Achievement Node ====================
class Achievement:
    """Gamification achievement badge earned by student"""
    
    def __init__(
        self,
        student_id: str,
        achievement_type: str,
        concept_id: Optional[str] = None,
        module_id: Optional[str] = None,
        earned_at: Optional[str] = None,
        achievement_id: Optional[str] = None
    ):
        """
        Args:
            student_id: Student user ID
            achievement_type: Badge type ("explorer" | "mastery" | "module_complete")
            concept_id: Concept ID (for mastery badges)
            module_id: Module ID (for explorer/module_complete badges)
            earned_at: ISO timestamp when badge was earned
            achievement_id: Unique achievement record ID
        """
        self.id = achievement_id or str(uuid.uuid4())[:12]
        self.student_id = student_id
        self.achievement_type = achievement_type
        self.concept_id = concept_id
        self.module_id = module_id
        self.earned_at = earned_at or datetime.now().isoformat()
        self.private = True  # Only visible to student who earned it
    
    def to_dict(self) -> Dict:
        """Convert to Neo4j properties"""
        return {
            "id": self.id,
            "student_id": self.student_id,
            "achievement_type": self.achievement_type,
            "concept_id": self.concept_id,
            "module_id": self.module_id,
            "earned_at": self.earned_at,
            "private": self.private
        }


# ==================== Memory Anchor Node ====================
class MemoryAnchor:
    """Long-term memory of a learning session (7+ days old)"""
    
    def __init__(
        self,
        student_id: str,
        session_date: str,
        concepts: Optional[List[str]] = None,
        confidence: Optional[Dict[str, float]] = None,
        misconceptions: Optional[List[str]] = None,
        summary_text: str = "",
        memory_id: Optional[str] = None
    ):
        """
        Args:
            student_id: Student user ID
            session_date: ISO date of the original session
            concepts: List of concept IDs discussed in session
            confidence: Dict of {concept_id: mastery_probability}
            misconceptions: List of identified misconceptions
            summary_text: LLM-generated summary of session
            memory_id: Unique memory anchor ID
        """
        self.id = memory_id or str(uuid.uuid4())[:12]
        self.student_id = student_id
        self.session_date = session_date
        self.concepts = concepts or []
        self.confidence = confidence or {}
        self.misconceptions = misconceptions or []
        self.summary_text = summary_text
        self.created_at = datetime.now().isoformat()
    
    def to_dict(self) -> Dict:
        """Convert to Neo4j properties"""
        return {
            "id": self.id,
            "student_id": self.student_id,
            "session_date": self.session_date,
            "summary_text": self.summary_text,
            "created_at": self.created_at,
            "concepts": json.dumps(self.concepts) if self.concepts else "[]",
            "confidence": json.dumps(self.confidence) if self.confidence else "{}",
            "misconceptions": json.dumps(self.misconceptions) if self.misconceptions else "[]"
        }


# ==================== Semantic Memory Node ====================
class SemanticNode:
    """
    Extracted fact/concept from session summarization.
    
    Semantic nodes represent key learnings and facts extracted
    during session summarization by the SummarisationAgent.
    
    Linked to concepts and student overlays for retrieval
    during TA Agent context assembly.
    """
    
    def __init__(
        self,
        student_id: str,
        fact: str,
        concept_id: str,
        confidence: float = 0.8,
        source_session_id: Optional[str] = None,
        semantic_id: Optional[str] = None
    ):
        """
        Args:
            student_id: Student ID who learned this
            fact: The extracted fact/insight (string)
            concept_id: Related concept node ID
            confidence: Confidence level 0.0-1.0
            source_session_id: Session ID where fact was extracted
            semantic_id: Unique semantic node ID
        """
        self.id = semantic_id or str(uuid.uuid4())[:12]
        self.student_id = student_id
        self.fact = fact
        self.concept_id = concept_id
        self.confidence = max(0.0, min(1.0, confidence))
        self.source_session_id = source_session_id
        self.created_at = datetime.now().isoformat()
        self.last_accessed = self.created_at
        self.access_count = 0
    
    def to_dict(self) -> Dict:
        """Convert to Neo4j properties"""
        return {
            "id": self.id,
            "student_id": self.student_id,
            "fact": self.fact,
            "concept_id": self.concept_id,
            "confidence": self.confidence,
            "source_session_id": self.source_session_id,
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
            "access_count": self.access_count
        }


# ==================== Edge Definition ====================
class GraphEdge:
    """Defines relationships between nodes"""
    
    def __init__(
        self,
        source_id: str,
        target_id: str,
        edge_type: EdgeType,
        weight: float = 1.0,
        properties: Optional[Dict] = None
    ):
        self.source_id = source_id
        self.target_id = target_id
        self.edge_type = edge_type
        self.weight = weight
        self.properties = properties or {}
    
    def to_dict(self) -> Dict:
        """Convert to Neo4j properties"""
        return {
            "weight": self.weight,
            **self.properties
        }


# ==================== Validation Schema ====================
class GraphValidator:
    """Validates graph integrity"""
    
    @staticmethod
    def validate_node_name(name: str) -> Tuple[bool, str]:
        """Check node name validity"""
        if not name or len(name.strip()) < 1:
            return False, "Name cannot be empty"
        if len(name) > 255:
            return False, "Name too long (max 255 chars)"
        return True, ""
    
    @staticmethod
    def validate_embedding(embedding: Optional[List[float]]) -> Tuple[bool, str]:
        """Check embedding vector"""
        if embedding is None:
            return True, ""
        if not isinstance(embedding, list):
            return False, "Embedding must be a list"
        if len(embedding) != 384:
            return False, f"Embedding must be 384-dimensional, got {len(embedding)}"
        if not all(isinstance(x, (int, float)) for x in embedding):
            return False, "Embedding values must be numeric"
        return True, ""
    
    @staticmethod
    def validate_visibility(visibility: str) -> Tuple[bool, str]:
        """Check visibility setting"""
        valid = [v.value for v in Visibility]
        if visibility not in valid:
            return False, f"Invalid visibility: {visibility}"
        return True, ""
    
    @staticmethod
    def validate_course_owner(course_owner: str) -> Tuple[bool, str]:
        """Check course owner is valid user_id"""
        if not course_owner or len(course_owner.strip()) < 1:
            return False, "Course owner cannot be empty"
        return True, ""
    
    @staticmethod
    def validate_bkt_parameters(theta: float, slip: float, guess: float) -> Tuple[bool, str]:
        """Validate Bayesian Knowledge Tracing parameters"""
        params = {"theta": theta, "slip": slip, "guess": guess}
        for name, value in params.items():
            if not isinstance(value, (int, float)):
                return False, f"{name} must be numeric"
            if not (0.0 <= value <= 1.0):
                return False, f"{name} must be in [0, 1], got {value}"
        return True, ""


# ==================== Neo4j Cypher Queries ====================
class CypherQueries:
    """Pre-built Cypher queries for common operations"""
    
    @staticmethod
    def create_module(module: Module) -> Tuple[str, Dict]:
        """Create a module node"""
        props = module.to_dict()
        return (
            f"CREATE (m:{NodeLevel.MODULE.value} $props) RETURN m",
            {"props": props}
        )
    
    @staticmethod
    def create_topic(topic: Topic) -> Tuple[str, Dict]:
        """Create a topic with CONTAINS relationship to module"""
        topic_props = topic.to_dict()
        return (
            "MATCH (m:MODULE {id: $module_id}) "
            "CREATE (t:TOPIC $topic_props)-[:CONTAINS]->(m) "
            "RETURN t",
            {"topic_props": topic_props, "module_id": topic.module_id}
        )
    
    @staticmethod
    def create_concept(concept: Concept) -> Tuple[str, Dict]:
        """Create a concept with CONTAINS relationship to topic"""
        concept_props = concept.to_dict()
        return (
            "MATCH (t:TOPIC {id: $topic_id}) "
            "CREATE (c:CONCEPT $concept_props)-[:CONTAINS]->(t) "
            "RETURN c",
            {"concept_props": concept_props, "topic_id": concept.topic_id}
        )
    
    @staticmethod
    def create_prerequisite(source_id: str, target_id: str, weight: float = 1.0) -> Tuple[str, Dict]:
        """Add prerequisite relationship (source REQUIRES target)"""
        return (
            "MATCH (c1 {id: $source_id}), (c2 {id: $target_id}) "
            "CREATE (c1)-[:REQUIRES {weight: $weight}]->(c2) "
            "RETURN c1, c2",
            {"source_id": source_id, "target_id": target_id, "weight": weight}
        )
    
    @staticmethod
    def create_student_overlay(overlay: StudentOverlay) -> Tuple[str, Dict]:
        """Create student overlay linked to concept"""
        overlay_props = overlay.to_dict()
        return (
            "MATCH (c:CONCEPT {id: $concept_id}) "
            "CREATE (s:StudentOverlay $overlay_props)-[:STUDIED_BY]->(c) "
            "RETURN s",
            {"overlay_props": overlay_props, "concept_id": overlay.concept_id}
        )
    
    @staticmethod
    def check_prerequisite_cycles(node_id: str) -> Tuple[str, Dict]:
        """Check if adding this node creates a cycle in REQUIRES edges"""
        return (
            "MATCH (n {id: $node_id}) "
            "MATCH (n)-[:REQUIRES*]->(n) "
            "RETURN count(*) as cycles",
            {"node_id": node_id}
        )
    
    @staticmethod
    def find_orphaned_nodes() -> Tuple[str, Dict]:
        """Find nodes not connected in hierarchy"""
        return (
            "MATCH (n) WHERE NOT (n)-[:CONTAINS]->() AND NOT ()-[:CONTAINS]->(n) "
            "RETURN n",
            {}
        )
    
    @staticmethod
    def check_duplicate_names(name: str) -> Tuple[str, Dict]:
        """Find nodes with same name"""
        return (
            "MATCH (n {name: $name}) RETURN count(n) as count",
            {"name": name}
        )
    
    @staticmethod
    def update_student_mastery(user_id: str, concept_id: str, mastery: float) -> Tuple[str, Dict]:
        """Update student overlay mastery probability"""
        return (
            "MATCH (s:StudentOverlay {user_id: $user_id, concept_id: $concept_id}) "
            "SET s.mastery_probability = $mastery "
            "RETURN s",
            {"user_id": user_id, "concept_id": concept_id, "mastery": mastery}
        )
    
    @staticmethod
    def create_defence_record(record: 'DefenceRecord') -> Tuple[str, Dict]:
        """Create a submission defence evaluation record"""
        record_props = record.to_dict()
        return (
            "CREATE (d:DefenceRecord $record_props) "
            "RETURN d",
            {"record_props": record_props}
        )
    
    @staticmethod
    def update_defence_record(record_id: str, status: str, integrity_score: float, 
                            anomalous_input: bool) -> Tuple[str, Dict]:
        """Update defence record with evaluation results"""
        return (
            "MATCH (d:DefenceRecord {id: $record_id}) "
            "SET d.status = $status, "
            "    d.integrity_score = $integrity_score, "
            "    d.anomalous_input = $anomalous_input "
            "RETURN d",
            {"record_id": record_id, "status": status, 
             "integrity_score": integrity_score, "anomalous_input": anomalous_input}
        )
    
    @staticmethod
    def create_achievement(achievement: 'Achievement') -> Tuple[str, Dict]:
        """Create an achievement badge for a student"""
        achievement_props = achievement.to_dict()
        return (
            "MATCH (student:User {id: $student_id}) "
            "CREATE (ach:Achievement $achievement_props) "
            "CREATE (student)-[:EARNED]->(ach) "
            "RETURN ach",
            {"achievement_props": achievement_props, "student_id": achievement.student_id}
        )
    
    @staticmethod
    def create_memory_anchor(memory: 'MemoryAnchor', session_id: str) -> Tuple[str, Dict]:
        """Create a memory anchor linked to session and student"""
        memory_props = memory.to_dict()
        return (
            "MATCH (student:User {id: $student_id}) "
            "MATCH (session:Session {id: $session_id}) "
            "CREATE (mem:MemoryAnchor $memory_props) "
            "CREATE (student)-[:HAS_MEMORY]->(mem) "
            "CREATE (session)-[:SUMMARIZED_TO]->(mem) "
            "RETURN mem",
            {"memory_props": memory_props, "student_id": memory.student_id, "session_id": session_id}
        )
    
    @staticmethod
    def link_memory_to_concepts(memory_id: str, concept_ids: List[str]) -> Tuple[str, Dict]:
        """Link memory anchor to discussion concepts"""
        return (
            "MATCH (mem:MemoryAnchor {id: $memory_id}) "
            "UNWIND $concept_ids as concept_id "
            "MATCH (c:CONCEPT {id: concept_id}) "
            "CREATE (mem)-[:DISCUSSED]->(c) "
            "RETURN mem",
            {"memory_id": memory_id, "concept_ids": concept_ids}
        )
    
    @staticmethod
    def create_semantic_node(semantic: 'SemanticNode') -> Tuple[str, Dict]:
        """Create a semantic memory node (extracted fact)"""
        semantic_props = semantic.to_dict()
        return (
            "MATCH (student:User {id: $student_id}) "
            "MATCH (concept:CONCEPT {id: $concept_id}) "
            "CREATE (sem:SemanticNode $semantic_props) "
            "CREATE (student)-[:LEARNED_FROM]->(sem) "
            "CREATE (sem)-[:EXTRACTED_FROM]->(concept) "
            "RETURN sem",
            {"semantic_props": semantic_props, "student_id": semantic.student_id, 
             "concept_id": semantic.concept_id}
        )
    
    @staticmethod
    def access_semantic_node(semantic_id: str) -> Tuple[str, Dict]:
        """Update access statistics for semantic node"""
        return (
            "MATCH (sem:SemanticNode {id: $semantic_id}) "
            "SET sem.last_accessed = $now, "
            "    sem.access_count = sem.access_count + 1 "
            "RETURN sem",
            {"semantic_id": semantic_id, "now": datetime.now().isoformat()}
        )
