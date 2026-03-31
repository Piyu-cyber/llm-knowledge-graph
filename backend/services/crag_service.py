from backend.services.graph_service import GraphService
from backend.services.llm_service import LLMService


class CRAGService:
    def __init__(self):
        self.graph = GraphService()
        self.llm = LLMService()

    def retrieve(self, query):
        # 🔹 Step 1: initial retrieval
        results = self.graph.search_concepts(query)

        # 🔹 Step 2: evaluate relevance
        decision = self.llm.evaluate_relevance(query, results)
        print("Initial decision:", decision)

        # 🔹 Step 3: retry if BAD
        if decision == "BAD":
            print("🔁 Retrying with simplified query...")

            simplified_query = query.split()[0]
            results = self.graph.search_concepts(simplified_query)

            decision = self.llm.evaluate_relevance(simplified_query, results)
            print("Retry decision:", decision)

        # 🔹 Step 4: prepare context
        context = "\n".join([
    f"{r['name']}: {r.get('description', '')}"
    for r in results
])

        # 🔥 Step 5: generate final answer
        answer = self.llm.generate_answer(query, context)

        return {
            "query": query,
            "results": results,
            "answer": answer
        }