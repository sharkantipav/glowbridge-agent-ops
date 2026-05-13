"""Tests for app/safety.py — the deterministic gates that protect us from a
model gone rogue. If any of these fail, the entire safety story collapses,
so they live separate from any model interaction.
"""
from __future__ import annotations

from unittest.mock import patch

from app import safety


# ---------- banned phrases ----------

def test_banned_phrases_catch_guarantees():
    cases = [
        "We guarantee 5 more bookings per week.",
        "Get guaranteed leads with our AI.",
        "Double your bookings in 30 days!",
        "Our AI quotes prices for your customers.",
        "100% booked, no exceptions.",
        "Never miss a call again.",
        "Triple your revenue this quarter.",
        "We promise $5,000 in new revenue.",
    ]
    for c in cases:
        hits = safety.find_banned_phrases(c)
        assert hits, f"expected banned phrase to fire on: {c!r}"


def test_clean_email_passes():
    body = (
        "Hi Mike — saw your site mentions same-day callbacks. "
        "We help small pest-control teams capture missed and after-hours calls "
        "with an AI receptionist. $199 setup, $99/mo, refund if you don't go live "
        "after a free test call. Want me to set up a quick demo?"
    )
    assert safety.find_banned_phrases(body) == []


def test_fabrications_catch_invented_customers():
    cases = [
        "One of our customers booked 30 jobs last week.",
        "Check out this case study with a Newark exterminator.",
        "Clients are seeing massive growth.",
        "Our $50K MRR proves it works.",
    ]
    for c in cases:
        hits = safety.find_fabrications(c)
        assert hits, f"expected fabrication to fire on: {c!r}"


# ---------- outreach send gate ----------

@patch("app.safety.db.is_unsubscribed", return_value=False)
def test_outreach_gate_passes_clean_email(_):
    body = (
        "Hi Mike — your site mentions emergency calls. We answer missed and "
        "after-hours calls with an AI receptionist. $199 setup, $99/mo, refund "
        "if you don't go live after a free test call. Want me to set up a demo?"
    )
    g = safety.outreach_send_gate(
        body=body, subject="Quick idea for X Pest Control",
        to_email="mike@xpest.com", score=9, is_pest_control=True,
    )
    assert g.passed, g.failures


@patch("app.safety.db.is_unsubscribed", return_value=False)
def test_outreach_gate_blocks_low_score(_):
    g = safety.outreach_send_gate(
        body="Hi.", subject="hi", to_email="x@y.com", score=6, is_pest_control=True,
    )
    assert not g.passed
    assert any("score_below_8" in f for f in g.failures)


@patch("app.safety.db.is_unsubscribed", return_value=False)
def test_outreach_gate_blocks_missing_email(_):
    g = safety.outreach_send_gate(
        body="Hi.", subject="hi", to_email=None, score=9, is_pest_control=True,
    )
    assert not g.passed
    assert "missing_email" in g.failures


@patch("app.safety.db.is_unsubscribed", return_value=False)
def test_outreach_gate_blocks_placeholder_email(_):
    g = safety.outreach_send_gate(
        body="Hi.",
        subject="hi",
        to_email="filler@godaddy.com",
        score=9,
        is_pest_control=True,
    )
    assert not g.passed
    assert "placeholder_email" in g.failures


@patch("app.safety.db.is_unsubscribed", return_value=False)
def test_outreach_gate_blocks_no_reply_email(_):
    g = safety.outreach_send_gate(
        body="Hi.",
        subject="hi",
        to_email="no-reply@company.com",
        score=9,
        is_pest_control=True,
    )
    assert not g.passed
    assert "no_reply_email" in g.failures


@patch("app.safety.db.is_unsubscribed", return_value=True)
def test_outreach_gate_blocks_unsubscribed(_):
    g = safety.outreach_send_gate(
        body="Hi.", subject="hi", to_email="x@y.com", score=9, is_pest_control=True,
    )
    assert not g.passed
    assert "unsubscribed" in g.failures


@patch("app.safety.db.is_unsubscribed", return_value=False)
def test_outreach_gate_blocks_banned_phrase(_):
    body = "We guarantee 10 more bookings per week. Reply yes."
    g = safety.outreach_send_gate(
        body=body, subject="Guaranteed bookings", to_email="x@y.com", score=10, is_pest_control=True,
    )
    assert not g.passed
    assert any(f.startswith("banned_phrase") for f in g.failures)


@patch("app.safety.db.is_unsubscribed", return_value=False)
def test_outreach_gate_blocks_over_word_limit(_):
    body = " ".join(["word"] * 105)  # 105 words
    g = safety.outreach_send_gate(
        body=body, subject="hi", to_email="x@y.com", score=9, is_pest_control=True,
    )
    assert not g.passed
    assert any("over_word_limit" in f for f in g.failures)


@patch("app.safety.db.is_unsubscribed", return_value=False)
def test_outreach_gate_blocks_not_pest_control(_):
    g = safety.outreach_send_gate(
        body="Hi.", subject="hi", to_email="x@y.com", score=9, is_pest_control=False,
    )
    assert not g.passed
    assert "not_clearly_pest_control" in g.failures


# ---------- reply autoreply gate ----------

def test_reply_gate_allows_simple_price_question():
    g = safety.reply_autoreply_gate(
        intent="asked_price", confidence=0.95, body="How much does it cost?"
    )
    assert g.passed, g.failures


def test_reply_gate_allows_simple_how_it_works():
    g = safety.reply_autoreply_gate(
        intent="asked_how_it_works", confidence=0.9, body="How does this work?"
    )
    assert g.passed, g.failures


def test_reply_gate_blocks_low_confidence():
    g = safety.reply_autoreply_gate(
        intent="asked_price", confidence=0.5, body="how much?"
    )
    assert not g.passed
    assert any("confidence_below_threshold" in f for f in g.failures)


def test_reply_gate_blocks_angry_intent():
    g = safety.reply_autoreply_gate(
        intent="angry", confidence=0.99, body="this is spam"
    )
    assert not g.passed


def test_reply_gate_blocks_legal_marker_even_in_safe_intent():
    g = safety.reply_autoreply_gate(
        intent="asked_price", confidence=0.95,
        body="How much? Also I'm reporting you to the FTC for CAN-SPAM violations.",
    )
    assert not g.passed
    assert any("legal_or_angry_marker" in f for f in g.failures)


def test_reply_gate_blocks_interested_intent():
    """Interested replies must escalate, never auto-reply."""
    g = safety.reply_autoreply_gate(
        intent="interested", confidence=0.99, body="Yes, sign me up!"
    )
    assert not g.passed


# ---------- social autopost gate ----------

def test_social_gate_blocks_reddit():
    g = safety.social_autopost_gate(platform="reddit", content="Anyone tried AI receptionists?")
    assert not g.passed
    assert any("platform_not_auto_eligible" in f for f in g.failures)


def test_social_gate_blocks_tiktok():
    g = safety.social_autopost_gate(platform="tiktok", content="some script")
    assert not g.passed


def test_social_gate_allows_clean_x_post():
    g = safety.social_autopost_gate(
        platform="x",
        content="Most missed calls happen between 6pm and 8am. Knowing this is half the fix.",
    )
    assert g.passed, g.failures


def test_social_gate_blocks_x_with_banned_phrase():
    g = safety.social_autopost_gate(
        platform="x",
        content="GlowBridge guarantees 10 more bookings per week. DM us.",
    )
    assert not g.passed
    assert any(f.startswith("banned_phrase") for f in g.failures)


def test_social_gate_blocks_x_with_fabrication():
    g = safety.social_autopost_gate(
        platform="x",
        content="One of our customers tripled their revenue. Wild.",
    )
    assert not g.passed
    assert any(f.startswith("fabrication") for f in g.failures) \
        or any(f.startswith("banned_phrase") for f in g.failures)
