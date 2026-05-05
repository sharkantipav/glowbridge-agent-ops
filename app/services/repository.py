from datetime import datetime, timezone
from typing import Any

from app.db.supabase_client import get_supabase


class Repository:
    def __init__(self):
        self.db = get_supabase()

    def log_event(self, agent: str, event_type: str, payload: dict[str, Any], status: str = "info") -> None:
        self.db.table("logs").insert(
            {
                "agent": agent,
                "event_type": event_type,
                "payload": payload,
                "status": status,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        ).execute()

    def insert_prospects(self, rows: list[dict[str, Any]]) -> None:
        if rows:
            self.db.table("prospects").upsert(rows, on_conflict="website").execute()

    def pending_approval(self, item_type: str, payload: dict[str, Any], reason: str) -> None:
        self.db.table("approval_queue").insert(
            {"item_type": item_type, "payload": payload, "reason": reason, "status": "pending"}
        ).execute()
