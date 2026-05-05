import stripe

from app.core.config import settings

stripe.api_key = settings.stripe_secret_key


def parse_event(payload: bytes, sig_header: str):
    return stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)
