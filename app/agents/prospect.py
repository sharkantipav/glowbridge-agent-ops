"""Prospect agent — find pest control companies in NJ/NY/PA/CT.

Strategy:
  1. For each of NJ/NY/PA/CT, run several targeted web searches.
  2. Dedupe by domain.
  3. For each candidate, fetch the homepage (best-effort).
  4. Ask Claude (Haiku — cheap, fine for structured extraction) to:
     - confirm it's a pest-control company,
     - extract company name, city, state, phone, email, owner/contact,
     - score the lead 1-10 based on signals like emergency-service language,
       no online booking, voicemail-heavy copy, etc.
  5. Upsert into `prospects`.

Output target: `target` new rows (default 25), best-effort.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

import tldextract

from app import db, llm
from app.agents.base import run_context
from app.integrations import fetch, search

# Searches we rotate through. Each state runs all of them; we dedupe by domain.
QUERIES = [
    "pest control {state} after hours",
    "pest control company {city} {state}",
    "exterminator {state} 24/7",
    "emergency pest control {state}",
    "termite control {state}",
    "rodent control {state}",
]

# A handful of seed cities per state to widen geographic spread.
SEED_CITIES: dict[str, list[str]] = {
    "NJ": ["Newark", "Jersey City", "Trenton", "Cherry Hill", "Edison", "Toms River"],
    "NY": ["New York", "Buffalo", "Rochester", "Syracuse", "Albany", "Yonkers"],
    "PA": ["Philadelphia", "Pittsburgh", "Allentown", "Erie", "Reading", "Scranton"],
    "CT": ["Bridgeport", "New Haven", "Hartford", "Stamford", "Waterbury"],
}

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\(?\b\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}\b")

# Domains we explicitly skip: directories, big franchises, social media, generic.
SKIP_DOMAIN_FRAGMENTS = {
    "yelp.com", "yellowpages.com", "bbb.org", "facebook.com", "instagram.com",
    "linkedin.com", "twitter.com", "x.com", "thumbtack.com", "homeadvisor.com",
    "angi.com", "angieslist.com", "google.com", "youtube.com", "tiktok.com",
    "reddit.com", "wikipedia.org", "indeed.com",
    # National franchises (we want local indies):
    "orkin.com", "terminix.com", "rollins.com", "ehrlich.com", "trulynolen.com",
    "westernpestservices.com",
}


def _root_domain(url: str) -> str | None:
    try:
        ext = tldextract.extract(url)
        if not ext.domain or not ext.suffix:
            return None
        return f"{ext.domain}.{ext.suffix}".lower()
    except Exception:
        return None


def _is_skip_domain(domain: str) -> bool:
    return any(frag in domain for frag in SKIP_DOMAIN_FRAGMENTS)


def _normalize_url(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme or 'https'}://{p.netloc or p.path}".rstrip("/")


SCORE_AND_EXTRACT_SYSTEM = """\
You are an analyst evaluating pest control company websites.

Given a homepage's text content and URL, you must:
1. Decide if it is a pest control / exterminator company (not a directory, blog, franchise corp page).
2. Extract: company_name, city, state, phone, email, contact_name (owner/founder if named), contact_role.
3. Score the lead 1-10 for likelihood that they would benefit from an AI receptionist that captures missed calls.
   Higher score = stronger signals like:
     - emergency / 24/7 / after-hours language (they get calls outside business hours)
     - "call now", "call us today", phone-only CTA (no online booking form)
     - voicemail mentions ("leave a message", "we'll call back")
     - small/independent (not a national franchise)
     - bad-review hints in copy (rebuttal language, "we always answer")
   Lower score = strong signals AGAINST:
     - online booking widget visible
     - chat/SMS already advertised
     - clearly part of a national franchise
     - not actually pest control (lawn care, general contractor, etc.)

Reply ONLY with JSON of shape:
{
  "is_pest_control": bool,
  "company_name": string|null,
  "city": string|null,
  "state": "NJ"|"NY"|"PA"|"CT"|null,
  "phone": string|null,
  "email": string|null,
  "contact_name": string|null,
  "contact_role": string|null,
  "score": int (1-10),
  "score_rationale": string (one sentence)
}
"""


def _candidates_for_state(state: str, per_state: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for city in SEED_CITIES[state]:
        if len(out) >= per_state * 3:  # collect a buffer; we'll filter later
            break
        for q_tmpl in QUERIES:
            q = q_tmpl.format(state=state, city=city)
            try:
                results = search.search(q, count=8)
            except Exception:
                continue
            for r in results:
                url = r.get("url") or ""
                domain = _root_domain(url)
                if not domain or domain in seen or _is_skip_domain(domain):
                    continue
                seen.add(domain)
                out.append({"url": _normalize_url(url), "domain": domain, "state": state, "city": city})
    return out


def _enrich_one(candidate: dict[str, str]) -> dict | None:
    """Fetch homepage, ask LLM to score+extract. Return prospect-row dict or None."""
    try:
        page = fetch.fetch(candidate["url"])
    except Exception:
        return None
    if not page.text or page.status >= 400:
        return None

    # Pull contact hints from raw text first, give them to the model as priors.
    emails = list(dict.fromkeys(EMAIL_RE.findall(page.text)))
    phones = list(dict.fromkeys(PHONE_RE.findall(page.text)))

    user = (
        f"URL: {page.url}\n"
        f"Title: {page.title}\n"
        f"State (from search): {candidate['state']}\n"
        f"Seed city (from search): {candidate['city']}\n"
        f"Emails detected: {emails[:5]}\n"
        f"Phones detected: {phones[:5]}\n"
        f"Page text (truncated):\n{page.text[:6000]}"
    )
    try:
        result = llm.json_call(
            system=SCORE_AND_EXTRACT_SYSTEM,
            user=user,
            tier="fast",
            temperature=0.1,
            max_tokens=600,
        )
    except Exception:
        return None

    if not result.get("is_pest_control"):
        return None
    score = result.get("score")
    if not isinstance(score, int) or not (1 <= score <= 10):
        return None

    state = result.get("state") or candidate["state"]
    if state not in {"NJ", "NY", "PA", "CT"}:
        return None

    # Prefer model's extraction but fall back to regex hits.
    email = (result.get("email") or (emails[0] if emails else None))
    if email:
        email = email.lower()
    phone = result.get("phone") or (phones[0] if phones else None)

    return {
        "company_name": result.get("company_name") or candidate["domain"],
        "website": _normalize_url(page.url),
        "city": result.get("city"),
        "state": state,
        "phone": phone,
        "email": email,
        "contact_name": result.get("contact_name"),
        "contact_role": result.get("contact_role"),
        "score": score,
        "source": "web_search",
        "raw_search_blob": {
            "candidate": candidate,
            "title": page.title,
            "score_rationale": result.get("score_rationale"),
            "rendered_via": page.rendered_via,
        },
    }


def run(target: int = 25) -> dict:
    """Find up to `target` new prospects and upsert into the prospects table."""
    with run_context("prospect", {"target": target}) as run:
        per_state = max(target // 4 + 2, 8)
        candidates: list[dict[str, str]] = []
        for state in ("NJ", "NY", "PA", "CT"):
            cands = _candidates_for_state(state, per_state)
            run.info("candidates_collected", state=state, count=len(cands))
            candidates.extend(cands)

        # Dedupe across states by domain
        seen: set[str] = set()
        unique: list[dict[str, str]] = []
        for c in candidates:
            if c["domain"] in seen:
                continue
            seen.add(c["domain"])
            # Drop ones already in DB
            if db.find_prospect_by_website(c["url"]):
                continue
            unique.append(c)

        run.info("unique_candidates", count=len(unique))

        added = 0
        skipped = 0
        for c in unique:
            if added >= target:
                break
            row = _enrich_one(c)
            if not row:
                skipped += 1
                continue
            try:
                db.insert("prospects", row)
                added += 1
                run.info("prospect_added", website=row["website"], score=row["score"])
            except Exception as e:  # likely unique-website conflict
                run.warn("prospect_insert_failed", website=row.get("website"), error=str(e))
                skipped += 1

        run.output = {"added": added, "skipped": skipped, "candidates_seen": len(unique)}
        return run.output
