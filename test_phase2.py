#!/usr/bin/env python3
"""
OmniProf v3.0 — Phase 2 Quick Test Script
Tests all graph schema operations with the new 4-level hierarchy
"""

from backend.services.graph_service import GraphService
import json


def print_section(title):
    print(f"\n{'='*60}")
    print(f"✅ {title}")
    print(f"{'='*60}")


def test_hierarchy_creation():
    print_section("Test 1: Create 4-Level Hierarchy")
    
    graph = GraphService()
    
    # Create Module
    print("Creating Module...")
    module = graph.create_module(
        name="Machine Learning Fundamentals",
        course_owner="prof_ml_001",
        description="Foundation course for ML",
        visibility="global"
    )
    print(f"  Module: {module['name']} (ID: {module['node_id']})")
    assert module["status"] == "success"
    
    # Create Topic
    print("Creating Topic...")
    topic = graph.create_topic(
        module_id=module["node_id"],
        name="Neural Networks",
        course_owner="prof_ml_001",
        description="Deep learning fundamentals",
        visibility="global"
    )
    print(f"  Topic: {topic['name']} (ID: {topic['node_id']})")
    assert topic["status"] == "success"
    
    # Create Concept with 384-dim embedding
    print("Creating Concept with embedding...")
    embedding = [0.5] * 384  # Simulate Sentence Transformer output
    concept = graph.create_concept(
        topic_id=topic["node_id"],
        name="Perceptron",
        course_owner="prof_ml_001",
        description="A simple neural network unit that implements binary classification",
        source_doc_ref="chapter_3_doc_001",
        embedding=embedding,
        visibility="global"
    )
    print(f"  Concept: {concept['name']} (ID: {concept['node_id']})")
    print(f"  Embedding dimensions: {concept['embedding_dim']}")
    assert concept["status"] == "success"
    
    # Create Fact
    print("Creating Fact...")
    fact = graph.create_fact(
        concept_id=concept["node_id"],
        name="Perceptron has a bias term",
        course_owner="prof_ml_001",
        description="The perceptron includes a bias weight to handle offset",
        source_doc_ref="chapter_3_doc_001",
        visibility="global"
    )
    print(f"  Fact: {fact['name']} (ID: {fact['node_id']})")
    assert fact["status"] == "success"
    
    print("\n✨ Hierarchy creation successful!")
    return {
        "module": module,
        "topic": topic,
        "concept": concept,
        "fact": fact
    }


def test_concepts_and_relationships(hierarchy):
    print_section("Test 2: Create Multiple Concepts & Relationships")
    
    graph = GraphService()
    topic_id = hierarchy["topic"]["node_id"]
    concept1_id = hierarchy["concept"]["node_id"]
    
    # Create another concept
    print("Creating second concept...")
    concept2 = graph.create_concept(
        topic_id=topic_id,
        name="Activation Function",
        course_owner="prof_ml_001",
        description="Function that introduces non-linearity",
        embedding=[0.3] * 384,
        visibility="global"
    )
    print(f"  Concept: {concept2['name']} (ID: {concept2['node_id']})")
    assert concept2["status"] == "success"
    
    # Create third concept
    print("Creating third concept...")
    concept3 = graph.create_concept(
        topic_id=topic_id,
        name="Backpropagation",
        course_owner="prof_ml_001",
        description="Training algorithm for neural networks",
        embedding=[0.7] * 384,
        visibility="global"
    )
    print(f"  Concept: {concept3['name']} (ID: {concept3['node_id']})")
    assert concept3["status"] == "success"
    
    # Add prerequisite: Backprop requires Perceptron
    print("\nAdding relationships...")
    print("  Backpropagation REQUIRES Perceptron...")
    prereq = graph.add_prerequisite(
        source_concept_id=concept3["node_id"],
        target_concept_id=concept1_id,
        weight=0.95
    )
    assert prereq["status"] == "success"
    
    # Add extends: Backprop extends Activation Function
    print("  Backpropagation EXTENDS Activation Function...")
    extends = graph.add_extends(
        source_id=concept3["node_id"],
        target_id=concept2["node_id"]
    )
    assert extends["status"] == "success"
    
    # Add contrasts: Perceptron contrasts with Decision Tree
    print("  Creating contrasting concept...")
    concept4 = graph.create_concept(
        topic_id=topic_id,
        name="Decision Tree",
        course_owner="prof_ml_001",
        description="Tree-based classification model",
        embedding=[0.2] * 384,
        visibility="global"
    )
    
    print("  Perceptron CONTRASTS with Decision Tree...")
    contrasts = graph.add_contrasts(
        source_id=concept1_id,
        target_id=concept4["node_id"]
    )
    assert contrasts["status"] == "success"
    
    print("\n✨ Relationships created successfully!")
    return {
        "concept1": hierarchy["concept"],
        "concept2": concept2,
        "concept3": concept3,
        "concept4": concept4
    }


def test_student_tracking(hierarchy):
    print_section("Test 3: Student Progress Tracking (BKT)")
    
    graph = GraphService()
    concept_id = hierarchy["concept"]["node_id"]
    user_id = "student_cs101_001"
    
    # Create student overlay
    print(f"Creating student overlay for {user_id}...")
    overlay = graph.track_student_concept(
        user_id=user_id,
        concept_id=concept_id,
        theta=0.2,  # Low initial knowledge
        slip=0.1,   # 10% mistake probability
        guess=0.1   # 10% guessing probability
    )
    print(f"  Initial mastery probability: {overlay['mastery_probability']:.2%}")
    assert overlay["status"] == "success"
    
    # Mark as visited
    print("Marking concept as visited...")
    visited = graph.mark_concept_visited(user_id, concept_id)
    assert visited["visited"] == True
    
    # Simulate learning - update mastery
    print("\nSimulating learning progress...")
    for theta in [0.35, 0.5, 0.7, 0.85]:
        update = graph.update_student_mastery(
            user_id=user_id,
            concept_id=concept_id,
            new_theta=theta
        )
        print(f"  Updated theta to {theta:.2%}")
        assert update["status"] == "success"
    
    # Get student's concepts
    print(f"\nGetting all concepts studied by {user_id}...")
    progress = graph.get_student_concepts(user_id)
    print(f"  Total concepts: {len(progress)}")
    
    print("\n✨ Student tracking successful!")


def test_validation(hierarchy):
    print_section("Test 4: Graph Validation")
    
    graph = GraphService()
    topic_id = hierarchy["topic"]["node_id"]
    
    # Validate before adding duplicate
    print("Checking for duplicate concept names...")
    validation = graph.validate_before_adding_concept(
        topic_id=topic_id,
        name="Perceptron"  # Already exists
    )
    print(f"  Valid: {validation['valid']}")
    print(f"  Issues: {validation['issues']}")
    assert not validation["valid"]
    
    # Full graph validation
    print("\nRunning full graph integrity check...")
    validation = graph.validate_graph()
    print(f"  Status: {validation['status']}")
    print(f"  Issues found: {validation['issue_count']}")
    if validation['issues']:
        for issue in validation['issues']:
            print(f"    - {issue['type']}: {issue['count']} issues")
    
    print("\n✨ Validation check complete!")


def test_llm_bulk_import():
    print_section("Test 5: LLM Bulk Import")
    
    graph = GraphService()
    
    llm_data = {
        "module": "Natural Language Processing",
        "topic": "Transformers",
        "course_owner": "prof_nlp_001",
        "visibility": "enrolled-only",
        "concepts": [
            {
                "name": "Attention Mechanism",
                "description": "Self-attention computes context-aware representations",
                "source_doc": "paper_001_transformers",
                "embedding": [0.1] * 384
            },
            {
                "name": "Transformer Block",
                "description": "Combines attention, feed-forward, and normalization",
                "source_doc": "paper_001_transformers",
                "embedding": [0.2] * 384
            },
            {
                "name": "BERT",
                "description": "Bidirectional Encoder Representations from Transformers",
                "source_doc": "paper_002_bert",
                "embedding": [0.3] * 384
            }
        ],
        "relationships": [
            {
                "source": "Transformer Block",
                "target": "Attention Mechanism",
                "type": "REQUIRES",
                "weight": 0.95
            },
            {
                "source": "BERT",
                "target": "Transformer Block",
                "type": "EXTENDS",
                "weight": 0.9
            }
        ]
    }
    
    print("Importing LLM-extracted knowledge...")
    result = graph.insert_from_llm(llm_data)
    
    print(f"  Status: {result['status']}")
    print(f"  Module created: {result.get('module_id', 'N/A')}")
    print(f"  Topic created: {result.get('topic_id', 'N/A')}")
    print(f"  Concepts created: {result.get('concepts_created', 0)}")
    print(f"  Relationships added: {result.get('relationships_added', 0)}")
    assert result["status"] == "success"
    
    print("\n✨ LLM bulk import successful!")


def main():
    print("\n" + "="*60)
    print("🚀 OmniProf v3.0 — Phase 2 Test Suite")
    print("="*60)
    
    try:
        # Test 1: Hierarchy
        hierarchy = test_hierarchy_creation()
        
        # Test 2: Concepts & Relationships
        concepts = test_concepts_and_relationships(hierarchy)
        
        # Test 3: Student Tracking
        test_student_tracking(hierarchy)
        
        # Test 4: Validation
        test_validation(hierarchy)
        
        # Test 5: LLM Import
        test_llm_bulk_import()
        
        print("\n" + "="*60)
        print("✅ ALL TESTS PASSED!")
        print("="*60)
        print("\nPhase 2: Graph Schema Upgrade is complete and working!")
        print("Ready for Phase 3: Semantic Search & Recommendations")
        
    except AssertionError as e:
        print(f"\n❌ Test failed: {str(e)}")
        return 1
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
