import json
import os
from datetime import datetime, timezone
from typing import Dict


class IntegrityPolicyService:
    """Persists and serves runtime integrity policy controls."""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self.policy_file = os.path.join(self.data_dir, "integrity_policy.json")
        os.makedirs(self.data_dir, exist_ok=True)

    def _default_policy(self) -> Dict:
        return {
            "min_token_threshold": int(os.getenv("INTEGRITY_MIN_TOKENS", "500")),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": "system",
        }

    def get_policy(self) -> Dict:
        if not os.path.exists(self.policy_file):
            return self._default_policy()

        try:
            with open(self.policy_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            threshold = int(data.get("min_token_threshold", self._default_policy()["min_token_threshold"]))
            return {
                "min_token_threshold": threshold,
                "updated_at": data.get("updated_at"),
                "updated_by": data.get("updated_by", "unknown"),
            }
        except Exception:
            return self._default_policy()

    def set_min_token_threshold(self, value: int, updated_by: str) -> Dict:
        threshold = int(value)
        if threshold < 100 or threshold > 20000:
            raise ValueError("min_token_threshold must be between 100 and 20000")

        policy = {
            "min_token_threshold": threshold,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": updated_by or "unknown",
        }
        with open(self.policy_file, "w", encoding="utf-8") as f:
            json.dump(policy, f, indent=2)
        return policy
