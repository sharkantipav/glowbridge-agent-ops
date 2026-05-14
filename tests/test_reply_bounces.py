from app.agents import reply


def test_detects_mailer_daemon_bounce():
    msg = {
        "from_raw": "Mail Delivery Subsystem <mailer-daemon@googlemail.com>",
        "subject": "Delivery Status Notification (Failure)",
        "body": "Address not found.",
    }

    assert reply._looks_like_bounce(msg)


def test_extracts_final_recipient_from_bounce_body():
    msg = {
        "body": """
        Delivery has failed.
        Final-Recipient: rfc822; info@examplepest.com
        Action: failed
        """,
    }

    assert reply._extract_bounced_email(msg) == "info@examplepest.com"


def test_non_delivery_question_is_not_bounce():
    msg = {
        "from_raw": "Owner <owner@examplepest.com>",
        "subject": "Question about delivery area",
        "body": "Do you work in our delivery area?",
    }

    assert not reply._looks_like_bounce(msg)
