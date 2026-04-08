import os
import time
import logging
import importlib
import json
from collections import deque
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
    DEFAULT_TASK_MODEL_MAP: Dict[str, Dict[str, str]] = {
        "intent_classification": {"groq": "llama-3.1-8b-instant", "cerebras": "llama3.1-8b"},
        "crag_grading": {"groq": "llama-3.1-8b-instant", "cerebras": "llama3.1-8b"},
        "memory_summarisation": {"groq": "llama-3.1-8b-instant", "cerebras": "llama3.1-8b"},
        "ta_tutoring": {"groq": "llama-3.3-70b-versatile", "cerebras": "llama3.1-70b"},
        "evaluator_defence": {"groq": "llama-3.3-70b-versatile", "cerebras": "llama3.1-70b"},
        "curriculum_reasoning": {"groq": "llama-3.3-70b-versatile", "cerebras": "llama3.1-70b"},
    }
    DEFAULT_TASK_DRAFT_MODEL_MAP: Dict[str, Dict[str, str]] = {
        "ta_tutoring": {"groq": "llama-3.1-8b-instant", "cerebras": "llama3.1-8b"},
        "evaluator_defence": {"groq": "llama-3.1-8b-instant", "cerebras": "llama3.1-8b"},
        "curriculum_reasoning": {"groq": "llama-3.1-8b-instant", "cerebras": "llama3.1-8b"},
    }

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
        self.task_model_map: Dict[str, Dict[str, str]] = self._load_task_model_map()
        self.task_draft_model_map: Dict[str, Dict[str, str]] = self._load_task_draft_model_map()
        self.spec_decode_enabled = os.getenv("LLMROUTER_SPECULATIVE_ENABLED", "true").strip().lower() == "true"
        self.spec_decode_min_prompt_chars = int(os.getenv("LLMROUTER_SPECULATIVE_MIN_PROMPT_CHARS", "120"))
        self.error_budget_target = float(os.getenv("LLMROUTER_ERROR_BUDGET_TARGET", "0.995"))
        self.route_events = deque(maxlen=int(os.getenv("LLMROUTER_TRACE_BUFFER_SIZE", "500")))
        self.provider_metrics: Dict[str, Dict[str, float]] = {
            "groq": {"calls": 0, "success": 0, "failures": 0, "total_ttft_ms": 0.0},
            "cerebras": {"calls": 0, "success": 0, "failures": 0, "total_ttft_ms": 0.0},
        }

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
            "task_model_map": self.task_model_map,
            "task_draft_model_map": self.task_draft_model_map,
            "speculative_decoding_enabled": self.spec_decode_enabled,
            "provider_metrics": self.provider_dashboards(),
            "error_budget": self.error_budget(),
        }

    def route(
        self,
        task: str,
        prompt: str,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        use_cache: bool = True,
    ) -> Dict:
        start = time.perf_counter()
        task = (task or "").strip().lower() or "ta_tutoring"
        prompt = (prompt or "").strip()

        cache_key = (task, prompt)
        if use_cache and cache_key in self.response_cache:
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
            self._record_route_event(task=task, provider="cache", status="success", ttft_ms=1.0, error=None)
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
                provider_start = time.perf_counter()
                self.provider_metrics.setdefault(provider, {"calls": 0, "success": 0, "failures": 0, "total_ttft_ms": 0.0})
                self.provider_metrics[provider]["calls"] += 1
                if self._should_use_speculative(task=task, prompt=prompt):
                    draft_text, verifier_text = self._speculative_decode(
                        provider=provider,
                        task=task,
                        prompt=prompt,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    text = verifier_text or draft_text
                else:
                    text = self.provider_callers[provider](
                        prompt,
                        task=task,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                if not text:
                    text = "I am operating in reduced mode with concise guidance."
                self._mark_provider_success(provider)
                provider_ttft_ms = (time.perf_counter() - provider_start) * 1000.0
                self.provider_metrics[provider]["success"] += 1
                self.provider_metrics[provider]["total_ttft_ms"] += provider_ttft_ms
                chosen_provider = provider
                if use_cache:
                    self.response_cache[cache_key] = text
                break
            except Exception as exc:
                last_error = str(exc)
                self.provider_metrics.setdefault(provider, {"calls": 0, "success": 0, "failures": 0, "total_ttft_ms": 0.0})
                self.provider_metrics[provider]["failures"] += 1
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
            self._record_route_event(
                task=task,
                provider=None,
                status="error",
                ttft_ms=result["ttft_ms"],
                error=last_error,
            )
            return result

        reduced_mode = False
        result = {
            "status": "success",
            "provider": chosen_provider,
            "priority": priority,
            "reduced_mode": reduced_mode,
            "reduced_mode_notification": None,
            "text": text,
            "cached": False,
            "ttft_ms": (time.perf_counter() - start) * 1000.0,
            "model": self._resolve_model_for_task(task, chosen_provider),
        }
        self.last_route_decision = result
        self._record_route_event(
            task=task,
            provider=chosen_provider,
            status="success",
            ttft_ms=result["ttft_ms"],
            error=None,
        )
        return result

    def _record_route_event(
        self,
        task: str,
        provider: Optional[str],
        status: str,
        ttft_ms: float,
        error: Optional[str],
    ) -> None:
        self.route_events.append(
            {
                "ts_unix": time.time(),
                "task": task,
                "provider": provider,
                "status": status,
                "ttft_ms": float(ttft_ms),
                "error": error,
            }
        )

    def recent_traces(self, limit: int = 100) -> Dict:
        rows = list(self.route_events)[-max(1, int(limit)) :]
        return {"status": "success", "count": len(rows), "events": rows}

    def error_budget(self) -> Dict:
        events = list(self.route_events)
        total = len(events)
        failures = len([e for e in events if e.get("status") != "success"])
        success_rate = 1.0 if total == 0 else max(0.0, 1.0 - (failures / total))
        return {
            "window_events": total,
            "target_success_rate": self.error_budget_target,
            "actual_success_rate": round(success_rate, 4),
            "within_budget": success_rate >= self.error_budget_target,
            "errors_observed": failures,
        }

    def provider_dashboards(self) -> Dict:
        dashboards: Dict[str, Dict] = {}
        for provider, row in self.provider_metrics.items():
            calls = int(row.get("calls", 0))
            successes = int(row.get("success", 0))
            failures = int(row.get("failures", 0))
            avg_ttft = (float(row.get("total_ttft_ms", 0.0)) / successes) if successes else 0.0
            dashboards[provider] = {
                "calls": calls,
                "successes": successes,
                "failures": failures,
                "success_rate": round((successes / calls), 4) if calls else 1.0,
                "avg_ttft_ms": round(avg_ttft, 3),
            }
        return dashboards

    def _load_task_model_map(self) -> Dict[str, Dict[str, str]]:
        configured_map = dict(self.DEFAULT_TASK_MODEL_MAP)
        raw = os.getenv("LLMROUTER_TASK_MODEL_MAP", "").strip()
        if not raw:
            return configured_map
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                for task_name, providers in parsed.items():
                    if not isinstance(task_name, str) or not isinstance(providers, dict):
                        continue
                    provider_map = configured_map.setdefault(task_name.strip().lower(), {})
                    for provider_name, model_name in providers.items():
                        if isinstance(provider_name, str) and isinstance(model_name, str) and model_name.strip():
                            provider_map[provider_name.strip().lower()] = model_name.strip()
        except Exception as exc:
            logger.warning("Failed to parse LLMROUTER_TASK_MODEL_MAP: %s", str(exc))
        return configured_map

    def _resolve_model_for_task(self, task: str, provider: str) -> str:
        task_name = (task or "").strip().lower()
        provider_name = (provider or "").strip().lower()
        fallback = {
            "groq": "llama-3.1-8b-instant",
            "cerebras": "llama3.1-8b",
        }
        provider_map = self.task_model_map.get(task_name, {})
        return provider_map.get(provider_name) or fallback.get(provider_name, "")

    def _load_task_draft_model_map(self) -> Dict[str, Dict[str, str]]:
        configured_map = dict(self.DEFAULT_TASK_DRAFT_MODEL_MAP)
        raw = os.getenv("LLMROUTER_TASK_DRAFT_MODEL_MAP", "").strip()
        if not raw:
            return configured_map
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                for task_name, providers in parsed.items():
                    if not isinstance(task_name, str) or not isinstance(providers, dict):
                        continue
                    provider_map = configured_map.setdefault(task_name.strip().lower(), {})
                    for provider_name, model_name in providers.items():
                        if isinstance(provider_name, str) and isinstance(model_name, str) and model_name.strip():
                            provider_map[provider_name.strip().lower()] = model_name.strip()
        except Exception as exc:
            logger.warning("Failed to parse LLMROUTER_TASK_DRAFT_MODEL_MAP: %s", str(exc))
        return configured_map

    def _resolve_draft_model_for_task(self, task: str, provider: str) -> str:
        task_name = (task or "").strip().lower()
        provider_name = (provider or "").strip().lower()
        provider_map = self.task_draft_model_map.get(task_name, {})
        return provider_map.get(provider_name, "")

    def _should_use_speculative(self, task: str, prompt: str) -> bool:
        if not self.spec_decode_enabled:
            return False
        if task in self.PRIORITY0_TASKS:
            return False
        if len(prompt or "") < self.spec_decode_min_prompt_chars:
            return False
        return bool(self._resolve_draft_model_for_task(task, "groq") or self._resolve_draft_model_for_task(task, "cerebras"))

    def _speculative_decode(
        self,
        provider: str,
        task: str,
        prompt: str,
        temperature: float,
        max_tokens: Optional[int],
    ) -> Tuple[str, str]:
        draft_model = self._resolve_draft_model_for_task(task, provider)
        if not draft_model:
            return "", ""

        draft_prompt = (
            "Respond with concise candidate answer only.\n"
            f"Task: {task}\n\n"
            f"{prompt}"
        )
        draft_text = self.provider_callers[provider](
            draft_prompt,
            task=task,
            temperature=temperature,
            max_tokens=max_tokens,
            model_override=draft_model,
        )
        if not draft_text:
            return "", ""

        verify_prompt = (
            "Verify and improve the candidate answer. Return final answer only.\n\n"
            f"User prompt:\n{prompt}\n\n"
            f"Candidate draft:\n{draft_text}"
        )
        verifier_text = self.provider_callers[provider](
            verify_prompt,
            task=task,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return draft_text, verifier_text or ""

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

    def _call_groq(
        self,
        prompt: str,
        task: str,
        temperature: float,
        max_tokens: Optional[int],
        model_override: Optional[str] = None,
    ) -> str:
        if "groq" in self.force_rate_limit:
            raise RuntimeError("429 rate limit from groq")
        if not os.getenv("GROQ_API_KEY"):
            raise RuntimeError("groq not configured")
        model = model_override or self._resolve_model_for_task(task, "groq")
        text = self.llm_service._call_llm(
            prompt,
            temperature=temperature,
            retries=1,
            model=model,
            max_tokens=max_tokens,
        )
        if not text:
            raise RuntimeError("groq empty response")
        return text

    def _call_cerebras(
        self,
        prompt: str,
        task: str,
        temperature: float,
        max_tokens: Optional[int],
        model_override: Optional[str] = None,
    ) -> str:
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
                model=model_override or self._resolve_model_for_task(task, "cerebras"),
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
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
