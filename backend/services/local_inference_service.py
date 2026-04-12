import time
from typing import Any, Dict

import requests


class LocalInferenceService:
    """Compatibility shim for legacy phase tests that expect a local health probe service."""

    def __init__(self, base_url: str = "http://127.0.0.1:11434"):
        self.base_url = base_url.rstrip("/")

    def health_check(self) -> Dict[str, Any]:
        started = time.perf_counter()
        response = requests.get(f"{self.base_url}/health", timeout=2.0)
        latency_ms = (time.perf_counter() - started) * 1000.0
        return {
            "ok": response.ok,
            "status": response.status_code,
            "latency_ms": latency_ms,
            "text": response.text,
        }

    def meets_latency_sla(self, max_latency_ms: float = 300.0) -> Dict[str, Any]:
        result = self.health_check()
        result["meets_sla"] = bool(result["ok"] and result["latency_ms"] <= max_latency_ms)
        return result
