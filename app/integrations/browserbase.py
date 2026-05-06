"""Browserbase render — JS-rendered HTML for sites that need it.

Browserbase provides hosted Chrome with a CDP endpoint. The simplest path is
their REST 'sessions' API + a /render endpoint, but this varies by SDK. To
avoid pinning to an SDK that may churn, we use Playwright over CDP against
a Browserbase session URL.

Optional dependency: install `playwright` and run `playwright install chromium`
on the host. If not available, this module raises and `fetch.fetch()` falls
back to the static fetch result.
"""
from __future__ import annotations

from app.config import get_settings


def render(url: str, wait_until: str = "networkidle", timeout_ms: int = 20_000) -> str:
    """Return the page's HTML after JS execution. Raises if not configured."""
    s = get_settings()
    if not s.browserbase_api_key or not s.browserbase_project_id:
        raise RuntimeError("Browserbase not configured")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError(
            "playwright not installed; pip install playwright && playwright install chromium"
        ) from e

    cdp_url = (
        f"wss://connect.browserbase.com?apiKey={s.browserbase_api_key}"
        f"&projectId={s.browserbase_project_id}"
    )

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_url)
        try:
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.new_page()
            page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            return page.content()
        finally:
            browser.close()
