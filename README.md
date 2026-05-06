# GlowBridge Agent Ops

Production agent operations backend for **GlowBridge Call Capture** — AI receptionist for pest control companies in NJ/NY/PA/CT.

Built with **FastAPI + Anthropic Claude + Supabase**. Six agents on a daily schedule, with a hard-coded safety layer that gates every outbound action through deterministic rules (not just prompts).

## What's in here

| Agent | Purpose | Auto-fires? |
|---|---|---|
| **Prospect** | Find 25 pest-control companies/day in NJ/NY/PA/CT, score 1–10 | yes (7:00 AM) |
| **Research** | Visit each prospect's site, extract pain signal | yes (7:30 AM) |
| **Outreach** | Draft <90-word email, gate through safety, send or queue | yes (8:00 AM) — only sends past gate |
| **Reply** | Classify Gmail replies; auto-reply ONLY simple price/how-it-works questions | partial (12 PM, 4 PM) |
| **Customer** | Triggered by Stripe $199 setup webhook → onboarding flow | event-driven |
| **Social** | Generate daily content drafts; auto-post only safe X educational posts | partial (6 PM) |

## Hard safety rules (enforced in code, not prompts)

These live in `app/safety.py` and run after every model call that could produce outbound content:

- **Outreach auto-send gate**: lead score ≥8 AND clearly pest control AND email exists AND no unsubscribe AND no banned phrase AND email <100 words. Anything failing → approval queue.
- **Banned phrases**: "guaranteed bookings", "guaranteed revenue", "AI quotes prices", etc.
- **Unsubscribe respect**: any address on the unsubscribe list is blocked at the DB layer.
- **Reply auto-reply gate**: only fires for `asked_price` or `asked_how_it_works` AND classifier confidence ≥0.85. Angry/legal/wants_call/interested/unsubscribe → escalate.
- **Social auto-post**: only X educational posts pass. Reddit, Customer-claim, revenue-claim → never auto-post.

Every agent run logs to `agent_runs` and `agent_logs` tables for audit.

## Daily schedule (America/New_York)

| Time | Job |
|---|---|
| 07:00 | `prospect.run(target=25)` |
| 07:30 | `research.run(prospects=pending)` |
| 08:00 | `outreach.run(researched=ready)` — gated send |
| 12:00 | `reply.run()` — Gmail poll + classify |
| 16:00 | `reply.run()` + follow-up sweep |
| 18:00 | `social.run()` — generate drafts |

## Quick start

```bash
# 1. Clone & set up env
cp .env.example .env
# Fill in ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY at minimum.

# 2. Apply Supabase schema
# In Supabase SQL editor, run:
cat supabase/schema.sql

# 3. Install
pip install -e ".[dev]"

# 4. Run
uvicorn app.main:app --reload --port 8000

# 5. Open admin
open http://localhost:8000/admin
```

## Going live, step by step

The default `.env.example` ships with all sends OFF. Flip these only when you've verified the queue:

```
ENABLE_OUTREACH_SEND=true     # turn on after reviewing 5+ queued drafts manually
ENABLE_REPLY_AUTOREPLY=true   # turn on after 20+ correct classifications
ENABLE_SOCIAL_AUTOPOST=true   # turn on after reviewing a week of drafts
```

## Manual triggers (for testing without waiting for cron)

```bash
# Run any agent on demand:
curl -X POST http://localhost:8000/runs/prospect \
  -H "Authorization: Bearer $ADMIN_TOKEN"

curl -X POST http://localhost:8000/runs/research \
  -H "Authorization: Bearer $ADMIN_TOKEN"

curl -X POST http://localhost:8000/runs/outreach \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

## Webhooks to configure

- **Stripe** → `POST {APP_BASE_URL}/webhooks/stripe`
  Events: `checkout.session.completed`, `payment_intent.succeeded` (for the $199 setup product)
- **Gmail** → use Pub/Sub push or fall back to APScheduler poll (default).

## Cost ceiling

At 25 prospects/day with prompt caching enabled: ~$0.40–0.50/day Anthropic. Supabase, Gmail, and Stripe are free at this scale. Browserbase has a free tier sufficient for this volume.

## Repo layout

```
app/
  main.py             FastAPI app + lifespan + scheduler bootstrap
  config.py           pydantic-settings
  llm.py              Anthropic adapter (single point of model swap)
  db.py               Supabase client + typed helpers
  safety.py           Hard gates: banned phrases, send rules, unsubscribe
  scheduler.py        APScheduler cron jobs
  agents/             one file per agent
  integrations/       gmail, stripe, browserbase, web search
  routers/            admin, approvals, webhooks, runs
  templates/          admin.html
supabase/
  schema.sql          tables, RLS, seed data
tests/
  test_safety.py      the gates that gate the gates
```

## Safety philosophy

The original brief includes "never claim guaranteed revenue", "never auto-reply to angry messages", etc. **These are not enforced by prompting alone**. Every outbound action passes through `app/safety.py` after the model produces output — so even a model gone rogue can't bypass them. Tests cover each rule.
