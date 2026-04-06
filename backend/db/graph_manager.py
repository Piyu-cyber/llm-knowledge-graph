"""
OmniProf v3.0 — RustWorkX-based Graph Manager (Neo4j Replacement)
In-memory graph with JSON persistence for knowledge graph operations
"""

import json
import os
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import logging

try:
    import rustworkx as rx
except ImportError:
    raise ImportError("rustworkx is required: pip install rustworkx")

from backend.db.neo4j_schema import (
    Module, Topic, Concept, Fact, StudentOverlay, SemanticNode, MemoryAnchor,
    GraphEdge, GraphValidator, NodeLevel, Visibility, EdgeType
)
from backend.auth.rbac import UserContext

logger = logging.getLogger(__name__)


class GraphManager:
    """RustWorkX-based graph manager with JSON persistence"""
    
    def __init__(self, data_dir: str = "data"):
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
        
        # Load existing data
        self._load_graph()
        
        logger.info("GraphManager initialized with RustWorkX backend")
    
    def _load_graph(self):
        """Load graph from JSON files"""
        try:
            if os.path.exists(self.nodes_file):
                with open(self.nodes_file, 'r') as f:
                    self.nodes_data = json.load(f)
                    # Rebuild graph nodes
                    for node_id, node_data in self.nodes_data.items():
                        self.graph.add_node(node_id, **node_data)
                logger.info(f"Loaded {len(self.nodes_data)} nodes")
            
            if os.path.exists(self.edges_file):
                with open(self.edges_file, 'r') as f:
                    edges_data = json.load(f)
                    for edge in edges_data:
                        self.graph.add_edge(
                            edge['source'], 
                            edge['target'], 
                            **edge.get('data', {})
                        )
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
            for source in self.graph.nodes():
                for target in self.graph.successors(source):
                    edge_data = self.graph.get_edge_data(source, target) or {}
                    edges_list.append({
                        'source': source,
                        'target': target,
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
        
        self.graph.add_node(module.id, **node_data)
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
        
        self.graph.add_node(topic.id, **node_data)
        self.nodes_data[topic.id] = node_data
        
        # Add CONTAINS edge
        self.graph.add_edge(module_id, topic.id, relation='CONTAINS')
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
                      visibility: str = "global") -> Dict:
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
            visibility=Visibility(visibility)
        )
        
        node_data = concept.to_dict()
        node_data['level'] = 'CONCEPT'
        node_data['topic_id'] = topic_id
        node_data['created_at'] = datetime.now().isoformat()
        
        self.graph.add_node(concept.id, **node_data)
        self.nodes_data[concept.id] = node_data
        
        # Add CONTAINS edge
        self.graph.add_edge(topic_id, concept.id, relation='CONTAINS')
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
        
        self.graph.add_node(fact.id, **node_data)
        self.nodes_data[fact.id] = node_data
        
        # Add CONTAINS edge
        self.graph.add_edge(concept_id, fact.id, relation='CONTAINS')
        self._save_graph()
        
        return {
            "status": "success",
            "node_id": fact.id,
            "name": name,
            "level": "FACT"
        }
    
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
                overlay = StudentOverlay(
                    user_id=user_id,
                    concept_id=concept_id,
                    theta=0.0,
                    slip=0.1,
                    guess=0.1,
                    visited=False,
                    mastery_probability=0.0
                )
                
                overlay_data = overlay.to_dict()
                overlay_data['created_at'] = datetime.now().isoformat()
                
                self.graph.add_node(overlay.id, **overlay_data)
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
                              theta: Optional[float] = None,
                              mastery_probability: Optional[float] = None,
                              visited: Optional[bool] = None) -> Dict:
        """Update a student overlay"""
        if overlay_id not in self.nodes_data:
            return {"status": "error", "message": "Overlay not found"}
        
        node_data = self.nodes_data[overlay_id]
        
        if theta is not None:
            node_data['theta'] = max(0.0, min(1.0, theta))
        if mastery_probability is not None:
            node_data['mastery_probability'] = max(0.0, min(1.0, mastery_probability))
        if visited is not None:
            node_data['visited'] = visited
        
        node_data['last_updated'] = datetime.now().isoformat()
        
        # Update in rustworkx
        self.graph.update_node_by_index(
            self.graph.nodes().index(overlay_id), **node_data)
        
        self._save_graph()
        
        return {"status": "success", "overlay_id": overlay_id}
    
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
                access_count=0,
                last_accessed=datetime.now().isoformat()
            )
            
            node_data = semantic.to_dict()
            node_data['created_at'] = datetime.now().isoformat()
            
            self.graph.add_node(semantic.id, **node_data)
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
                session_id=session_id,
                summary_text=summary,
                key_concept_ids=key_concepts,
                created_at=datetime.now().isoformat(),
                last_accessed=datetime.now().isoformat()
            )
            
            node_data = anchor.to_dict()
            
            self.graph.add_node(anchor.id, **node_data)
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
                concept_id in node_data.get('key_concept_ids', [])):
                results.append({**node_data, 'id': node_id})
        return results
    
    # ==================== Graph Query Operations ====================
    
    def get_concept_hierarchy(self, concept_id: str) -> Dict:
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
    
    def search_concepts(self, query: str, course_id: str) -> List[Dict]:
        """Search for concepts by name"""
        results = []
        query_lower = query.lower()
        
        for node_id, node_data in self.nodes_data.items():
            if (node_data.get('level') == 'CONCEPT' and 
                node_data.get('course_owner') == course_id and
                query_lower in node_data.get('name', '').lower()):
                results.append({**node_data, 'id': node_id})
        
        return results[:10]  # Limit results
    
    # ==================== Prerequisite Operations ====================
    
    def add_prerequisite(self, concept_id: str, prerequisite_id: str) -> Dict:
        """Add a prerequisite relationship"""
        if not all(x in self.nodes_data for x in [concept_id, prerequisite_id]):
            return {"status": "error", "message": "Concept(s) not found"}
        
        self.graph.add_edge(prerequisite_id, concept_id, relation='REQUIRES')
        self._save_graph()
        
        return {"status": "success"}
    
    def get_prerequisites(self, concept_id: str) -> List[Dict]:
        """Get all prerequisites for a concept"""
        results = []
        for pred_id in self.graph.predecessors(concept_id):
            if pred_id in self.nodes_data:
                results.append({**self.nodes_data[pred_id], 'id': pred_id})
        return results
    
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
        return sum(len(list(self.graph.successors(n))) for n in self.graph.nodes())


# Alias for backward compatibility
class Neo4jGraphManager(GraphManager):
    """Backward compatibility alias - uses RustWorkX backend"""
    
    def __init__(self, uri: Optional[str] = None, user: Optional[str] = None,
                 password: Optional[str] = None, data_dir: str = "data"):
        # Ignore Neo4j parameters, use RustWorkX backend
        super().__init__(data_dir=data_dir)
