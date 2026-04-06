"""
OmniProf v3.0 — Neo4j Database Manager
Handles all graph operations with the 4-level hierarchy
"""

import os
from typing import List, Dict, Optional, Tuple
from dotenv import load_dotenv
from neo4j import GraphDatabase
import logging

from backend.db.neo4j_schema import (
    Module, Topic, Concept, Fact, StudentOverlay,
    GraphEdge, GraphValidator, CypherQueries,
    NodeLevel, Visibility, EdgeType
)
from backend.auth.rbac import UserContext, RBACFilter

load_dotenv()
logger = logging.getLogger(__name__)


class Neo4jDriver:
    """Low-level Neo4j connectivity"""
    
    def __init__(self):
        self.driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            auth=(
                os.getenv("NEO4J_USER", "neo4j"),
                os.getenv("NEO4J_PASSWORD", "password")
            )
        )
    
    def run_query(self, query: str, params: Optional[Dict] = None) -> List[Dict]:
        """Execute a Cypher query"""
        try:
            with self.driver.session() as session:
                result = session.run(query, params or {})
                return [record.data() for record in result]
        except Exception as e:
            logger.error(f"Query failed: {str(e)}")
            return []
    
    def close(self):
        """Close driver connection"""
        self.driver.close()


class Neo4jGraphManager:
    """High-level graph operations with new schema"""
    
    def __init__(self):
        self.db = Neo4jDriver()
        self.validator = GraphValidator()
        self._init_indexes()
    
    def _init_indexes(self):
        """Create indexes for performance"""
        indexes = [
            "CREATE INDEX IF NOT EXISTS FOR (m:MODULE) ON (m.id)",
            "CREATE INDEX IF NOT EXISTS FOR (t:TOPIC) ON (t.id)",
            "CREATE INDEX IF NOT EXISTS FOR (c:CONCEPT) ON (c.id)",
            "CREATE INDEX IF NOT EXISTS FOR (f:FACT) ON (f.id)",
            "CREATE INDEX IF NOT EXISTS FOR (s:StudentOverlay) ON (s.user_id, s.concept_id)",
        ]
        for index_query in indexes:
            self.db.run_query(index_query)
        logger.info("Graph indexes initialized")
    
    # ==================== Module Operations ====================
    
    def create_module(self, name: str, course_owner: str, 
                     description: str = "", visibility: str = "global") -> Dict:
        """Create a new module"""
        # Validate
        valid, msg = self.validator.validate_node_name(name)
        if not valid:
            return {"status": "error", "message": msg}
        
        valid, msg = self.validator.validate_course_owner(course_owner)
        if not valid:
            return {"status": "error", "message": msg}
        
        valid, msg = self.validator.validate_visibility(visibility)
        if not valid:
            return {"status": "error", "message": msg}
        
        # Create node
        module = Module(
            name=name,
            course_owner=course_owner,
            description=description,
            visibility=Visibility(visibility)
        )
        
        query, params = CypherQueries.create_module(module)
        result = self.db.run_query(query, params)
        
        if result:
            return {
                "status": "success",
                "node_id": module.id,
                "name": name,
                "level": "MODULE"
            }
        return {"status": "error", "message": "Failed to create module"}
    
    
    def create_topic(self, module_id: str, name: str, course_owner: str,
                    description: str = "", visibility: str = "global") -> Dict:
        """Create a new topic under a module"""
        # Validate
        valid, msg = self.validator.validate_node_name(name)
        if not valid:
            return {"status": "error", "message": msg}
        
        # Check module exists
        result = self.db.run_query(
            "MATCH (m:MODULE {id: $id}) RETURN count(m) as exists",
            {"id": module_id}
        )
        if not result or result[0]["exists"] == 0:
            return {"status": "error", "message": "Module not found"}
        
        # Create topic
        topic = Topic(
            name=name,
            course_owner=course_owner,
            module_id=module_id,
            description=description,
            visibility=Visibility(visibility)
        )
        
        query, params = CypherQueries.create_topic(topic)
        result = self.db.run_query(query, params)
        
        if result:
            return {
                "status": "success",
                "node_id": topic.id,
                "name": name,
                "level": "TOPIC"
            }
        return {"status": "error", "message": "Failed to create topic"}
    
    
    def create_concept(self, topic_id: str, name: str, course_owner: str,
                      description: str = "", source_doc_ref: str = "",
                      embedding: Optional[List[float]] = None,
                      visibility: str = "global") -> Dict:
        """Create a new concept under a topic"""
        # Validate
        valid, msg = self.validator.validate_node_name(name)
        if not valid:
            return {"status": "error", "message": msg}
        
        valid, msg = self.validator.validate_embedding(embedding)
        if not valid:
            return {"status": "error", "message": msg}
        
        # Check for duplicate names in same topic
        result = self.db.run_query(
            "MATCH (t:TOPIC {id: $topic_id})-[:CONTAINS]->(c:CONCEPT {name: $name}) "
            "RETURN count(c) as count",
            {"topic_id": topic_id, "name": name}
        )
        if result and result[0]["count"] > 0:
            return {"status": "error", "message": "Concept with this name already exists in topic"}
        
        # Check topic exists
        result = self.db.run_query(
            "MATCH (t:TOPIC {id: $id}) RETURN count(t) as exists",
            {"id": topic_id}
        )
        if not result or result[0]["exists"] == 0:
            return {"status": "error", "message": "Topic not found"}
        
        # Create concept
        concept = Concept(
            name=name,
            course_owner=course_owner,
            topic_id=topic_id,
            description=description,
            source_doc_ref=source_doc_ref,
            embedding=embedding,
            visibility=Visibility(visibility)
        )
        
        query, params = CypherQueries.create_concept(concept)
        result = self.db.run_query(query, params)
        
        if result:
            return {
                "status": "success",
                "node_id": concept.id,
                "name": name,
                "level": "CONCEPT",
                "embedding_dim": len(embedding) if embedding else 0
            }
        return {"status": "error", "message": "Failed to create concept"}
    
    
    def create_fact(self, concept_id: str, name: str, course_owner: str,
                   description: str = "", source_doc_ref: str = "",
                   visibility: str = "global") -> Dict:
        """Create a new fact under a concept"""
        # Validate
        valid, msg = self.validator.validate_node_name(name)
        if not valid:
            return {"status": "error", "message": msg}
        
        # Check concept exists
        result = self.db.run_query(
            "MATCH (c:CONCEPT {id: $id}) RETURN count(c) as exists",
            {"id": concept_id}
        )
        if not result or result[0]["exists"] == 0:
            return {"status": "error", "message": "Concept not found"}
        
        # Create fact
        fact = Fact(
            name=name,
            course_owner=course_owner,
            concept_id=concept_id,
            description=description,
            source_doc_ref=source_doc_ref,
            visibility=Visibility(visibility)
        )
        
        query = (
            "MATCH (c:CONCEPT {id: $concept_id}) "
            "CREATE (f:FACT $fact_props)-[:CONTAINS]->(c) "
            "RETURN f"
        )
        result = self.db.run_query(query, {"fact_props": fact.to_dict(), "concept_id": concept_id})
        
        if result:
            return {
                "status": "success",
                "node_id": fact.id,
                "name": name,
                "level": "FACT"
            }
        return {"status": "error", "message": "Failed to create fact"}
    
    
    # ==================== Relationship Operations ====================
    
    def add_prerequisite(self, source_concept_id: str, target_concept_id: str,
                        weight: float = 1.0) -> Dict:
        """Add REQUIRES edge (source requires target as prerequisite)"""
        # Validate
        valid, msg = self.validator.validate_prerequisite_cycles(source_concept_id, target_concept_id)
        if not valid:
            return {"status": "error", "message": f"Cycle detection: {msg}"}
        
        query, params = CypherQueries.create_prerequisite(source_concept_id, target_concept_id, weight)
        result = self.db.run_query(query, params)
        
        if result:
            return {
                "status": "success",
                "edge_type": "REQUIRES",
                "source": source_concept_id,
                "target": target_concept_id
            }
        return {"status": "error", "message": "Failed to create prerequisite"}
    
    
    def add_extends_relationship(self, source_id: str, target_id: str) -> Dict:
        """Add EXTENDS edge (source extends/advances target concept)"""
        query = (
            "MATCH (c1 {id: $source_id}), (c2 {id: $target_id}) "
            "CREATE (c1)-[:EXTENDS]->(c2) "
            "RETURN c1, c2"
        )
        result = self.db.run_query(query, {"source_id": source_id, "target_id": target_id})
        
        if result:
            return {
                "status": "success",
                "edge_type": "EXTENDS",
                "source": source_id,
                "target": target_id
            }
        return {"status": "error", "message": "Failed to create extends relationship"}
    
    
    def add_contrasts_relationship(self, source_id: str, target_id: str) -> Dict:
        """Add CONTRASTS edge (source contrasts with target)"""
        query = (
            "MATCH (c1 {id: $source_id}), (c2 {id: $target_id}) "
            "CREATE (c1)-[:CONTRASTS]->(c2) "
            "RETURN c1, c2"
        )
        result = self.db.run_query(query, {"source_id": source_id, "target_id": target_id})
        
        if result:
            return {
                "status": "success",
                "edge_type": "CONTRASTS",
                "source": source_id,
                "target": target_id
            }
        return {"status": "error", "message": "Failed to create contrasts relationship"}
    
    
    # ==================== Student Overlay Operations ====================
    
    def create_student_overlay(self, user_id: str, concept_id: str,
                              theta: float = 0.0, slip: float = 0.1, 
                              guess: float = 0.1, visited: bool = False) -> Dict:
        """Create Bayesian Knowledge Tracing overlay for student"""
        # Validate BKT parameters
        valid, msg = self.validator.validate_bkt_parameters(theta, slip, guess)
        if not valid:
            return {"status": "error", "message": msg}
        
        # Check concept exists
        result = self.db.run_query(
            "MATCH (c:CONCEPT {id: $id}) RETURN count(c) as exists",
            {"id": concept_id}
        )
        if not result or result[0]["exists"] == 0:
            return {"status": "error", "message": "Concept not found"}
        
        # Calculate initial mastery probability using BKT
        mastery_probability = theta
        
        # Create overlay
        overlay = StudentOverlay(
            user_id=user_id,
            concept_id=concept_id,
            theta=theta,
            slip=slip,
            guess=guess,
            visited=visited,
            mastery_probability=mastery_probability
        )
        
        query, params = CypherQueries.create_student_overlay(overlay)
        result = self.db.run_query(query, params)
        
        if result:
            return {
                "status": "success",
                "user_id": user_id,
                "concept_id": concept_id,
                "mastery_probability": mastery_probability,
                "overlay_id": overlay.id
            }
        return {"status": "error", "message": "Failed to create student overlay"}
    
    
    def update_student_mastery(self, user_id: str, concept_id: str,
                              new_theta: float) -> Dict:
        """Update student's knowledge state"""
        valid, msg = self.validator.validate_bkt_parameters(new_theta, 0.1, 0.1)
        if not valid:
            return {"status": "error", "message": msg}
        
        query, params = CypherQueries.update_student_mastery(user_id, concept_id, new_theta)
        result = self.db.run_query(query, params)
        
        if result:
            return {
                "status": "success",
                "user_id": user_id,
                "concept_id": concept_id,
                "new_theta": new_theta
            }
        return {"status": "error", "message": "Failed to update mastery"}
    
    
    def mark_concept_visited(self, user_id: str, concept_id: str) -> Dict:
        """Mark concept as visited by student"""
        query = (
            "MATCH (s:StudentOverlay {user_id: $user_id, concept_id: $concept_id}) "
            "SET s.visited = true "
            "RETURN s"
        )
        result = self.db.run_query(query, {"user_id": user_id, "concept_id": concept_id})
        
        if result:
            return {"status": "success", "visited": True}
        return {"status": "error", "message": "Failed to mark as visited"}
    
    
    def initialize_student_overlays(self, user_id: str, course_id: str) -> Dict:
        """
        Initialize StudentOverlay nodes for all Concepts in a course when student enrolls.
        
        Args:
            user_id: Student user ID
            course_id: Course ID (same as course_owner in nodes)
        
        Returns:
            Dict with status, count of overlays created, and any errors
        """
        try:
            # Find all concepts in the course
            find_concepts_query = (
                "MATCH (c:CONCEPT {course_owner: $course_id}) "
                "RETURN c.id as concept_id"
            )
            concepts = self.db.run_query(find_concepts_query, {"course_id": course_id})
            
            if not concepts:
                return {
                    "status": "success",
                    "message": "No concepts found in course",
                    "overlays_created": 0,
                    "user_id": user_id,
                    "course_id": course_id
                }
            
            overlays_created = 0
            errors = []
            
            # Create StudentOverlay for each concept
            for concept_record in concepts:
                try:
                    concept_id = concept_record.get("concept_id")
                    
                    # Create StudentOverlay with initial parameters
                    overlay = StudentOverlay(
                        user_id=user_id,
                        concept_id=concept_id,
                        theta=0.0,
                        slip=0.1,
                        guess=0.1,
                        visited=False,
                        mastery_probability=0.5
                    )
                    
                    # Create in Neo4j
                    query, params = CypherQueries.create_student_overlay(overlay)
                    result = self.db.run_query(query, params)
                    
                    if result:
                        overlays_created += 1
                    else:
                        errors.append(f"Failed to create overlay for concept {concept_id}")
                        
                except Exception as e:
                    errors.append(f"Error creating overlay: {str(e)}")
            
            return {
                "status": "success",
                "message": f"Initialized {overlays_created} overlays for student",
                "overlays_created": overlays_created,
                "user_id": user_id,
                "course_id": course_id,
                "errors": errors if errors else None
            }
            
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to initialize overlays: {str(e)}",
                "overlays_created": 0,
                "user_id": user_id,
                "course_id": course_id
            }
    
    
    # ==================== Validation Operations ====================
    
    def validate_graph_integrity(self) -> Dict:
        """Comprehensive graph validation"""
        issues = []
        
        # Check for prerequisite cycles
        result = self.db.run_query(
            "MATCH (n)-[:REQUIRES*]->(n) RETURN n.id as node_id, n.name as name"
        )
        if result:
            issues.append({
                "type": "prerequisite_cycle",
                "count": len(result),
                "details": result
            })
        
        # Check for orphaned nodes (not in hierarchy)
        result = self.db.run_query(
            "MATCH (n) WHERE NOT (n)-[:CONTAINS]->() AND NOT ()-[:CONTAINS]->(n) "
            "AND NOT (n:StudentOverlay) RETURN n.id as id, n.name as name, labels(n) as labels"
        )
        if result:
            issues.append({
                "type": "orphaned_nodes",
                "count": len(result),
                "details": result
            })
        
        # Check for duplicate concept names
        result = self.db.run_query(
            "MATCH (c:CONCEPT) WITH c.name as name, count(c) as cnt "
            "WHERE cnt > 1 RETURN name, cnt"
        )
        if result:
            issues.append({
                "type": "duplicate_concept_names",
                "count": len(result),
                "details": result
            })
        
        return {
            "status": "valid" if not issues else "has_issues",
            "issue_count": len(issues),
            "issues": issues
        }
    
    
    def validate_prerequisite_cycles(self, source_id: str, target_id: str) -> Tuple[bool, str]:
        """Check if adding source->target would create a cycle"""
        # Check if target can reach source (which would create a cycle)
        result = self.db.run_query(
            "MATCH (source {id: $source_id}), (target {id: $target_id}) "
            "MATCH (target)-[:REQUIRES*]->(source) "
            "RETURN count(*) as path_count",
            {"source_id": source_id, "target_id": target_id}
        )
        
        if result and result[0]["path_count"] > 0:
            return False, f"Would create cycle: {target_id} already depends on {source_id}"
        return True, ""
    
    
    def check_duplicate_concept_in_topic(self, topic_id: str, name: str) -> bool:
        """Check if concept name already exists in topic"""
        result = self.db.run_query(
            "MATCH (t:TOPIC {id: $topic_id})-[:CONTAINS]->(c:CONCEPT {name: $name}) "
            "RETURN count(c) as count",
            {"topic_id": topic_id, "name": name}
        )
        return result and result[0]["count"] > 0
    
    
    # ==================== Query Operations ====================
    
    def get_node_by_id(
        self,
        node_id: str,
        user_context: Optional[UserContext] = None
    ) -> Optional[Dict]:
        """
        Retrieve node by ID with visibility filtering.
        
        Args:
            node_id: Node ID to retrieve
            user_context: User context for RBAC filtering (if None, assumes admin access)
        
        Returns:
            Node data if accessible by user, None otherwise
        """
        # If no user_context, assume admin and return any node
        if user_context is None:
            result = self.db.run_query(
                "MATCH (n {id: $id}) RETURN n",
                {"id": node_id}
            )
            return result[0] if result else None
        
        # Build visibility filter
        where_clause, params = RBACFilter.build_visibility_filter("n", user_context)
        params["id"] = node_id
        
        # Apply visibility filter
        query = f"MATCH (n {{id: $id}}) {where_clause} RETURN n"
        result = self.db.run_query(query, params)
        
        if result:
            # Additional post-query validation
            allowed, reason = RBACFilter.assert_read_permission(result[0]["n"].properties if hasattr(result[0]["n"], "properties") else result[0]["n"], user_context)
            if allowed:
                return result[0]
        
        return None
    
    
    def get_concept_hierarchy(
        self,
        concept_id: str,
        user_context: Optional[UserContext] = None
    ) -> Optional[Dict]:
        """
        Get full path: Module <- Topic <- Concept <- Facts
        
        Args:
            concept_id: Concept node ID
            user_context: User context for RBAC filtering
        
        Returns:
            Hierarchy data if accessible, None if user cannot access concept
        """
        
        # If no user_context, assume admin access
        if user_context is None:
            result = self.db.run_query(
                "MATCH (m:MODULE)-[:CONTAINS]->(t:TOPIC)-[:CONTAINS]->(c:CONCEPT {id: $concept_id})-[:CONTAINS]->(f:FACT) "
                "RETURN m, t, c, collect(f) as facts",
                {"concept_id": concept_id}
            )
            return result[0] if result else None
        
        # Build visibility filters for each level
        # Students cannot see professor-only concepts at all
        if user_context.is_student:
            # Students: can only see global or enrolled-only
            where_clause = (
                "WHERE (m.visibility IN ['global', 'enrolled-only'] "
                "AND t.visibility IN ['global', 'enrolled-only'] "
                "AND c.visibility IN ['global', 'enrolled-only'] "
                "AND f.visibility IN ['global', 'enrolled-only'])"
            )
            query = (
                "MATCH (m:MODULE)-[:CONTAINS]->(t:TOPIC)-[:CONTAINS]->(c:CONCEPT {id: $concept_id})-[:CONTAINS]->(f:FACT) "
                f"{where_clause} "
                "RETURN m, t, c, collect(f) as facts"
            )
            params = {"concept_id": concept_id}
        
        elif user_context.is_professor:
            # Professors: can see global, enrolled-only, and professor-only in their domain
            where_clause = (
                "WHERE (m.visibility IN ['global', 'enrolled-only', 'professor-only'] "
                "AND t.visibility IN ['global', 'enrolled-only', 'professor-only'] "
                "AND c.visibility IN ['global', 'enrolled-only', 'professor-only'] "
                "AND f.visibility IN ['global', 'enrolled-only', 'professor-only'])"
            )
            query = (
                "MATCH (m:MODULE)-[:CONTAINS]->(t:TOPIC)-[:CONTAINS]->(c:CONCEPT {id: $concept_id})-[:CONTAINS]->(f:FACT) "
                f"{where_clause} "
                "RETURN m, t, c, collect(f) as facts"
            )
            params = {"concept_id": concept_id}
        
        else:  # admin
            # Admins see everything
            query = (
                "MATCH (m:MODULE)-[:CONTAINS]->(t:TOPIC)-[:CONTAINS]->(c:CONCEPT {id: $concept_id})-[:CONTAINS]->(f:FACT) "
                "RETURN m, t, c, collect(f) as facts"
            )
            params = {"concept_id": concept_id}
        
        result = self.db.run_query(query, params)
        return result[0] if result else None
    
    
    def get_student_concepts(
        self,
        user_id: str,
        user_context: Optional[UserContext] = None
    ) -> List[Dict]:
        """
        Get all concepts a student is studying.
        
        Args:
            user_id: Student user ID
            user_context: User context for RBAC filtering
        
        Returns:
            List of concept overlays visible to the user
        """
        
        # If no user_context, assume admin access
        if user_context is None:
            result = self.db.run_query(
                "MATCH (s:StudentOverlay {user_id: $user_id})-[:STUDIED_BY]->(c:CONCEPT) "
                "RETURN s, c ORDER BY s.mastery_probability DESC",
                {"user_id": user_id}
            )
            return result
        
        # Students can only see their own overlays
        if user_context.is_student:
            if user_id != user_context.user_id:
                # Student cannot view another student's progress
                return []
            
            # Get overlays for visible concepts
            where_clause = (
                "WHERE (c.visibility = 'global' "
                "OR (c.visibility = 'enrolled-only' AND c.course_owner IN $course_ids))"
            )
            query = (
                "MATCH (s:StudentOverlay {user_id: $user_id})-[:STUDIED_BY]->(c:CONCEPT) "
                f"{where_clause} "
                "RETURN s, c ORDER BY s.mastery_probability DESC"
            )
            params = {
                "user_id": user_id,
                "course_ids": user_context.course_ids
            }
        
        elif user_context.is_professor:
            # Professors see overlays for their courses only
            query = (
                "MATCH (s:StudentOverlay {user_id: $user_id})-[:STUDIED_BY]->(c:CONCEPT) "
                "WHERE c.course_owner = $professor_id "
                "OR c.visibility = 'global' "
                "RETURN s, c ORDER BY s.mastery_probability DESC"
            )
            params = {
                "user_id": user_id,
                "professor_id": user_context.user_id
            }
        
        else:  # admin
            # Admins see all overlays
            query = (
                "MATCH (s:StudentOverlay {user_id: $user_id})-[:STUDIED_BY]->(c:CONCEPT) "
                "RETURN s, c ORDER BY s.mastery_probability DESC"
            )
            params = {"user_id": user_id}
        
        result = self.db.run_query(query, params)
        return result


# Compatibility alias for existing code
class GraphManager(Neo4jGraphManager):
    """Alias for backwards compatibility"""
    pass
