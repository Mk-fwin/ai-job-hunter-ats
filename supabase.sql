-- Run in Supabase SQL editor. The service role key stays server-side in Streamlit secrets.
create table if not exists public.applications (
  id text primary key,
  company text not null,
  title text not null,
  url text,
  location text,
  source text,
  salary text,
  stage text,
  track text,
  score integer,
  notes text,
  applied_date text,
  followup_date text,
  created_at text not null
);
alter table public.applications enable row level security;
-- No public policies: access through server-side service role only.
