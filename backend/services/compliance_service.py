import json
import os
from datetime import datetime, timezone
from typing import Dict, Optional


class ComplianceService:
    """Tracks compliance health and student data access audit logging."""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self.audit_file = os.path.join(self.data_dir, "audit_log.json")

    def _read_audit(self):
        if not os.path.exists(self.audit_file):
            return []
        try:
            with open(self.audit_file, "r", encoding="utf-8") as f:
                rows = json.load(f)
            return rows if isinstance(rows, list) else []
        except Exception:
            return []

    def _write_audit(self, rows):
        with open(self.audit_file, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2)

    def log_access(self, actor_user_id: str, actor_role: str, resource: str, target_user_id: Optional[str] = None):
        rows = self._read_audit()
        rows.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "actor_user_id": actor_user_id,
                "actor_role": actor_role,
                "resource": resource,
                "target_user_id": target_user_id,
            }
        )
        self._write_audit(rows)

    def status(self) -> Dict:
        # Default true for local dev; can be overridden by env.
        encryption_at_rest = os.getenv("DATA_ENCRYPTION_AT_REST", "true").strip().lower() == "true"
        encryption_in_transit = os.getenv("TLS_ENFORCED", "true").strip().lower() == "true"

        # Audit log operational if file can be read and a heartbeat write succeeds.
        audit_operational = True
        try:
            self.log_access("system", "admin", "compliance_heartbeat")
            _ = self._read_audit()
        except Exception:
            audit_operational = False

        return {
            "status": "success",
            "ferpa_gdpr_pass": bool(encryption_at_rest and encryption_in_transit and audit_operational),
            "encryption_at_rest": encryption_at_rest,
            "encryption_in_transit": encryption_in_transit,
            "audit_log_operational": audit_operational,
            "audit_entries": len(self._read_audit()),
        }
