"""Web search — Brave Search API by default, Tavily fallback.

Both are free for ~2k queries/month, more than enough for 25 prospects/day.
"""
from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings


def search(query: str, count: int = 10) -> list[dict[str, Any]]:
    """Return list of {title, url, description} dicts."""
    s = get_settings()
    if s.brave_api_key:
        return _brave(query, count, s.brave_api_key)
    if s.tavily_api_key:
        return _tavily(query, count, s.tavily_api_key)
    raise RuntimeError("No search provider configured. Set BRAVE_API_KEY or TAVILY_API_KEY.")


def _brave(query: str, count: int, api_key: str) -> list[dict[str, Any]]:
    r = httpx.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": count, "country": "US", "safesearch": "moderate"},
        headers={"Accept": "application/json", "X-Subscription-Token": api_key},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    results = data.get("web", {}).get("results", []) or []
    return [
        {"title": x.get("title"), "url": x.get("url"), "description": x.get("description")}
        for x in results
    ]


def _tavily(query: str, count: int, api_key: str) -> list[dict[str, Any]]:
    r = httpx.post(
        "https://api.tavily.com/search",
        json={
            "api_key": api_key,
            "query": query,
            "max_results": count,
            "search_depth": "basic",
            "include_answer": False,
        },
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    return [
        {"title": x.get("title"), "url": x.get("url"), "description": x.get("content")}
        for x in data.get("results", []) or []
    ]
