"""
OmniProf TA Agent
LangGraph node for adaptive tutoring with CRAG loop integration.

Features:
- Runs CRAG pipeline for knowledge retrieval
- Adapts explanation depth based on student mastery_probability
- Uses Socratic questioning for low-mastery concepts (< 0.4)
- Updates student overlay after generating responses
"""

import logging
import json
import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

from groq import Groq
from backend.agents.state import AgentState, GraphContext
from backend.services.crag_service import CRAGService
from backend.services.cognitive_engine import CognitiveEngine
from backend.services.llm_service import LLMService
from backend.services.rag_service import RAGService
from backend.services.graph_service import GraphService
from backend.db.neo4j_driver import Neo4jGraphManager

logger = logging.getLogger(__name__)


@dataclass
class TAAgentResponse:
    """Structure for TA Agent response"""
    answer: str                           # Main answer/explanation
    explanation_depth: str                # "basic" | "intermediate" | "advanced"
    is_socratic: bool                     # Whether response uses Socratic approach
    socratic_question: Optional[str] = None  # Probing question if Socratic
    referenced_concepts: List[str] = None  # Concept IDs discussed
    mastery_levels: Dict[str, float] = None  # Mastery prob for each concept
    next_steps: Optional[str] = None      # Recommended next steps
    confidence: float = 0.0               # Answer confidence


class TAAgent:
    """
    Teaching Assistant Agent for OmniProf.
    
    Responsibilities:
    1. Retrieve relevant knowledge using CRAG pipeline
    2. Adapt explanation depth based on student mastery
    3. Apply Socratic questioning for low-mastery concepts
    4. Update student knowledge state after interaction
    
    The agent acts as a LangGraph node in the multiagent orchestration system.
    """
    
    def __init__(self, 
                 groq_api_key: Optional[str] = None,
                 neo4j_uri: Optional[str] = None,
                 neo4j_user: Optional[str] = None,
                 neo4j_password: Optional[str] = None):
        """
        Initialize TA Agent with services.
        
        Args:
            groq_api_key: Groq API key (defaults to env variable)
            neo4j_uri: Neo4j database URI
            neo4j_user: Neo4j username
            neo4j_password: Neo4j password
        """
        import os
        from dotenv import load_dotenv
        
        load_dotenv()
        
        self.groq_key = groq_api_key or os.getenv("GROQ_API_KEY")
        self.client = Groq(api_key=self.groq_key)
        self.model = "llama-3.3-70b-versatile"  # Larger model for better reasoning
        
        # Initialize services
        self.graph_manager = Neo4jGraphManager(
            uri=neo4j_uri or os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            user=neo4j_user or os.getenv("NEO4J_USER", "neo4j"),
            password=neo4j_password or os.getenv("NEO4J_PASSWORD", "password")
        )
        
        self.llm_service = LLMService()
        self.rag_service = RAGService()
        self.graph_service = GraphService(self.graph_manager)
        self.cognitive_engine = CognitiveEngine()
        self.crag_service = CRAGService(
            rag_service=self.rag_service,
            graph_service=self.graph_service,
            llm_service=self.llm_service
        )
        
        # Socratic questioning threshold
        self.mastery_threshold_socratic = 0.4
        self.mastery_threshold_basic = 0.6
        self.mastery_threshold_advanced = 0.8
    
    
    # ==================== Main Agent Entry Point ====================
    
    def process(self, state: AgentState) -> AgentState:
        """
        Main entry point for TA Agent as LangGraph node.
        
        Workflow:
        1. Run CRAG loop to retrieve answer
        2. Extract concepts from response
        3. Check student mastery for each concept
        4. Adapt explanation depth and structure
        5. Apply Socratic questioning if needed
        6. Update student overlay
        7. Add response to conversation
        
        Args:
            state: Current agent state
        
        Returns:
            Updated agent state with response added
        """
        try:
            logger.info(f"TAAgent processing query for student {state.student_id}")
            
            # Step 1: Run CRAG loop
            logger.debug(f"Running CRAG loop for query: {state.current_input}")
            crag_result = self._run_crag_loop(state.current_input)
            
            # Step 2: Extract concepts from query and response
            logger.debug("Extracting concepts from response")
            concepts = self._extract_concepts(
                state.current_input,
                crag_result.get("answer", "")
            )
            
            # Step 3: Retrieve student's mastery levels
            logger.debug(f"Retrieving mastery levels for {len(concepts)} concepts")
            mastery_data = self._get_student_mastery(state.student_id, concepts)
            
            # Step 4: Determine explanation depth
            logger.debug("Determining explanation depth")
            explanation_depth = self._determine_explanation_depth(mastery_data)
            
            # Step 5: Check for Socratic questioning need
            logger.debug("Checking for Socratic questioning")
            should_use_socratic, primary_concept = self._should_use_socratic(
                state.current_input,
                mastery_data
            )
            
            # Step 6: Build adaptive response
            logger.debug("Building adaptive response")
            ta_response = self._build_adaptive_response(
                crag_result=crag_result,
                concepts=concepts,
                mastery_data=mastery_data,
                explanation_depth=explanation_depth,
                should_use_socratic=should_use_socratic,
                primary_concept=primary_concept
            )
            
            # Step 7: Update student overlay
            logger.debug("Updating student overlay")
            self._update_overlays(state.student_id, concepts)
            
            # Step 8: Update state
            state.add_message(
                role="assistant",
                content=ta_response.answer,
                intent="academic_query"
            )
            
            state.active_agent = "ta_agent"
            state.graph_context = GraphContext(
                query_text=state.current_input,
                retrieved_concepts=[{"name": c, "mastery": mastery_data.get(c, 0.5)} 
                                   for c in concepts],
                metadata={
                    "explanation_depth": explanation_depth,
                    "socratic": ta_response.is_socratic,
                    "confidence": ta_response.confidence
                }
            )
            
            logger.info(f"TAAgent completed successfully (depth={explanation_depth}, "
                       f"socratic={ta_response.is_socratic})")
            
            return state
            
        except Exception as e:
            logger.error(f"TAAgent error: {str(e)}", exc_info=True)
            state.error = str(e)
            state.error_count += 1
            state.add_message(
                role="assistant",
                content=f"I encountered an error processing your question: {str(e)}"
            )
            return state
    
    
    # ==================== CRAG Loop ====================
    
    def _run_crag_loop(self, query: str) -> Dict:
        """
        Run the Corrective RAG (CRAG) pipeline.
        
        CRAG Loop Steps:
        1. Retrieve candidate answer using RAG and graph
        2. Score relevance of retrieved documents
        3. If score is low, refine query and retry
        4. Generate answer from best context
        
        Args:
            query: User's question
        
        Returns:
            Dict with answer, graph_results, rag_results, confidence
        """
        try:
            logger.debug(f"CRAG loop start: {query}")
            
            # Use existing CRAG service
            crag_result = self.crag_service.retrieve(query)
            
            logger.debug(f"CRAG loop result: confidence={crag_result.get('confidence', 0)}")
            return crag_result
            
        except Exception as e:
            logger.error(f"CRAG loop error: {str(e)}")
            return {
                "query": query,
                "answer": "I couldn't retrieve relevant information to answer your question.",
                "confidence": 0.0,
                "graph_results": [],
                "rag_results": []
            }
    
    
    # ==================== Concept Extraction ====================
    
    def _extract_concepts(self, query: str, answer: str) -> List[str]:
        """
        Extract concept names/IDs from query and answer.
        
        Uses NLP to identify domain concepts mentioned.
        
        Args:
            query: Original user query
            answer: Generated answer
        
        Returns:
            List of concept IDs
        """
        try:
            combined_text = f"{query}\n{answer}"
            
            # Use LLM to extract concepts
            prompt = f"""
Given this educational content, extract the main concepts discussed.

CONTENT:
{combined_text[:1000]}

Return a JSON array with concept names:
{{"concepts": ["concept1", "concept2", ...]}}

Return ONLY the JSON, no other text.
"""
            
            response = self._call_llm(prompt)
            
            # Parse JSON
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                concepts = data.get("concepts", [])
                logger.debug(f"Extracted concepts: {concepts}")
                return concepts
            
            return []
            
        except Exception as e:
            logger.warning(f"Concept extraction error: {str(e)}")
            return []
    
    
    # ==================== Mastery Retrieval ====================
    
    def _get_student_mastery(self, student_id: str, concepts: List[str]) -> Dict[str, float]:
        """
        Get student's mastery_probability for each concept.
        
        Retrieves from StudentOverlay in Neo4j.
        
        Args:
            student_id: Student user ID
            concepts: List of concept names/IDs
        
        Returns:
            Dict mapping concept_id -> mastery_probability [0, 1]
        """
        try:
            mastery_data = {}
            
            for concept in concepts:
                try:
                    # Query StudentOverlay
                    query = """
                    MATCH (s:StudentOverlay {user_id: $user_id})
                    MATCH (c:CONCEPT {name: $concept})
                    MATCH (s)-[:KNOWS]->(c)
                    RETURN s.mastery_probability as mastery
                    """
                    
                    result = self.graph_manager.db.run_query(
                        query,
                        {"user_id": student_id, "concept": concept}
                    )
                    
                    if result:
                        mastery = result[0].get("mastery", 0.5)
                    else:
                        # Default for unseen concepts
                        mastery = 0.5
                    
                    mastery_data[concept] = mastery
                    
                except Exception as e:
                    logger.debug(f"Mastery lookup error for concept {concept}: {str(e)}")
                    mastery_data[concept] = 0.5  # Default
            
            return mastery_data
            
        except Exception as e:
            logger.error(f"Mastery retrieval error: {str(e)}")
            return {c: 0.5 for c in concepts}
    
    
    # ==================== Explanation Depth Adaptation ====================
    
    def _determine_explanation_depth(self, mastery_data: Dict[str, float]) -> str:
        """
        Determine appropriate explanation depth based on average mastery.
        
        Depth Levels:
        - "basic": mastery < 0.6 (foundational concepts)
        - "intermediate": 0.6 <= mastery < 0.8 (building understanding)
        - "advanced": mastery >= 0.8 (deep concepts)
        
        Args:
            mastery_data: Dict of concept -> mastery probability
        
        Returns:
            "basic" | "intermediate" | "advanced"
        """
        if not mastery_data:
            return "intermediate"
        
        avg_mastery = sum(mastery_data.values()) / len(mastery_data)
        
        if avg_mastery < self.mastery_threshold_basic:
            return "basic"
        elif avg_mastery < self.mastery_threshold_advanced:
            return "intermediate"
        else:
            return "advanced"
    
    
    # ==================== Socratic Questioning ====================
    
    def _should_use_socratic(self, query: str, mastery_data: Dict[str, float]) -> Tuple[bool, Optional[str]]:
        """
        Determine if Socratic questioning should be used.
        
        Socratic approach is triggered when:
        - Primary concept (main focus) has mastery < 0.4
        - Student seems to have a knowledge gap
        
        Args:
            query: Original query
            mastery_data: Student mastery for concepts
        
        Returns:
            (should_use_socratic, primary_concept_id)
        """
        try:
            if not mastery_data:
                return False, None
            
            # Find primary concept (usually the first or most mentioned)
            primary_concept = list(mastery_data.keys())[0] if mastery_data else None
            primary_mastery = mastery_data.get(primary_concept, 0.5)
            
            should_use_socratic = primary_mastery < self.mastery_threshold_socratic
            
            logger.debug(f"Socratic decision: use={should_use_socratic}, "
                        f"primary={primary_concept}, mastery={primary_mastery}")
            
            return should_use_socratic, primary_concept if should_use_socratic else None
            
        except Exception as e:
            logger.warning(f"Socratic decision error: {str(e)}")
            return False, None
    
    
    # ==================== Adaptive Response Building ====================
    
    def _build_adaptive_response(self,
                                 crag_result: Dict,
                                 concepts: List[str],
                                 mastery_data: Dict[str, float],
                                 explanation_depth: str,
                                 should_use_socratic: bool,
                                 primary_concept: Optional[str]) -> TAAgentResponse:
        """
        Build adaptive response with appropriate depth and structure.
        
        Response Strategy:
        - BASIC: Simple definitions, analogies, concrete examples
        - INTERMEDIATE: Context, connections to other concepts
        - ADVANCED: Deep reasoning, edge cases, applications
        
        Socratic Approach:
        - Ask probing question instead of direct answer
        - Guide student toward understanding
        - Hint at key concepts
        
        Args:
            crag_result: CRAG pipeline output
            concepts: Extracted concepts
            mastery_data: Student mastery levels
            explanation_depth: "basic" | "intermediate" | "advanced"
            should_use_socratic: Whether to use Socratic method
            primary_concept: Main concept if Socratic
        
        Returns:
            TAAgentResponse with structured output
        """
        try:
            base_answer = crag_result.get("answer", "")
            confidence = crag_result.get("confidence", 0.5)
            
            # Adapt explanation based on depth
            if explanation_depth == "basic":
                adapted_answer = self._simplify_explanation(base_answer)
            elif explanation_depth == "advanced":
                adapted_answer = self._deepen_explanation(
                    base_answer,
                    crag_result.get("graph_results", [])
                )
            else:
                adapted_answer = base_answer
            
            # Apply Socratic approach if needed
            socratic_question = None
            if should_use_socratic and primary_concept:
                socratic_question = self._generate_socratic_question(
                    primary_concept,
                    adapted_answer
                )
                
                # Replace with Socratic approach
                adapted_answer = self._apply_socratic_method(
                    adapted_answer,
                    socratic_question
                )
            
            # Generate next steps
            next_steps = self._recommend_next_steps(concepts, mastery_data)
            
            return TAAgentResponse(
                answer=adapted_answer,
                explanation_depth=explanation_depth,
                is_socratic=should_use_socratic,
                socratic_question=socratic_question,
                referenced_concepts=concepts,
                mastery_levels=mastery_data,
                next_steps=next_steps,
                confidence=confidence
            )
            
        except Exception as e:
            logger.error(f"Response building error: {str(e)}")
            return TAAgentResponse(
                answer="I encountered an error generating your answer.",
                explanation_depth="basic",
                is_socratic=False,
                confidence=0.0
            )
    
    
    # ==================== Explanation Adaptation ====================
    
    def _simplify_explanation(self, answer: str) -> str:
        """
        Simplify explanation for basic mastery level.
        
        Removes technical jargon, adds analogies and examples.
        """
        try:
            prompt = f"""
Simplify this educational explanation for a beginner who is struggling to understand.
- Use simple, everyday language
- Add a simple analogy or example
- Keep key concepts but explain them simply
- Remove technical jargon where possible

ORIGINAL:
{answer[:500]}

Return only the simplified explanation, no other text.
"""
            
            simplified = self._call_llm(prompt)
            return simplified if simplified else answer
            
        except Exception as e:
            logger.warning(f"Simplification error: {str(e)}")
            return answer
    
    
    def _deepen_explanation(self, answer: str, graph_results: List[Dict]) -> str:
        """
        Deepen explanation for advanced mastery level.
        
        Adds connections, advanced concepts, applications. """
        try:
            # Format graph results
            related_concepts = "\n".join([
                f"- {r.get('name')}: {r.get('description', '')}"
                for r in graph_results[:3]
            ])
            
            prompt = f"""
Deepen and expand this explanation for an advanced student.
- Add connections to related concepts
- Discuss applications and implications
- Include edge cases or nuances
- Suggest areas for deeper exploration

ORIGINAL:
{answer[:500]}

RELATED CONCEPTS:
{related_concepts}

Return the enhanced explanation, no other text.
"""
            
            deepened = self._call_llm(prompt)
            return deepened if deepened else answer
            
        except Exception as e:
            logger.warning(f"Deepening error: {str(e)}")
            return answer
    
    
    # ==================== Socratic Method ====================
    
    def _generate_socratic_question(self, concept: str, context: str) -> str:
        """
        Generate a probing question to guide learning.
        
        Instead of telling, ask questions that:
        - Activate prior knowledge
        - Identify misconceptions
        - Guide toward understanding
        """
        try:
            prompt = f"""
Generate a probing Socratic question to help a student understand the concept: {concept}

Context of their question:
{context[:300]}

The question should:
- Be open-ended (not yes/no)
- Guide them to think about the concept
- Help them build understanding step by step
- Be appropriate for someone who hasn't yet mastered this concept

Return ONLY the question, no explanation.
"""
            
            question = self._call_llm(prompt)
            return question if question else f"What do you already know about {concept}?"
            
        except Exception as e:
            logger.warning(f"Socratic question generation error: {str(e)}")
            return f"How would you explain {concept} in your own words?"
    
    
    def _apply_socratic_method(self, answer: str, socratic_question: str) -> str:
        """
        Restructure response using Socratic method.
        
        Instead of directly answering, guide student through understanding.
        """
        try:
            prompt = f"""
Rewrite this response using the Socratic method.
- Start with the probing question
- Guide the student through key concepts
- Ask follow-up questions
- Avoid simply telling the answer
- Help them discover the answer themselves

ORIGINAL ANSWER:
{answer[:500]}

GUIDING QUESTION:
{socratic_question}

Return the Socratic restructuring, no other text.
"""
            
            socratic_response = self._call_llm(prompt)
            return socratic_response if socratic_response else answer
            
        except Exception as e:
            logger.warning(f"Socratic method application error: {str(e)}")
            return answer
    
    
    # ==================== Next Steps ====================
    
    def _recommend_next_steps(self, concepts: List[str], mastery_data: Dict[str, float]) -> str:
        """
        Recommend next learning steps.
        
        Based on mastery levels, suggest:
        - Concepts that need more practice
        - Related concepts to explore
        - Advanced topics ready for learning
        """
        try:
            # Identify weak areas
            weak_concepts = [c for c, m in mastery_data.items() 
                           if m < 0.6]
            strong_concepts = [c for c, m in mastery_data.items() 
                             if m >= 0.8]
            
            prompt = f"""
Recommend 1-2 next learning steps for a student based on their learning progress.

Concepts discussed: {', '.join(concepts)}
Concepts they struggle with: {', '.join(weak_concepts) or 'None identified'}
Concepts they master: {', '.join(strong_concepts) or 'None yet'}

Provide practical, specific recommendations for what to study next.
Keep it to 1-2 sentences.
"""
            
            steps = self._call_llm(prompt)
            return steps if steps else "Review the key concepts before moving forward."
            
        except Exception as e:
            logger.warning(f"Next steps recommendation error: {str(e)}")
            return "Continue practicing these concepts."
    
    
    # ==================== Student Overlay Update ====================
    
    def _update_overlays(self, student_id: str, concepts: List[str]) -> None:
        """
        Update StudentOverlay for all concepts referenced in answer.
        
        Marks that student interacted with these concepts.
        Uses cognitive engine to update theta, slip, mastery probability.
        
        Args:
            student_id: Student user ID
            concepts: List of concept IDs discussed
        """
        try:
            logger.debug(f"Updating overlays for {len(concepts)} concepts")
            
            for concept in concepts:
                try:
                    # Mark interaction as "saw this concept and got feedback"
                    # Assume positive interaction (student learned from explanation)
                    result = self.cognitive_engine.update_student_overlay(
                        user_id=student_id,
                        concept_id=concept,
                        answered_correctly=True,  # Implicit positive: exposed to material
                        difficulty=None  # Auto-estimate from prerequisites
                    )
                    
                    if result.get("status") == "success":
                        logger.debug(f"Updated overlay for {concept}: "
                                   f"theta={result.get('new_theta')}, "
                                   f"slip={result.get('new_slip')}")
                    else:
                        logger.warning(f"Overlay update failed for {concept}: "
                                     f"{result.get('message')}")
                    
                except Exception as e:
                    logger.error(f"Error updating overlay for {concept}: {str(e)}")
            
            logger.debug("Overlay updates completed")
            
        except Exception as e:
            logger.error(f"Overlay update batch error: {str(e)}")
    
    
    # ==================== Utilities ====================
    
    def _call_llm(self, prompt: str, temperature: float = 0.7) -> str:
        """
        Call Groq LLM safely with error handling.
        
        Args:
            prompt: Input prompt
            temperature: Model temperature [0, 1]
        
        Returns:
            Model response or empty string on error
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                top_p=0.95,
                max_tokens=1024
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"LLM call error: {str(e)}")
            return ""
