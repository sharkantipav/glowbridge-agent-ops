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
