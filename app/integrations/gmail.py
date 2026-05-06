"""Gmail integration — send + list replies via Google's Python client.

OAuth flow is run once via `scripts/gmail_oauth.py` (see below) which writes
gmail_token.json. The backend reads/refreshes that token; the client_id and
client_secret come from env.
"""
from __future__ import annotations

import base64
import json
import os
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.config import get_settings

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]

TOKEN_PATH = Path(os.environ.get("GMAIL_TOKEN_PATH", "gmail_token.json"))


def _credentials() -> Credentials:
    if not TOKEN_PATH.exists():
        raise RuntimeError(
            f"Gmail token not found at {TOKEN_PATH}. Run `python -m scripts.gmail_oauth` once."
        )
    s = get_settings()
    data = json.loads(TOKEN_PATH.read_text())
    creds = Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=s.gmail_client_id,
        client_secret=s.gmail_client_secret,
        scopes=SCOPES,
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json())
    return creds


def _service():
    return build("gmail", "v1", credentials=_credentials(), cache_discovery=False)


def send_email(*, to: str, subject: str, body: str, reply_to_message_id: str | None = None) -> str:
    """Send a plain-text email. Returns the Gmail message id."""
    s = get_settings()
    msg = EmailMessage()
    msg["To"] = to
    msg["From"] = f"{s.gmail_from_name} <{s.gmail_from_address}>"
    msg["Subject"] = subject
    msg.set_content(body)

    payload: dict[str, Any] = {
        "raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()
    }
    if reply_to_message_id:
        payload["threadId"] = reply_to_message_id

    sent = _service().users().messages().send(userId="me", body=payload).execute()
    return sent.get("id", "")


def list_recent_replies(query: str = "in:inbox newer_than:2d", max_results: int = 50) -> list[dict[str, Any]]:
    """List Gmail messages matching the query. Returns a list of dicts with from/subject/body."""
    svc = _service()
    resp = svc.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    out = []
    for ref in resp.get("messages", []) or []:
        msg = svc.users().messages().get(userId="me", id=ref["id"], format="full").execute()
        out.append(_parse_message(msg))
    return out


def _parse_message(msg: dict[str, Any]) -> dict[str, Any]:
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    body = _extract_body(msg.get("payload", {}))
    return {
        "id": msg.get("id"),
        "thread_id": msg.get("threadId"),
        "from_email": _email_only(headers.get("from", "")),
        "from_raw": headers.get("from"),
        "subject": headers.get("subject"),
        "date": headers.get("date"),
        "body": body,
        "snippet": msg.get("snippet"),
    }


def _email_only(raw_from: str) -> str:
    if "<" in raw_from and ">" in raw_from:
        return raw_from.split("<", 1)[1].split(">", 1)[0].strip().lower()
    return raw_from.strip().lower()


def _extract_body(payload: dict[str, Any]) -> str:
    """Walk the MIME tree and return the first text/plain (or text/html) body decoded."""
    if payload.get("mimeType", "").startswith("text/") and payload.get("body", {}).get("data"):
        return _decode(payload["body"]["data"])
    for part in payload.get("parts", []) or []:
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return _decode(part["body"]["data"])
    for part in payload.get("parts", []) or []:
        if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
            return _decode(part["body"]["data"])
    # Recurse into multipart
    for part in payload.get("parts", []) or []:
        b = _extract_body(part)
        if b:
            return b
    return ""


def _decode(data: str) -> str:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad).decode("utf-8", errors="replace")
