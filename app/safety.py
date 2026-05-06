"""Hard safety gates.

These are deterministic rules enforced AFTER the model produces output.
A model gone rogue cannot bypass them. Tests cover each rule.

The rules come straight from the business brief:
  - Never claim guaranteed revenue.
  - Never say AI quotes pest-control prices.
  - Never say AI guarantees bookings.
  - Never continue emailing someone who unsubscribes.
  - Never auto-reply to angry/legal/compliance messages.
  - Outreach auto-send: score>=8 AND clearly pest control AND email exists
                       AND no unsubscribe AND no banned phrase AND <100 words.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app import db

# ---------- Banned phrases / risky patterns ----------
# These are matched case-insensitively. Order doesn't matter; any one match fails the gate.
BANNED_PHRASE_PATTERNS: list[tuple[str, str]] = [
    # "guarantee[s|d] ... bookings/revenue/leads/jobs/customers/sales" — allow up to
    # ~30 non-terminal characters between the verb and the noun so phrases like
    # "guarantee 5 more bookings" or "guarantees 10 more bookings per week" still trip.
    (r"\bguarantee[ds]?\b[^.!?\n]{0,30}?\b(?:bookings?|revenue|leads?|jobs?|customers?|sales?|appointments?)\b",
        "guarantees outcomes"),
    (r"\bguaranteed\s+results?\b", "guarantees outcomes"),
    (r"\bAI\s+(?:quotes|prices|sets the price|pricing)\b", "claims AI quotes prices"),
    (r"\bquotes?\s+pest[-\s]control\s+prices?\b", "claims AI quotes prices"),
    (r"\b(?:guarantee|promise)s?\s+\$\d", "guarantees a dollar amount"),
    (r"\b(?:guarantee|promise)s?\s+(?:[\w\s]{0,20}?)?\$\d", "guarantees a dollar amount"),
    (r"\b(?:double|triple|10x|2x|3x)\s+your\s+(?:revenue|bookings|leads|customers)\b",
        "guarantees a revenue multiple"),
    (r"\bget\s+\d+\s+(?:more\s+)?(?:bookings?|jobs?|leads?|customers?)\s+(?:per|a|each|every)\s+(?:day|week|month|year)\b",
        "guarantees a booking volume"),
    (r"\b100%\s+(?:booked|conversion|capture|guaranteed)\b", "claims 100% outcomes"),
    (r"\bnever\s+miss(?:es|ed)?\s+a\s+(?:call|lead|job|booking|customer)\b",
        "claims absolute reliability ('never miss')"),
]
BANNED_RE = [(re.compile(p, re.IGNORECASE), label) for p, label in BANNED_PHRASE_PATTERNS]

# Customer-fabrication patterns — Social agent must never invent these.
FABRICATION_PATTERNS: list[tuple[str, str]] = [
    (r"\bone\s+of\s+our\s+customers?\b", "fabricated customer reference"),
    (r"\bcase\s+study\b", "claimed case study"),
    (r"\bclients?\s+(?:are\s+seeing|reported|saw)\b", "fabricated client result"),
    (r"\bour\s+\$\d+[KkMm]\s+MRR\b", "fabricated revenue claim"),
]
FABRICATION_RE = [(re.compile(p, re.IGNORECASE), label) for p, label in FABRICATION_PATTERNS]

# Reply intents that must escalate — never auto-reply.
ESCALATE_INTENTS: set[str] = {
    "interested",
    "wants_call",
    "angry",
    "unsubscribe",
    "objection",      # may be salvageable but needs a human eye
    "not_interested", # don't pester
    "unknown",        # can't tell -> safer to escalate
}
# The ONLY intents we can safely auto-reply to:
AUTOREPLY_OK_INTENTS: set[str] = {"asked_price", "asked_how_it_works"}
AUTOREPLY_MIN_CONFIDENCE = 0.85


@dataclass
class GateResult:
    passed: bool
    failures: list[str]

    def fail(self, reason: str) -> "GateResult":
        return GateResult(passed=False, failures=[*self.failures, reason])


def _word_count(text: str) -> int:
    return len([w for w in re.split(r"\s+", text.strip()) if w])


def find_banned_phrases(text: str) -> list[str]:
    """Return labels of every banned-phrase match in text. Empty list = clean."""
    hits: list[str] = []
    for rx, label in BANNED_RE:
        if rx.search(text):
            hits.append(label)
    return hits


def find_fabrications(text: str) -> list[str]:
    hits: list[str] = []
    for rx, label in FABRICATION_RE:
        if rx.search(text):
            hits.append(label)
    return hits


# ---------- Outreach send gate ----------

def outreach_send_gate(
    *,
    body: str,
    subject: str,
    to_email: str | None,
    score: int | None,
    is_pest_control: bool,
) -> GateResult:
    """The brief's hard rule: only auto-send if EVERY condition holds."""
    failures: list[str] = []

    if score is None or score < 8:
        failures.append(f"score_below_8 (got {score})")
    if not is_pest_control:
        failures.append("not_clearly_pest_control")
    if not to_email:
        failures.append("missing_email")
    elif db.is_unsubscribed(to_email):
        failures.append("unsubscribed")

    full = f"{subject}\n{body}"
    banned = find_banned_phrases(full)
    if banned:
        failures.append(f"banned_phrase: {', '.join(banned)}")

    wc = _word_count(body)
    # Brief: under 90 words preferred, hard limit 100.
    if wc >= 100:
        failures.append(f"over_word_limit ({wc})")

    fabs = find_fabrications(full)
    if fabs:
        failures.append(f"fabrication: {', '.join(fabs)}")

    return GateResult(passed=not failures, failures=failures)


# ---------- Reply auto-reply gate ----------

def reply_autoreply_gate(*, intent: str, confidence: float, body: str) -> GateResult:
    failures: list[str] = []
    if intent not in AUTOREPLY_OK_INTENTS:
        failures.append(f"intent_not_safe_for_autoreply ({intent})")
    if confidence < AUTOREPLY_MIN_CONFIDENCE:
        failures.append(f"confidence_below_threshold ({confidence:.2f})")

    # Even on the safe intents, if the body contains anger/legal markers, escalate.
    angry_markers = re.search(
        r"\b(lawsuit|attorney|sue|fraud|scam|complaint|reported you|FTC|CAN-?SPAM)\b",
        body,
        re.IGNORECASE,
    )
    if angry_markers:
        failures.append(f"legal_or_angry_marker: {angry_markers.group(0)}")

    return GateResult(passed=not failures, failures=failures)


# ---------- Social auto-post gate ----------

def social_autopost_gate(*, platform: str, content: str) -> GateResult:
    failures: list[str] = []
    if platform != "x":
        failures.append(f"platform_not_auto_eligible ({platform})")  # never Reddit/TikTok/Insta auto

    banned = find_banned_phrases(content)
    if banned:
        failures.append(f"banned_phrase: {', '.join(banned)}")

    fabs = find_fabrications(content)
    if fabs:
        failures.append(f"fabrication: {', '.join(fabs)}")

    return GateResult(passed=not failures, failures=failures)
