from app.db import _has_existing_outreach, _unresearched_prospects
from app.agents.prospect import _contact_urls_for, _usable_emails


def test_unresearched_prospects_excludes_existing_research_and_limits():
    candidates = [
        {"id": "p1", "company_name": "Already Researched"},
        {"id": "p2", "company_name": "Ready One"},
        {"id": "p3", "company_name": "Ready Two"},
    ]

    assert _unresearched_prospects(candidates, {"p1"}, 1) == [
        {"id": "p2", "company_name": "Ready One"}
    ]


def test_existing_outreach_blocks_reprocessing_for_any_status():
    assert _has_existing_outreach([{"status": "blocked"}])
    assert _has_existing_outreach([{"status": "bounced"}])
    assert _has_existing_outreach([{"status": "queued"}])
    assert not _has_existing_outreach([])


def test_contact_urls_for_root_domain():
    assert _contact_urls_for("https://example.com/some/page")[0] == "https://example.com/contact"


def test_usable_emails_filters_placeholders_and_dedupes():
    assert _usable_emails(["INFO@PestCo.com", "info@pestco.com", "filler@godaddy.com"]) == [
        "info@pestco.com"
    ]
