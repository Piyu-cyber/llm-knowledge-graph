import json
import os
import time
import uuid
import random
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional


class BackgroundJobQueue:
    """Simple persistent queue with dead-letter support for failed jobs."""

    def __init__(self, data_dir: str = "data", max_attempts: int = 3):
        self.data_dir = data_dir
        self.max_attempts = max_attempts
        self.base_retry_seconds = float(os.getenv("BGJOB_BASE_RETRY_SECONDS", "1.0"))
        self.max_retry_seconds = float(os.getenv("BGJOB_MAX_RETRY_SECONDS", "120.0"))
        self.jitter_seconds = float(os.getenv("BGJOB_RETRY_JITTER_SECONDS", "0.25"))
        self.trace_buffer_limit = int(os.getenv("BGJOB_TRACE_BUFFER_SIZE", "500"))
        os.makedirs(self.data_dir, exist_ok=True)

        self.queue_file = os.path.join(self.data_dir, "background_jobs.json")
        self.dead_letter_file = os.path.join(self.data_dir, "background_jobs_dead_letter.json")
        self.history_file = os.path.join(self.data_dir, "background_jobs_history.json")

    def _read_rows(self, file_path: str) -> List[Dict]:
        if not os.path.exists(file_path):
            return []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                rows = json.load(f)
            return rows if isinstance(rows, list) else []
        except Exception:
            return []

    def _write_rows(self, file_path: str, rows: List[Dict]) -> None:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2)

    def _append_history(self, event: Dict[str, Any]) -> None:
        rows = self._read_rows(self.history_file)
        rows.append(event)
        if len(rows) > self.trace_buffer_limit:
            rows = rows[-self.trace_buffer_limit :]
        self._write_rows(self.history_file, rows)

    def enqueue(self, job_type: str, payload: Dict[str, Any], run_at_unix: Optional[float] = None) -> Dict:
        rows = self._read_rows(self.queue_file)
        entry = {
            "job_id": str(uuid.uuid4())[:12],
            "job_type": job_type,
            "payload": payload,
            "attempts": 0,
            "run_at_unix": float(run_at_unix if run_at_unix is not None else time.time()),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_error": None,
        }
        rows.append(entry)
        self._write_rows(self.queue_file, rows)
        self._append_history(
            {
                "event": "enqueue",
                "ts": datetime.now(timezone.utc).isoformat(),
                "job_id": entry["job_id"],
                "job_type": entry["job_type"],
                "run_at_unix": entry["run_at_unix"],
            }
        )
        return {"status": "success", "job_id": entry["job_id"]}

    def run_due_jobs(
        self,
        handlers: Dict[str, Callable[[Dict[str, Any]], None]],
        now_unix: Optional[float] = None,
        max_jobs: Optional[int] = None,
    ) -> Dict:
        now_unix = float(now_unix if now_unix is not None else time.time())
        rows = self._read_rows(self.queue_file)
        dlq = self._read_rows(self.dead_letter_file)

        remaining = []
        succeeded = 0
        failed = 0
        retried = 0
        processed = 0

        for row in rows:
            if max_jobs is not None and processed >= int(max_jobs):
                remaining.append(row)
                continue
            if float(row.get("run_at_unix", 0.0)) > now_unix:
                remaining.append(row)
                continue
            processed += 1

            job_type_raw = row.get("job_type")
            job_type = str(job_type_raw) if isinstance(job_type_raw, str) else ""
            handler = handlers.get(job_type)
            if handler is None:
                row["attempts"] = int(row.get("attempts", 0)) + 1
                row["last_error"] = f"No handler for job_type={job_type}"
            else:
                try:
                    handler(row.get("payload", {}))
                    succeeded += 1
                    continue
                except Exception as exc:
                    row["attempts"] = int(row.get("attempts", 0)) + 1
                    row["last_error"] = str(exc)

            if int(row.get("attempts", 0)) >= self.max_attempts:
                row["moved_to_dlq_at"] = datetime.now(timezone.utc).isoformat()
                dlq.append(row)
                failed += 1
                self._append_history(
                    {
                        "event": "dead_letter",
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "job_id": row.get("job_id"),
                        "job_type": job_type,
                        "attempts": row.get("attempts", 0),
                        "error": row.get("last_error"),
                    }
                )
            else:
                backoff = min(self.max_retry_seconds, self.base_retry_seconds * (2 ** max(0, int(row.get("attempts", 1)) - 1)))
                jitter = random.uniform(0.0, max(0.0, self.jitter_seconds))
                row["run_at_unix"] = now_unix + backoff + jitter
                remaining.append(row)
                retried += 1
                self._append_history(
                    {
                        "event": "retry_scheduled",
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "job_id": row.get("job_id"),
                        "job_type": job_type,
                        "attempts": row.get("attempts", 0),
                        "next_run_at_unix": row.get("run_at_unix"),
                        "error": row.get("last_error"),
                    }
                )

        self._write_rows(self.queue_file, remaining)
        self._write_rows(self.dead_letter_file, dlq)

        return {
            "status": "success",
            "succeeded": succeeded,
            "moved_to_dead_letter": failed,
            "retried": retried,
            "processed": processed,
            "queue_depth": len(remaining),
            "dead_letter_depth": len(dlq),
        }

    def replay_dead_letter(self, limit: Optional[int] = None, reset_attempts: bool = True) -> Dict:
        queue_rows = self._read_rows(self.queue_file)
        dlq_rows = self._read_rows(self.dead_letter_file)
        moved = 0
        kept = []
        cap = int(limit) if limit is not None else len(dlq_rows)
        for row in dlq_rows:
            if moved >= cap:
                kept.append(row)
                continue
            replay = dict(row)
            replay["last_error"] = None
            replay["run_at_unix"] = time.time()
            replay["replayed_at"] = datetime.now(timezone.utc).isoformat()
            if reset_attempts:
                replay["attempts"] = 0
            queue_rows.append(replay)
            moved += 1
            self._append_history(
                {
                    "event": "dlq_replay",
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "job_id": replay.get("job_id"),
                    "job_type": replay.get("job_type"),
                }
            )
        self._write_rows(self.queue_file, queue_rows)
        self._write_rows(self.dead_letter_file, kept)
        return {"status": "success", "replayed": moved, "queue_depth": len(queue_rows), "dead_letter_depth": len(kept)}

    def recent_history(self, limit: int = 100) -> Dict:
        rows = self._read_rows(self.history_file)
        out = rows[-max(1, int(limit)) :]
        return {"status": "success", "count": len(out), "events": out}

    def stats(self) -> Dict:
        queue_rows = self._read_rows(self.queue_file)
        dlq_rows = self._read_rows(self.dead_letter_file)
        now = time.time()
        due = len([r for r in queue_rows if float(r.get("run_at_unix", 0.0)) <= now])
        oldest_due_unix = None
        due_rows = [r for r in queue_rows if float(r.get("run_at_unix", 0.0)) <= now]
        if due_rows:
            oldest_due_unix = min(float(r.get("run_at_unix", now)) for r in due_rows)
        return {
            "queue_depth": len(queue_rows),
            "dead_letter_depth": len(dlq_rows),
            "max_attempts": self.max_attempts,
            "due_jobs": due,
            "oldest_due_age_s": (now - oldest_due_unix) if oldest_due_unix is not None else 0.0,
            "retry_policy": {
                "base_retry_seconds": self.base_retry_seconds,
                "max_retry_seconds": self.max_retry_seconds,
                "jitter_seconds": self.jitter_seconds,
            },
        }
