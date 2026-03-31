-- 0010: Hub messages table for cross-conclave messaging
--
-- Purpose-built table replacing the previous approach of storing messages
-- as cerefox documents with metadata conventions.

create table if not exists hub_messages (
  id uuid primary key default gen_random_uuid(),
  from_conclave text not null,
  from_agent text not null,
  to_conclave text not null,
  to_agent text not null default 'all',
  subject text not null,
  body text not null,
  created_at timestamptz not null default now(),
  received_at timestamptz,
  received_by text
);

create index if not exists idx_hub_messages_to
  on hub_messages(to_conclave, received_at);

create index if not exists idx_hub_messages_created
  on hub_messages(created_at desc);
