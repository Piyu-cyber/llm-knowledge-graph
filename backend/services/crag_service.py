class CRAGService:
    def __init__(self, rag_service, graph_service, llm_service):
        self.graph = graph_service
        self.llm = llm_service
        self.rag = rag_service

    def retrieve(self, query):
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
                        results = self.graph.search_concepts(w)
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
            graph_results = self.graph.search_concepts(refined_query) or []
            rag_results = self.rag.retrieve(refined_query) or []

            graph_results = self._filter_graph_results(refined_query, graph_results)

            # 🔹 Step 4: Context
            combined_context = self._build_context(graph_results, rag_results)

            # 🔹 Step 5: Relevance check
            decision = self._safe_evaluate(refined_query, combined_context)

            # 🔁 Step 6: Retry if BAD
            if decision == "BAD":
                improved_query = self._refine_query(refined_query)

                graph_results = self.graph.search_concepts(improved_query) or []
                rag_results = self.rag.retrieve(improved_query) or []

                graph_results = self._filter_graph_results(improved_query, graph_results)

                combined_context = self._build_context(graph_results, rag_results)

                decision = self._safe_evaluate(improved_query, combined_context)

                if decision == "BAD":
                    return {
                        "query": query,
                        "graph_results": [],
                        "rag_results": [],
                        "answer": "Context not relevant to query.",
                        "confidence": 0.0
                    }

            # ⚠️ Fallback if nothing retrieved
            if not graph_results and not rag_results:
                return {
                    "query": query,
                    "graph_results": [],
                    "rag_results": [],
                    "answer": "No relevant information found.",
                    "confidence": 0.1
                }

            # 🔹 Step 7: Generate answer
            answer = self.llm.generate_answer(query, combined_context)

            # 🔹 Step 8: Confidence scoring
            confidence = self._compute_confidence(
                refined_query,
                graph_results,
                rag_results,
                decision,
                query,
                is_ambiguous
            )

            return {
                "query": query,
                "graph_results": graph_results,
                "rag_results": rag_results,
                "answer": answer,
                "confidence": confidence
            }

        except Exception as e:
            return {
                "query": query,
                "error": str(e),
                "answer": "Something went wrong.",
                "confidence": 0.0
            }

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

    # 🔥 SAFE EVALUATION (FIXED)
    def _safe_evaluate(self, query, context):
        try:
            return self.llm.evaluate_relevance(query, context)
        except Exception as e:
            print("⚠️ Evaluation failed:", e)
            return "BAD"

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