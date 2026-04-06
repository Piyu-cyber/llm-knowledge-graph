import os
import time
import urllib.error
import urllib.request
from typing import Dict


class LocalInferenceService:
    """Health and latency checks for local llama.cpp-style inference server."""

    def __init__(self, base_url: str = ""):
        self.base_url = (base_url or os.getenv("LLAMA_CPP_BASE_URL", "http://127.0.0.1:8080")).rstrip("/")

    def health_check(self, path: str = "/health", timeout: float = 3.0) -> Dict:
        url = f"{self.base_url}{path}"
        start = time.perf_counter()
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                status = response.status
            latency_ms = (time.perf_counter() - start) * 1000.0
            return {
                "ok": status == 200,
                "status": status,
                "latency_ms": latency_ms,
                "url": url,
            }
        except urllib.error.URLError as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            return {
                "ok": False,
                "status": None,
                "latency_ms": latency_ms,
                "url": url,
                "error": str(exc),
            }

    def meets_latency_sla(self, max_latency_ms: float = 300.0, path: str = "/health") -> Dict:
        result = self.health_check(path=path)
        result["meets_sla"] = bool(result.get("ok") and result.get("latency_ms", 10_000) < max_latency_ms)
        return result
