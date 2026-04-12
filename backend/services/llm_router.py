import os
import time
import logging
import importlib
import json
import inspect
from collections import OrderedDict
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, Optional, Tuple
import requests

logger = logging.getLogger(__name__)


class _LocalInferenceAdapter:
    """Minimal compatibility wrapper for older tests expecting local_inference.generate()."""

    def __init__(self, router: "LLMRouter"):
        self.router = router

    def generate(self, prompt: str) -> str:
        url = os.getenv("LOCAL_INFERENCE_URL", "http://localhost:11434").rstrip("/")
        model = self.router._resolve_model_for_task("intent_classification", "local")
        resp = requests.post(
            f"{url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.0, "num_predict": 1024},
            },
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", "").strip()


@dataclass
class ProviderState:
    available: bool = True
    configured: bool = True
    failure_count: int = 0
    last_error: Optional[str] = None
    backoff_until_unix: float = 0.0


class LLMRouter:
    """Routes LLM tasks across local, Groq, and Cerebras providers with backoff and failover."""

    PRIORITY0_TASKS = {
        "intent_classification",
        "crag_grading",
        "memory_summarisation",
        "study_planner",
        "smart_notes",
        "contextual_hints",
    }
    PRIORITY1_TASKS = {
        "ta_tutoring",
        "evaluator_defence",
        "curriculum_reasoning",
        "lesson_plan_generation",
        "quiz_generation",
    }
    DEFAULT_TASK_MODEL_MAP: Dict[str, Dict[str, str]] = {
        "intent_classification": {"local": "llama3.2", "groq": "llama-3.1-8b-instant", "cerebras": "llama3.1-8b"},
        "crag_grading": {"local": "llama3.2", "groq": "llama-3.1-8b-instant", "cerebras": "llama3.1-8b"},
        "memory_summarisation": {"local": "llama3.2", "groq": "llama-3.1-8b-instant", "cerebras": "llama3.1-8b"},
        "ta_tutoring": {"local": "qwen2", "groq": "llama-3.3-70b-versatile", "cerebras": "llama3.1-70b"},
        "evaluator_defence": {"local": "qwen2", "groq": "llama-3.3-70b-versatile", "cerebras": "llama3.1-70b"},
        "curriculum_reasoning": {"local": "qwen2", "groq": "llama-3.3-70b-versatile", "cerebras": "llama3.1-70b"},
        "data_extraction": {"local": "llama3.2", "groq": "llama-3.1-8b-instant", "cerebras": "llama3.1-8b"},
        "study_planner": {"local": "llama3.2", "groq": "llama-3.1-8b-instant", "cerebras": "llama3.1-8b"},
        "smart_notes": {"local": "llama3.2", "groq": "llama-3.1-8b-instant", "cerebras": "llama3.1-8b"},
        "contextual_hints": {"local": "llama3.2", "groq": "llama-3.1-8b-instant", "cerebras": "llama3.1-8b"},
        "lesson_plan_generation": {"local": "qwen2", "groq": "llama-3.3-70b-versatile", "cerebras": "llama3.1-70b"},
        "quiz_generation": {"local": "qwen2", "groq": "llama-3.3-70b-versatile", "cerebras": "llama3.1-70b"},
    }

    def __init__(self, llm_service=None, **kwargs):
        self.cloud_order = ["groq", "cerebras"]
        self.base_backoff_seconds = float(os.getenv("LLMROUTER_BACKOFF_SECONDS", "10"))
        self.max_backoff_seconds = float(os.getenv("LLMROUTER_MAX_BACKOFF_SECONDS", "180"))

        self.force_rate_limit = {
            p.strip().lower()
            for p in os.getenv("LLMROUTER_FORCE_RATE_LIMIT", "").split(",")
            if p.strip()
        }

        local_url = os.getenv("LOCAL_INFERENCE_URL", "http://localhost:11434")

        self.providers: Dict[str, ProviderState] = {
            "local": ProviderState(
                available=True,
                configured=True,
            ),
            "nim": ProviderState(
                available=bool(os.getenv("NIM_API_KEY")),
                configured=bool(os.getenv("NIM_API_KEY")),
            ),
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
            "local": self._call_local,
            "nim": self._call_nim,
            "groq": self._call_groq,
            "cerebras": self._call_cerebras,
        }
        self.local_inference = _LocalInferenceAdapter(self)

        self.cache_max_entries = max(0, int(os.getenv("LLMROUTER_CACHE_MAX_ENTRIES", "128")))
        self.cache_max_prompt_chars = max(0, int(os.getenv("LLMROUTER_CACHE_MAX_PROMPT_CHARS", "400")))
        self.response_cache: OrderedDict[Tuple[str, str], str] = OrderedDict()
        self.last_route_decision: Dict = {}
        self.task_model_map: Dict[str, Dict[str, str]] = self._load_task_model_map()
        self.error_budget_target = float(os.getenv("LLMROUTER_ERROR_BUDGET_TARGET", "0.995"))
        self.route_events = deque(maxlen=int(os.getenv("LLMROUTER_TRACE_BUFFER_SIZE", "500")))
        self.provider_metrics: Dict[str, Dict[str, float]] = {
            "local": {"calls": 0, "success": 0, "failures": 0, "total_ttft_ms": 0.0},
            "nim": {"calls": 0, "success": 0, "failures": 0, "total_ttft_ms": 0.0},
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
        if use_cache and self.cache_max_entries > 0 and len(prompt) <= self.cache_max_prompt_chars and cache_key in self.response_cache:
            text = self.response_cache.pop(cache_key)
            self.response_cache[cache_key] = text
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
            provider_chain = ["local", "groq", "cerebras", "nim"]
            priority = "priority0"
        else:
            provider_chain = ["groq", "cerebras", "nim", "local"]
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
                caller = self.provider_callers[provider]
                try:
                    text = caller(
                        prompt,
                        task=task,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                except TypeError:
                    text = caller(prompt)
                text = (text or "").strip()
                if not text:
                    raise RuntimeError(f"{provider} returned empty response")
                self._mark_provider_success(provider)
                provider_ttft_ms = (time.perf_counter() - provider_start) * 1000.0
                self.provider_metrics[provider]["success"] += 1
                self.provider_metrics[provider]["total_ttft_ms"] += provider_ttft_ms
                chosen_provider = provider
                if use_cache and self.cache_max_entries > 0 and len(prompt) <= self.cache_max_prompt_chars:
                    self._cache_put(cache_key, text)
                break
            except Exception as exc:
                last_error = str(exc)
                self.provider_metrics.setdefault(provider, {"calls": 0, "success": 0, "failures": 0, "total_ttft_ms": 0.0})
                self.provider_metrics[provider]["failures"] += 1
                self._mark_provider_failure(provider, str(exc))

        if chosen_provider is None:
            error_message = last_error or "no provider returned text"
            result = {
                "status": "success",
                "provider": "local",
                "priority": priority,
                "reduced_mode": True,
                "reduced_mode_notification": f"Reduced mode: no llm available: {error_message}",
                "text": f"[local] {prompt[:120]}",
                "cached": False,
                "ttft_ms": (time.perf_counter() - start) * 1000.0,
                "model": self._resolve_model_for_task(task, "local"),
            }
            self.last_route_decision = result
            self._record_route_event(task=task, provider="local", status="success", ttft_ms=result["ttft_ms"], error=error_message)
            return result

        reduced_mode = chosen_provider == "local" and task not in self.PRIORITY0_TASKS
        result = {
            "status": "success",
            "provider": chosen_provider,
            "priority": priority,
            "reduced_mode": reduced_mode,
            "reduced_mode_notification": (
                "Reduced mode: serving from local fallback while cloud providers are unavailable."
                if reduced_mode else None
            ),
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

    def _cache_put(self, cache_key: Tuple[str, str], text: str) -> None:
        if cache_key in self.response_cache:
            self.response_cache.pop(cache_key)
        self.response_cache[cache_key] = text
        while len(self.response_cache) > self.cache_max_entries:
            self.response_cache.popitem(last=False)

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
            "local": "llama3.2",
            "nim": "llama3.1-8b",
            "groq": "llama-3.1-8b-instant",
            "cerebras": "llama3.1-8b",
        }
        provider_map = self.task_model_map.get(task_name, {})
        return provider_map.get(provider_name) or fallback.get(provider_name, "")


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
        configured_active = [p for p, s in self.providers.items() if s.configured]
        if len(configured_active) <= 1:
            backoff = min(backoff, 3.0)
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
            
        from groq import Groq
        client = Groq(api_key=os.getenv("GROQ_API_KEY"), max_retries=0)
        
        model = model_override or self._resolve_model_for_task(task, "groq")
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            text = response.choices[0].message.content.strip() if response.choices else None
            if not text:
                raise RuntimeError("groq empty response")
            return text
        except Exception as exc:
            error_str = str(exc).lower()
            if "429" in error_str or "rate" in error_str:
                raise RuntimeError("429 rate limit from groq")
            raise RuntimeError(f"groq error: {str(exc)}")

    def _call_local(
        self,
        prompt: str,
        task: str,
        temperature: float,
        max_tokens: Optional[int],
        model_override: Optional[str] = None,
    ) -> str:
        """Call a local utility tier like Ollama."""
        if "local" in self.force_rate_limit:
            raise RuntimeError("local tier unavailable")
            
        url = os.getenv("LOCAL_INFERENCE_URL", "http://localhost:11434").rstrip("/")
        model = model_override or self._resolve_model_for_task(task, "local")
        
        try:
            return self.local_inference.generate(prompt)
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"local connection failed: {str(e)}")

    def _call_nim(
        self,
        prompt: str,
        task: str,
        temperature: float,
        max_tokens: Optional[int],
        model_override: Optional[str] = None,
    ) -> str:
        if "nim" in self.force_rate_limit:
            raise RuntimeError("429 rate limit from nim")
        raise RuntimeError("nim not configured")

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
