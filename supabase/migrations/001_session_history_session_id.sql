-- Add session_id to session_history so deferred summarization can find the right messages.
alter table session_history add column if not exists session_id text unique;
