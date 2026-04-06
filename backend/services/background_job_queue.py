import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional


class BackgroundJobQueue:
    """Simple persistent queue with dead-letter support for failed jobs."""

    def __init__(self, data_dir: str = "data", max_attempts: int = 3):
        self.data_dir = data_dir
        self.max_attempts = max_attempts
        os.makedirs(self.data_dir, exist_ok=True)

        self.queue_file = os.path.join(self.data_dir, "background_jobs.json")
        self.dead_letter_file = os.path.join(self.data_dir, "background_jobs_dead_letter.json")

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
        return {"status": "success", "job_id": entry["job_id"]}

    def run_due_jobs(self, handlers: Dict[str, Callable[[Dict[str, Any]], None]], now_unix: Optional[float] = None) -> Dict:
        now_unix = float(now_unix if now_unix is not None else time.time())
        rows = self._read_rows(self.queue_file)
        dlq = self._read_rows(self.dead_letter_file)

        remaining = []
        succeeded = 0
        failed = 0

        for row in rows:
            if float(row.get("run_at_unix", 0.0)) > now_unix:
                remaining.append(row)
                continue

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
            else:
                row["run_at_unix"] = now_unix + 1.0
                remaining.append(row)

        self._write_rows(self.queue_file, remaining)
        self._write_rows(self.dead_letter_file, dlq)

        return {
            "status": "success",
            "succeeded": succeeded,
            "moved_to_dead_letter": failed,
            "queue_depth": len(remaining),
            "dead_letter_depth": len(dlq),
        }

    def stats(self) -> Dict:
        queue_rows = self._read_rows(self.queue_file)
        dlq_rows = self._read_rows(self.dead_letter_file)
        return {
            "queue_depth": len(queue_rows),
            "dead_letter_depth": len(dlq_rows),
            "max_attempts": self.max_attempts,
        }
