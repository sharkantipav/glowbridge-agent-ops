from app.routers.public import SiteLeadIn, _lead_payload, _notification_body


def test_site_lead_payload_normalizes_contact_fields():
    lead = SiteLeadIn(
        source="pilot_setup",
        name=" Charles ",
        business_name=" Glow Pest ",
        phone=" (201) 555-1212 ",
        email="OWNER@GLOWPEST.COM",
        industry="Pest Control",
    )

    payload = _lead_payload(lead)

    assert payload["name"] == "Charles"
    assert payload["business_name"] == "Glow Pest"
    assert payload["email"] == "owner@glowpest.com"


def test_notification_body_contains_lead_details():
    body = _notification_body(
        {
            "source": "demo_call",
            "name": "Charles",
            "business_name": "Glow Pest",
            "phone": "2015551212",
            "email": "owner@glowpest.com",
            "industry": "Pest Control",
            "website": "https://glowpest.com",
            "avg_job_value": "$350",
            "missed_calls_per_week": "5",
            "notes": "Wants test call",
        }
    )

    assert "New GlowBridge website lead" in body
    assert "Glow Pest" in body
    assert "Wants test call" in body
