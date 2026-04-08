import argparse
import json
import os
import statistics
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

from backend.services.background_job_queue import BackgroundJobQueue
from backend.services.llm_router import LLMRouter


def run_router_load(router: LLMRouter, concurrency: int, requests: int):
    tasks = [
        "ta_tutoring",
        "evaluator_defence",
        "curriculum_reasoning",
        "intent_classification",
        "memory_summarisation",
        "crag_grading",
    ]

    def one(i: int):
        task = tasks[i % len(tasks)]
        return router.route(task=task, prompt=f"Benchmark prompt {i} " + ("x" * 160), use_cache=False)

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(one, range(requests)))
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    ttfts = [float(r.get("ttft_ms", 0.0)) for r in results]
    success = len([r for r in results if r.get("status") == "success"])
    p95 = statistics.quantiles(ttfts, n=100)[94] if len(ttfts) >= 20 else (max(ttfts) if ttfts else 0.0)
    return {
        "total_requests": requests,
        "success_count": success,
        "success_rate": (success / requests) if requests else 1.0,
        "avg_ttft_ms": (sum(ttfts) / len(ttfts)) if ttfts else 0.0,
        "p95_ttft_ms": p95,
        "elapsed_ms": elapsed_ms,
    }


def run_queue_soak(duration_s: int, enqueue_per_tick: int, drain_max_jobs: int):
    with tempfile.TemporaryDirectory() as tmp:
        queue = BackgroundJobQueue(data_dir=tmp, max_attempts=3)
        start = time.time()
        i = 0
        while time.time() - start < duration_s:
            for _ in range(enqueue_per_tick):
                queue.enqueue("ok_job", {"i": i})
                i += 1
            queue.run_due_jobs(
                handlers={"ok_job": lambda _payload: None},
                max_jobs=drain_max_jobs,
            )
            time.sleep(0.2)
        return queue.stats()


def main():
    parser = argparse.ArgumentParser(description="Operational soak and concurrency benchmark")
    parser.add_argument("--concurrency", type=int, default=30)
    parser.add_argument("--requests", type=int, default=300)
    parser.add_argument("--soak-seconds", type=int, default=60)
    parser.add_argument("--enqueue-per-tick", type=int, default=20)
    parser.add_argument("--drain-max-jobs", type=int, default=200)
    parser.add_argument("--output", type=str, default="benchmark_report.json")
    args = parser.parse_args()

    router = LLMRouter()
    router_report = run_router_load(router, concurrency=args.concurrency, requests=args.requests)
    queue_report = run_queue_soak(
        duration_s=args.soak_seconds,
        enqueue_per_tick=args.enqueue_per_tick,
        drain_max_jobs=args.drain_max_jobs,
    )

    report = {
        "timestamp_unix": time.time(),
        "router_load": router_report,
        "router_provider_dashboard": router.provider_dashboards(),
        "router_error_budget": router.error_budget(),
        "queue_soak": queue_report,
        "params": vars(args),
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
