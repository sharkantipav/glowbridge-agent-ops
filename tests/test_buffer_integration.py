from app.integrations import buffer


def test_pick_channels_returns_matching_service_ids():
    channels = [
        {"id": "ig1", "service": "instagram", "isQueuePaused": False},
        {"id": "x1", "service": "twitter", "isQueuePaused": False},
        {"id": "tt1", "service": "tiktok", "isQueuePaused": False},
        {"id": "x2", "service": "twitter", "isQueuePaused": True},
    ]

    selected = buffer.pick_channel_ids(channels, services=["twitter", "x"])

    assert selected == ["x1"]


def test_create_post_mutation_uses_add_to_queue_mode():
    query, variables = buffer.create_post_mutation(
        channel_id="channel_123",
        text="Most pest control calls happen after hours.",
    )

    assert "createPost" in query
    assert variables == {
        "input": {
            "text": "Most pest control calls happen after hours.",
            "channelId": "channel_123",
            "schedulingType": "automatic",
            "mode": "addToQueue",
        }
    }
