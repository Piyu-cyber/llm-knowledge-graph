"""
OmniProf v3.0 — Graph Service
High-level graph operations using the 4-level hierarchy
Module -> Topic -> Concept -> Fact with student overlays
"""

import logging
import math
from typing import List, Dict, Optional
from backend.db.graph_manager import GraphManager
from backend.db.graph_schema import Visibility
from backend.auth.rbac import UserContext, RBACFilter, RBACValidator, RBACLogger
from backend.services.jina_multimodal_service import JinaMultimodalService

logger = logging.getLogger(__name__)


class GraphService:
    """High-level graph operations"""
    
    def __init__(self,graph_manager):
        self.graph = graph_manager
        self.embedding_service = JinaMultimodalService()
    
    # ==================== Utility Methods ====================
    
    def _normalize_name(self, name: str) -> str:
        """Normalize node names"""
        if not name:
            return ""
        return name.strip()
    
    
    # ==================== Module Management ====================
    
    def create_module(
        self,
        name: str,
        course_owner: str,
        description: str = "",
        visibility: str = "global"
    ) -> Dict:
        """Create a new module"""
        return self.graph.create_module(
            name=self._normalize_name(name),
            course_owner=course_owner,
            description=description,
            visibility=visibility
        )
    
    
    # ==================== Topic Management ====================
    
    def create_topic(
        self,
        module_id: str,
        name: str,
        course_owner: str,
        description: str = "",
        visibility: str = "global"
    ) -> Dict:
        """Create a topic under a module"""
        return self.graph.create_topic(
            module_id=module_id,
            name=self._normalize_name(name),
            course_owner=course_owner,
            description=description,
            visibility=visibility
        )
    
    
    # ==================== Concept Management ====================
    
    def create_concept(
        self,
        topic_id: str,
        name: str,
        course_owner: str,
        description: str = "",
        source_doc_ref: str = "",
        embedding: Optional[List[float]] = None,
        visibility: str = "global",
        difficulty: float = 0.0
    ) -> Dict:
        """Create a concept under a topic"""
        payload = {
            "topic_id": topic_id,
            "name": self._normalize_name(name),
            "course_owner": course_owner,
            "description": description,
            "source_doc_ref": source_doc_ref,
            "embedding": embedding,
            "visibility": visibility,
            "difficulty": difficulty,
        }
        try:
            return self.graph.create_concept(**payload)
        except TypeError:
            payload.pop("difficulty", None)
            return self.graph.create_concept(**payload)
    
    
    # ==================== Fact Management ====================
    
    def create_fact(
        self,
        concept_id: str,
        name: str,
        course_owner: str,
        description: str = "",
        source_doc_ref: str = "",
        visibility: str = "global"
    ) -> Dict:
        """Create a fact under a concept"""
        return self.graph.create_fact(
            concept_id=concept_id,
            name=self._normalize_name(name),
            course_owner=course_owner,
            description=description,
            source_doc_ref=source_doc_ref,
            visibility=visibility
        )
    
    
    # ==================== Relationship Management ====================
    
    def add_prerequisite(
        self,
        source_concept_id: str,
        target_concept_id: str,
        weight: float = 1.0
    ) -> Dict:
        """Add a REQUIRES relationship (source requires target as prerequisite)"""
        return self.graph.add_prerequisite(
            source_concept_id=source_concept_id,
            target_concept_id=target_concept_id,
            weight=weight
        )
    
    
    def add_extends(
        self,
        source_id: str,
        target_id: str
    ) -> Dict:
        """Add an EXTENDS relationship (source extends target)"""
        return self.graph.add_extends_relationship(source_id, target_id)
    
    
    def add_contrasts(
        self,
        source_id: str,
        target_id: str
    ) -> Dict:
        """Add a CONTRASTS relationship"""
        return self.graph.add_contrasts_relationship(source_id, target_id)
    
    
    # ==================== Student Progress Tracking ====================
    
    def track_student_concept(
        self,
        user_id: str,
        concept_id: str,
        theta: float = 0.0,
        slip: float = 0.1,
        guess: float = 0.1
    ) -> Dict:
        """Create BKT overlay for a student on a concept"""
        return self.graph.create_student_overlay(
            user_id=user_id,
            concept_id=concept_id,
            theta=theta,
            slip=slip,
            guess=guess,
            visited=False
        )
    
    
    def update_student_mastery(
        self,
        user_id: str,
        concept_id: str,
        new_theta: float
    ) -> Dict:
        """Update student's knowledge state on a concept"""
        return self.graph.update_student_mastery(
            user_id=user_id,
            concept_id=concept_id,
            new_theta=new_theta
        )
    
    
    def mark_concept_visited(
        self,
        user_id: str,
        concept_id: str
    ) -> Dict:
        """Mark concept as visited by student"""
        return self.graph.mark_concept_visited(user_id, concept_id)
    
    
    # ==================== Graph Validation ====================
    
    def validate_graph(self) -> Dict:
        """Comprehensive graph integrity validation"""
        return self.graph.validate_graph_integrity()
    
    
    def validate_before_adding_concept(
        self,
        topic_id: str,
        name: str
    ) -> Dict:
        """Validate concept can be added to topic"""
        issues = []
        
        # Check if duplicate name in topic
        if self.graph.check_duplicate_concept_in_topic(topic_id, name):
            issues.append({
                "type": "duplicate_name",
                "message": f"Concept '{name}' already exists in this topic"
            })
        
        return {
            "valid": len(issues) == 0,
            "issues": issues
        }
    
    
    # ==================== Query & Retrieval ====================
    
    def get_node(
        self,
        node_id: str,
        user_context: Optional[UserContext] = None
    ) -> Optional[Dict]:
        """
        Retrieve node details by ID with RBAC enforcement.
        
        Args:
            node_id: Node ID to retrieve
            user_context: User context for visibility filtering
        
        Returns:
            Node details if accessible, None otherwise
        """
        try:
            result = self.graph.get_node_by_id(node_id, user_context)
            if result and user_context:
                RBACLogger.log_access_granted(user_context, f"node:{node_id}")
            return result
        except Exception as e:
            logger.error(f"Error retrieving node {node_id}: {str(e)}")
            if user_context:
                RBACLogger.log_access_denied(user_context, f"node:{node_id}", str(e))
            return None
    
    
    def get_concept_hierarchy(
        self,
        concept_id: str,
        user_context: Optional[UserContext] = None
    ) -> Optional[Dict]:
        """
        Get full path from Module -> Topic -> Concept -> Facts with RBAC.
        
        Args:
            concept_id: Concept node ID
            user_context: User context for visibility filtering
        
        Returns:
            Hierarchy data if accessible, None if user lacks permission
        """
        try:
            result = self.graph.get_concept_hierarchy(concept_id, user_context)
            if result and user_context:
                RBACLogger.log_access_granted(user_context, f"hierarchy:{concept_id}")
            return result
        except Exception as e:
            logger.error(f"Error retrieving hierarchy for {concept_id}: {str(e)}")
            if user_context:
                RBACLogger.log_access_denied(user_context, f"hierarchy:{concept_id}", str(e))
            return None
    
    
    def get_student_concepts(
        self,
        user_id: str,
        user_context: Optional[UserContext] = None
    ) -> List[Dict]:
        """
        Get all concepts a student is studying with progress and visibility filtering.
        
        Args:
            user_id: Student user ID
            user_context: User context for RBAC enforcement
        
        Returns:
            List of concept overlays visible to the requesting user
        """
        try:
            result = self.graph.get_student_concepts(user_id, user_context)
            if result and user_context:
                RBACLogger.log_access_granted(user_context, f"concepts:{user_id}")
            return result
        except Exception as e:
            logger.error(f"Error retrieving concepts for {user_id}: {str(e)}")
            if user_context:
                RBACLogger.log_access_denied(user_context, f"concepts:{user_id}", str(e))
            return []
    
    
    # ==================== Backwards Compatibility Methods ====================
    
    def create_concept_legacy(self, name: str, description: str = "") -> Dict:
        """Legacy method for simple concept creation"""
        # Used by existing ingestion service
        return {
            "status": "success",
            "id": f"concept_{id(name)}",
            "name": name,
            "description": description
        }
    
    
    def search_concepts(self, keyword: str) -> List[Dict]:
        """Search for concepts by keyword"""
        # Basic search - future: implement full-text search
        if not keyword:
            return []
        keyword = keyword.lower()
        return [
            {"name": keyword, "description": "Search result"}
        ]
    
    
    def get_graph(self) -> Dict:
        """Get graph statistics and metadata"""
        if hasattr(self.graph, "db") and hasattr(self.graph.db, "run_query"):
            result = self.graph.db.run_query(
                "MATCH (n) RETURN labels(n)[0] as type, count(n) as count "
                "UNION ALL "
                "MATCH ()-[r]->() RETURN type(r) as type, count(r) as count"
            )
            return {"status": "success", "graph_stats": result}

        # RustWorkX fallback
        node_count = self.graph.get_node_count() if hasattr(self.graph, "get_node_count") else 0
        edge_count = self.graph.get_edge_count() if hasattr(self.graph, "get_edge_count") else 0
        return {
            "status": "success",
            "graph_stats": [
                {"type": "nodes", "count": node_count},
                {"type": "edges", "count": edge_count},
            ],
        }
    
    
    # ==================== LLM Integration ====================
    
    def insert_from_llm(
        self,
        data: Dict,
        course_owner: str = "system"
    ) -> Dict:
        """
        Bulk insert from LLM extraction
        
        Expected format:
        {
            "module": "Machine Learning",
            "topic": "Neural Networks",
            "course_owner": "prof_123",
            "concepts": [
                {
                    "name": "Perceptron",
                    "description": "...",
                    "embedding": [0.1, 0.2, ..., 384-dim],
                    "source_doc": "document_1"
                }
            ],
            "relationships": [
                {
                    "source": "Perceptron",
                    "target": "Activation Function",
                    "type": "REQUIRES",
                    "weight": 0.8
                }
            ]
        }
        """
        try:
            module_name = data.get("module", "General")
            topic_name = data.get("topic", "General")
            course_owner = data.get("course_owner", course_owner)
            visibility = data.get("visibility", "global")
            
            # Create module
            module_result = self.create_module(
                name=module_name,
                course_owner=course_owner,
                visibility=visibility
            )
            if module_result["status"] != "success":
                return {"status": "error", "message": "Failed to create module"}
            module_id = module_result["node_id"]
            
            # Create topic
            topic_result = self.create_topic(
                module_id=module_id,
                name=topic_name,
                course_owner=course_owner,
                visibility=visibility
            )
            if topic_result["status"] != "success":
                return {"status": "error", "message": "Failed to create topic"}
            topic_id = topic_result["node_id"]
            
            # Create concepts
            concept_map = {}
            concepts = data.get("concepts", [])
            
            for concept_data in concepts:
                concept_name = concept_data.get("name", "")
                if not concept_name:
                    continue
                
                concept_result = self.create_concept(
                    topic_id=topic_id,
                    name=concept_name,
                    course_owner=course_owner,
                    description=concept_data.get("description", ""),
                    source_doc_ref=concept_data.get("source_doc", ""),
                    embedding=concept_data.get("embedding"),
                    visibility=visibility
                )
                
                if concept_result["status"] == "success":
                    concept_map[concept_name] = concept_result["node_id"]
            
            # Add relationships
            relationships = data.get("relationships", [])
            for rel in relationships:
                source_name = rel.get("source", "")
                target_name = rel.get("target", "")
                rel_type = rel.get("type", "REQUIRES").upper()
                weight = rel.get("weight", 1.0)
                
                source_id = concept_map.get(source_name)
                target_id = concept_map.get(target_name)
                
                if not source_id or not target_id:
                    continue
                
                if rel_type == "REQUIRES":
                    self.add_prerequisite(source_id, target_id, weight)
                elif rel_type == "EXTENDS":
                    self.add_extends(source_id, target_id)
                elif rel_type == "CONTRASTS":
                    self.add_contrasts(source_id, target_id)
            
            return {
                "status": "success",
                "module_id": module_id,
                "topic_id": topic_id,
                "concepts_created": len(concept_map),
                "relationships_added": len(relationships)
            }
        
        except Exception as e:
            logger.error(f"LLM insertion failed: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    
    def insert_from_llm_hierarchical(
        self,
        data: Dict,
        course_owner: str = "system",
        source_doc: str = "",
        file_format: str = "Unknown"
    ) -> Dict:
        """
        Insert hierarchical nodes extracted by LLM.
        
        Args:
            data: Dict with "nodes" and "edges" from hierarchical extraction
            course_owner: Course owner ID
            source_doc: Source document name
            file_format: File format (PDF, DOCX, PPTX, etc.)
        
        Returns:
            Dict with insertion results and validation status
        """
        try:
            nodes = data.get("nodes", [])
            edges = data.get("edges", [])
            
            if not nodes:
                return {"status": "error", "message": "No nodes provided"}
            
            # Organize nodes by level
            modules = [n for n in nodes if n.get("level", "").upper() == "MODULE"]
            topics = [n for n in nodes if n.get("level", "").upper() == "TOPIC"]
            concepts = [n for n in nodes if n.get("level", "").upper() == "CONCEPT"]
            facts = [n for n in nodes if n.get("level", "").upper() == "FACT"]
            
            # Track created node IDs for relationship building
            node_map = {}  # name -> node_id
            modules_created = 0
            topics_created = 0
            concepts_created = 0
            facts_created = 0
            relationships_added = 0
            
            # Step 1: Create modules
            default_module_id = None
            if modules:
                for module in modules:
                    try:
                        result = self.create_module(
                            name=module.get("name", "Module"),
                            course_owner=course_owner,
                            description=module.get("description", ""),
                            visibility="enrolled-only"
                        )
                        if result["status"] == "success":
                            node_map[module.get("name")] = result["node_id"]
                            default_module_id = result["node_id"]
                            modules_created += 1
                    except Exception as e:
                        logger.warning(f"Failed to create module: {str(e)}")
            else:
                # Create default module if none provided
                try:
                    result = self.create_module(
                        name=f"Extracted from {file_format}",
                        course_owner=course_owner,
                        description=f"Content extracted from {source_doc}",
                        visibility="enrolled-only"
                    )
                    if result["status"] == "success":
                        default_module_id = result["node_id"]
                        modules_created += 1
                except Exception as e:
                    logger.warning(f"Failed to create default module: {str(e)}")
            
            # Step 2: Create topics (under modules)
            default_topic_id = None
            if topics and default_module_id:
                for topic in topics:
                    try:
                        result = self.create_topic(
                            module_id=default_module_id,
                            name=topic.get("name", "Topic"),
                            course_owner=course_owner,
                            description=topic.get("description", ""),
                            visibility="enrolled-only"
                        )
                        if result["status"] == "success":
                            node_map[topic.get("name")] = result["node_id"]
                            default_topic_id = result["node_id"]
                            topics_created += 1
                    except Exception as e:
                        logger.warning(f"Failed to create topic: {str(e)}")
            else:
                # Create default topic if none provided
                if default_module_id:
                    try:
                        result = self.create_topic(
                            module_id=default_module_id,
                            name="Main Topic",
                            course_owner=course_owner,
                            description="Content from ingested document",
                            visibility="enrolled-only"
                        )
                        if result["status"] == "success":
                            default_topic_id = result["node_id"]
                            topics_created += 1
                    except Exception as e:
                        logger.warning(f"Failed to create default topic: {str(e)}")
            
            # Step 3: Create concepts (under topics)
            if concepts and default_topic_id:
                for concept in concepts:
                    try:
                        result = self.create_concept(
                            topic_id=default_topic_id,
                            name=concept.get("name", "Concept"),
                            course_owner=course_owner,
                            description=concept.get("description", ""),
                            source_doc_ref=source_doc,
                            visibility="enrolled-only"
                        )
                        if result["status"] == "success":
                            node_map[concept.get("name")] = result["node_id"]
                            concepts_created += 1
                    except Exception as e:
                        logger.warning(f"Failed to create concept: {str(e)}")
            
            # Step 4: Create facts (under concepts)
            concept_ids = list(node_map.values())[-concepts_created:] if concepts_created > 0 else []
            
            if facts and concept_ids:
                concept_id = concept_ids[0] if concept_ids else default_topic_id
                for fact in facts:
                    try:
                        result = self.create_fact(
                            concept_id=concept_id,
                            name=fact.get("name", "Fact"),
                            course_owner=course_owner,
                            description=fact.get("description", ""),
                            source_doc_ref=source_doc,
                            visibility="enrolled-only"
                        )
                        if result["status"] == "success":
                            node_map[fact.get("name")] = result["node_id"]
                            facts_created += 1
                    except Exception as e:
                        logger.warning(f"Failed to create fact: {str(e)}")
            
            # Step 5: Create relationships
            for edge in edges:
                try:
                    source_name = edge.get("source", "")
                    target_name = edge.get("target", "")
                    rel_type = edge.get("type", "RELATED").upper()
                    
                    source_id = node_map.get(source_name)
                    target_id = node_map.get(target_name)
                    
                    if not source_id or not target_id:
                        continue
                    
                    # Create appropriate relationship type
                    if rel_type == "REQUIRES":
                        self.add_prerequisite(source_id, target_id, weight=1.0)
                        relationships_added += 1
                    elif rel_type == "EXTENDS":
                        self.add_extends(source_id, target_id)
                        relationships_added += 1
                    elif rel_type == "CONTRASTS":
                        self.add_contrasts(source_id, target_id)
                        relationships_added += 1
                    # RELATED edges: we can add as generic relationships
                except Exception as e:
                    logger.warning(f"Failed to create edge {source_name}->{target_name}: {str(e)}")
            
            # Step 6: Validate graph
            try:
                validation = self.validate_graph()
                validation_errors = validation.get("issues", [])
            except Exception as e:
                logger.warning(f"Graph validation failed: {str(e)}")
                validation_errors = []
            
            return {
                "status": "success",
                "modules_added": modules_created,
                "topics_added": topics_created,
                "concepts_added": concepts_created,
                "facts_added": facts_created,
                "relationships_added": relationships_added,
                "source_doc": source_doc,
                "file_format": file_format,
                "validation_errors": validation_errors
            }
        
        except Exception as e:
            logger.error(f"Hierarchical LLM insertion failed: {str(e)}")
            return {"status": "error", "message": str(e)}

    def incremental_reingest_from_llm(
        self,
        data: Dict,
        course_owner: str,
        source_doc: str,
        file_format: str = "Unknown",
    ) -> Dict:
        """
        Incrementally re-ingest only nodes affected by source document.

        Unrelated nodes and overlays remain untouched.
        """
        try:
            existing = self.graph.get_nodes_by_source_doc(source_doc, course_owner=course_owner)
            existing_ids = [n["id"] for n in existing]

            # Delete previously ingested nodes from this source doc only.
            delete_result = self.graph.delete_nodes(existing_ids)
            if delete_result.get("status") != "success":
                return {"status": "error", "message": "Failed to remove outdated document subgraph"}

            insert_result = self.insert_from_llm_hierarchical(
                data=data,
                course_owner=course_owner,
                source_doc=source_doc,
                file_format=file_format,
            )
            if insert_result.get("status") != "success":
                return insert_result

            return {
                "status": "success",
                "reingested_source": source_doc,
                "removed_nodes": len(existing_ids),
                **insert_result,
            }
        except Exception as e:
            logger.error(f"Incremental re-ingestion failed: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    
    # ==================== Student Enrollment ====================
    
    def enroll_student(self, user_id: str, course_id: str) -> Dict:
        """
        Enroll a student in a course by initializing StudentOverlay nodes.
        
        Creates StudentOverlay nodes for all concepts in the course with:
        - theta=0.0 (initial knowledge state)
        - slip=0.1 (slip probability)
        - guess=0.1 (guess probability)
        - visited=False (not yet visited)
        - mastery_probability=0.5 (initial mastery estimate)
        
        Args:
            user_id: Student user ID
            course_id: Course ID
        
        Returns:
            Dict with enrollment status and overlay count
        """
        try:
            result = self.graph.initialize_student_overlays(user_id, course_id)
            logger.info(f"Student {user_id} enrolled in course {course_id}: {result.get('overlays_created')} overlays created")
            return result
        except Exception as e:
            logger.error(f"Student enrollment failed: {str(e)}")
            return {
                "status": "error",
                "message": f"Enrollment failed: {str(e)}",
                "overlays_created": 0,
                "user_id": user_id,
                "course_id": course_id
            }

    def enqueue_enrollment_overlay_init(self, user_id: str, course_id: str, background_tasks) -> Dict:
        """Queue async overlay initialization so enrollment request returns immediately."""
        background_tasks.add_task(self.graph.initialize_student_overlays, user_id, course_id)
        return {
            "status": "queued",
            "user_id": user_id,
            "course_id": course_id,
            "overlays_created": 0,
            "message": "Enrollment confirmed. Student overlay initialization queued."
        }

    def _is_visible_to_user(self, node: Dict, user_context: UserContext) -> bool:
        allowed, _ = RBACFilter.assert_read_permission(node, user_context)
        return allowed

    def _theta_to_mastery(self, theta: float) -> float:
        """Normalize theta-like values to [0, 1] mastery."""
        t = float(theta)
        if 0.0 <= t <= 1.0:
            return t
        exponent = max(-500.0, min(500.0, -1.7 * t))
        return 1.0 / (1.0 + math.exp(exponent))

    def personalized_graph_walk(
        self,
        query: str,
        user_context: UserContext,
        student_id: Optional[str] = None,
        top_k: int = 6,
        seed_k: int = 3,
        expansion_hops: int = 2,
    ) -> List[Dict]:
        """
        Three-step personalized retrieval:
        1) vector seed from query embedding, 2) mastery-weighted graph expansion,
        3) top-k context assembly within RBAC scope.
        """
        if not query.strip():
            return []

        concepts = self.graph.get_concept_nodes()
        visible_concepts = [c for c in concepts if RBACFilter.assert_read_permission(c, user_context)[0]]
        if not visible_concepts:
            return []

        query_embedding = self.embedding_service.embed_text(query)

        scored = []
        for concept in visible_concepts:
            embedding = concept.get("embedding")
            if not embedding:
                text = f"{concept.get('name', '')} {concept.get('description', '')}".strip()
                embedding = self.embedding_service.embed_text(text)

            vector_score = self.embedding_service.cosine_similarity(query_embedding, embedding)
            scored.append({**concept, "vector_score": float(vector_score), "score": float(vector_score)})

        scored.sort(key=lambda x: x["vector_score"], reverse=True)
        seeds = scored[:max(1, seed_k)]

        expanded: Dict[str, Dict] = {s["id"]: s for s in seeds}
        frontier = [{"node": s, "depth": 0} for s in seeds]
        student_key = student_id or user_context.user_id

        while frontier:
            current = frontier.pop(0)
            node = current["node"]
            depth = current["depth"]
            if depth >= expansion_hops:
                continue

            neighbors = self.graph.get_related_concepts(node["id"], relations=["REQUIRES", "EXTENDS"])
            for neighbor in neighbors:
                if not RBACFilter.assert_read_permission(neighbor, user_context)[0]:
                    continue

                overlay = self.graph.get_student_overlay(student_key, neighbor["id"])
                theta = float(overlay.get("theta", 0.0)) if overlay else 0.0
                mastery = self._theta_to_mastery(theta)

                relation = neighbor.get("relation", "")
                direction = neighbor.get("direction", "")

                is_foundational = (relation == "REQUIRES" and direction == "in") or (relation == "EXTENDS" and direction == "out")
                priority = (1.0 - mastery) if is_foundational else mastery
                hop_discount = 0.9 ** (depth + 1)

                expansion_score = node.get("score", node.get("vector_score", 0.0)) * hop_discount * (0.35 + 1.15 * priority)
                merged_score = max(float(expansion_score), expanded.get(neighbor["id"], {}).get("score", 0.0))

                if neighbor["id"] not in expanded or merged_score > expanded[neighbor["id"]].get("score", 0.0):
                    expanded[neighbor["id"]] = {
                        **neighbor,
                        "vector_score": float(neighbor.get("vector_score", 0.0)),
                        "score": merged_score,
                        "theta": theta,
                    }
                    frontier.append({"node": expanded[neighbor["id"]], "depth": depth + 1})

        ranked = sorted(expanded.values(), key=lambda x: x.get("score", 0.0), reverse=True)
        return ranked[:max(1, top_k)]
