from app.agents import outreach


def test_send_budget_allows_remaining_daily_capacity():
    budget = outreach._send_budget(max_daily=10, sent_today=3)

    assert budget.enabled
    assert budget.remaining == 7


def test_send_budget_blocks_when_daily_capacity_used():
    budget = outreach._send_budget(max_daily=10, sent_today=10)

    assert not budget.enabled
    assert budget.remaining == 0
    assert budget.reason == "daily_outreach_cap_reached (10/10)"


def test_send_budget_zero_or_negative_disables_sending():
    budget = outreach._send_budget(max_daily=0, sent_today=0)

    assert not budget.enabled
    assert budget.remaining == 0
    assert budget.reason == "daily_outreach_cap_disabled"


def test_placeholder_email_failures_are_hard_blocks():
    assert outreach._is_hard_block(["placeholder_email"])
