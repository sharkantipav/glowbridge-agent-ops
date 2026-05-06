"""One-time Gmail OAuth bootstrap.

Run once to authorize the agent ops backend to send and read your Gmail:

    python -m scripts.gmail_oauth

This opens a browser, you grant access, and a `gmail_token.json` is written
to the project root (gitignored). The backend reads/refreshes that token.

You need GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET in .env first. Create them in
Google Cloud Console > Credentials > OAuth client ID > Desktop App.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

from app.config import get_settings
from app.integrations.gmail import SCOPES, TOKEN_PATH


def main() -> int:
    s = get_settings()
    if not s.gmail_client_id or not s.gmail_client_secret:
        print("ERROR: set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET in .env first.", file=sys.stderr)
        return 1

    client_config = {
        "installed": {
            "client_id": s.gmail_client_id,
            "client_secret": s.gmail_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0)
    Path(TOKEN_PATH).write_text(creds.to_json())
    print(f"Wrote {TOKEN_PATH}. Token will refresh automatically.")
    print(f"Authorized scopes: {SCOPES}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
