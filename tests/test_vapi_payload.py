from app.integrations import vapi


def test_assistant_payload_uses_accent_friendly_transcriber_and_turn_taking():
    call_flow = {
        "greeting": "Thanks for calling Test Pest.",
        "questions": ["What is your name?", "What pest issue are you seeing?"],
        "boundaries": ["Never quote prices."],
        "after_hours_note": "We are closed but can take a message.",
    }

    payload = vapi.build_assistant_payload(
        company_name="Test Pest",
        call_flow=call_flow,
        server_url="https://example.com/webhooks/vapi",
    )

    assert payload["transcriber"] == {
        "provider": "deepgram",
        "model": "flux-general-en",
        "language": "en",
        "eotThreshold": 0.7,
        "eotTimeoutMs": 5000,
    }
    assert payload["startSpeakingPlan"] == {"waitSeconds": 0.45}
    assert payload["stopSpeakingPlan"] == {
        "numWords": 1,
        "voiceSeconds": 0.25,
        "backoffSeconds": 0.8,
        "acknowledgementPhrases": ["okay", "ok", "yeah", "yes", "uh-huh", "mm-hmm"],
    }
    assert payload["backgroundSound"] == "office"
    assert payload["voice"]["voiceId"] == "paige"


def test_call_quality_patch_reuses_production_payload_knobs_without_prompt_overwrite():
    patch = vapi.build_call_quality_patch()

    assert set(patch) == {
        "transcriber",
        "startSpeakingPlan",
        "stopSpeakingPlan",
        "backgroundSound",
        "voice",
    }
    assert patch["transcriber"]["provider"] == "deepgram"
    assert patch["transcriber"]["model"] == "flux-general-en"
    assert patch["voice"] == {"provider": "11labs", "voiceId": "paige"}
