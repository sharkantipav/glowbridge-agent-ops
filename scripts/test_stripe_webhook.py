"""Fire a synthetic Stripe checkout.session.completed at the local backend.

Setup (one-time):
  1. Install Stripe CLI: https://stripe.com/docs/stripe-cli
  2. `stripe login` — links the CLI to your Stripe account.

Then, in two terminals:

  Terminal A (forward webhooks to your local backend):
    stripe listen --forward-to localhost:8000/webhooks/stripe
    # The CLI prints a webhook signing secret like `whsec_xxxxxxxx`.
    # Put THAT secret in your .env as STRIPE_WEBHOOK_SECRET while testing locally,
    # then revert to the production webhook secret for deploy.

  Terminal B (uvicorn):
    uvicorn app.main:app --port 8000

  Terminal C (fire the fake event):
    python -m scripts.test_stripe_webhook

You should see the Customer agent fire in the uvicorn logs and a new row appear
in the `customers` table + an entry in the approval queue.
"""
from __future__ import annotations

import shutil
import subprocess
import sys


def main() -> int:
    if not shutil.which("stripe"):
        print(
            "ERROR: Stripe CLI not found on PATH. Install from https://stripe.com/docs/stripe-cli",
            file=sys.stderr,
        )
        return 1

    cmd = [
        "stripe",
        "trigger",
        "checkout.session.completed",
        "--add",
        "checkout_session:metadata.company_name=Test Pest Control LLC",
        "--add",
        "checkout_session:customer_details.email=charles+test@glowbridge.ai",
        "--add",
        "checkout_session:customer_details.phone=+15555550199",
    ]
    print("Running:", " ".join(cmd))
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    sys.exit(main())
