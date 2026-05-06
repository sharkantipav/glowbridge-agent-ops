"""Bearer-token auth for admin endpoints."""
from __future__ import annotations

from fastapi import Header, HTTPException, status

from app.config import get_settings


def require_admin(authorization: str = Header(None)) -> None:
    s = get_settings()
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if token != s.admin_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid token")
