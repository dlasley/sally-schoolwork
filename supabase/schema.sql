-- Consolidated schema for sally-schoolwork
-- Run this to create all tables from scratch.

-- User profiles: permanent properties collected during onboarding
create table if not exists user_profiles (
  device_id text primary key,
  name text,
  relation_to_student text,
  priorities text[],
  communication_preferences text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- Session history: rolling log of conversation summaries
create table if not exists session_history (
  id uuid default gen_random_uuid() primary key,
  device_id text not null references user_profiles(device_id) on delete cascade,
  session_date timestamptz default now(),
  summary text not null,
  topics_discussed text[],
  classes_mentioned text[]
);

create index if not exists idx_session_history_device_id
  on session_history(device_id, session_date desc);

-- Session messages: raw conversation messages, saved incrementally per turn
create table if not exists session_messages (
  id uuid default gen_random_uuid() primary key,
  device_id text not null references user_profiles(device_id) on delete cascade,
  session_id text not null,
  role text not null,
  content text not null,
  created_at timestamptz default now()
);

create index if not exists idx_session_messages_session
  on session_messages(session_id, created_at);

create index if not exists idx_session_messages_device
  on session_messages(device_id, created_at desc);

-- Auto-update updated_at on profile changes
create or replace function update_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists user_profiles_updated_at on user_profiles;
create trigger user_profiles_updated_at
  before update on user_profiles
  for each row
  execute function update_updated_at();
