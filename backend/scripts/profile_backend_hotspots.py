import argparse
import cProfile
import importlib
import io
import json
import os
import pstats
import time
import tracemalloc
from dataclasses import asdict, dataclass
from typing import Callable, Dict, List

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None


@dataclass
class ScenarioReport:
    name: str
    wall_ms: float
    cpu_ms: float
    rss_delta_mb: float
    tracemalloc_peak_mb: float
    top_cpu: List[Dict[str, str]]
    top_alloc: List[Dict[str, str]]


def _rss_mb() -> float:
    if not psutil:
        return 0.0
    proc = psutil.Process(os.getpid())
    return float(proc.memory_info().rss) / (1024 * 1024)


def _cpu_seconds() -> float:
    if not psutil:
        return time.process_time()
    proc = psutil.Process(os.getpid())
    times = proc.cpu_times()
    return float(times.user + times.system)


def _top_cpu_lines(profile: cProfile.Profile, limit: int = 12) -> List[Dict[str, str]]:
    stats = pstats.Stats(profile)
    stats.sort_stats("cumulative")
    rows: List[Dict[str, str]] = []
    for idx, (func, func_stats) in enumerate(stats.stats.items()):
        if idx > 3000:
            break
        cc, nc, tt, ct, callers = func_stats
        if ct <= 0.002:
            continue
        file_name, line_no, fn_name = func
        rows.append(
            {
                "func": f"{file_name}:{line_no}:{fn_name}",
                "cum_s": f"{ct:.4f}",
                "self_s": f"{tt:.4f}",
                "calls": str(nc),
            }
        )
    rows.sort(key=lambda r: float(r["cum_s"]), reverse=True)
    return rows[:limit]


def _top_alloc_lines(snapshot: tracemalloc.Snapshot, limit: int = 12) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for stat in snapshot.statistics("lineno")[:limit]:
        frame = stat.traceback[0]
        rows.append(
            {
                "location": f"{frame.filename}:{frame.lineno}",
                "size_mb": f"{stat.size / (1024 * 1024):.3f}",
                "count": str(stat.count),
            }
        )
    return rows


def run_scenario(name: str, fn: Callable[[], None]) -> ScenarioReport:
    prof = cProfile.Profile()
    rss_before = _rss_mb()
    cpu_before = _cpu_seconds()
    tracemalloc.start(25)
    start = time.perf_counter()

    prof.enable()
    fn()
    prof.disable()

    wall_ms = (time.perf_counter() - start) * 1000.0
    cpu_ms = (_cpu_seconds() - cpu_before) * 1000.0
    rss_delta_mb = _rss_mb() - rss_before
    current, peak = tracemalloc.get_traced_memory()
    snapshot = tracemalloc.take_snapshot()
    tracemalloc.stop()

    return ScenarioReport(
        name=name,
        wall_ms=round(wall_ms, 2),
        cpu_ms=round(cpu_ms, 2),
        rss_delta_mb=round(rss_delta_mb, 2),
        tracemalloc_peak_mb=round(peak / (1024 * 1024), 2),
        top_cpu=_top_cpu_lines(prof),
        top_alloc=_top_alloc_lines(snapshot),
    )


def scenario_import_app() -> None:
    importlib.import_module("backend.app")


def scenario_init_graph() -> None:
    app = importlib.import_module("backend.app")
    app.get_omniprof_graph()


def scenario_ta_agent_only() -> None:
    module = importlib.import_module("backend.agents.ta_agent")
    module.TAAgent()


def main() -> None:
    parser = argparse.ArgumentParser(description="Profile backend CPU/RAM hotspots")
    parser.add_argument("--output", default="backend_hotspots_report.json")
    args = parser.parse_args()

    scenarios = [
        ("import_backend_app", scenario_import_app),
        ("initialize_omniprof_graph", scenario_init_graph),
        ("construct_ta_agent", scenario_ta_agent_only),
    ]

    reports = []
    for name, fn in scenarios:
        report = run_scenario(name, fn)
        reports.append(asdict(report))
        print(f"\n=== {name} ===")
        print(json.dumps(asdict(report), indent=2))

    summary = {
        "generated_at_unix": time.time(),
        "reports": reports,
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"\nSaved report to {args.output}")


if __name__ == "__main__":
    main()
