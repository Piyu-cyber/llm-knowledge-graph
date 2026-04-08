import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List


class NondeterminismService:
    """Runs repeated router probes and persists diff artifacts for auditability."""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self.artifact_dir = os.path.join(self.data_dir, "nondeterminism")
        os.makedirs(self.artifact_dir, exist_ok=True)

    def run_router_diff(self, router: Any, task: str, prompt: str, runs: int = 5) -> Dict:
        run_count = max(2, min(int(runs), 25))
        responses: List[Dict] = []

        for i in range(run_count):
            # Clear route cache so we can observe output variance across repeated calls.
            if hasattr(router, "response_cache"):
                router.response_cache.clear()
            result = router.route(task, prompt)
            responses.append(
                {
                    "run": i + 1,
                    "provider": result.get("provider"),
                    "text": result.get("text", ""),
                    "status": result.get("status"),
                }
            )

        unique_texts = sorted({str(r.get("text", "")) for r in responses})
        unique_providers = sorted({str(r.get("provider")) for r in responses})

        payload = {
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task": task,
            "prompt": prompt,
            "runs": run_count,
            "unique_text_count": len(unique_texts),
            "unique_provider_count": len(unique_providers),
            "stable": len(unique_texts) == 1,
            "responses": responses,
        }

        artifact_name = f"ndiff_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}.json"
        artifact_path = os.path.join(self.artifact_dir, artifact_name)
        with open(artifact_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        payload["artifact_path"] = artifact_path
        return payload
