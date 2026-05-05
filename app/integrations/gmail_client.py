from typing import Any


class GmailClient:
    def send_email(self, to_email: str, subject: str, body: str) -> dict[str, Any]:
        # TODO: wire Google Gmail API send call.
        return {"to": to_email, "subject": subject, "body": body, "status": "queued"}

    def fetch_replies(self) -> list[dict[str, Any]]:
        # TODO: wire Gmail threads polling.
        return []
