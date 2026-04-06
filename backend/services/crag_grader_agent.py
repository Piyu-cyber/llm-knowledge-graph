import re
import time
from typing import Dict


class CRAGGraderAgent:
    """Lightweight relevance grader with deterministic fallback for local SLA."""

    def __init__(self, llm_service=None):
        self.llm_service = llm_service

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
        if self.llm_service is not None:
            try:
                score = float(self.llm_service.evaluate_relevance(query, context))
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
        }
