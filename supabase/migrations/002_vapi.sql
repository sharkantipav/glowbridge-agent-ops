-- =====================================================================
-- Migration 002 — Vapi voice AI integration
-- Adds per-customer Vapi assistant/phone fields and a `calls` table for
-- real call records (transcripts, durations, structured lead data).
-- =====================================================================

alter table customers
    add column if not exists vapi_assistant_id text,
    add column if not exists vapi_phone_number text,
    add column if not exists vapi_provisioned_at timestamptz;

create unique index if not exists customers_vapi_assistant_uniq
    on customers (vapi_assistant_id) where vapi_assistant_id is not null;
create unique index if not exists customers_vapi_phone_uniq
    on customers (vapi_phone_number) where vapi_phone_number is not null;

do $$ begin
    create type call_status as enum (
        'initiated', 'in_progress', 'ended', 'failed', 'voicemail_left'
    );
exception
    when duplicate_object then null;
end $$;

create table if not exists calls (
    id uuid primary key default uuid_generate_v4(),
    customer_id uuid references customers(id) on delete cascade,
    vapi_call_id text unique,
    vapi_assistant_id text,
    caller_phone text,
    direction text default 'inbound',
    status call_status not null default 'initiated',
    started_at timestamptz,
    ended_at timestamptz,
    duration_sec int,
    transcript text,
    summary text,                  -- short AI-generated summary
    structured_data jsonb,         -- caller_name, callback_number, issue, urgency, etc.
    handoff_sent boolean not null default false,
    handoff_via text,              -- 'sms', 'email', 'both'
    cost_usd numeric(8,4),
    raw_payload jsonb,             -- raw Vapi event for debugging
    created_at timestamptz not null default now()
);
create index if not exists calls_customer_idx on calls (customer_id, started_at desc);
create index if not exists calls_status_idx on calls (status);

alter table calls enable row level security;
