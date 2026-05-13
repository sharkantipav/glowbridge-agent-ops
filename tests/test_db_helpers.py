from app.db import _unresearched_prospects


def test_unresearched_prospects_excludes_existing_research_and_limits():
    candidates = [
        {"id": "p1", "company_name": "Already Researched"},
        {"id": "p2", "company_name": "Ready One"},
        {"id": "p3", "company_name": "Ready Two"},
    ]

    assert _unresearched_prospects(candidates, {"p1"}, 1) == [
        {"id": "p2", "company_name": "Ready One"}
    ]
