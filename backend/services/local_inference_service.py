import os
import json
import time
import urllib.error
import urllib.request
from typing import Dict


class LocalInferenceService:
    """Health checks and text generation against a local llama.cpp-style server."""

    def __init__(self, base_url: str = ""):
        self.base_url = (base_url or os.getenv("LLAMA_CPP_BASE_URL", "http://127.0.0.1:8080")).rstrip("/")
        self.chat_path = os.getenv("LLAMA_CPP_CHAT_PATH", "/v1/chat/completions")
        self.default_model = os.getenv("LLAMA_CPP_MODEL", "local-model")

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

    def generate(
        self,
        prompt: str,
        timeout: float = 20.0,
        max_tokens: int = 256,
        temperature: float = 0.2,
    ) -> str:
        """Generate text from the local server using OpenAI-compatible chat completion shape."""
        clean_prompt = (prompt or "").strip()
        if not clean_prompt:
            return ""

        payload = {
            "model": self.default_model,
            "messages": [{"role": "user", "content": clean_prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        url = f"{self.base_url}{self.chat_path}"
        request = urllib.request.Request(
            url=url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
                parsed = json.loads(body)
        except urllib.error.URLError as exc:
            raise RuntimeError(f"local inference unavailable: {str(exc)}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("local inference returned non-JSON response") from exc

        choices = parsed.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, str) and content.strip():
                return content.strip()

        direct_content = parsed.get("content")
        if isinstance(direct_content, str) and direct_content.strip():
            return direct_content.strip()

        raise RuntimeError("local inference returned empty completion")
