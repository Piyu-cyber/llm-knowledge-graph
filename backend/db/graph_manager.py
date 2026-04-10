"""
OmniProf v3.0 — RustWorkX-based Graph Manager (Neo4j Replacement)
In-memory graph with JSON persistence for knowledge graph operations
"""

import json
import os
import math
import uuid
import threading
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime
import logging

try:
    import rustworkx as rx
except ImportError:
    raise ImportError("rustworkx is required: pip install rustworkx")

from backend.db.graph_schema import (
    Module, Topic, Concept, Fact, StudentOverlay, SemanticNode, MemoryAnchor,
    GraphEdge, GraphValidator, NodeLevel, Visibility, EdgeType
)
from backend.auth.rbac import UserContext

logger = logging.getLogger(__name__)


class GraphManager:
    """RustWorkX-based graph manager with JSON persistence"""

    _instances: Dict[str, "GraphManager"] = {}
    _instances_lock = threading.Lock()

    def __new__(cls, data_dir: str = "data", *args, **kwargs):
        key = os.path.abspath(data_dir or "data")
        with cls._instances_lock:
            instance = cls._instances.get(key)
            if instance is None:
                instance = super().__new__(cls)
                cls._instances[key] = instance
                instance._initialized = False
            return instance
    
    def __init__(self, data_dir: str = "data"):
        if getattr(self, "_initialized", False):
            return

        self.data_dir = data_dir
        self.graph_file = os.path.join(data_dir, "knowledge_graph.json")
        self.nodes_file = os.path.join(data_dir, "nodes.json")
        self.edges_file = os.path.join(data_dir, "edges.json")
        
        # Create data directory if needed
        os.makedirs(data_dir, exist_ok=True)
        
        # Initialize rustworkx graph
        self.graph = rx.PyDiGraph()
        self.validator = GraphValidator()
        
        # Node storage: {node_id -> node_data}
        self.nodes_data = {}
        # rustworkx node index mapping: {node_id -> node_index}
        self.node_index_by_id = {}
        
        # Load existing data
        self._load_graph()

        self._initialized = True
        
        logger.info("GraphManager initialized with RustWorkX backend")

    def _theta_to_mastery_probability(self, theta: float) -> float:
        """Map theta to [0,1] mastery probability using logistic transform."""
        exponent = -1.7 * float(theta)
        exponent = max(-500.0, min(500.0, exponent))
        return 1.0 / (1.0 + math.exp(exponent))

    def _check_same_course(self, source_id: str, target_id: str) -> Optional[str]:
        """Disallow structured cross-course edges in v1."""
        source_owner = self.nodes_data.get(source_id, {}).get("course_owner")
        target_owner = self.nodes_data.get(target_id, {}).get("course_owner")
        if source_owner and target_owner and source_owner != target_owner:
            return (
                "Cross-course structured edges are disabled in v1. "
                "Use informal prerequisite text until v2."
            )
        return None

    def _add_node_to_graph(self, node_id: str) -> None:
        """Add node id payload to rustworkx graph if not already present."""
        if node_id in self.node_index_by_id:
            return
        self.node_index_by_id[node_id] = self.graph.add_node(node_id)

    def _add_edge_to_graph(self, source_id: str, target_id: str, data: Optional[Dict] = None) -> None:
        """Add directed edge between node ids in rustworkx graph."""
        self._add_node_to_graph(source_id)
        self._add_node_to_graph(target_id)
        source_idx = self.node_index_by_id[source_id]
        target_idx = self.node_index_by_id[target_id]
        self.graph.add_edge(source_idx, target_idx, data or {})

    def _edge_records(self) -> List[Dict]:
        """Return edge records using node ids."""
        records = []
        for source_idx, target_idx in self.graph.edge_list():
            source_id = self.graph[source_idx]
            target_id = self.graph[target_idx]
            records.append(
                {
                    "source": source_id,
                    "target": target_id,
                    "data": self.graph.get_edge_data(source_idx, target_idx) or {},
                }
            )
        return records

    def _rebuild_graph(self, edge_records: List[Dict]) -> None:
        """Rebuild in-memory rustworkx graph from nodes_data and edge records."""
        self.graph = rx.PyDiGraph()
        self.node_index_by_id = {}
        for node_id in self.nodes_data:
            self._add_node_to_graph(node_id)
        for edge in edge_records:
            source_id = edge.get("source")
            target_id = edge.get("target")
            if source_id in self.nodes_data and target_id in self.nodes_data:
                self._add_edge_to_graph(source_id, target_id, edge.get("data", {}))
    
    def _load_graph(self):
        """Load graph from JSON files"""
        try:
            if os.path.exists(self.nodes_file):
                with open(self.nodes_file, 'r') as f:
                    self.nodes_data = json.load(f)
                    # Rebuild graph nodes
                    for node_id, node_data in self.nodes_data.items():
                        self._add_node_to_graph(node_id)
                logger.info(f"Loaded {len(self.nodes_data)} nodes")
            
            if os.path.exists(self.edges_file):
                with open(self.edges_file, 'r') as f:
                    edges_data = json.load(f)
                    for edge in edges_data:
                        source_id = edge.get('source')
                        target_id = edge.get('target')
                        if source_id in self.nodes_data and target_id in self.nodes_data:
                            self._add_edge_to_graph(source_id, target_id, edge.get('data', {}))
                logger.info(f"Loaded {len(edges_data)} edges")
        except Exception as e:
            logger.warning(f"Could not load graph: {str(e)}. Starting fresh.")
            self.nodes_data = {}
    
    def _save_graph(self):
        """Save graph to JSON files"""
        try:
            # Save nodes
            with open(self.nodes_file, 'w') as f:
                json.dump(self.nodes_data, f, indent=2)
            
            # Save edges
            edges_list = []
            for source_idx, target_idx in self.graph.edge_list():
                source_id = self.graph[source_idx]
                target_id = self.graph[target_idx]
                edge_data = self.graph.get_edge_data(source_idx, target_idx) or {}
                edges_list.append({
                    'source': source_id,
                    'target': target_id,
                    'data': edge_data
                })
            
            with open(self.edges_file, 'w') as f:
                json.dump(edges_list, f, indent=2)
            
            logger.debug("Graph saved to JSON")
        except Exception as e:
            logger.error(f"Failed to save graph: {str(e)}")
    
    # ==================== Module Operations ====================
    
    def create_module(self, name: str, course_owner: str, 
                     description: str = "", visibility: str = "global") -> Dict:
        """Create a new module"""
        valid, msg = self.validator.validate_node_name(name)
        if not valid:
            return {"status": "error", "message": msg}
        
        module = Module(
            name=name,
            course_owner=course_owner,
            description=description,
            visibility=Visibility(visibility)
        )
        
        node_data = module.to_dict()
        node_data['level'] = 'MODULE'
        node_data['created_at'] = datetime.now().isoformat()
        
        self._add_node_to_graph(module.id)
        self.nodes_data[module.id] = node_data
        self._save_graph()
        
        return {
            "status": "success",
            "node_id": module.id,
            "name": name,
            "level": "MODULE"
        }
    
    def create_topic(self, module_id: str, name: str, course_owner: str,
                    description: str = "", visibility: str = "global") -> Dict:
        """Create a new topic under a module"""
        valid, msg = self.validator.validate_node_name(name)
        if not valid:
            return {"status": "error", "message": msg}
        
        # Check module exists
        if module_id not in self.nodes_data:
            return {"status": "error", "message": "Module not found"}
        
        topic = Topic(
            name=name,
            course_owner=course_owner,
            module_id=module_id,
            description=description,
            visibility=Visibility(visibility)
        )
        
        node_data = topic.to_dict()
        node_data['level'] = 'TOPIC'
        node_data['module_id'] = module_id
        node_data['created_at'] = datetime.now().isoformat()
        
        self._add_node_to_graph(topic.id)
        self.nodes_data[topic.id] = node_data
        
        # Add CONTAINS edge
        self._add_edge_to_graph(module_id, topic.id, {'relation': 'CONTAINS'})
        self._save_graph()
        
        return {
            "status": "success",
            "node_id": topic.id,
            "name": name,
            "level": "TOPIC"
        }
    
    def create_concept(self, topic_id: str, name: str, course_owner: str,
                      description: str = "", source_doc_ref: str = "",
                      embedding: Optional[List[float]] = None,
                      visibility: str = "global",
                      difficulty: float = 0.0) -> Dict:
        """Create a new concept under a topic"""
        valid, msg = self.validator.validate_node_name(name)
        if not valid:
            return {"status": "error", "message": msg}
        
        if topic_id not in self.nodes_data:
            return {"status": "error", "message": "Topic not found"}
        
        concept = Concept(
            name=name,
            course_owner=course_owner,
            topic_id=topic_id,
            description=description,
            source_doc_ref=source_doc_ref,
            embedding=embedding,
            visibility=Visibility(visibility),
            difficulty=difficulty
        )
        
        node_data = concept.to_dict()
        node_data['level'] = 'CONCEPT'
        node_data['topic_id'] = topic_id
        node_data['created_at'] = datetime.now().isoformat()
        
        self._add_node_to_graph(concept.id)
        self.nodes_data[concept.id] = node_data
        
        # Add CONTAINS edge
        self._add_edge_to_graph(topic_id, concept.id, {'relation': 'CONTAINS'})
        self._save_graph()
        
        return {
            "status": "success",
            "node_id": concept.id,
            "name": name,
            "level": "CONCEPT",
            "embedding_dim": len(embedding) if embedding else 0
        }
    
    def create_fact(self, concept_id: str, name: str, course_owner: str,
                   description: str = "", source_doc_ref: str = "",
                   visibility: str = "global") -> Dict:
        """Create a new fact under a concept"""
        valid, msg = self.validator.validate_node_name(name)
        if not valid:
            return {"status": "error", "message": msg}
        
        if concept_id not in self.nodes_data:
            return {"status": "error", "message": "Concept not found"}
        
        fact = Fact(
            name=name,
            course_owner=course_owner,
            concept_id=concept_id,
            description=description,
            source_doc_ref=source_doc_ref,
            visibility=Visibility(visibility)
        )
        
        node_data = fact.to_dict()
        node_data['level'] = 'FACT'
        node_data['concept_id'] = concept_id
        node_data['created_at'] = datetime.now().isoformat()
        
        self._add_node_to_graph(fact.id)
        self.nodes_data[fact.id] = node_data
        
        # Add CONTAINS edge
        self._add_edge_to_graph(concept_id, fact.id, {'relation': 'CONTAINS'})
        self._save_graph()
        
        return {
            "status": "success",
            "node_id": fact.id,
            "name": name,
            "level": "FACT"
        }

    # ==================== Relationship Operations ====================

    def add_extends_relationship(self, source_id: str, target_id: str) -> Dict:
        """Add EXTENDS relationship between concept nodes."""
        if not all(x in self.nodes_data for x in [source_id, target_id]):
            return {"status": "error", "message": "Node(s) not found"}
        course_error = self._check_same_course(source_id, target_id)
        if course_error:
            return {"status": "error", "message": course_error}
        self._add_edge_to_graph(source_id, target_id, {"relation": "EXTENDS"})
        self._save_graph()
        return {"status": "success", "source": source_id, "target": target_id}

    def add_contrasts_relationship(self, source_id: str, target_id: str) -> Dict:
        """Add CONTRASTS relationship between concept nodes."""
        if not all(x in self.nodes_data for x in [source_id, target_id]):
            return {"status": "error", "message": "Node(s) not found"}
        course_error = self._check_same_course(source_id, target_id)
        if course_error:
            return {"status": "error", "message": course_error}
        self._add_edge_to_graph(source_id, target_id, {"relation": "CONTRASTS"})
        self._save_graph()
        return {"status": "success", "source": source_id, "target": target_id}

    # ==================== Overlay Compatibility Operations ====================

    def create_student_overlay(
        self,
        user_id: str,
        concept_id: str,
        theta: float = 0.0,
        slip: float = 0.1,
        guess: float = 0.1,
        visited: bool = False,
    ) -> Dict:
        """Create a single student overlay node for a concept."""
        if concept_id not in self.nodes_data:
            return {"status": "error", "message": "Concept not found"}

        existing = self.get_student_overlay(user_id, concept_id)
        if existing:
            return {"status": "success", "overlay_id": existing["id"], "mastery_probability": existing.get("mastery_probability", 0.0)}

        mastery_probability = self._theta_to_mastery_probability(theta)
        overlay = StudentOverlay(
            user_id=user_id,
            concept_id=concept_id,
            theta=theta,
            slip=slip,
            guess=guess,
            visited=visited,
            mastery_probability=mastery_probability,
        )
        overlay_data = overlay.to_dict()
        overlay_data["node_type"] = "StudentOverlay"
        overlay_data["created_at"] = datetime.now().isoformat()

        self._add_node_to_graph(overlay.id)
        self.nodes_data[overlay.id] = overlay_data
        self._save_graph()

        return {"status": "success", "overlay_id": overlay.id, "mastery_probability": mastery_probability}

    def update_student_mastery(self, user_id: str, concept_id: str, new_theta: float) -> Dict:
        """Update student theta/mastery for one concept overlay."""
        overlay = self.get_student_overlay(user_id, concept_id)
        if not overlay:
            return {"status": "error", "message": "Overlay not found"}

        overlay_id = overlay["id"]
        overlay_data = self.nodes_data[overlay_id]
        overlay_data["theta"] = max(-4.0, min(4.0, float(new_theta)))
        slip = float(overlay_data.get("slip", 0.1))
        guess = float(overlay_data.get("guess", 0.1))
        theta01 = max(0.0, min(1.0, (overlay_data["theta"] + 4.0) / 8.0))
        overlay_data["mastery_probability"] = theta01 * (1 - slip) + (1 - theta01) * guess
        overlay_data["last_updated"] = datetime.now().isoformat()
        self._save_graph()
        return {"status": "success", "theta": overlay_data["theta"], "mastery_probability": overlay_data["mastery_probability"]}

    def mark_concept_visited(self, user_id: str, concept_id: str) -> Dict:
        """Mark concept visited for a student overlay."""
        overlay = self.get_student_overlay(user_id, concept_id)
        if not overlay:
            return {"status": "error", "message": "Overlay not found"}
        overlay_id = overlay["id"]
        self.nodes_data[overlay_id]["visited"] = True
        self.nodes_data[overlay_id]["last_updated"] = datetime.now().isoformat()
        self._save_graph()
        return {"status": "success", "visited": True}

    # ==================== Validation Operations ====================

    def check_duplicate_concept_in_topic(self, topic_id: str, name: str) -> bool:
        """Check duplicate concept name in a topic (case-insensitive)."""
        name_norm = name.strip().lower()
        for node in self.nodes_data.values():
            if node.get("level") == "CONCEPT" and node.get("topic_id") == topic_id and node.get("name", "").strip().lower() == name_norm:
                return True
        return False

    def _requires_adjacency(self) -> Dict[str, List[str]]:
        adj: Dict[str, List[str]] = {}
        for edge in self._edge_records():
            relation = str(edge.get("data", {}).get("relation", "")).upper()
            if relation != "REQUIRES":
                continue
            src = edge["source"]
            tgt = edge["target"]
            if self.nodes_data.get(src, {}).get("level") == "CONCEPT" and self.nodes_data.get(tgt, {}).get("level") == "CONCEPT":
                adj.setdefault(src, []).append(tgt)
        return adj

    def _detect_requires_cycles(self) -> List[List[str]]:
        adj = self._requires_adjacency()
        visited = set()
        in_stack = set()
        stack: List[str] = []
        cycles: List[List[str]] = []

        def dfs(node: str) -> None:
            visited.add(node)
            in_stack.add(node)
            stack.append(node)
            for nxt in adj.get(node, []):
                if nxt not in visited:
                    dfs(nxt)
                elif nxt in in_stack:
                    try:
                        idx = stack.index(nxt)
                        cycles.append(stack[idx:] + [nxt])
                    except ValueError:
                        cycles.append([node, nxt])
            stack.pop()
            in_stack.remove(node)

        for n in adj:
            if n not in visited:
                dfs(n)
        return cycles

    def _find_orphans(self) -> List[str]:
        incoming: Dict[str, int] = {nid: 0 for nid in self.nodes_data}
        outgoing: Dict[str, int] = {nid: 0 for nid in self.nodes_data}
        for edge in self._edge_records():
            source = edge["source"]
            target = edge["target"]
            if source in outgoing:
                outgoing[source] += 1
            if target in incoming:
                incoming[target] += 1

        orphans = []
        for node_id, node in self.nodes_data.items():
            level = node.get("level")
            if level == "MODULE":
                continue
            if incoming.get(node_id, 0) == 0 and outgoing.get(node_id, 0) == 0:
                orphans.append(node_id)
        return orphans

    def _find_duplicate_concepts(self) -> List[Dict]:
        seen: Dict[Tuple[str, str], str] = {}
        duplicates: List[Dict] = []
        for node_id, node in self.nodes_data.items():
            if node.get("level") != "CONCEPT":
                continue
            key = (str(node.get("course_owner", "")), str(node.get("name", "")).strip().lower())
            if key in seen:
                duplicates.append({"first": seen[key], "duplicate": node_id, "name": node.get("name", "")})
            else:
                seen[key] = node_id
        return duplicates

    def _append_review_queue(self, issues: List[Dict]) -> None:
        if not issues:
            return
        review_path = os.path.join(self.data_dir, "review_queue.json")
        existing: List[Dict] = []
        if os.path.exists(review_path):
            try:
                with open(review_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = []

        existing.append({"timestamp": datetime.now().isoformat(), "issues": issues})
        with open(review_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)

    def validate_graph_integrity(self) -> Dict:
        """Validate cycles/orphans/duplicates and append failures to review queue."""
        issues: List[Dict] = []

        cycles = self._detect_requires_cycles()
        for cycle in cycles:
            issues.append({"type": "prerequisite_cycle", "path": cycle})

        for orphan_id in self._find_orphans():
            issues.append({"type": "orphan_node", "node_id": orphan_id, "level": self.nodes_data.get(orphan_id, {}).get("level")})

        for dup in self._find_duplicate_concepts():
            issues.append({"type": "duplicate_concept", **dup})

        self._append_review_queue(issues)

        return {
            "status": "valid" if not issues else "invalid",
            "issue_count": len(issues),
            "issues": issues,
        }

    # ==================== Query Compatibility Methods ====================

    def get_node_by_id(self, node_id: str, user_context: Optional[UserContext] = None) -> Optional[Dict]:
        node = self.nodes_data.get(node_id)
        if not node:
            return None
        if user_context:
            visibility = node.get("visibility", "global")
            if visibility == "professor-only" and user_context.role not in ["professor", "admin"]:
                return None
            if visibility == "enrolled-only" and user_context.role == "student":
                if node.get("course_owner") not in user_context.course_ids:
                    return None
        return {**node, "id": node_id}

    def get_student_concepts(self, user_id: str, user_context: Optional[UserContext] = None) -> List[Dict]:
        results = []
        for node_id, node in self.nodes_data.items():
            if node.get("user_id") != user_id or "concept_id" not in node:
                continue
            if user_context and user_context.role == "student" and user_context.user_id != user_id:
                continue
            results.append({**node, "id": node_id})
        return results

    # ==================== Incremental Re-ingestion Helpers ====================

    def get_nodes_by_source_doc(self, source_doc_ref: str, course_owner: Optional[str] = None) -> List[Dict]:
        results = []
        for node_id, node in self.nodes_data.items():
            if node.get("source_doc_ref") != source_doc_ref:
                continue
            if course_owner and node.get("course_owner") != course_owner:
                continue
            results.append({**node, "id": node_id})
        return results

    def delete_nodes(self, node_ids: List[str]) -> Dict:
        delete_set = set(node_ids)
        if not delete_set:
            return {"status": "success", "deleted": 0}

        edge_records = [
            e for e in self._edge_records()
            if e.get("source") not in delete_set and e.get("target") not in delete_set
        ]

        for node_id in delete_set:
            self.nodes_data.pop(node_id, None)

        self._rebuild_graph(edge_records)
        self._save_graph()
        return {"status": "success", "deleted": len(delete_set)}
    
    # ==================== Student Overlay Operations ====================
    
    def initialize_student_overlays(self, user_id: str, course_id: str) -> Dict:
        """Create StudentOverlay for all concepts in a course"""
        try:
            # Find all concepts for the course
            concept_ids = []
            for node_id, node_data in self.nodes_data.items():
                if (node_data.get('level') == 'CONCEPT' and 
                    node_data.get('course_owner') == course_id):
                    concept_ids.append(node_id)
            
            created_count = 0
            for concept_id in concept_ids:
                existing = self.get_student_overlay(user_id, concept_id)
                if existing:
                    continue

                overlay = StudentOverlay(
                    user_id=user_id,
                    concept_id=concept_id,
                    theta=0.0,
                    slip=0.1,
                    guess=0.1,
                    visited=False,
                    mastery_probability=0.5
                )
                
                overlay_data = overlay.to_dict()
                overlay_data['node_type'] = 'StudentOverlay'
                overlay_data['created_at'] = datetime.now().isoformat()
                
                self._add_node_to_graph(overlay.id)
                self.nodes_data[overlay.id] = overlay_data
                created_count += 1
            
            self._save_graph()
            
            return {
                "status": "success",
                "user_id": user_id,
                "course_id": course_id,
                "overlays_created": created_count
            }
        except Exception as e:
            logger.error(f"Failed to initialize overlays: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def get_student_overlay(self, user_id: str, concept_id: str) -> Optional[Dict]:
        """Get a student's overlay for a concept"""
        for node_id, node_data in self.nodes_data.items():
            if (node_data.get('user_id') == user_id and 
                node_data.get('concept_id') == concept_id):
                return {**node_data, 'id': node_id}
        return None
    
    def update_student_overlay(self, overlay_id: str, 
                              updates: Optional[Dict] = None,
                              theta: Optional[float] = None,
                              mastery_probability: Optional[float] = None,
                              visited: Optional[bool] = None) -> Dict:
        """Update a student overlay
        
        Can be called with either:
        - update_student_overlay(id, updates={...})
        - update_student_overlay(id, theta=..., mastery_probability=..., visited=...)
        """
        if overlay_id not in self.nodes_data:
            return {"status": "error", "message": "Overlay not found"}
        
        node_data = self.nodes_data[overlay_id]
        
        # Support both calling patterns
        if updates:
            # Dict-based update
            if 'theta' in updates:
                node_data['theta'] = max(-4.0, min(4.0, float(updates['theta'])))
            if 'slip' in updates:
                node_data['slip'] = updates['slip']
            if 'mastery_probability' in updates:
                node_data['mastery_probability'] = max(0.0, min(1.0, updates['mastery_probability']))
            if 'visited' in updates:
                node_data['visited'] = updates['visited']
        else:
            # Individual parameter updates
            if theta is not None:
                node_data['theta'] = max(-4.0, min(4.0, float(theta)))
            if mastery_probability is not None:
                node_data['mastery_probability'] = max(0.0, min(1.0, mastery_probability))
            elif theta is not None:
                node_data['mastery_probability'] = self._theta_to_mastery_probability(node_data['theta'])
            if visited is not None:
                node_data['visited'] = visited
        
        node_data['last_updated'] = datetime.now().isoformat()
        
        self._save_graph()
        
        return {"status": "success", "overlay_id": overlay_id}
    
    def remove_student_overlay(self, student_id: str, concept_id: str) -> Dict:
        """Remove a student overlay for a concept"""
        try:
            overlay = self.get_student_overlay(student_id, concept_id)
            if not overlay:
                return {"status": "error", "message": "Overlay not found"}
            
            overlay_id = overlay.get('id')
            if overlay_id in self.nodes_data:
                del self.nodes_data[overlay_id]
                # Also remove from rustworkx graph
                if overlay_id in self.node_index_by_id:
                    node_idx = self.node_index_by_id[overlay_id]
                    del self.node_index_by_id[overlay_id]
                    # rustworkx.remove_node_from_index() would go here if available
                
                self._save_graph()
                return {"status": "success", "removed_overlay_id": overlay_id}
            
            return {"status": "error", "message": "Failed to remove overlay"}
        except Exception as e:
            logger.error(f"Failed to remove student overlay: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    # ==================== Semantic Memory Operations ====================
    
    def create_semantic_node(self, student_id: str, fact: str, concept_id: str,
                            confidence: float = 0.9) -> Dict:
        """Create a SemanticNode for learned facts"""
        try:
            semantic = SemanticNode(
                student_id=student_id,
                fact=fact,
                concept_id=concept_id,
                confidence=confidence,
                source_session_id="session_unknown",
            )
            
            node_data = semantic.to_dict()
            node_data['created_at'] = datetime.now().isoformat()
            
            self._add_node_to_graph(semantic.id)
            self.nodes_data[semantic.id] = node_data
            
            self._save_graph()
            
            return {
                "status": "success",
                "node_id": semantic.id,
                "fact": fact,
                "concept_id": concept_id
            }
        except Exception as e:
            logger.error(f"Failed to create semantic node: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def get_semantic_nodes(self, student_id: str, concept_id: str) -> List[Dict]:
        """Get semantic nodes for a student and concept"""
        results = []
        for node_id, node_data in self.nodes_data.items():
            if (node_data.get('student_id') == student_id and 
                node_data.get('concept_id') == concept_id):
                results.append({**node_data, 'id': node_id})
        return results
    
    def access_semantic_node(self, semantic_id: str) -> Dict:
        """Update access tracking for semantic node"""
        if semantic_id not in self.nodes_data:
            return {"status": "error", "message": "Semantic node not found"}
        
        node_data = self.nodes_data[semantic_id]
        node_data['access_count'] = node_data.get('access_count', 0) + 1
        node_data['last_accessed'] = datetime.now().isoformat()
        
        self._save_graph()
        
        return {"status": "success", "semantic_id": semantic_id}
    
    # ==================== Memory Anchor Operations ====================
    
    def create_memory_anchor(self, student_id: str, session_id: str,
                            summary: str, key_concepts: List[str]) -> Dict:
        """Create a MemoryAnchor for session summary"""
        try:
            anchor = MemoryAnchor(
                student_id=student_id,
                session_date=session_id,
                summary_text=summary,
                concepts=key_concepts,
            )
            
            node_data = anchor.to_dict()
            
            self._add_node_to_graph(anchor.id)
            self.nodes_data[anchor.id] = node_data
            
            self._save_graph()
            
            return {
                "status": "success",
                "node_id": anchor.id,
                "session_id": session_id
            }
        except Exception as e:
            logger.error(f"Failed to create memory anchor: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def get_memory_anchors(self, student_id: str, concept_id: str) -> List[Dict]:
        """Get memory anchors for a student and concept"""
        results = []
        for node_id, node_data in self.nodes_data.items():
            if (node_data.get('student_id') == student_id and 
                concept_id in node_data.get('concepts', [])):
                results.append({**node_data, 'id': node_id})
        return results

    # ==================== Defence Record + HITL Queue ====================

    def _defence_records_path(self) -> str:
        return os.path.join(self.data_dir, "defence_records.json")

    def _hitl_queue_path(self) -> str:
        return os.path.join(self.data_dir, "hitl_queue.json")

    def _learning_paths_path(self) -> str:
        return os.path.join(self.data_dir, "learning_paths.json")

    def _read_json_list(self, file_path: str) -> List[Dict]:
        if not os.path.exists(file_path):
            return []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _write_json_list(self, file_path: str, rows: List[Dict]) -> None:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2)

    def create_defence_record(self, record_props: Dict) -> Dict:
        """Persist a defence record for evaluator/integrity flow."""
        record_id = str(record_props.get("id") or f"def_{datetime.now().timestamp()}")
        rows = self._read_json_list(self._defence_records_path())

        payload = {
            **record_props,
            "id": record_id,
            "created_at": record_props.get("created_at") or datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }

        rows = [r for r in rows if str(r.get("id")) != record_id]
        rows.append(payload)
        self._write_json_list(self._defence_records_path(), rows)
        return {"status": "success", "record_id": record_id}

    def update_defence_record(self, record_id: str, updates: Dict) -> Dict:
        """Update an existing defence record."""
        rows = self._read_json_list(self._defence_records_path())
        found = False
        for row in rows:
            if str(row.get("id")) != str(record_id):
                continue
            row.update(updates)
            row["updated_at"] = datetime.now().isoformat()
            found = True
            break

        if not found:
            return {"status": "error", "message": "Defence record not found"}

        self._write_json_list(self._defence_records_path(), rows)
        return {"status": "success", "record_id": record_id}

    def get_defence_record(self, record_id: str) -> Optional[Dict]:
        """Return one defence record by id."""
        rows = self._read_json_list(self._defence_records_path())
        for row in rows:
            if str(row.get("id")) == str(record_id):
                return row
        return None

    def enqueue_hitl_review(self, payload: Dict) -> Dict:
        """Append one professor review entry to HITL queue."""
        queue = self._read_json_list(self._hitl_queue_path())
        entry = {
            "queue_id": payload.get("queue_id") or str(uuid.uuid4())[:12],
            "created_at": datetime.now().isoformat(),
            **payload,
        }
        queue.append(entry)
        self._write_json_list(self._hitl_queue_path(), queue)
        return {"status": "success", "queue_id": entry["queue_id"]}

    def list_hitl_queue(self, course_ids: Optional[List[str]] = None) -> List[Dict]:
        """List HITL queue entries, optionally filtered by course ids."""
        queue = self._read_json_list(self._hitl_queue_path())
        if not course_ids:
            return queue
        allowed = set(course_ids)
        return [q for q in queue if q.get("course_id") in allowed]

    def update_hitl_queue_entry(self, queue_id: str, updates: Dict) -> Dict:
        """Update one HITL queue row by queue_id."""
        queue = self._read_json_list(self._hitl_queue_path())
        found = False
        for row in queue:
            if str(row.get("queue_id")) != str(queue_id):
                continue
            row.update(updates)
            row["updated_at"] = datetime.now().isoformat()
            found = True
            break

        if not found:
            return {"status": "error", "message": "HITL queue entry not found"}

        self._write_json_list(self._hitl_queue_path(), queue)
        return {"status": "success", "queue_id": queue_id}

    # ==================== Learning Path Operations ====================

    def set_learning_path(
        self,
        course_id: str,
        ordered_concept_ids: Optional[List[str]] = None,
        partial_order_edges: Optional[List[Dict]] = None,
    ) -> Dict:
        """Persist learning path configuration and add curriculum path edges."""
        ordered_concept_ids = ordered_concept_ids or []
        partial_order_edges = partial_order_edges or []

        for concept_id in ordered_concept_ids:
            node = self.nodes_data.get(concept_id)
            if not node or node.get("level") != "CONCEPT":
                return {"status": "error", "message": f"Invalid concept id in ordered path: {concept_id}"}
            if str(node.get("course_owner", "")) != str(course_id):
                return {
                    "status": "error",
                    "message": f"Concept {concept_id} does not belong to course {course_id}",
                }

        for edge in partial_order_edges:
            source_id = edge.get("source_id")
            target_id = edge.get("target_id")
            source = self.nodes_data.get(source_id)
            target = self.nodes_data.get(target_id)
            if not source or source.get("level") != "CONCEPT" or not target or target.get("level") != "CONCEPT":
                return {"status": "error", "message": "Invalid concept id in partial order edges"}
            if str(source.get("course_owner", "")) != str(course_id) or str(target.get("course_owner", "")) != str(course_id):
                return {
                    "status": "error",
                    "message": "Partial order edges must reference concepts from the same course",
                }

        paths = self._read_json_list(self._learning_paths_path())
        payload = {
            "course_id": course_id,
            "ordered_concept_ids": ordered_concept_ids,
            "partial_order_edges": partial_order_edges,
            "updated_at": datetime.now().isoformat(),
        }
        paths = [row for row in paths if str(row.get("course_id")) != str(course_id)]
        paths.append(payload)
        self._write_json_list(self._learning_paths_path(), paths)

        # Replace prior CURRICULUM_PATH edges for this course to avoid duplicate edge accumulation.
        existing_edges = self._edge_records()
        retained_edges = []
        for edge in existing_edges:
            edge_data = edge.get("data") or {}
            if edge_data.get("relation") != "CURRICULUM_PATH":
                retained_edges.append(edge)
                continue

            source_owner = str(self.nodes_data.get(edge.get("source"), {}).get("course_owner", ""))
            target_owner = str(self.nodes_data.get(edge.get("target"), {}).get("course_owner", ""))
            if source_owner == str(course_id) or target_owner == str(course_id):
                continue
            retained_edges.append(edge)

        self._rebuild_graph(retained_edges)

        # Add explicit curriculum path edges so recommendation traversal can consume weights.
        for idx in range(len(ordered_concept_ids) - 1):
            src = ordered_concept_ids[idx]
            tgt = ordered_concept_ids[idx + 1]
            weight = max(0.1, 1.0 - (idx * 0.05))
            self._add_edge_to_graph(src, tgt, {"relation": "CURRICULUM_PATH", "weight": float(weight)})

        for edge in partial_order_edges:
            src = edge.get("source_id")
            tgt = edge.get("target_id")
            weight = float(edge.get("weight", 0.7))
            self._add_edge_to_graph(src, tgt, {"relation": "CURRICULUM_PATH", "weight": weight})

        self._save_graph()
        return {"status": "success", "course_id": course_id}

    def get_learning_path(self, course_id: str) -> Dict:
        """Read learning path configuration for one course."""
        paths = self._read_json_list(self._learning_paths_path())
        for row in paths:
            if str(row.get("course_id")) == str(course_id):
                return {"status": "success", **row}
        return {
            "status": "success",
            "course_id": course_id,
            "ordered_concept_ids": [],
            "partial_order_edges": [],
        }
    
    # ==================== Graph Query Operations ====================
    
    def get_concept_hierarchy(self, concept_id: str, user_context: Optional[UserContext] = None) -> Dict:
        """Get the full hierarchy from module down to a concept"""
        if concept_id not in self.nodes_data:
            return {"status": "error", "message": "Concept not found"}
        
        concept = self.nodes_data[concept_id]
        topic_id = concept.get('topic_id')
        
        if not topic_id or topic_id not in self.nodes_data:
            return {"status": "error", "message": "Topic not found"}
        
        topic = self.nodes_data[topic_id]
        module_id = topic.get('module_id')
        
        if not module_id or module_id not in self.nodes_data:
            return {"status": "error", "message": "Module not found"}
        
        module = self.nodes_data[module_id]

        if user_context:
            for node in (module, topic, concept):
                visibility = node.get("visibility", "global")
                if visibility == "professor-only" and user_context.role not in ["professor", "admin"]:
                    return {"status": "error", "message": "Access denied"}
                if visibility == "enrolled-only" and user_context.role == "student":
                    if node.get("course_owner") not in user_context.course_ids:
                        return {"status": "error", "message": "Access denied"}
        
        return {
            "status": "success",
            "module": {**module, 'id': module_id},
            "topic": {**topic, 'id': topic_id},
            "concept": {**concept, 'id': concept_id}
        }
    
    def get_curriculum(self, course_id: str, user_context: Optional[UserContext] = None) -> Dict:
        """Get full curriculum structure with visibility filtering"""
        modules = {}
        
        for node_id, node_data in self.nodes_data.items():
            level = node_data.get('level')
            
            # Apply visibility filtering
            if user_context:
                visibility = node_data.get('visibility', 'global')
                if visibility == 'professor-only' and user_context.role != 'professor':
                    continue
            
            if level == 'MODULE' and node_data.get('course_owner') == course_id:
                modules[node_id] = {**node_data, 'id': node_id}
        
        return {
            "status": "success",
            "course_id": course_id,
            "modules": modules
        }
    
    def search_concepts(self, query: str, course_id: Optional[str] = None) -> List[Dict]:
        """Search for concepts by name"""
        results = []
        query_lower = query.lower()
        
        for node_id, node_data in self.nodes_data.items():
            if (node_data.get('level') == 'CONCEPT' and 
                (course_id is None or node_data.get('course_owner') == course_id) and
                query_lower in node_data.get('name', '').lower()):
                results.append({**node_data, 'id': node_id})
        
        return results[:10]  # Limit results
    
    # ==================== Prerequisite Operations ====================
    
    def add_prerequisite(
        self,
        concept_id: Optional[str] = None,
        prerequisite_id: Optional[str] = None,
        source_concept_id: Optional[str] = None,
        target_concept_id: Optional[str] = None,
        weight: float = 1.0,
    ) -> Dict:
        """Add a prerequisite relationship"""
        if source_concept_id and target_concept_id:
            concept_id = source_concept_id
            prerequisite_id = target_concept_id

        if not concept_id or not prerequisite_id:
            return {"status": "error", "message": "Concept ids are required"}

        if not all(x in self.nodes_data for x in [concept_id, prerequisite_id]):
            return {"status": "error", "message": "Concept(s) not found"}

        course_error = self._check_same_course(concept_id, prerequisite_id)
        if course_error:
            return {"status": "error", "message": course_error}
        
        self._add_edge_to_graph(prerequisite_id, concept_id, {'relation': 'REQUIRES', 'weight': float(weight)})
        self._save_graph()
        
        return {"status": "success", "source": concept_id, "target": prerequisite_id, "weight": float(weight)}

    def add_concept_relationship(
        self,
        source_id: str,
        target_id: str,
        relation: str,
        weight: float = 1.0,
    ) -> Dict[str, Any]:
        """Add a directed relationship between concept nodes."""
        source = self.nodes_data.get(source_id)
        target = self.nodes_data.get(target_id)
        if not source or source.get("level") != "CONCEPT":
            return {"status": "error", "message": "Invalid source concept"}
        if not target or target.get("level") != "CONCEPT":
            return {"status": "error", "message": "Invalid target concept"}

        relation_norm = str(relation or "").strip().upper()
        allowed = {"REQUIRES", "EXTENDS", "CONTRASTS", "CURRICULUM_PATH"}
        if relation_norm not in allowed:
            return {
                "status": "error",
                "message": f"Unsupported relation '{relation_norm}'. Allowed: {sorted(allowed)}",
            }

        course_error = self._check_same_course(source_id, target_id)
        if course_error:
            return {"status": "error", "message": course_error}

        # Ensure one directed edge per relation pair by rewriting the edge set.
        existing_edges = self._edge_records()
        retained_edges = []
        for edge in existing_edges:
            data = edge.get("data", {})
            if (
                edge.get("source") == source_id
                and edge.get("target") == target_id
                and str(data.get("relation", "")).upper() == relation_norm
            ):
                continue
            retained_edges.append(edge)

        self._rebuild_graph(retained_edges)
        self._add_edge_to_graph(
            source_id,
            target_id,
            {"relation": relation_norm, "weight": float(weight)},
        )
        self._save_graph()
        return {
            "status": "success",
            "source": source_id,
            "target": target_id,
            "relation": relation_norm,
            "weight": float(weight),
        }

    def remove_concept_relationship(
        self,
        source_id: str,
        target_id: str,
        relation: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Remove directed relationship(s) between concept nodes."""
        relation_norm = str(relation or "").strip().upper()
        existing_edges = self._edge_records()
        removed = 0
        retained_edges = []
        for edge in existing_edges:
            data = edge.get("data", {})
            same_pair = (
                edge.get("source") == source_id and edge.get("target") == target_id
            )
            same_relation = (
                not relation_norm
                or str(data.get("relation", "")).upper() == relation_norm
            )
            if same_pair and same_relation:
                removed += 1
                continue
            retained_edges.append(edge)

        if removed == 0:
            return {"status": "error", "message": "Relationship not found"}

        self._rebuild_graph(retained_edges)
        self._save_graph()
        return {
            "status": "success",
            "removed": removed,
            "source": source_id,
            "target": target_id,
            "relation": relation_norm or None,
        }

    def get_concept_nodes(self, course_id: Optional[str] = None) -> List[Dict]:
        """Return concept nodes, optionally filtered by course owner."""
        results: List[Dict] = []
        for node_id, node_data in self.nodes_data.items():
            if node_data.get("level") != "CONCEPT":
                continue
            if course_id is not None and node_data.get("course_owner") != course_id:
                continue
            results.append({**node_data, "id": node_id})
        return results

    def get_related_concepts(self, concept_id: str, relations: Optional[List[str]] = None) -> List[Dict]:
        """Return neighboring concepts including relation metadata and edge direction."""
        if concept_id not in self.nodes_data:
            return []

        allowed = {r.upper() for r in (relations or ["REQUIRES", "EXTENDS", "CONTRASTS"])}
        neighbors: Dict[str, Dict] = {}

        for edge in self._edge_records():
            data = edge.get("data", {})
            relation = str(data.get("relation", "")).upper()
            if relation not in allowed:
                continue

            src = edge.get("source")
            tgt = edge.get("target")
            if concept_id not in (src, tgt):
                continue

            neighbor_id = tgt if src == concept_id else src
            neighbor = self.nodes_data.get(neighbor_id)
            if not neighbor or neighbor.get("level") != "CONCEPT":
                continue

            direction = "out" if src == concept_id else "in"
            neighbors[neighbor_id] = {
                **neighbor,
                "id": neighbor_id,
                "relation": relation,
                "direction": direction,
                "weight": float(data.get("weight", 1.0)),
            }

        return list(neighbors.values())
    
    def get_prerequisites(self, concept_id: str) -> List[Dict]:
        """Get all prerequisites for a concept"""
        results = []
        concept_index = self.node_index_by_id.get(concept_id)
        if concept_index is None:
            return results

        for pred_idx in self.graph.predecessor_indices(concept_index):
            pred_id = self.graph[pred_idx]
            if pred_id in self.nodes_data:
                results.append({**self.nodes_data[pred_id], 'id': pred_id})
        return results
    
    # ==================== Additional Overlay Operations ====================
    
    def get_all_student_overlays(self, student_id: str) -> List[Dict]:
        """Get all overlays for a student across all concepts"""
        results = []
        for node_id, node_data in self.nodes_data.items():
            # StudentOverlay nodes are identified by user/concept linkage, not hierarchy level.
            if node_data.get('user_id') == student_id and node_data.get('concept_id'):
                results.append({**node_data, 'id': node_id})
        return results
    
    def get_least_confident_concept(self, student_id: str) -> Optional[str]:
        """Get the concept with lowest mastery_probability for a student"""
        overlays = self.get_all_student_overlays(student_id)
        if not overlays:
            return None
        
        # Find the one with lowest mastery
        min_overlay = min(overlays, key=lambda x: x.get('mastery_probability', 1.0))
        return min_overlay.get('concept_id')
    
    # ==================== Concept Lookup Operations ====================
    
    def get_concept_by_id(self, concept_id: str) -> Optional[Dict]:
        """Get a concept node by ID"""
        if concept_id in self.nodes_data:
            node = self.nodes_data[concept_id]
            if node.get('level') == 'CONCEPT':
                return {**node, 'id': concept_id}
        return None
    
    def get_concept_by_name(self, name: str, course_id: Optional[str] = None) -> Optional[Dict]:
        """Get a concept node by name, optionally filtered by course"""
        name_lower = name.lower()
        for node_id, node_data in self.nodes_data.items():
            if (node_data.get('level') == 'CONCEPT' and 
                node_data.get('name', '').lower() == name_lower):
                if course_id is None or node_data.get('course_owner') == course_id:
                    return {**node_data, 'id': node_id}
        return None
    
    # ==================== Achievement Operations ====================
    
    def _achievements_path(self) -> str:
        return os.path.join(self.data_dir, "achievements.json")
    
    def create_achievement(self, student_id: str, achievement_dict: Dict) -> Dict:
        """Create an achievement for a student"""
        try:
            achievements = self._read_json_list(self._achievements_path())
            
            achievement_id = achievement_dict.get('id') or f"ach_{uuid.uuid4().hex[:8]}"
            
            payload = {
                'id': achievement_id,
                'student_id': student_id,
                'created_at': datetime.now().isoformat(),
                **achievement_dict
            }
            
            # Avoid duplicates
            achievements = [a for a in achievements if not (
                a.get('student_id') == student_id and 
                a.get('achievement_type') == achievement_dict.get('achievement_type') and
                a.get('concept_id') == achievement_dict.get('concept_id') and
                a.get('module_id') == achievement_dict.get('module_id')
            )]
            
            achievements.append(payload)
            self._write_json_list(self._achievements_path(), achievements)
            
            return {'status': 'success', 'achievement_id': achievement_id}
        except Exception as e:
            logger.error(f"Failed to create achievement: {str(e)}")
            return {'status': 'error', 'message': str(e)}
    
    def get_student_achievements(self, student_id: str) -> List[Dict]:
        """Get all achievements for a student"""
        achievements = self._read_json_list(self._achievements_path())
        return [a for a in achievements if a.get('student_id') == student_id]
    
    def has_achievement(self, student_id: str, achievement_type: str, 
                       concept_id: Optional[str] = None, 
                       module_id: Optional[str] = None) -> bool:
        """Check if student has earned a specific achievement"""
        achievements = self.get_student_achievements(student_id)
        for ach in achievements:
            if ach.get('achievement_type') != achievement_type:
                continue
            if concept_id is not None and ach.get('concept_id') != concept_id:
                continue
            if module_id is not None and ach.get('module_id') != module_id:
                continue
            return True
        return False
    
    # ==================== Enrollment Operations ====================
    
    def get_enrolled_students(self, course_id: str) -> List[str]:
        """Get all student IDs enrolled in a course"""
        students = set()

        for _node_id, node_data in self.nodes_data.items():
            # RustWorkX overlays are stored with user_id/concept_id fields and node_type marker.
            is_overlay = (
                node_data.get("node_type") == "StudentOverlay"
                or ("user_id" in node_data and "concept_id" in node_data)
            )
            if not is_overlay:
                continue

            concept_id = node_data.get("concept_id")
            concept = self.nodes_data.get(concept_id, {}) if concept_id else {}
            if concept.get("course_owner") != course_id:
                continue

            user_id = node_data.get("user_id")
            if user_id:
                students.add(user_id)
        return sorted(list(students))
    
    # ==================== Utility Methods ====================
    
    def close(self):
        """Close/cleanup (for compatibility)"""
        self._save_graph()
        logger.info("GraphManager closed")
    
    def get_node_count(self) -> int:
        """Get total number of nodes"""
        return len(self.nodes_data)
    
    def get_edge_count(self) -> int:
        """Get total number of edges"""
        return len(self.graph.edge_list())


# Alias for backward compatibility
class GraphManager(GraphManager):
    """Backward compatibility alias - uses RustWorkX backend"""
    
    def __init__(self, uri: Optional[str] = None, user: Optional[str] = None,
                 password: Optional[str] = None, data_dir: str = "data"):
        # Ignore Neo4j parameters, use RustWorkX backend
        super().__init__(data_dir=data_dir)
