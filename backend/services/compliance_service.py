import json
import os
import hashlib
from datetime import datetime, timezone
from typing import Dict, Optional, Any


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

    def _hash_payload(self, payload: Dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def _next_chain_hash(self, rows, entry_without_hash: Dict[str, Any]) -> str:
        prev = rows[-1].get("chain_hash", "") if rows else ""
        payload = {"prev": prev, "entry": entry_without_hash}
        return self._hash_payload(payload)

    def verify_audit_chain(self) -> Dict:
        rows = self._read_audit()
        prev = ""
        for idx, row in enumerate(rows):
            material = dict(row)
            actual = str(material.pop("chain_hash", ""))
            expected = self._hash_payload({"prev": prev, "entry": material})
            if actual != expected:
                return {
                    "valid": False,
                    "broken_at_index": idx,
                    "expected_chain_hash": expected,
                    "actual_chain_hash": actual,
                }
            prev = actual
        return {"valid": True, "entries_checked": len(rows)}

    def log_access(
        self,
        actor_user_id: str,
        actor_role: str,
        resource: str,
        target_user_id: Optional[str] = None,
        action: str = "read",
        lawful_basis: str = "legitimate_interest",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        rows = self._read_audit()
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor_user_id": actor_user_id,
            "actor_role": actor_role,
            "resource": resource,
            "target_user_id": target_user_id,
            "action": action,
            "lawful_basis": lawful_basis,
            "metadata": metadata or {},
        }
        entry["chain_hash"] = self._next_chain_hash(rows, entry)
        rows.append(entry)
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
        chain = self.verify_audit_chain()
        retention_days = int(os.getenv("COMPLIANCE_RETENTION_DAYS", "365"))
        dpo_contact = os.getenv("DPO_CONTACT", "unset")
        dsar_enabled = os.getenv("DSAR_WORKFLOW_ENABLED", "true").strip().lower() == "true"

        return {
            "status": "success",
            "ferpa_gdpr_pass": bool(
                encryption_at_rest
                and encryption_in_transit
                and audit_operational
                and chain.get("valid", False)
                and retention_days >= 30
                and dsar_enabled
            ),
            "encryption_at_rest": encryption_at_rest,
            "encryption_in_transit": encryption_in_transit,
            "audit_log_operational": audit_operational,
            "audit_entries": len(self._read_audit()),
            "audit_chain_valid": chain.get("valid", False),
            "audit_chain_details": chain,
            "retention_policy_days": retention_days,
            "dsar_workflow_enabled": dsar_enabled,
            "dpo_contact_configured": dpo_contact != "unset",
        }
