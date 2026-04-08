import os
import time
import logging
import importlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, Optional, Tuple

from backend.services.llm_service import LLMService


logger = logging.getLogger(__name__)


@dataclass
class ProviderState:
    available: bool = True
    configured: bool = True
    failure_count: int = 0
    last_error: Optional[str] = None
    backoff_until_unix: float = 0.0


class LLMRouter:
    """Routes LLM tasks across Groq and Cerebras providers with backoff and failover."""

    PRIORITY0_TASKS = {"intent_classification", "crag_grading", "memory_summarisation"}
    PRIORITY1_TASKS = {"ta_tutoring", "evaluator_defence", "curriculum_reasoning"}

    def __init__(self, llm_service: Optional[LLMService] = None):
        self.llm_service = llm_service or LLMService()

        self.cloud_order = ["groq", "cerebras"]
        self.base_backoff_seconds = float(os.getenv("LLMROUTER_BACKOFF_SECONDS", "20"))
        self.max_backoff_seconds = float(os.getenv("LLMROUTER_MAX_BACKOFF_SECONDS", "180"))

        self.force_rate_limit = {
            p.strip().lower()
            for p in os.getenv("LLMROUTER_FORCE_RATE_LIMIT", "").split(",")
            if p.strip()
        }

        self.providers: Dict[str, ProviderState] = {
            "groq": ProviderState(
                available=bool(os.getenv("GROQ_API_KEY")),
                configured=bool(os.getenv("GROQ_API_KEY")),
            ),
            "cerebras": ProviderState(
                available=bool(os.getenv("CEREBRAS_API_KEY")),
                configured=bool(os.getenv("CEREBRAS_API_KEY")),
            ),
        }

        self.provider_callers: Dict[str, Callable[[str], str]] = {
            "groq": self._call_groq,
            "cerebras": self._call_cerebras,
        }

        self.response_cache: Dict[Tuple[str, str], str] = {}
        self.last_route_decision: Dict = {}

    def health_status(self) -> Dict:
        now = time.time()
        providers = {}
        for name, state in self.providers.items():
            providers[name] = {
                "available": state.available,
                "failure_count": state.failure_count,
                "last_error": state.last_error,
                "backoff_remaining_s": max(0.0, state.backoff_until_unix - now),
            }
        return {
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "providers": providers,
            "cloud_order": self.cloud_order,
            "priority0_tasks": sorted(self.PRIORITY0_TASKS),
            "priority1_tasks": sorted(self.PRIORITY1_TASKS),
        }

    def route(self, task: str, prompt: str) -> Dict:
        start = time.perf_counter()
        task = (task or "").strip().lower() or "ta_tutoring"
        prompt = (prompt or "").strip()

        cache_key = (task, prompt)
        if cache_key in self.response_cache:
            text = self.response_cache[cache_key]
            result = {
                "status": "success",
                "provider": "cache",
                "priority": "cache",
                "reduced_mode": False,
                "reduced_mode_notification": None,
                "text": text,
                "cached": True,
                "ttft_ms": 1.0,
            }
            self.last_route_decision = result
            return result

        if task in self.PRIORITY0_TASKS:
            provider_chain = ["groq", "cerebras"]
            priority = "priority0"
        else:
            provider_chain = ["groq", "cerebras"]
            priority = "priority1"

        last_error = None
        chosen_provider = None

        for provider in provider_chain:
            self._maybe_retry_provider(provider)
            state = self.providers[provider]
            if not state.available:
                continue

            try:
                text = self.provider_callers[provider](prompt)
                if not text:
                    text = "I am operating in reduced mode with concise guidance."
                self._mark_provider_success(provider)
                chosen_provider = provider
                self.response_cache[cache_key] = text
                break
            except Exception as exc:
                last_error = str(exc)
                self._mark_provider_failure(provider, str(exc))

        if chosen_provider is None:
            result = {
                "status": "error",
                "provider": None,
                "priority": priority,
                "reduced_mode": True,
                "reduced_mode_notification": "Reduced mode active: Groq/Cerebras unavailable.",
                "text": "System is temporarily degraded. Please retry shortly.",
                "cached": False,
                "ttft_ms": (time.perf_counter() - start) * 1000.0,
                "error": last_error,
            }
            self.last_route_decision = result
            return result

        reduced_mode = False
        result = {
            "status": "success",
            "provider": chosen_provider,
            "priority": priority,
            "reduced_mode": reduced_mode,
            "reduced_mode_notification": None,
            "text": self.response_cache[cache_key],
            "cached": False,
            "ttft_ms": (time.perf_counter() - start) * 1000.0,
        }
        self.last_route_decision = result
        return result

    def _mark_provider_success(self, provider: str):
        state = self.providers[provider]
        state.available = True
        state.failure_count = 0
        state.last_error = None
        state.backoff_until_unix = 0.0

    def _mark_provider_failure(self, provider: str, error: str):
        state = self.providers[provider]
        state.failure_count += 1
        state.last_error = error

        backoff = min(self.max_backoff_seconds, self.base_backoff_seconds * max(1, state.failure_count))
        state.backoff_until_unix = time.time() + backoff
        state.available = False

    def _maybe_retry_provider(self, provider: str):
        state = self.providers[provider]
        if not state.configured:
            state.available = False
            return
        if state.available:
            return
        if state.backoff_until_unix <= 0.0:
            return
        if time.time() >= state.backoff_until_unix:
            state.available = True

    def _call_groq(self, prompt: str) -> str:
        if "groq" in self.force_rate_limit:
            raise RuntimeError("429 rate limit from groq")
        if not os.getenv("GROQ_API_KEY"):
            raise RuntimeError("groq not configured")
        text = self.llm_service._call_llm(prompt, temperature=0, retries=1)
        if not text:
            raise RuntimeError("groq empty response")
        return text

    def _call_cerebras(self, prompt: str) -> str:
        """Call Cerebras Cloud API using cerebras-cloud-sdk."""
        if "cerebras" in self.force_rate_limit:
            raise RuntimeError("429 rate limit from cerebras")
        if not os.getenv("CEREBRAS_API_KEY"):
            raise RuntimeError("cerebras not configured")
        
        try:
            sdk_module = importlib.import_module("cerebras.cloud.sdk")
            Cerebras = getattr(sdk_module, "Cerebras")

            client = Cerebras(api_key=os.getenv("CEREBRAS_API_KEY"))
            response = client.chat.completions.create(
                model="llama3.1-8b",
                messages=[{"role": "user", "content": prompt}]
            )
            return response.choices[0].message.content.strip()
            
        except ModuleNotFoundError:
            raise RuntimeError("cerebras-cloud-sdk not installed")
        except Exception as e:
            # Mark provider as rate-limited and return None for fallthrough
            error_str = str(e).lower()
            if "429" in error_str or "rate" in error_str:
                self.providers["cerebras"].available = False
                self.providers["cerebras"].backoff_until_unix = (
                    time.time() + self.base_backoff_seconds
                )
            raise RuntimeError(f"cerebras error: {str(e)}")
