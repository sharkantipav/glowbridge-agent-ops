"""Research agent — visit each prospect's website and extract pain signals.

Reads from `prospects` where there is no corresponding `research` row.
For each, fetches the homepage (re-using fetch.fetch with Browserbase fallback),
asks Sonnet to surface specific signals from the brief:
  - advertises emergency / after-hours service
  - call-only booking (no online form)
  - voicemail-heavy copy
  - bad-review echoes ("we always answer", apology language)
Then writes a one-sentence pain_signal to `research`.
"""
from __future__ import annotations

from app import db, llm
from app.agents.base import run_context
from app.integrations import fetch

RESEARCH_SYSTEM = """\
You analyze pest control company websites for signals that the business is losing
calls outside business hours or has poor call-handling.

Look at the page text for explicit and implicit signals:
- "emergency" / "24/7" / "after hours" / "same day" language
- "call now" / phone-as-only-CTA (no booking form)
- voicemail mentions: "leave a message", "we'll call you back", "after the tone"
- review-rebuttal phrasing in the copy: "we always answer", "we never miss a call",
  "unlike other companies that don't return calls" — these often come from REAL bad reviews
  the owner is trying to counter.

Reply ONLY with JSON:
{
  "advertises_emergency": bool,
  "advertises_after_hours": bool,
  "has_booking_form": bool,
  "voicemail_heavy": bool,
  "review_excerpt": string|null (a quoted snippet from the page that's most telling, max 200 chars),
  "pain_signal": string (ONE sentence describing the most actionable pain point for this lead),
  "confidence": number between 0 and 1
}

Be honest. If the site is well-designed with a working booking widget, say so — score-wise
that's a weaker lead, but we still record the truth.
"""


def _research_one(prospect: dict) -> dict | None:
    website = prospect.get("website")
    if not website:
        return None
    try:
        page = fetch.fetch(website)
    except Exception:
        return None
    if not page.text or page.status >= 400:
        return None

    user = (
        f"Company: {prospect.get('company_name')}\n"
        f"URL: {page.url}\n"
        f"Page text (truncated):\n{page.text[:8000]}"
    )
    try:
        result = llm.json_call(
            system=RESEARCH_SYSTEM,
            user=user,
            tier="smart",
            temperature=0.2,
            max_tokens=700,
        )
    except Exception:
        return None

    return {
        "prospect_id": prospect["id"],
        "advertises_emergency": bool(result.get("advertises_emergency")),
        "advertises_after_hours": bool(result.get("advertises_after_hours")),
        "has_booking_form": bool(result.get("has_booking_form")),
        "voicemail_heavy": bool(result.get("voicemail_heavy")),
        "review_excerpt": result.get("review_excerpt"),
        "pain_signal": result.get("pain_signal") or "",
        "confidence": float(result.get("confidence") or 0.5),
        "page_html_excerpt": page.html[:4000],
    }


def run(limit: int = 50) -> dict:
    with run_context("research", {"limit": limit}) as run:
        targets = db.pending_research_prospects(limit=limit)
        run.info("research_targets", count=len(targets))

        added = 0
        failed = 0
        for p in targets:
            row = _research_one(p)
            if not row:
                failed += 1
                continue
            try:
                db.insert("research", row)
                added += 1
                run.info(
                    "research_added",
                    prospect_id=p["id"],
                    pain_signal=row["pain_signal"],
                )
            except Exception as e:
                run.warn("research_insert_failed", prospect_id=p["id"], error=str(e))
                failed += 1

        run.output = {"researched": added, "failed": failed}
        return run.output
