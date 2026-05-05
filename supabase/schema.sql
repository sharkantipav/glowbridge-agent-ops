create table if not exists prospects (
  id uuid primary key default gen_random_uuid(),
  company_name text not null,
  website text unique,
  city text,
  state text,
  phone text,
  email text,
  contact_name text,
  lead_score int check (lead_score between 1 and 10),
  is_pest_control boolean default true,
  research jsonb default '{}'::jsonb,
  pain_signal text,
  status text default 'new',
  created_at timestamptz default now()
);

create table if not exists outreach_messages (
  id uuid primary key default gen_random_uuid(),
  prospect_id uuid references prospects(id),
  subject text,
  body text,
  status text not null,
  reason text,
  sent_at timestamptz,
  created_at timestamptz default now()
);

create table if not exists approval_queue (
  id uuid primary key default gen_random_uuid(),
  item_type text not null,
  payload jsonb not null,
  reason text not null,
  status text default 'pending',
  created_at timestamptz default now()
);

create table if not exists logs (
  id bigserial primary key,
  agent text not null,
  event_type text not null,
  payload jsonb default '{}'::jsonb,
  status text default 'info',
  created_at timestamptz default now()
);

create table if not exists customers (
  id uuid primary key default gen_random_uuid(),
  stripe_customer_id text,
  company_name text,
  contact_email text,
  setup_paid boolean default false,
  setup_form_url text,
  call_flow_draft text,
  onboarding_status text default 'pending_approval',
  created_at timestamptz default now()
);
