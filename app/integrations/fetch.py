"""Page fetching — httpx for simple sites, Browserbase for JS-heavy ones.

For pest-control company websites in NJ/NY/PA/CT, the vast majority are
WordPress/Squarespace/Wix and render fully without JS. We try httpx first
and only fall back to Browserbase when the static HTML looks empty.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (compatible; GlowBridgeBot/1.0; +https://glowbridge.ai/bot)"
)


@dataclass
class FetchedPage:
    url: str
    status: int
    html: str
    text: str               # plain-text body, collapsed whitespace
    title: str | None
    rendered_via: str       # 'httpx' or 'browserbase'


def _to_text(html: str) -> tuple[str, str | None]:
    soup = BeautifulSoup(html, "html.parser")
    # Strip noise
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    title = soup.title.string.strip() if soup.title and soup.title.string else None
    body_text = " ".join(soup.get_text(separator=" ").split())
    return body_text, title


def fetch_static(url: str, timeout: float = 20) -> FetchedPage:
    """Plain GET. Suitable for ~95% of pest control sites."""
    with httpx.Client(
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
    ) as c:
        r = c.get(url)
    text, title = _to_text(r.text)
    return FetchedPage(
        url=str(r.url),
        status=r.status_code,
        html=r.text,
        text=text,
        title=title,
        rendered_via="httpx",
    )


def looks_empty(page: FetchedPage, min_chars: int = 400) -> bool:
    """If a static fetch returns very little text, the page is probably JS-rendered."""
    return len(page.text) < min_chars


def fetch(url: str) -> FetchedPage:
    """Try static first; fall back to Browserbase if it looks empty."""
    page = fetch_static(url)
    if not looks_empty(page):
        return page
    try:
        from app.integrations.browserbase import render

        rendered_html = render(url)
        text, title = _to_text(rendered_html)
        return FetchedPage(
            url=url,
            status=200,
            html=rendered_html,
            text=text,
            title=title,
            rendered_via="browserbase",
        )
    except Exception:
        # If Browserbase isn't configured, return the thin static result.
        return page
