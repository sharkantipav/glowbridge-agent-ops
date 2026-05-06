-- =====================================================================
-- GlowBridge Agent Ops — Supabase schema
-- Run this in the Supabase SQL editor on a fresh project.
-- Idempotent: safe to re-run.
-- =====================================================================

-- Required extensions
create extension if not exists "uuid-ossp";
create extension if not exists "pgcrypto";

-- ---------- Prospects ----------
create table if not exists prospects (
    id uuid primary key default uuid_generate_v4(),
    company_name text not null,
    website text,
    city text,
    state text check (state in ('NJ','NY','PA','CT')),
    phone text,
    email text,
    contact_name text,
    contact_role text,
    score int check (score between 1 and 10),
    source text,                 -- 'web_search', 'referral', etc.
    raw_search_blob jsonb,       -- audit trail of what we found
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create unique index if not exists prospects_website_uniq
    on prospects (lower(website)) where website is not null;
create index if not exists prospects_state_score_idx on prospects (state, score desc);
create index if not exists prospects_email_idx on prospects (lower(email)) where email is not null;

-- ---------- Research findings ----------
create table if not exists research (
    id uuid primary key default uuid_generate_v4(),
    prospect_id uuid not null references prospects(id) on delete cascade,
    advertises_emergency boolean,
    advertises_after_hours boolean,
    has_booking_form boolean,
    voicemail_heavy boolean,
    pain_signal text,            -- one-sentence summary
    review_excerpt text,         -- bad-review snippet, if any
    page_html_excerpt text,      -- truncated HTML for audit
    confidence numeric(3,2),     -- 0.00 - 1.00
    created_at timestamptz not null default now()
);
create index if not exists research_prospect_idx on research (prospect_id);

-- ---------- Outreach (drafted + sent) ----------
create type outreach_status as enum (
    'draft',         -- generated, awaiting gate
    'queued',        -- failed gate, in approval queue
    'approved',      -- human approved
    'sent',          -- delivered
    'bounced',
    'rejected',     -- human rejected
    'blocked'        -- safety hard-block (banned phrase, unsubscribed, etc.)
);

create table if not exists outreach (
    id uuid primary key default uuid_generate_v4(),
    prospect_id uuid not null references prospects(id) on delete cascade,
    research_id uuid references research(id),
    subject text not null,
    body text not null,
    word_count int generated always as (array_length(regexp_split_to_array(trim(body), '\s+'), 1)) stored,
    status outreach_status not null default 'draft',
    gate_failures jsonb,         -- ["banned_phrase","over_word_limit",...]
    gmail_message_id text,
    sent_at timestamptz,
    bounced_at timestamptz,
    rejected_reason text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index if not exists outreach_status_idx on outreach (status, created_at desc);
create index if not exists outreach_prospect_idx on outreach (prospect_id);

-- ---------- Replies ----------
create type reply_intent as enum (
    'interested',
    'not_interested',
    'asked_price',
    'asked_how_it_works',
    'wants_call',
    'objection',
    'angry',
    'unsubscribe',
    'unknown'
);

create table if not exists replies (
    id uuid primary key default uuid_generate_v4(),
    outreach_id uuid references outreach(id) on delete set null,
    from_email text not null,
    subject text,
    body text,
    intent reply_intent not null default 'unknown',
    confidence numeric(3,2),
    auto_replied boolean not null default false,
    auto_reply_body text,
    escalated boolean not null default false,
    received_at timestamptz not null default now(),
    gmail_message_id text unique,
    created_at timestamptz not null default now()
);
create index if not exists replies_intent_idx on replies (intent, received_at desc);
create index if not exists replies_from_idx on replies (lower(from_email));

-- ---------- Unsubscribe list (hard block) ----------
create table if not exists unsubscribes (
    id uuid primary key default uuid_generate_v4(),
    email text not null,
    reason text,                 -- 'replied_unsubscribe', 'manual', 'bounced'
    created_at timestamptz not null default now()
);
create unique index if not exists unsubscribes_email_uniq on unsubscribes (lower(email));

-- ---------- Customers (post-Stripe) ----------
create type customer_status as enum (
    'pending_setup',     -- $199 paid, awaiting form completion
    'awaiting_test_call',
    'test_call_approved',
    'live',
    'cancelled',
    'refunded'
);

create table if not exists customers (
    id uuid primary key default uuid_generate_v4(),
    prospect_id uuid references prospects(id),
    company_name text not null,
    contact_email text not null,
    contact_phone text,
    stripe_customer_id text unique,
    stripe_setup_payment_id text,
    setup_paid_at timestamptz,
    monthly_subscription_id text,
    status customer_status not null default 'pending_setup',
    setup_form_url text,
    setup_form_completed_at timestamptz,
    call_flow_draft jsonb,
    test_call_approved_at timestamptz,
    went_live_at timestamptz,
    cancelled_at timestamptz,
    refunded_at timestamptz,
    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index if not exists customers_status_idx on customers (status);

-- ---------- Approval queue ----------
-- Anything that fails an auto-send gate ends up here for Charles to approve/reject.
create type approval_kind as enum ('outreach', 'reply', 'social', 'customer_action');
create type approval_state as enum ('pending', 'approved', 'rejected', 'expired');

create table if not exists approvals (
    id uuid primary key default uuid_generate_v4(),
    kind approval_kind not null,
    target_id uuid not null,         -- FK semantics depend on kind
    payload jsonb not null,          -- snapshot of what would be sent
    reason_for_review text,          -- why it landed here (which gate failed)
    state approval_state not null default 'pending',
    decided_by text,
    decided_at timestamptz,
    created_at timestamptz not null default now()
);
create index if not exists approvals_state_kind_idx on approvals (state, kind, created_at desc);

-- ---------- Social content ----------
create type social_platform as enum ('x', 'tiktok', 'reels', 'instagram', 'reddit');
create type social_status as enum ('draft', 'queued', 'posted', 'rejected');

create table if not exists social_posts (
    id uuid primary key default uuid_generate_v4(),
    platform social_platform not null,
    content text not null,
    media_hint text,                 -- TikTok script/Reels description
    status social_status not null default 'draft',
    auto_eligible boolean not null default false,  -- only safe X educational posts
    posted_at timestamptz,
    external_post_id text,
    created_at timestamptz not null default now()
);

-- ---------- Agent runs (audit) ----------
create table if not exists agent_runs (
    id uuid primary key default uuid_generate_v4(),
    agent text not null,             -- 'prospect','research','outreach','reply','customer','social'
    status text not null,            -- 'started','completed','failed'
    input jsonb,
    output jsonb,
    error text,
    duration_ms int,
    started_at timestamptz not null default now(),
    completed_at timestamptz
);
create index if not exists agent_runs_agent_idx on agent_runs (agent, started_at desc);

-- ---------- Logs (free-form) ----------
create table if not exists agent_logs (
    id bigserial primary key,
    run_id uuid references agent_runs(id) on delete set null,
    agent text,
    level text not null check (level in ('debug','info','warn','error')),
    message text not null,
    data jsonb,
    created_at timestamptz not null default now()
);
create index if not exists agent_logs_run_idx on agent_logs (run_id);
create index if not exists agent_logs_agent_idx on agent_logs (agent, created_at desc);

-- ---------- updated_at triggers ----------
create or replace function set_updated_at() returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

drop trigger if exists trg_prospects_updated on prospects;
create trigger trg_prospects_updated
    before update on prospects for each row execute function set_updated_at();

drop trigger if exists trg_outreach_updated on outreach;
create trigger trg_outreach_updated
    before update on outreach for each row execute function set_updated_at();

drop trigger if exists trg_customers_updated on customers;
create trigger trg_customers_updated
    before update on customers for each row execute function set_updated_at();

-- ---------- RLS ----------
-- Backend uses the service role key, which bypasses RLS. We still enable RLS
-- so that if anyone ever points a client-side anon key at these tables, they
-- get nothing. No public-readable policies are created.
alter table prospects        enable row level security;
alter table research         enable row level security;
alter table outreach         enable row level security;
alter table replies          enable row level security;
alter table unsubscribes     enable row level security;
alter table customers        enable row level security;
alter table approvals        enable row level security;
alter table social_posts     enable row level security;
alter table agent_runs       enable row level security;
alter table agent_logs       enable row level security;
