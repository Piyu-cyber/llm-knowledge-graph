class CRAGService:
    def __init__(self, rag_service, graph_service, llm_service):
        self.graph = graph_service
        self.llm = llm_service
        self.rag = rag_service

    def retrieve(self, query):
        try:
            # 🔥 STEP 0: BETTER SUMMARY DETECTION
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

            # 🔥 STEP 1: Ambiguity
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

            # 🔹 Step 3: retrieval
            graph_results = self.graph.search_concepts(refined_query) or []
            rag_results = self.rag.retrieve(refined_query) or []

            graph_results = self._filter_graph_results(refined_query, graph_results)

            # 🔹 Step 4: context
            combined_context = self._build_context(graph_results, rag_results)

            # 🔹 Step 5: relevance
            decision = self._safe_evaluate(refined_query, combined_context)

            # 🔁 Step 6: retry
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

            # ⚠️ fallback
            if not graph_results and not rag_results:
                return {
                    "query": query,
                    "graph_results": [],
                    "rag_results": [],
                    "answer": "No relevant information found.",
                    "confidence": 0.1
                }

            # 🔹 Step 7: answer
            answer = self.llm.generate_answer(query, combined_context)

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

    # 🔥 IMPROVED summary detection
    def _is_summary_query(self, query):
        query_lower = query.lower()

        # stricter keywords
        keywords = ["summarize", "summary", "explain this document", "what is this document"]
        if any(k in query_lower for k in keywords):
            return True

        # fallback LLM
        prompt = f"""
Query: {query}
Is this asking for a document summary?
Answer YES or NO.
"""
        result = self.llm._call_llm(prompt)
        return result and "yes" in result.lower()

    # 🔥 SAME (kept clean)
    def _is_ambiguous(self, query):
        prompt = f"""
Query: {query}
Is this query ambiguous?
Answer YES or NO.
"""
        result = self.llm._call_llm(prompt)
        return result and any(w in result.lower() for w in ["yes", "ambiguous"])

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

    def _build_context(self, graph_results, rag_results):
        graph_context = ""

        for r in graph_results[:5]:
            graph_context += f"{r.get('name','')}: {r.get('description','')}\n"

            # 🔥 INCLUDE RELATIONSHIPS
            for rel in r.get("related", []):
                graph_context += f"→ {rel.get('name')} ({rel.get('relation')})\n"

        rag_context = "\n".join(rag_results[:5])

        return f"""
GRAPH KNOWLEDGE:
{graph_context}

RETRIEVED DOCUMENTS:
{rag_context}
"""