"""Bearer-token auth for admin endpoints.

Accepts the token in any of:
  1. `Authorization: Bearer <token>` header (preferred — used by curl, the dashboard JS, CI).
  2. `?token=<token>` query string (fallback — lets you paste an admin URL into a browser).
  3. `glowbridge_admin_token` cookie (set by the dashboard on first visit so refreshes work).
"""
from __future__ import annotations

from fastapi import Cookie, Header, HTTPException, Query, status

from app.config import get_settings


def require_admin(
    authorization: str = Header(None),
    token: str | None = Query(None, description="Admin token (fallback for browser GETs)"),
    glowbridge_admin_token: str | None = Cookie(None),
) -> None:
    s = get_settings()
    presented: str | None = None
    if authorization and authorization.startswith("Bearer "):
        presented = authorization.removeprefix("Bearer ").strip()
    elif token:
        presented = token.strip()
    elif glowbridge_admin_token:
        presented = glowbridge_admin_token.strip()

    if not presented:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token (or ?token=...)",
        )
    if presented != s.admin_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid token")
