from backend.services.crag_grader_agent import CRAGGraderAgent
from backend.auth.rbac import UserContext


class CRAGService:
    def __init__(self, rag_service, graph_service, llm_service):
        self.graph = graph_service
        self.llm = llm_service
        self.rag = rag_service
        self.grader = CRAGGraderAgent(llm_service=llm_service)

    def retrieve(self, query, user_context: UserContext = None, student_id: str = None):
        try:
            # 🔥 STEP 0: SUMMARY DETECTION
            if self._is_summary_query(query):
                rag_results = self.rag.retrieve(query)

                if not rag_results:
                    return {
                        "query": query,
                        "answer": "No document content found.",
                        "confidence": 0.2
                    }

                # 🔥 Extract key terms for graph usage
                graph_results = []
                for chunk in rag_results[:3]:
                    words = chunk.split()[:5]
                    for w in words:
                        results = self._retrieve_graph_results(
                            w,
                            user_context=user_context,
                            student_id=student_id,
                        )
                        if results:
                            graph_results.extend(results)

                # Remove duplicates
                seen = set()
                graph_results = [
                    g for g in graph_results
                    if not (g["name"] in seen or seen.add(g["name"]))
                ]

                context = self._build_context(graph_results, rag_results)

                answer = self.llm.generate_answer(
                    "Summarize this document",
                    context
                )

                return {
                    "query": query,
                    "graph_results": graph_results,
                    "rag_results": rag_results,
                    "answer": answer,
                    "confidence": 0.85
                }

            # 🔥 STEP 1: Ambiguity detection
            is_ambiguous = self._is_ambiguous(query)

            if is_ambiguous:
                options = self._get_query_options(query)
                return {
                    "query": query,
                    "message": "Your query is ambiguous. Please choose:",
                    "options": options,
                    "confidence": 0.3
                }

            # 🔥 STEP 2: Disambiguation
            refined_query = self.llm.disambiguate_query(query)

            # 🔹 Step 3: Retrieval
            graph_results = self._retrieve_graph_results(
                refined_query,
                user_context=user_context,
                student_id=student_id,
            )
            rag_results = self.rag.retrieve(refined_query) or []

            graph_results = self._filter_graph_results(refined_query, graph_results)

            # 🔹 Step 4: Context
            combined_context = self._build_context(graph_results, rag_results)

            # 🔹 Step 5: Relevance check (UPGRADED: scalar score)
            grade = self.grader.grade(refined_query, combined_context)
            score = grade["score"]
            
            # 🔁 Step 5b: Handle low scores
            if score < 0.5:
                # Try refinement for low confidence
                improved_query = self._refine_query(refined_query)
                graph_results = self._retrieve_graph_results(
                    improved_query,
                    user_context=user_context,
                    student_id=student_id,
                )
                rag_results = self.rag.retrieve(improved_query) or []
                graph_results = self._filter_graph_results(improved_query, graph_results)
                combined_context = self._build_context(graph_results, rag_results)
                grade = self.grader.grade(improved_query, combined_context)
                score = grade["score"]
            
            # ⚠️ Handle different score ranges
            if score < 0.5:
                # Very low confidence: add disclaimer, generate from base knowledge
                answer = self.llm.generate_answer(query, combined_context)
                answer_with_disclaimer = (
                    f"{answer}\n\n"
                    f"⚠️ Note: This answer draws on general knowledge, not course material. "
                    f"Please consult course documents for authoritative information."
                )
                
                return {
                    "query": query,
                    "graph_results": [],
                    "rag_results": [],
                    "answer": answer_with_disclaimer,
                    "confidence": score,
                    "grading_score": score
                }
            
            elif 0.5 <= score <= 0.7:
                # Medium confidence: ask clarifying question instead of answering directly
                clarifying_question = self._generate_clarifying_question(
                    query,
                    combined_context
                )
                
                return {
                    "query": query,
                    "graph_results": graph_results,
                    "rag_results": rag_results,
                    "answer": clarifying_question,
                    "confidence": score,
                    "grading_score": score,
                    "type": "clarifying_question"
                }
            
            else:
                # High confidence (> 0.7): proceed normally with answer generation
                
                # ⚠️ Fallback if nothing retrieved
                if not graph_results and not rag_results:
                    return {
                        "query": query,
                        "graph_results": [],
                        "rag_results": [],
                        "answer": "No relevant information found.",
                        "confidence": score
                    }

                # 🔹 Step 7: Generate answer
                answer = self.llm.generate_answer(query, combined_context)

                return {
                    "query": query,
                    "graph_results": graph_results,
                    "rag_results": rag_results,
                    "answer": answer,
                    "confidence": score,
                    "grading_score": score
                }

        except Exception as e:
            return {
                "query": query,
                "error": str(e),
                "answer": "Something went wrong.",
                "confidence": 0.0
            }

    def _retrieve_graph_results(self, query: str, user_context: UserContext = None, student_id: str = None):
        """Prefer personalized hierarchical retrieval when user context is available."""
        if user_context is not None:
            try:
                results = self.graph.personalized_graph_walk(
                    query=query,
                    user_context=user_context,
                    student_id=student_id,
                    top_k=6,
                )
                if results:
                    return results
            except Exception:
                # Fall back to legacy retrieval to preserve availability.
                pass
        return self.graph.search_concepts(query) or []

    # 🔥 SUMMARY DETECTION
    def _is_summary_query(self, query):
        query_lower = query.lower()

        keywords = ["summarize", "summary", "explain this document", "what is this document", "proposal"]
        if any(k in query_lower for k in keywords):
            return True

        prompt = f"""
Query: {query}
Is this asking for a document summary?
Answer YES or NO.
"""
        result = self.llm._call_llm(prompt)
        return result and "yes" in result.lower()

    # 🔥 AMBIGUITY DETECTION
    def _is_ambiguous(self, query):
        prompt = f"""
Query: {query}
Is this query ambiguous?
Answer YES or NO.
"""
        result = self.llm._call_llm(prompt)
        return result and any(w in result.lower() for w in ["yes", "ambiguous"])

    # 🔥 OPTIONS GENERATION
    def _get_query_options(self, query):
        prompt = f"""
Query: {query}
Give 2 meanings as JSON list.
"""
        content = self.llm._call_llm(prompt)

        import re, json
        match = re.search(r"\[.*\]", content or "")
        if match:
            try:
                return json.loads(match.group(0))
            except:
                pass
        return ["General meaning", "Technical meaning"]

    # 🔥 SAFE EVALUATION (UPGRADED: returns scalar score 0.0-1.0)
    def _safe_evaluate(self, query, context):
        """
        Evaluate relevance of context to query.
        
        Returns:
            score: float 0.0-1.0 where:
            - > 0.7: High confidence, proceed with answer
            - 0.5-0.7: Medium confidence, ask clarifying question
            - < 0.5: Low confidence, add disclaimer
        """
        try:
            score = self.llm.evaluate_relevance(query, context)
            return float(score) if isinstance(score, (int, float)) else 0.5
        except Exception as e:
            print("⚠️ Evaluation failed:", e)
            return 0.3  # Return low score on error
    
    # 🔥 CLARIFYING QUESTION GENERATION (NEW)
    def _generate_clarifying_question(self, query, context):
        """
        Generate a clarifying question when confidence is medium (0.5-0.7).
        
        This helps the system understand the student's intent better
        before generating a full answer.
        
        Args:
            query: Original query
            context: Available context
        
        Returns:
            Clarifying question string
        """
        prompt = f"""
The student asked: {query}

We have some relevant material but need clarification.

Generate ONE clarifying question to better understand their intent.
The question should:
- Be brief (1 sentence)
- Ask them to clarify a specific aspect
- Help us provide better information

Question:
"""
        
        question = self.llm._call_llm(prompt, temperature=0.5)
        return question if question else f"Could you clarify what aspect of {query} you're most interested in?"

    # 🔥 QUERY REFINEMENT (FIXED)
    def _refine_query(self, query):
        words = query.split()

        if len(words) <= 2:
            return query

        return " ".join(words[:3])

    # 🔥 GRAPH FILTERING (FIXED)
    def _filter_graph_results(self, query, results):
        if not results:
            return []

        words = set(query.lower().split())

        filtered = [
            r for r in results
            if any(w in (r.get("name") or "").lower() for w in words)
        ]

        return filtered if filtered else results

    # 🔥 CONFIDENCE SCORING (FIXED)
    def _compute_confidence(self, query, graph_results, rag_results, decision, original_query, is_ambiguous):
        score = 0.5

        if graph_results:
            score += 0.2

        if rag_results:
            score += 0.2

        if decision == "GOOD":
            score += 0.1

        if is_ambiguous:
            score -= 0.1

        return round(max(0.0, min(score, 1.0)), 2)

    # 🔥 CONTEXT BUILDER
    def _build_context(self, graph_results, rag_results):
        graph_context = ""

        for r in graph_results[:5]:
            graph_context += f"{r.get('name','')}: {r.get('description','')}\n"

            for rel in r.get("related", []):
                graph_context += f"→ {rel.get('name')} ({rel.get('relation')})\n"

        rag_context = "\n".join(rag_results[:5])

        return f"""
GRAPH KNOWLEDGE:
{graph_context}

RETRIEVED DOCUMENTS:
{rag_context}
"""