# GlowBridge Agent Ops — Go Live Runbook

A checklist with copy-pasteable values. Work top to bottom.

---

## 0. Pre-filled config

Your decisions, locked in:

| Setting | Value |
|---|---|
| From address | `cb@glowbridge.ai` |
| From name | `Charles at GlowBridge` |
| Operator inbox (escalations) | `chbensoussan@gmail.com` |
| Search provider | Brave |
| Stripe mode | Live |
| Stripe shape | Payment Link |
| Browserbase | enabled |
| Timezone | `America/New_York` |
| App env | `production` |

---

## 1. Supabase — apply schema

1. Go to your Supabase project → **SQL editor** → **New query**.
2. Open `supabase/schema.sql` from this repo, paste the whole thing, **Run**.
3. Confirm 11 tables exist under **Table editor**.
4. Project Settings → **API** — copy:
   - `Project URL` → `SUPABASE_URL`
   - `service_role` key (NOT the anon key) → `SUPABASE_SERVICE_ROLE_KEY`

> ⚠️ The `service_role` key bypasses RLS. Only the backend gets this. Never expose it client-side.

---

## 2. Anthropic — copy your key

console.anthropic.com → **API Keys** → copy → `ANTHROPIC_API_KEY`.

---

## 3. Brave Search — copy your key

api.search.brave.com → **API keys** → copy → `BRAVE_API_KEY`.

The free tier is 2,000 queries/month. Prospect runs use ~24 queries/day (6 query templates × 4 states, with seed-city expansion as needed). You'll be at ~720/month — well under the limit.

---

## 4. Google Cloud OAuth client (for Gmail send + read)

You have Google Workspace, but the Cloud project is a separate thing. Five-minute setup:

1. Go to https://console.cloud.google.com/ and sign in with `cb@glowbridge.ai`.
2. **Create a new project** → name it `glowbridge-agent-ops`.
3. Top search: **Gmail API** → **Enable**.
4. Left nav → **APIs & Services** → **OAuth consent screen**:
   - User type: **Internal** (since you're on Workspace, this is the easy path — keeps it scoped to your workspace, no public verification needed)
   - App name: `GlowBridge Agent Ops`
   - User support email: `cb@glowbridge.ai`
   - Developer contact email: `cb@glowbridge.ai`
   - Scopes: skip (we request scopes at runtime)
   - Save & continue.
5. Left nav → **Credentials** → **+ Create credentials** → **OAuth client ID**:
   - Application type: **Desktop app**
   - Name: `glowbridge-agent-ops-desktop`
   - **Create** → a dialog shows `Client ID` and `Client secret` — copy both:
     - `GMAIL_CLIENT_ID` = the long `...apps.googleusercontent.com` string
     - `GMAIL_CLIENT_SECRET` = the shorter `GOCSPX-...` string

> Note: "Desktop app" type is correct here even though we're running a server. The token flow runs once locally on your machine via `python -m scripts.gmail_oauth`, then the refresh token persists.

After step 8 below you'll run `python -m scripts.gmail_oauth` once, sign in as `cb@glowbridge.ai`, and a `gmail_token.json` will be written to the repo (gitignored).

---

## 5. Browserbase

1. Sign up at https://www.browserbase.com/ (free tier).
2. Project dashboard → **API keys** → copy:
   - `BROWSERBASE_API_KEY`
   - `BROWSERBASE_PROJECT_ID`
3. Free tier sessions are plenty for ~5% of pest-control sites that need JS rendering.

---

## 6. Stripe — webhook + price ID

You said you have a Payment Link working on the site. Two things to extract:

### A. Find the `price_id` for the $199 setup product

1. Stripe Dashboard → **Products** → click the $199 setup product.
2. Pricing section shows the **Price ID** (`price_xxxxxxxxxxxx`). Copy → `STRIPE_PRICE_SETUP`.
3. If you also have a $99/month subscription product, do the same → `STRIPE_PRICE_MONTHLY`. (Optional — only needed if you'll trigger the monthly subscription from this backend.)

### B. Create the webhook endpoint

The webhook lets the Customer agent fire when a $199 payment lands.

1. Stripe Dashboard → **Developers** → **Webhooks** → **+ Add endpoint**.
2. Endpoint URL: `https://YOUR-DEPLOYED-DOMAIN/webhooks/stripe`
   - For testing locally first, use `stripe listen --forward-to localhost:8000/webhooks/stripe` (see step 9).
3. Events to send: select
   - `checkout.session.completed`
   - `payment_intent.succeeded`
4. **Add endpoint** → click it → **Signing secret** → reveal → copy → `STRIPE_WEBHOOK_SECRET` (`whsec_...`).
5. Get your live secret key: **Developers** → **API keys** → copy `Secret key` (live mode toggle ON) → `STRIPE_SECRET_KEY` (`sk_live_...`).

> 💡 Since you're going live mode, also confirm the Payment Link uses the same product (the price_id matches `STRIPE_PRICE_SETUP`).

---

## 7. Generate an admin token

Run this once and paste the output into `.env` as `ADMIN_TOKEN`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

This token is the only auth on `/admin` and `/runs/*`. If you ever rotate it, update `.env` and restart.

---

## 8. Build your `.env`

```bash
cp .env.example .env
```

Then fill `.env` with:

```env
# --- Anthropic ---
ANTHROPIC_API_KEY=          # from step 2
LLM_MODEL_FAST=claude-haiku-4-5-20251001
LLM_MODEL_SMART=claude-sonnet-4-6

# --- Supabase ---
SUPABASE_URL=               # from step 1
SUPABASE_SERVICE_ROLE_KEY=  # from step 1

# --- Gmail ---
GMAIL_CLIENT_ID=            # from step 4
GMAIL_CLIENT_SECRET=        # from step 4
GMAIL_FROM_ADDRESS=cb@glowbridge.ai
GMAIL_FROM_NAME=Charles at GlowBridge

# --- Stripe (LIVE mode) ---
STRIPE_SECRET_KEY=          # from step 6B (sk_live_...)
STRIPE_WEBHOOK_SECRET=      # from step 6B (whsec_...)
STRIPE_PRICE_SETUP=         # from step 6A (price_...)
STRIPE_PRICE_MONTHLY=       # optional, can leave blank

# --- Browserbase ---
BROWSERBASE_API_KEY=        # from step 5
BROWSERBASE_PROJECT_ID=     # from step 5

# --- Search ---
BRAVE_API_KEY=              # from step 3

# --- Admin ---
ADMIN_TOKEN=                # from step 7
OPERATOR_EMAIL=chbensoussan@gmail.com

# --- App ---
APP_ENV=production
APP_BASE_URL=https://YOUR-DEPLOYED-DOMAIN
TIMEZONE=America/New_York

# --- Safety toggles: keep ALL THREE off for first 24-48h ---
ENABLE_OUTREACH_SEND=false
ENABLE_REPLY_AUTOREPLY=false
ENABLE_SOCIAL_AUTOPOST=false
```

---

## 9. Install + Gmail OAuth bootstrap + first boot

```bash
# 1. Create venv + install
python -m venv .venv
source .venv/bin/activate    # or: .\.venv\Scripts\Activate.ps1 on Windows PowerShell
pip install -e ".[dev]"

# 2. Sanity-check the safety gates BEFORE going further
pytest -q

# 3. One-time Gmail OAuth — opens browser, sign in as cb@glowbridge.ai
python -m scripts.gmail_oauth

# 4. (Optional) For local Stripe webhook testing:
#    Install Stripe CLI: https://stripe.com/docs/stripe-cli
#    Forward webhooks to local:
stripe listen --forward-to localhost:8000/webhooks/stripe
#    The CLI prints a different webhook secret for local testing — use that
#    one in .env while testing locally, swap to the production secret on deploy.

# 5. Run the backend
uvicorn app.main:app --port 8000

# 6. Open the dashboard (in another terminal)
#    /admin requires the bearer token in a Authorization header. The dashboard
#    JS prompts you for it once and stores it in localStorage.
open http://localhost:8000/admin
```

---

## 10. First-day smoke test (everything DRY-RUN — no real emails sent)

With all three `ENABLE_*` flags still `false`:

```bash
# Find 25 prospects (this hits Brave + your model API; takes a couple minutes)
curl -X POST http://localhost:8000/runs/prospect \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Research them (visits sites, extracts pain signals)
curl -X POST http://localhost:8000/runs/research \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Draft outreach — every draft will land in the approval queue
curl -X POST http://localhost:8000/runs/outreach \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Open `/admin` — you'll see ~25 prospects listed, ~25 research rows, and a stack of outreach drafts in the approval queue with `reason_for_review = ENABLE_OUTREACH_SEND=false (dry run)`.

**Read every draft.** The first batch is your QA pass on the prompts. Note any drafts that:
- Sound robotic / pitchy
- Mention the wrong city or company
- Cite a pain signal that isn't actually on the site

If you see consistent issues, ping me and we'll tune the prompts in `app/agents/outreach.py` before you flip the switch.

---

## 11. Going live — flipping the toggles

Only after the dry run looks clean (target: <10% of drafts feel "off"):

```env
ENABLE_OUTREACH_SEND=true
```

Restart the backend. Tomorrow's 8 AM run will actually send. Keep auto-reply OFF until you've seen 20+ classified replies in the dashboard and confirmed the classifier is right.

When you're confident:
```env
ENABLE_REPLY_AUTOREPLY=true
```

Social auto-post — leave OFF until you've posted 5+ X drafts manually and like the tone.

---

## 12. Where to deploy

The backend is cloud-agnostic; pick whichever you're comfortable with:

| Option | Why |
|---|---|
| **Railway** (recommended for solo) | One-click deploy, persistent disk for `gmail_token.json`, $5/mo. Webhooks just work. |
| Fly.io | Similar to Railway, slightly more knobs. |
| Render | Same idea, has free tier for small services (but cold starts hurt cron). |
| A small VPS + Docker | Most control, more ops. |

Whichever you pick:
- Set every env var via the platform's secret store, not in a committed file.
- Mount or persist `gmail_token.json` (or move it to Supabase storage if you want it stateless — small follow-up).
- Point the Stripe webhook endpoint at the deployed URL after the first deploy.

---

## What you can't break

The `app/safety.py` gates run regardless of model output, env settings, or prompt changes. Even if you set `ENABLE_OUTREACH_SEND=true` on day one and the model produces a draft saying "we guarantee 10 bookings", that email will not send — it'll land in the queue with `banned_phrase: guarantees outcomes`. Tests in `tests/test_safety.py` cover every rule from the brief.
