# GlowBridge Agent Ops Backend

Production-oriented FastAPI backend for GlowBridge Call Capture using OpenAI-powered agents.

## Features
- Multi-agent backend: Prospect, Research, Outreach, Reply, Customer, Social.
- Supabase-backed persistence for prospects, approvals, logs, outreach, and customers.
- Stripe webhook ingestion for $199 setup payment onboarding.
- Gmail integration interface for outbound and reply monitoring.
- Browser automation integration interface (Browserbase/Stagehand hooks).
- Admin dashboard endpoint at `/admin`.
- Scheduled jobs via APScheduler.
- Safety constraints and escalation-first behavior.

## Safety Guardrails Implemented
- No guaranteed revenue claims.
- No guaranteed booking claims.
- No pest-control price quote claims.
- Unsubscribe / angry / legal classes escalate.
- Outreach only auto-sends when score >= 8 and compliance checks pass.

## Daily Schedule (configured baseline)
- 07:00 find prospects
- 07:30 research/enrich prospects (wire as next job)
- 08:00 send safe outreach (wire as next job)
- 12:00 reply checks (wire as next job)
- 16:00 second reply check (wire as next job)
- 18:00 social content generation

> Current implementation includes key 07:00 and 18:00 jobs in scheduler scaffold with TODOs for the rest.

## Quick Start
1. Create env file:
   ```bash
   cp .env.example .env
   ```
2. Install dependencies:
   ```bash
   pip install -e .
   ```
3. Apply `supabase/schema.sql` in your Supabase SQL editor.
4. Run API:
   ```bash
   uvicorn app.main:app --reload
   ```
5. Open:
   - API docs: `http://localhost:8000/docs`
   - Admin: `http://localhost:8000/admin`

## Core Endpoints
- `GET /health`
- `POST /webhooks/stripe`
- `POST /ops/outreach`
- `POST /ops/reply/classify`

## Production Hardening TODOs
- Replace placeholder Gmail client with OAuth-authenticated API calls.
- Replace Browserbase/Stagehand placeholder with real session automation.
- Add robust JSON parsing/validation for Prospect and Research extraction outputs.
- Add authn/authz for `/admin` and ops endpoints.
- Add retry queues (e.g., Celery/Arq) and dead-letter handling.
- Add monitoring dashboards and alerting.
