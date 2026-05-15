from app.agents import digest


def test_digest_body_summarizes_metrics_and_recent_replies():
    body = digest._format_digest(
        {
            "prospects_added": 80,
            "researched": 75,
            "sent": 15,
            "bounced": 1,
            "replies": 2,
            "hot_replies": 1,
            "pending_approvals": 3,
        },
        [
            {
                "intent": "wants_call",
                "confidence": 0.91,
                "from_email": "owner@examplepest.com",
                "subject": "Re: after-hours calls",
            }
        ],
        "https://example.com/admin",
    )

    assert "Prospects added today: 80" in body
    assert "First-touch/follow-up emails sent today: 15" in body
    assert "Interested / wants call today: 1" in body
    assert "wants_call (0.91) from owner@examplepest.com" in body
    assert "https://example.com/admin" in body


def test_digest_body_shows_no_recent_replies_when_filtered_empty():
    body = digest._format_digest(
        {
            "prospects_added": 25,
            "researched": 25,
            "sent": 9,
            "bounced": 1,
            "replies": 0,
            "hot_replies": 0,
            "pending_approvals": 58,
        },
        [],
        "https://example.com/admin",
    )

    assert "Replies received today: 0" in body
    assert "Recent replies:\n- None yet." in body


def test_hot_replies_count_only_known_prospect_replies():
    rows = [
        {"from_email": "owner@examplepest.com", "intent": "wants_call"},
        {"from_email": "mailer-daemon@googlemail.com", "intent": "unknown"},
        {"from_email": "search-api@brave.com", "intent": "unknown"},
    ]
    prospect_rows = [r for r in rows if r["from_email"] == "owner@examplepest.com"]

    assert len(prospect_rows) == 1
    assert sum(1 for r in prospect_rows if r.get("intent") in {"interested", "wants_call"}) == 1
