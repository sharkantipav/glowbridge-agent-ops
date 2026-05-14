from datetime import UTC, datetime, timedelta

from app import safety
from app.agents import followup


def test_followup_subject_detection():
    assert followup._is_followup_subject("Re: After-hours calls")
    assert not followup._is_followup_subject("After-hours calls")


def test_followup_body_stays_safe_and_has_test_call_cta():
    body = followup._followup_body("Smith Pest Control", "After-hours calls")

    assert "test call" in body.lower()
    assert "handles pricing conversations" in body
    assert "guarantee" not in body.lower()
    assert not safety.find_banned_phrases(body)


def test_parse_dt_handles_supabase_timestamp():
    ts = (datetime.now(UTC) - timedelta(days=3)).isoformat()

    assert followup._parse_dt(ts) is not None
