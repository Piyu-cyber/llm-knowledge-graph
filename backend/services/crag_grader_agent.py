import re
import time
import json
from typing import Dict
from backend.services.llm_router import LLMRouter


class CRAGGraderAgent:
    """Lightweight relevance grader with deterministic fallback for local SLA."""

    def __init__(self, llm_service=None):
        self.llm_service = llm_service
        self.router = LLMRouter(llm_service=llm_service)

    def _lexical_score(self, query: str, context: str) -> float:
        q_tokens = {t for t in re.split(r"[^a-zA-Z0-9]+", query.lower()) if t}
        if not q_tokens:
            return 0.0
        c_tokens = {t for t in re.split(r"[^a-zA-Z0-9]+", context.lower()) if t}
        overlap = len(q_tokens.intersection(c_tokens))
        return min(1.0, overlap / max(1, len(q_tokens)))

    def grade(self, query: str, context: str) -> Dict:
        start = time.perf_counter()
        score = None
        route_meta = {"provider": None, "model": None, "status": "fallback"}

        prompt = f"""
You are a strict CRAG grading module.
Score how relevant the context is for answering the query.
Return ONLY JSON: {{"score": <float between 0 and 1>}}

Query:
{query}

Context:
{context[:4000]}
"""
        try:
            routed = self.router.route(
                task="crag_grading",
                prompt=prompt,
                temperature=0.0,
                max_tokens=80,
                use_cache=False,
            )
            route_meta = {
                "provider": routed.get("provider"),
                "model": routed.get("model"),
                "status": routed.get("status"),
            }
            match = re.search(r"\{.*\}", (routed.get("text") or "").strip(), re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                score = float(parsed.get("score"))
        except Exception:
            score = None

        if score is None:
            score = self._lexical_score(query, context)

        score = max(0.0, min(1.0, float(score)))
        latency_ms = (time.perf_counter() - start) * 1000.0

        if score > 0.7:
            route = "proceed"
        elif score < 0.5:
            route = "expand"
        else:
            route = "clarify"

        return {
            "score": score,
            "route": route,
            "latency_ms": latency_ms,
            "within_sla_100ms": latency_ms < 100.0,
            "router_provider": route_meta.get("provider"),
            "router_model": route_meta.get("model"),
            "router_status": route_meta.get("status"),
        }
