from backend.services.graph_service import GraphService
from backend.services.llm_service import LLMService


class CRAGService:
    def __init__(self, rag_service):
        self.graph = GraphService()
        self.llm = LLMService()
        self.rag = rag_service  # ✅ shared instance (FIXED)

    def retrieve(self, query):
        # 🔹 Step 1: initial retrieval (Graph + RAG)
        graph_results = self.graph.search_concepts(query)
        rag_results = self.rag.retrieve(query)

        # 🔹 Step 2: combine context
        combined_context = self._build_context(graph_results, rag_results)

        # 🔹 Step 3: evaluate relevance
        decision = self.llm.evaluate_relevance(query, combined_context)
        print("Initial decision:", decision)

        # 🔹 Step 4: retry if BAD
        if decision == "BAD":
            print("🔁 Retrying with simplified query...")

            simplified_query = query.split()[0]

            graph_results = self.graph.search_concepts(simplified_query)
            rag_results = self.rag.retrieve(simplified_query)

            combined_context = self._build_context(graph_results, rag_results)

            decision = self.llm.evaluate_relevance(simplified_query, combined_context)
            print("Retry decision:", decision)

        # 🔹 Step 5: generate final answer
        answer = self.llm.generate_answer(query, combined_context)

        return {
            "query": query,
            "graph_results": graph_results,
            "rag_results": rag_results,
            "answer": answer
        }

    def _build_context(self, graph_results, rag_results):
        # Graph context
        graph_context = "\n".join([
            f"{r['name']}: {r.get('description', '')}"
            for r in graph_results
        ])

        # RAG context
        rag_context = "\n".join(rag_results)

        return f"""
GRAPH KNOWLEDGE:
{graph_context}

RETRIEVED DOCUMENTS:
{rag_context}
"""